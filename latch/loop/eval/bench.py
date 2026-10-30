"""Per-case benchmark metrics and totals for `latch eval`: pure functions over receipts, no models, no I/O.

A receipt is what `latch.loop.run_loop` writes. Every field here is read from it or derived by the harness, never
supplied by a model. A value that is unknown is None (never 0), so a run that did not record tokens does not look free.

Named verdict: if the receipt already carries one (`named_verdict`, `verdict_name`, or a `verdict` that is one of
latch.verdict.VERDICTS) it is used as is (`verdict_source: "receipt"`). Otherwise it is derived from the facts the
receipt recorded, by the same pure function the harness uses (`latch.verdict.decide_verdict`), and flagged
`verdict_source: "derived"`. The verdict is about the change as submitted (iteration 0), before any repair.
"""

import statistics

from ...modelcalls import total_cost
from ...verdict import VALIDATED, VERDICTS, decide_verdict

CONTESTED = ("cachetools-423", "click-3360")  # same list as summary.CONTESTED (kept here to avoid an import cycle)


def _rate(k, n):
    return round(k / n, 3) if n else None


def _result(block):
    """loop receipt pytest block {returncode, output} -> the {returncode, stdout, stderr} form decide_verdict reads."""
    if not block:
        return None
    return {"returncode": block.get("returncode"), "stdout": block.get("output") or block.get("stdout") or "",
            "stderr": block.get("stderr") or ""}


def named_verdict(receipt):
    """-> (verdict | None, reason | None, source | None). None when the run never reached a verdict (error, no proof test)."""
    if not receipt:
        return None, None, None
    for key in ("named_verdict", "verdict_name", "verdict"):
        if receipt.get(key) in VERDICTS:
            return receipt[key], receipt.get("verdict_reason"), "receipt"
    initial = receipt.get("initial") or {}
    proof = receipt.get("proof_test") or {}
    base = _result(initial.get("base_proof"))
    if receipt.get("verdict") == "error" or not proof.get("name") or base is None:
        return None, None, None
    head = _result(initial.get("head_proof"))
    if head is None and base["returncode"] == 0:
        head = base  # the loop stops at "passes on base" before it runs head; NO_REGRESSION_FOUND does not depend on head
    triage = receipt.get("triage")
    triage_blocked = None
    if isinstance(triage, dict) and triage.get("verdict") in ("not_reproduced", "unclear"):
        triage_blocked = f"triage did not confirm the failure reproduces the issue ({triage.get('verdict')})"
    revert = receipt.get("revert_check")
    if isinstance(revert, dict):
        revert = {"skipped": revert["skipped"]} if revert.get("skipped") else {"ok": bool(revert.get("ok")), "summary": revert.get("summary")}
    suite = initial.get("head_suite")
    evidence = {"base": base, "head": head, "test_name": proof["name"],
                "suite_ok": None if suite is None else suite.get("returncode") == 0,
                "triage_blocked": triage_blocked, "flaky": receipt.get("flaky"), "mutation": receipt.get("mutation"), "revert": revert}
    if evidence["suite_ok"] is None:
        del evidence["suite_ok"]
    verdict, reason = decide_verdict({k: v for k, v in evidence.items() if v is not None})
    return verdict, reason, "derived"


def kill_rate(receipt):
    """-> (killed, total, rate, source). Prefer the mutation check; else the revert check's mutants; else unknown."""
    mutation = (receipt or {}).get("mutation")
    if isinstance(mutation, dict) and mutation.get("total"):
        return mutation.get("killed"), mutation["total"], mutation.get("kill_rate"), "mutation"
    revert = (receipt or {}).get("revert_check")
    mutants = revert.get("mutants") if isinstance(revert, dict) else None
    if mutants:
        killed = sum(1 for m in mutants if m.get("failed_as_expected"))
        return killed, len(mutants), _rate(killed, len(mutants)), "revert_check"
    return None, None, None, None


