"""Named verdicts, chosen by deterministic harness logic and never by a model.

Every prove/loop run that reaches a verdict gets exactly one of the VERDICTS and a human-readable reason.
`proven` stays in receipts for back-compat and is derived: proven == (verdict == VALIDATED).

Precedence (the first rule that matches wins):

 1. INVALID_TEST         the validator rejected the test (vacuous, malformed, or the tautology check), nothing ran, the
                         proof test errored on base or head with something other than an assertion (collection, import
                         or runtime error), or (loop only) triage did not confirm the failure reproduces the issue.
 2. FLAKY                re-running the frozen proof test N times on base and on head gave inconsistent outcomes.
 3. NO_REGRESSION_FOUND  the proof test passes on base: it does not detect the reported bug.
 4. FIX_FAILS_TEST       the test is valid (red on base) but the change under test still fails it, or breaks the repo's
                         own suite. This is a sixth value beyond the five requested ones, on purpose: none of the five
                         describes "valid test, patch does not satisfy it" and mislabelling it would be dishonest. The
                         loop's "wrong patch rejected" outcome carries this verdict. To fold it into another value, change
                         FIX_FAILS_TEST in `decide_verdict` only.
 5. MUTATION_SURVIVED    reverting the fix, or too many mutants of the changed lines, did not make the proof test fail,
                         or the check could not complete (fails closed).
 6. VALIDATED            none of the above.

Evidence is facts only; `decide_verdict` is a pure function of it.
"""

VALIDATED = "VALIDATED"
NO_REGRESSION_FOUND = "NO_REGRESSION_FOUND"
INVALID_TEST = "INVALID_TEST"
MUTATION_SURVIVED = "MUTATION_SURVIVED"
FLAKY = "FLAKY"
FIX_FAILS_TEST = "FIX_FAILS_TEST"
VERDICTS = (INVALID_TEST, FLAKY, NO_REGRESSION_FOUND, FIX_FAILS_TEST, MUTATION_SURVIVED, VALIDATED)  # precedence order

MUTATION_THRESHOLD = 0.6   # kill_rate needed (when at least one mutant was generated)
FLAKE_RUNS = 5             # proof-test runs on each of base and head (including the first)
FLAKE_RUNS_MAX = 10

# Receipt field names (prove and loop receipts alike):
#   verdict, verdict_reason, proven (derived), base_sha, head_sha, verdict_logs{base, head, survivors, flake},
#   flaky{ran, runs, base_fail_rate, head_pass_rate, flake_rate, flaky, outcomes, note},
#   mutation{mutants[{id, operator, file, line, what, diff, killed, output_excerpt}], killed, total, kill_rate,
#            threshold, ok, note},
#   tautology{checked, changed_symbols, asserted_symbols, ok, reason}
RECEIPT_FIELDS = ("verdict", "verdict_reason", "proven", "base_sha", "head_sha", "verdict_logs", "flaky", "mutation", "tautology")


def _excerpt(result, limit=800):
    if not result:
        return ""
    return ((result.get("stdout") or "") + (result.get("stderr") or ""))[-limit:]


def flake_summary(base_passes, head_passes, note_extra=None):
    """Summarise N proof-test outcomes (True = passed) on base and on head into the receipt's `flaky` dict.

    base_fail_rate: share of base runs that failed (a good proof test fails every time on base: 1.0).
    head_pass_rate: share of head runs that passed (1.0 for a good fix).
    flake_rate: share of all runs that disagree with their side's majority outcome (0.0 when stable).
    Any disagreement within a side makes the test FLAKY.
    """
    runs = len(base_passes)
    minority = lambda xs: min(sum(xs), len(xs) - sum(xs))
    flaky = minority(base_passes) > 0 or minority(head_passes) > 0
    total = len(base_passes) + len(head_passes)
    out = {"ran": True, "runs": runs, "flaky": flaky,
           "base_fail_rate": round(sum(1 for p in base_passes if not p) / runs, 3) if runs else None,
           "head_pass_rate": round(sum(1 for p in head_passes if p) / len(head_passes), 3) if head_passes else None,
           "flake_rate": round((minority(base_passes) + minority(head_passes)) / total, 3) if total else None,
           "outcomes": {"base_passed": list(base_passes), "head_passed": list(head_passes)},
           "note": ("inconsistent outcomes across reruns" if flaky else f"consistent over {runs} runs on base and on head")}
    if note_extra:
        out["note"] += "; " + note_extra
    return out


