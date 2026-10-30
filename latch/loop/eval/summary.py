"""Build latch/runs/eval-summary.json (the numbers latch-web shows) from a finished eval run.

Pure functions: `build_summary(doc, cases, load_receipt)` takes the eval document that run_eval writes, the full
case list (so cases that did not run show up as "not run", never vanish) and a loader for receipts.
Schema: see latch/loop/eval/RESULTS.md ("eval-summary.json schema"). There is no placeholder output: this module
only runs on a real eval document.
"""

import datetime
import json
import statistics
from pathlib import Path

from . import bench, compare

SCHEMA_VERSION = 2  # v2 is additive over v1; the one exception: cases[].verdict is now the named verdict (v1 loop verdict -> cases[].loop_verdict)
CONTESTED = ("cachetools-423", "click-3360")  # the second reviewer called the wrong patch "equivalent"; I do not; both reported
CONTESTED_NOTE = ("A second reviewer (codex) judged the constructed wrong patches for these cases semantically equivalent "
                  "to the real fix; I judge them wrong. Both counts are reported, with and without them.")
BASELINES = [
    {"name": "Otter (GPT-4o)", "metric": "fail-to-pass rate", "value": 0.314, "benchmark": "TDD-Bench-Verified (449 issues)",
     "source_url": "https://arxiv.org/abs/2502.05368", "note": "Otter++ (5-test ensemble) reaches 37.0%."},
    {"name": "AssertFlip", "metric": "fail-to-pass rate", "value": 0.436, "benchmark": "SWT-Bench-Verified (433 issues)",
     "source_url": "https://arxiv.org/abs/2507.17542", "note": "189 of 433 issues."},
]
CAVEAT = ("Small sample: the cases here are few, single runs, with an LLM that is not deterministic, so the rates carry wide "
          "uncertainty. The wrong patches are constructed by hand (not agent output). The baselines use different benchmarks "
          "and a different, weaker success condition (fail-to-pass only, no revert check, no wrong-patch test), so the "
          "numbers are not directly comparable.")


def _rate(k, n):
    return round(k / n, 3) if n else None


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 4) if values else None


def _kind(case):
    return "swebench_lite" if case.get("swe") else "upstream"


def _relative(path, root):
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return str(path)


