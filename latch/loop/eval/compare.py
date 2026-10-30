"""The Slopgate-style comparison block. Slopgate's numbers are quoted only as its own repo states them, with the link.

Slopgate (https://github.com/agno-nymous/slopgate) injects "slop" into SWE-bench Lite repos and measures whether its gate
flags it and whether the one-click rewrite it proves breaks a hidden test. Latch measures a different task: whether a PR's
fix is correct (a model-written test fails on base, passes on head, the suite stays green, and the test fails again with the
fix reverted). The two tables line up by shape (dataset, items, flagged, proven, broke a hidden test, cost), not by meaning.
"""

SLOPGATE = {
    "name": "Slopgate",
    "repo_url": "https://github.com/agno-nymous/slopgate",
    "readme_url": "https://github.com/agno-nymous/slopgate#readme",
    "results_url": "https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md",
    "run_date": "2026-10-25",
    "task": "removes injected code slop (redundant checks, wrappers, dead code, duplicates) and proves the rewrite keeps behavior",
    "dataset": "15 SWE-bench Lite instances from 7 repositories",
    "items": 45, "items_what": "injected slop items",
    "flagged": 41, "flagged_rate": 0.911,
    "proven": 14, "proven_of": 41, "proven_rate_of_flagged": 0.341, "proven_what": "flagged items that got a proven one-click fix",
    "review_note_only": 27,
    "broke_hidden_test": 0, "broke_hidden_test_of": 14,
    "cost_usd": 1.1632, "cost_note": "the README rounds it to $1.16 for the whole run (15 instances)",
    "judge": "the hidden SWE-bench tests of each instance, never shown to the gate",
    "models": "nvidia/nemotron-3-super-120b-a12b (tests and rewrites), nvidia/Nemotron-3-Ultra-550b-a55b (retry and summary)",
    "per_kind_note": "per-kind results (for example redundant_check 0/9 accepted, dead 5/6) are in the results file linked above",
}

DIFFERENT_TASKS = ("These two benchmarks measure different tasks, so the columns are parallel in shape, not in meaning. "
                   "Slopgate removes injected slop and proves the rewrite keeps behavior; Latch proves that a PR's fix is correct. "
                   "Slopgate's numbers are quoted from its own repo (link above), not re-run by Latch. The datasets, the instances "
                   "and the judges differ, and Latch's instance set is smaller and pools hand-built wrong patches with real fixes.")


def _frac(k, n):
    return None if not n else f"{k}/{n} ({k / n * 100:.0f}%)"


def latch_side(bench, cases):
    """Latch's column, from the benchmark totals. Everything not measured in this run is None, never a guess."""
    swe = [c for c in cases if c.get("suite") == "swebench_lite" and c.get("status") == "ran"]
    swe_cases = sorted({c["case"] for c in swe})
    ran_cases = sorted({c["case"] for c in cases if c.get("status") == "ran"})
    rej, val = bench["wrong_patch_rejection"], bench["real_validated"]
    nofix = bench["nofix_gate_open"]
    return {
        "dataset": f"{len(swe_cases)} SWE-bench Lite instances (1 repository, sympy) plus {len(ran_cases) - len(swe_cases)} upstream bug fixes",
        "swe_bench_lite_instances": len(swe_cases), "cases_with_a_run": len(ran_cases), "runs": bench["runs"],
        "wrong_patches_rejected": rej, "real_fixes_validated": val, "nofix_gate_open": nofix,
        "gate_accepted_but_oracle_fails": bench["gate_accepted_but_oracle_fails"]["n"],
        "cost_usd": bench["cost_usd"], "cost_usd_per_run": bench["cost_usd_per_run"],
    }


def table_rows(latch, mode):
    """[(row label, Slopgate cell, Latch cell)] for the Markdown report."""
    s = SLOPGATE
    na = "not run (needs live model credit)" if mode == "live" else "fixture value, not a result"
    tag = "" if mode == "live" else "[fixture, not a result] "
    def cell(ratio, label):
        return (tag + _frac(ratio["k"], ratio["n"]) + " " + label) if ratio and ratio["n"] else na
    rej = latch["wrong_patches_rejected"]
    val = latch["real_fixes_validated"]
    cost = latch["cost_usd"]
    return [
        ("Task", s["task"], "proves a PR's fix is correct: a model-written test fails on base, passes on head, the repo suite stays green, "
                            "and the test fails again with the fix reverted"),
        ("Dataset", s["dataset"], latch["dataset"]),
        ("Items tested", f"{s['items']} {s['items_what']}", f"{latch['runs']} runs: real fixes, hand-built wrong patches, and no-fix (the model writes the patch)"),
        ("Flagged / caught", f"{s['flagged']}/{s['items']} ({s['flagged_rate'] * 100:.0f}%) injected slop items flagged",
         cell(rej, "wrong patches rejected (gate shut before any repair)")),
        ("Proven", f"{s['proven']}/{s['proven_of']} ({s['proven_rate_of_flagged'] * 100:.0f}%) flagged items got a proven one-click fix",
         cell(val, "real fixes VALIDATED (red on base, green on head, suite green, revert check)")),
        ("Broke a hidden test", f"{s['broke_hidden_test']} of the {s['broke_hidden_test_of']} proven fixes",
         (tag + f"{latch['gate_accepted_but_oracle_fails']} gate-accepted patches the oracle (the upstream tests) rejects"
          if latch["runs"] else na)),
        ("Judge", s["judge"], "the upstream fix's own tests (upstream cases) or the instance's FAIL_TO_PASS tests (SWE-bench Lite), never shown to the model"),
        ("Cost", f"${s['cost_usd']:.2f} total for the run" if s.get("cost_usd") else na,
         (tag + f"${cost:.2f} total over {latch['runs']} runs (${latch['cost_usd_per_run']:.3f} per run), from receipt model_calls" if cost is not None else na)),
    ]