def decide_verdict(evidence):
    """Pure function: evidence dict -> (verdict, reason).

    Keys (all optional, absent means "not applicable"):
      rejected       the validator's rejection text (None when accepted)
      tautology      {ok: bool, reason: str} from the AST tautology check; ok False -> INVALID_TEST
      base, head     {returncode, stdout, stderr} of the proof test; None means nothing ran
      test_name      name of the proof test (used to classify failures)
      suite_ok       the repo's own suite passes on the code under test (default True)
      flaky          the `flaky` dict from flake_summary; flaky True -> FLAKY
      revert         the revert_check receipt: {ok, summary} or {skipped: ...}
      mutation       the mutation dict: {ok, kill_rate, threshold, killed, total}
      triage_blocked reason text when triage refused to confirm the failure (loop)
      patch_loop     True when `head` is code the fix loop rewrote: its non-assertion errors indict the patch, not the test
    """
    from .prove import expected_base_failure

    e = evidence
    if e.get("rejected"):
        return INVALID_TEST, f"the validator rejected the proof test: {e['rejected']}"
    taut = e.get("tautology")
    if taut and taut.get("checked", True) and taut.get("ok") is False:
        return INVALID_TEST, f"tautology check: {taut.get('reason')}"
    base, head, name = e.get("base"), e.get("head"), e.get("test_name")
    if base is None or head is None:
        return INVALID_TEST, "no proof test ran"
    if base["returncode"] != 0 and expected_base_failure(base, name) is None:
        return INVALID_TEST, ("the proof test errored on base (collection, import or runtime error) "
                              "instead of failing an assertion")
    if head["returncode"] != 0 and expected_base_failure(head, name) is None and not e.get("patch_loop"):
        return INVALID_TEST, ("the proof test errored on head (collection, import or runtime error) "
                              "instead of failing an assertion")
    if e.get("triage_blocked"):
        return INVALID_TEST, e["triage_blocked"]
    flaky = e.get("flaky")
    if flaky and flaky.get("flaky"):
        return FLAKY, f"the proof test gave inconsistent results over {flaky.get('runs')} runs (flake rate {flaky.get('flake_rate')})"
    if base["returncode"] == 0:
        return NO_REGRESSION_FOUND, "the proof test passes on base, so it does not detect the reported bug"
    if head["returncode"] != 0:
        return FIX_FAILS_TEST, "the proof test fails on the change under test too (the bug is not fixed, or the fix is incomplete)"
    if e.get("suite_ok") is False:
        return FIX_FAILS_TEST, "the proof test passes but the repo's own test suite fails on the change under test"
    revert = e.get("revert")
    if revert is not None and not revert.get("skipped") and not revert.get("ok"):
        return MUTATION_SURVIVED, "revert check failed: " + str(revert.get("summary"))
    mutation = e.get("mutation")
    if mutation is not None and not mutation.get("ok", True):
        rate = mutation.get("kill_rate")
        if rate is None:  # the check itself could not run: fail closed
            return MUTATION_SURVIVED, "the mutation check could not complete: " + str(mutation.get("note"))
        return MUTATION_SURVIVED, (f"mutation kill rate {rate:.0%} is below the {mutation.get('threshold', MUTATION_THRESHOLD):.0%} "
                                   f"threshold ({mutation.get('killed')}/{mutation.get('total')} mutants of the changed lines killed)")
    notes = []
    if revert is not None and revert.get("skipped"):
        notes.append("revert check was " + str(revert["skipped"]))
    if mutation is not None and mutation.get("incomplete"):
        notes.append(mutation.get("note") or "mutation check incomplete: budget")
    elif mutation is not None and mutation.get("total") == 0:
        notes.append("no mutable lines, so no mutants were generated")
    elif mutation is None:
        notes.append("mutation check was not run")
    reason = "red on base with an assertion, green on head"
    if flaky and flaky.get("ran"):
        reason += f", stable over {flaky.get('runs')} runs"
    if revert is not None and not revert.get("skipped"):
        reason += ", killed the revert"
    if mutation is not None and mutation.get("total"):
        reason += f", killed {mutation['killed']}/{mutation['total']} mutants"
        if mutation.get("not_run") and not mutation.get("incomplete"):
            notes.append(f"{mutation['not_run']} more mutants were not run: budget")
    return VALIDATED, reason + (f" ({'; '.join(notes)})" if notes else "")


def verdict_fields(evidence, base_sha=None, head_sha=None):
    """Decide and return the receipt fields: verdict, verdict_reason, proven, shas, log excerpts, flaky, mutation, tautology."""
    verdict, reason = decide_verdict(evidence)
    mutation = evidence.get("mutation")
    return {
        "verdict": verdict, "verdict_reason": reason, "proven": verdict == VALIDATED,
        "base_sha": base_sha, "head_sha": head_sha,
        "verdict_logs": {
            "base": _excerpt(evidence.get("base")), "head": _excerpt(evidence.get("head")),
            "survivors": [{"id": m["id"], "operator": m["operator"], "file": m["file"], "line": m["line"],
                           "output_excerpt": m.get("output_excerpt", "")[-300:]}
                          for m in (mutation or {}).get("mutants", []) if not m.get("killed")][:5],
        },
        "flaky": evidence.get("flaky"), "mutation": mutation, "tautology": evidence.get("tautology"),
    }


def step_detail(fields):
    """The detail of the `verdict` step event, a contract with latch-web: exactly {verdict, reason}."""
    return {"verdict": fields["verdict"], "reason": fields["verdict_reason"]}