def build_summary(doc, cases, load_receipt=lambda path: None, dropped=(), generated_at=None, root=".", oracle=None, manifest=None,
                  mode="live", latch_git_sha=None):
    runs = {(r["case"], r["variant"]): r for r in doc["runs"]}
    dropped_by_id = {}
    for d in dropped:
        reason = d.get("reason", "")
        dropped_by_id.setdefault(d["id"], "; ".join(map(str, reason)) if isinstance(reason, (list, tuple)) else str(reason))
    case_ids = {c["id"] for c in cases}
    suite_of = {c["id"]: _kind(c) for c in cases}
    rows, validator, abstentions, failures = [], [], [], []
    for case in cases:
        variants = ("real", "nofix") if case.get("swe") else ("real", "wrong")
        for variant in variants:
            run = runs.get((case["id"], variant))
            base = {"case": case["id"], "suite": suite_of[case["id"]], "variant": variant, "repo": case["repo"], "title": case.get("title"),
                    "contested": case["id"] in CONTESTED and variant == "wrong"}
            if run is None:
                why = ("dropped before the run: " + dropped_by_id[case["id"]]) if case["id"] in dropped_by_id else \
                    "this case did not run in this evaluation (it is listed so the omission is visible)"
                rows.append({**base, "status": "not run", "outcome": None, "reason": why, "verdict": None, "verdict_reason": None,
                             "loop_verdict": None, "flaky": None, "mutation": None})
                continue
            receipt = load_receipt(run.get("receipt")) or {}
            row = {**base, "status": "ran", "label": run.get("label"), "outcome": run["outcome"], "loop_verdict": run.get("verdict"),
                   "reason": run.get("reason"), "wall_s": run.get("wall_seconds"), "cost_usd": receipt.get("model_cost_usd", run.get("model_cost_usd")),
                   "iterations_used": run.get("iterations_used"), "gate_open_at_iteration_0": run.get("gate_open_at_iteration_0"),
                   "completion_ids": run.get("completion_ids"), "receipt": _relative(run.get("receipt"), root),
                   "links": next((m.get("links") for m in doc.get("cases", []) if m["id"] == case["id"]), None)}
            row.update(bench.case_metrics(variant, run, receipt))
            rows.append(row)
            for attempt in receipt.get("proof_test_attempts") or []:
                if not attempt.get("valid"):
                    validator.append({"case": case["id"], "variant": variant, "attempt": attempt.get("attempt"),
                                      "rejection": attempt.get("rejection"), "completion_id": attempt.get("completion_id"),
                                      "receipt": row["receipt"]})
            if run["outcome"] == "error":
                failures.append({"case": case["id"], "variant": variant, "reason": run.get("reason"), "receipt": row["receipt"]})
            elif run["outcome"] in ("gave_up", "shut_gave_up"):
                triage = (receipt.get("triage") or {}).get("verdict") or run.get("triage_verdict")
                kind = "triage_not_reproduced" if triage in ("not_reproduced", "unclear") else "gave_up"
                abstentions.append({"case": case["id"], "variant": variant, "kind": kind, "reason": run.get("reason"),
                                    "receipt": row["receipt"]})

    ran = [r for r in rows if r["status"] == "ran"]
    suites = {}
    for name in ("upstream", "swebench_lite"):
        real = [r for r in ran if r["suite"] == name and r["variant"] == "real"]
        proven = sum(1 for r in real if r["outcome"] == "proven")
        suites[name] = {"n": len(real), "proven": proven, "proven_rate": _rate(proven, len(real)),
                        "errors": sum(1 for r in real if r["outcome"] == "error"),
                        "not_run": sum(1 for r in rows if r["suite"] == name and r["variant"] == "real" and r["status"] == "not run")}
    nofix = [r for r in ran if r["variant"] == "nofix"]
    suites["swebench_lite"]["nemotron_fix"] = {
        "n": len(nofix), "gate_open": sum(1 for r in nofix if r["outcome"] in ("nemotron_fix_correct", "green_but_wrong")),
        "oracle_pass": sum(1 for r in nofix if r["outcome"] == "nemotron_fix_correct"),
        "green_but_wrong": [r["case"] for r in nofix if r["outcome"] == "green_but_wrong"],
        "note": "no fix submitted: Nemotron wrote the patch; oracle = the instance's own FAIL_TO_PASS tests, never shown to the model"}

    wrong = [r for r in ran if r["variant"] == "wrong" and r["outcome"] != "error"]

    def caught(rs):
        return {"n": len(rs), "caught": sum(1 for r in rs if r["outcome"] != "false_accept")}

    false_accepts = [r["case"] for r in wrong if r["outcome"] == "false_accept"]
    wrong_fixes = {**caught(wrong), "rule": "caught = the gate was shut at iteration 0 on the wrong patch (before any repair)",
                   "without_contested": caught([r for r in wrong if r["case"] not in CONTESTED]),
                   "contested_cases": [c for c in CONTESTED if any(r["case"] == c for r in wrong)],
                   "contested_note": CONTESTED_NOTE, "false_accepts": false_accepts,
                   "errors": sum(1 for r in ran if r["variant"] == "wrong" and r["outcome"] == "error"),
                   "not_run": sum(1 for r in rows if r["variant"] == "wrong" and r["status"] == "not run"),
                   "repaired_by_loop": {"n": sum(1 for r in wrong if r["outcome"] in ("repaired", "repaired_but_oracle_fails")),
                                        "oracle_pass": sum(1 for r in wrong if r["outcome"] == "repaired")}}

    featured, featured_note = None, None
    shut = [r for r in wrong if r.get("loop_verdict") == "gave_up" and r["receipt"]]
    if shut:
        featured = shut[0]["receipt"]
        featured_note = "NOT PROVEN: the gate stayed shut on a wrong patch"
    else:
        early = [r for r in wrong if r["outcome"] in ("repaired", "repaired_but_oracle_fails") and r["receipt"]]
        if early:
            featured = early[0]["receipt"]
            featured_note = ("the gate was shut on the wrong patch at iteration 0 (NOT PROVEN); the loop then repaired it, "
                             "so this receipt ends gate_open: no run ended with the wrong patch still shut")

    real_all = [r for r in ran if r["variant"] == "real"]
    proven_all = sum(1 for r in real_all if r["outcome"] == "proven")
    pct = lambda v: f"{v * 100:.1f}%"
    comparison = (f"On real fixes Latch proved {proven_all}/{len(real_all)} ({pct(proven_all / len(real_all)) if real_all else 'n/a'}) "
                  f"against Otter's 31.4% (TDD-Bench-Verified) and AssertFlip's 43.6% (SWT-Bench-Verified) fail-to-pass rates, "
                  f"but with only {len(real_all)} cases, on different benchmarks and a different pass condition (proof test plus repo suite "
                  f"plus revert check), so treat it as a small-sample indication, not a like-for-like comparison.")
    benchmark = bench.totals(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,  # "live" (real model calls) or "dry-run" (fixture receipts, spends nothing; never a result)
        "fixture": mode != "live",
        "latch_git_sha": latch_git_sha,
        "verdicts": bench.verdict_counts(rows),
        "flaky": bench.flaky_totals(rows),
        "benchmark": benchmark,
        "slopgate_comparison": {"slopgate": compare.SLOPGATE, "latch": compare.latch_side(benchmark, rows),
                                "caveat": compare.DIFFERENT_TASKS},
        "oracle_baseline": oracle,
        "manifest": manifest,
        "generated_at": generated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_run": doc.get("date"), "models": doc.get("models"), "max_iterations": doc.get("max_iterations"),
        "suites": suites,
        "wrong_fixes": wrong_fixes,
        "median_wall_s": _median([r["wall_s"] for r in ran]),
        "median_cost_usd": _median([r["cost_usd"] for r in ran]),
        "runs_with_known_cost": sum(1 for r in ran if r["cost_usd"] is not None),
        "runs": len(ran),
        "validator_rejections": {"n": len(validator), "runs_affected": len({(v["case"], v["variant"]) for v in validator}),
                                 "note": "proof tests the harness rejected as vacuous or malformed before running the gate", "items": validator},
        "abstentions": {"n": len(abstentions), "note": "runs where the gate stayed shut and Latch gave up, or triage said the failure did not reproduce the issue",
                        "items": abstentions},
        "failures": {"n": len(failures), "items": failures},
        "not_run": [{"case": r["case"], "variant": r["variant"], "reason": r["reason"]} for r in rows if r["status"] == "not run"]
                   + [{"case": i, "variant": None, "reason": "dropped before the run: " + why}
                      for i, why in dropped_by_id.items() if i not in case_ids],
        "dropped_cases": [{"id": i, "reason": why} for i, why in dropped_by_id.items()],
        "baselines": BASELINES,
        "comparison": comparison,
        "caveat": CAVEAT,
        "featured_wrong_fix_receipt": featured,
        "featured_wrong_fix_note": featured_note,
        "cases": rows,
    }


def write_summary(path, doc, cases, load_receipt, dropped=(), root=".", **kwargs):
    summary = build_summary(doc, cases, load_receipt, dropped, root=root, **kwargs)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def extras(root):
    """oracle baseline, compact manifest and the Latch git SHA, each only if it exists: {oracle, manifest, latch_git_sha}."""
    root = Path(root)
    oracle_file = root / "latch" / "runs" / "eval-oracle-baseline.json"
    oracle = json.loads(oracle_file.read_text()) if oracle_file.exists() else None
    manifest_file = root / "latch" / "loop" / "eval" / "manifest.json"
    manifest = None
    if manifest_file.exists():
        m = json.loads(manifest_file.read_text())
        manifest = {"path": "latch/loop/eval/manifest.json", "models": m.get("models"), "latch": m.get("latch"),
                    "prompts": [{"role": p["role"], "path": p["path"], "sha256": p["sha256"]} for p in m.get("prompts", [])],
                    "dataset": {k: (m.get("dataset") or {}).get(k) for k in ("name", "revision", "n_instances")}}
    from .manifest import latch_git
    return {"oracle": oracle, "manifest": manifest, "latch_git_sha": latch_git(root).get("sha")}
