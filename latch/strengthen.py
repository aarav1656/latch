"""Survivor-driven test strengthening: one honest retry of the test writer after a real mutation-check failure.

When the mutation check actually fails (kill rate below the threshold, so MUTATION_SURVIVED), the test writer gets
ONE more try with the surviving mutants' diffs in the prompt, asking for a proof test that also fails on them. The
new test then goes through the whole gate again (tautology, base red, head green, flake, revert, mutation) and the
harness decides exactly as before. Nothing is lowered: the threshold is untouched, the mutants are the same kind,
a test that merely sits near the threshold never triggers a retry, and the round is capped at one.

This module holds only the deterministic helpers (who survived, the prompt text, the receipt record); the
pipelines (latch.prove, latch.loop.core) own the gate stages.
"""

MAX_ROUNDS = 1              # the cap: a second failure stays failed
MAX_DIFF_CHARS = 1200       # per surviving mutant in the prompt and the receipt
RECORD_KEYS = ("id", "operator", "file", "line", "what", "diff")


def _clip(text, limit=MAX_DIFF_CHARS):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "\n... (clipped)"


def survivors(mutation):
    """The mutants that ran and were NOT killed ({id, operator, file, line, what, diff}); errored or unrun ones are not survivors."""
    found = []
    for mutant in (mutation or {}).get("mutants") or []:
        if mutant.get("killed") or mutant.get("not_run") or mutant.get("error") or mutant.get("timed_out"):
            continue
        record = {key: mutant.get(key) for key in RECORD_KEYS}
        record["diff"] = _clip(record["diff"])
        found.append(record)
    return found


def eligible(mutation):
    """True only for an actual failure with a measured kill rate and at least one survivor.

    Passing (including exactly at the threshold), an incomplete run, and a run that could not measure anything
    (kill_rate None) are not triggers.
    """
    if not isinstance(mutation, dict) or mutation.get("ok", True) or mutation.get("incomplete"):
        return False
    return mutation.get("kill_rate") is not None and bool(survivors(mutation))


def new_record(mutation, found, test_name):
    """The `mutation.strengthened` stub, filled in with an outcome by `finish`."""
    return {"attempted": True, "survivors_before": found, "killed_before": mutation.get("killed"),
            "total_before": mutation.get("total"), "kill_rate_before": mutation.get("kill_rate"),
            "threshold": mutation.get("threshold"), "test_before": test_name}


def not_attempted(reason):
    return {"attempted": False, "reason": reason}


def finish(record, outcome, reason=None, after=None, completion_id=None):
    """outcome: adopted (the new test passed every gate), still_surviving (it ran the mutation check and failed again)
    or kept_original (the new test never reached the mutation check, so the original verdict stands)."""
    done = {**record, "outcome": outcome}
    if reason:
        done["reason"] = reason
    if completion_id:
        done["completion_id"] = completion_id
    if after is not None:
        done.update(killed_after=after.get("killed"), total_after=after.get("total"), kill_rate_after=after.get("kill_rate"))
    return done


def addendum(previous_source, mutation, found):
    """Prompt text appended to the original test-writing prompt for the retry."""
    lines = [
        "\n\nSTRENGTHENING ROUND (the only one). The harness ran your previous proof test against mutated copies of "
        f"the fixed code and it still PASSED on {len(found)} of {mutation.get('total')} mutants "
        f"(killed {mutation.get('killed')}/{mutation.get('total')}; the bar is {mutation.get('threshold')}). "
        "Write ONE replacement test function that still fails on the buggy base revision and passes on the fixed "
        "code, and that ALSO fails on each surviving mutant below. Pin down exactly the behavior the issue "
        "specifies (boundary values, both sides of a condition, returned values rather than only types); do not "
        "assert behavior the issue does not state, do not mention mutants in the test, and keep it deterministic. "
        "If a surviving change cannot alter behavior at all, ignore it.\n",
        "Previous proof test:\n" + _clip(previous_source, 4000) + "\n",
        "Surviving mutants (each is the fixed code with one small change):",
    ]
    for mutant in found:
        lines.append(f"--- {mutant['id']} {mutant['file']}:{mutant['line']} ({mutant['what']})\n{mutant['diff']}")
    return "\n".join(lines) + "\n"
