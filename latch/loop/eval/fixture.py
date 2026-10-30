"""Stubbed model outputs for `latch eval run --dry-run` (alias --fixture): a deterministic, offline stand-in for a live run.

It builds an eval document and one receipt per (case, variant) in the real receipt schema, covering every verdict path (validated,
no regression found, flaky, wrong patch caught or accepted, no-fix correct or green-but-wrong). Nothing here is a measurement:
every receipt carries `"fixture": true` and the summary built from it says `"mode": "dry-run"`. It spends nothing and never
touches Token Factory, git or pytest. Use it to exercise the harness, the summary math and the report; never as a result.
"""

from ...modelcalls import estimate_cost, total_cost
from ...run import LIGHTNING, MODEL
from ...verdict import flake_summary

FIXTURE_NOTE = "FIXTURE: stubbed model output for a dry run, not a measurement"


def _red(name):
    return {"returncode": 1, "output": f"___ {name} ___\nE   AssertionError: fixture expected behaviour\n1 failed"}


def _green():
    return {"returncode": 0, "output": "1 passed"}


def _calls(i, variant, fixer):
    roles = [("repo_map", LIGHTNING, 2400, 300), ("test_writer", MODEL, 3100 + 40 * i, 420), ("triage", LIGHTNING, 1500, 90)]
    if fixer:
        roles.append(("fixer", MODEL, 5200 + 30 * i, 900))
    out = []
    for n, (role, model, p, c) in enumerate(roles):
        out.append({"role": role, "model": model, "prompt_tokens": p, "completion_tokens": c, "latency_ms": 900 + 100 * n,
                    "completion_id": f"fixture-{i}-{variant}-{n}", "cost_usd": estimate_cost(model, p, c), "status": 200})
    return out


def scenario(i, variant):
    """-> (outcome, receipt-parts dict). Deterministic in the case index and variant."""
    name = f"test_fixture_{i}"
    revert_ok = {"ran": True, "ok": True, "summary": "the proof test went red again on every mutant (fix reverted)",
                 "mutants": [{"name": "revert_fix_to_base", "failed_as_expected": True}]
                 + ([{"name": "restore_submitted_patch", "failed_as_expected": True}] if i % 3 == 0 else [])}
    parts = {"proof_test": {"name": name}, "triage": {"verdict": "reproduced", "model": LIGHTNING}, "iterations": []}
    if variant == "real":
        if i % 7 == 5:  # flaky proof test: one stray pass on base
            parts.update(initial={"base_proof": _red(name), "head_proof": _green(), "head_suite": _green(), "base_red": True,
                                  "head_suite_green": True, "gate_open": True},
                         flaky=flake_summary([False, False, True, False, False], [True] * 5), revert_check=revert_ok)
            return "gave_up", parts, "gave_up", "fixture: flaky proof test"
        if i % 5 == 3:  # the proof test passes on base: it does not detect the bug
            parts.update(initial={"base_proof": _green(), "base_red": False}, triage=None)
            return "gave_up", parts, "gave_up", "fixture: proof test does not fail on base"
        parts.update(initial={"base_proof": _red(name), "head_proof": _green(), "head_suite": _green(), "base_red": True,
                              "head_suite_green": True, "gate_open": True}, flaky=flake_summary([False] * 5, [True] * 5),
                     revert_check=revert_ok)
        return "proven", parts, "gate_open", "fixture: real fix validated"
    if variant == "wrong":
        if i % 5 == 2:  # a wrong patch the gate wrongly accepts (listed, never hidden)
            parts.update(initial={"base_proof": _red(name), "head_proof": _green(), "head_suite": _green(), "base_red": True,
                                  "head_suite_green": True, "gate_open": True}, revert_check=revert_ok)
            return "false_accept", parts, "gate_open", "fixture: wrong patch accepted"
        shut = {"base_proof": _red(name), "head_proof": _red(name), "head_suite": _green(), "base_red": True, "head_suite_green": True,
                "gate_open": False}
        parts.update(initial=shut, iterations=[{"iteration": 1, "verdict": "gate_open"}], revert_check=revert_ok)
        return ("repaired" if i % 2 else "shut_gave_up"), parts, ("gate_open" if i % 2 else "gave_up"), "fixture: wrong patch rejected"
    shut = {"base_proof": _red(name), "head_proof": _red(name), "head_suite": _green(), "base_red": True, "head_suite_green": True,
            "gate_open": False}
    parts.update(initial=shut, iterations=[{"iteration": 1, "verdict": "gate_open"}], revert_check=revert_ok)
    if i % 3 == 0:
        return "green_but_wrong", parts, "gate_open", "fixture: no-fix run opened the gate on code the oracle rejects"
    if i % 3 == 1:
        return "nemotron_fix_correct", parts, "gate_open", "fixture: no-fix run fixed correctly"
    return "gave_up", parts, "gave_up", "fixture: no-fix run gave up"


def make_fixture(cases, date="fixture"):
    """-> (eval document, {receipt path: receipt}) for every (case, variant) in `cases`."""
    runs, receipts = [], {}
    for i, case in enumerate(cases):
        for variant in (("real", "nofix") if case.get("swe") else ("real", "wrong")):
            outcome, parts, loop_verdict, reason = scenario(i, variant)
            calls = _calls(i, variant, fixer=bool(parts["iterations"]))
            path = f"fixture/{case['id']}-{variant}.json"
            receipts[path] = {"run_id": f"fixture-{case['id']}-{variant}", "fixture": True, "fixture_note": FIXTURE_NOTE,
                              "verdict": loop_verdict, "reason": reason, "model_calls": calls, "model_cost_usd": total_cost(calls), **parts}
            runs.append({"case": case["id"], "variant": variant, "label": variant, "outcome": outcome, "verdict": loop_verdict, "reason": reason,
                         "wall_seconds": round(20.0 + 3.5 * i + (8 if variant != "real" else 0), 1), "receipt": path,
                         "iterations_used": len(parts["iterations"]), "gate_open_at_iteration_0": outcome == "false_accept",
                         "completion_ids": {}, "triage_verdict": (parts.get("triage") or {}).get("verdict")})
    models = {"proof_test": MODEL, "fix": MODEL, "triage": LIGHTNING}
    return {"date": date, "models": models, "max_iterations": 3, "runs": runs, "cases": [], "fixture": True,
            "summary": {"note": FIXTURE_NOTE}}, receipts