def token_totals(receipt):
    """-> {prompt_tokens, completion_tokens, cost_usd, calls, by_role}; tokens None unless some call reported them."""
    calls = (receipt or {}).get("model_calls") or []
    def total(key):
        known = [c[key] for c in calls if c.get(key) is not None]
        return sum(known) if known else None
    by_role = {}
    for c in calls:
        r = by_role.setdefault(c.get("role") or "unknown", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
        r["calls"] += 1
        r["prompt_tokens"] += c.get("prompt_tokens") or 0
        r["completion_tokens"] += c.get("completion_tokens") or 0
        r["cost_usd"] = round(r["cost_usd"] + (c.get("cost_usd") or 0.0), 6)
    cost = (receipt or {}).get("model_cost_usd")
    return {"prompt_tokens": total("prompt_tokens"), "completion_tokens": total("completion_tokens"),
            "cost_usd": cost if cost is not None else total_cost(calls), "calls": len(calls), "by_role": by_role}


def case_metrics(variant, run, receipt):
    """The additive per-case fields for one finished run (`run` = the run_eval row, `receipt` = its receipt or {})."""
    receipt = receipt or {}
    initial = receipt.get("initial") or {}
    verdict, reason, source = named_verdict(receipt)
    base_red = initial.get("base_red")
    head_proof = initial.get("head_proof") or {}
    pass_on_head = (head_proof.get("returncode") == 0) if head_proof else None
    killed, total, rate, rate_source = kill_rate(receipt)
    flaky = receipt.get("flaky") if isinstance(receipt.get("flaky"), dict) else {}  # same dict as the receipt's `flaky`
    errored = run.get("outcome") == "error"
    tokens = token_totals(receipt)
    return {
        "verdict": verdict, "verdict_reason": reason, "verdict_source": source,
        "fail_on_base": base_red, "pass_on_head": pass_on_head,
        "fail_to_pass": (bool(base_red) and bool(pass_on_head)) if base_red is not None and pass_on_head is not None else None,
        "suite_green_on_head": initial.get("head_suite_green"),
        "mutation": ({"killed": killed, "total": total, "kill_rate": rate} if total else None), "mutation_source": rate_source,
        "flaky": flaky or None,
        "wrong_patch_rejected": (None if variant != "wrong" or errored else run.get("outcome") != "false_accept"),
        "prompt_tokens": tokens["prompt_tokens"], "completion_tokens": tokens["completion_tokens"],
        "model_calls": tokens["calls"], "tokens_by_role": tokens["by_role"],
        "cost_usd": tokens["cost_usd"], "wall_s": run.get("wall_seconds"),
    }


def _ratio(k, n):
    return {"k": k, "n": n, "rate": _rate(k, n)}


def totals(rows):
    """Totals over the case rows (status "ran" rows carry the metrics; "not run" rows only count as not run)."""
    ran = [r for r in rows if r.get("status") == "ran"]
    ok = [r for r in ran if r.get("outcome") != "error"]
    real = [r for r in ok if r["variant"] == "real"]
    wrong = [r for r in ok if r["variant"] == "wrong"]
    nofix = [r for r in ok if r["variant"] == "nofix"]
    by_variant = {}
    for variant in ("real", "wrong", "nofix"):
        counts = {}
        for r in ok:
            if r["variant"] == variant and r.get("verdict"):
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        by_variant[variant] = counts
    with_rate = [r for r in ok if (r.get("mutation") or {}).get("kill_rate") is not None]
    killed = sum(r["mutation"]["killed"] or 0 for r in with_rate)
    mutants = sum(r["mutation"]["total"] or 0 for r in with_rate)
    known = lambda key: [r[key] for r in ran if r.get(key) is not None]
    walls, costs = known("wall_s"), known("cost_usd")
    accepted_wrong = [r["case"] for r in ok if r["variant"] in ("wrong", "nofix") and r["outcome"] in ("false_accept", "green_but_wrong", "repaired_but_oracle_fails")]
    return {
        "runs": len(ran), "errors": len(ran) - len(ok), "not_run": sum(1 for r in rows if r.get("status") == "not run"),
        "named_verdicts_by_variant": by_variant,
        "real_validated": _ratio(sum(1 for r in real if r.get("verdict") == VALIDATED), len(real)),
        "real_fail_to_pass": _ratio(sum(1 for r in real if r.get("fail_to_pass")), len([r for r in real if r.get("fail_to_pass") is not None])),
        "real_fail_on_base": _ratio(sum(1 for r in real if r.get("fail_on_base")), len([r for r in real if r.get("fail_on_base") is not None])),
        "wrong_patch_rejection": {**_ratio(sum(1 for r in wrong if r.get("wrong_patch_rejected")), len(wrong)),
                                  "without_contested": _ratio(sum(1 for r in wrong if r.get("wrong_patch_rejected") and r["case"] not in CONTESTED),
                                                              len([r for r in wrong if r["case"] not in CONTESTED])),
                                  # the gate shut for any reason counts above; this counts only wrong patches a VALID proof test failed
                                  "by_valid_test": _ratio(sum(1 for r in wrong if r.get("verdict") == "FIX_FAILS_TEST"), len(wrong)),
                                  "by_valid_test_without_contested": _ratio(
                                      sum(1 for r in wrong if r.get("verdict") == "FIX_FAILS_TEST" and r["case"] not in CONTESTED),
                                      len([r for r in wrong if r["case"] not in CONTESTED]))},
        "nofix_gate_open": _ratio(sum(1 for r in nofix if r["outcome"] in ("nemotron_fix_correct", "green_but_wrong")), len(nofix)),
        "gate_accepted_but_oracle_fails": {"n": len(accepted_wrong), "cases": accepted_wrong,
                                           "note": "gate opened (at iteration 0, or after repair) on code the oracle rejects; listed, never hidden"},
        "mutation": {"runs_with_data": len(with_rate), "mutants_killed": killed, "mutants_total": mutants,
                     "pooled_kill_rate": _rate(killed, mutants),
                     "mean_kill_rate": round(statistics.mean(r["mutation"]["kill_rate"] for r in with_rate), 3) if with_rate else None},
        "prompt_tokens": sum(known("prompt_tokens")) if known("prompt_tokens") else None,
        "completion_tokens": sum(known("completion_tokens")) if known("completion_tokens") else None,
        "model_calls": sum(r.get("model_calls") or 0 for r in ran),
        "cost_usd": round(sum(costs), 4) if costs else None, "runs_with_known_cost": len(costs),
        "cost_usd_per_run": round(sum(costs) / len(costs), 4) if costs else None,
        "wall_s": {"total": round(sum(walls), 1) if walls else None, "median": round(statistics.median(walls), 1) if walls else None},
    }


def verdict_counts(rows):
    """{VERDICT: n} over every run that reached a verdict, with all six keys present (0 when none)."""
    counts = {v: 0 for v in VERDICTS}
    for r in rows:
        if r.get("status") == "ran" and r.get("outcome") != "error" and r.get("verdict") in counts:
            counts[r["verdict"]] += 1
    return counts


def flaky_totals(rows):
    """{n_cases_checked, n_flaky, median_flake_rate} over runs whose receipt has a flaky check (`flaky.ran`)."""
    checked = [r["flaky"] for r in rows if r.get("status") == "ran" and isinstance(r.get("flaky"), dict) and r["flaky"].get("ran")]
    rates = [f["flake_rate"] for f in checked if f.get("flake_rate") is not None]
    return {"n_cases_checked": len(checked), "n_flaky": sum(1 for f in checked if f.get("flaky")),
            "median_flake_rate": round(statistics.median(rates), 3) if rates else None}
