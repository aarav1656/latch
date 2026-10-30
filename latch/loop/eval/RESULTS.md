# Latch evaluation

**Status: live Nebius Token Factory run complete (2026-10-30, Latch 74c9f41, 3 iterations max, 3 jobs).** Numbers below come from
`latch/runs/eval-2026-10-30.json` / `latch/runs/eval-summary.json` / `latch/runs/eval-report.md`. One run per case, no cherry-picking, no reruns of the eval.

## Results (live, Nemotron-3-Ultra-550b-a55b writes tests and fixes)

| Measure | Result |
|---|---|
| Real fixes VALIDATED (red on base, green on head, suite green, stable, revert and mutation checks) | **7/21 (33%)**: upstream 3/9, SWE-bench Lite sympy 4/12 (small sample, wide uncertainty) |
| Real fixes that ended INVALID_TEST | 12/21: 3 NameError (test forgot an import), 6 the bug's own exception propagated uncaught instead of an assertion (cachetools-423, toolz-602, sympy-22005, 22714, 24066, 24213), 1 IndexError in the test, 1 missing optional package (antlr4), 1 triage unclear. The other 2 real runs: NO_REGRESSION_FOUND 1, FIX_FAILS_TEST 1 |
| Wrong patches, gate shut for any reason | 8/9 (6/7 without the two contested cases) |
| **Wrong patches failed by a valid proof test (FIX_FAILS_TEST)** | **3/9 (2/7 without the contested cases)**. The other 5 "shut" runs had an INVALID_TEST proof test, so the gate stayed shut for the wrong reason; do not read 8/9 as a rejection rate |
| Wrong patches that got through | 1/9: packaging-810 passed the gate (VALIDATED, 5/5 mutants killed) but the upstream tests reject it |
| No-fix (Nemotron writes the patch) runs where the gate opened | 0/12 |
| Verdict counts (42 runs) | INVALID_TEST 23, FIX_FAILS_TEST 10, VALIDATED 8, NO_REGRESSION_FOUND 1, FLAKY 0, MUTATION_SURVIVED 0 |
| Flaky check | 9 runs checked, 0 flaky |
| Mutation kill rate (pooled, VALIDATED runs) | 23/23 |
| Cost (from receipt model_calls; an upper bound at list prices) | $1.38 over 42 runs, median $0.009 per run |
| Wall time | 21.6 min elapsed with 3 jobs (2803 s summed over runs), median 56 s per run |

Contested cases (a second reviewer judged the constructed wrong patch equivalent to the real fix; I judge them wrong), both ways:
cachetools-423 wrong: gate shut, but on an INVALID_TEST proof test (`TypeError`), so neither a rejection nor an acceptance by merit; click-3360 wrong:
FIX_FAILS_TEST after 3 iterations, with a valid proof test (the real fix was VALIDATED). With them: 8/9 shut, 3/9 on a valid test; without: 6/7 and 2/7.

Baselines for context only, on different benchmarks and a weaker pass condition: Otter 31.4%, AssertFlip 43.6% fail-to-pass.
The dominant failure mode is the model's proof test, not the fixer: most INVALID_TEST runs are a test that never reached an assertion.
A single repair retry for that (feed the error back to the test writer) is not in this run.

The one measured thing so far is the **oracle baseline (no model)**: the human-written upstream tests, run for real with git and
pytest, $0, no Token Factory call. Over the 21 kept cases the upstream tests fail on base for 21/21, pass on the real fix for
21/21, and reject the constructed wrong patch for 9/9 upstream cases (total 185 s wall with 3 jobs; `latch/runs/eval-oracle-baseline.json`,
`.md`). That is the answer key the gate is judged against, not a Latch result: the cases were selected for this property (3 were
dropped before any run: cachetools-221, boltons-4457decc, boltons-8177b933), so the oracle separates real from wrong by construction.
Run `latch eval run --dry-run` to exercise the whole pipeline on stubbed
output (clearly labelled, never written to `latch/runs/eval-summary.json`).

## What is measured

Two suites, one gate (`latch.loop`): a model-written proof test must fail on the base commit with an assertion, pass on
the head commit, keep the repo suite green, and fail again when the harness reverts the fix (revert/mutation check).

| Suite | Cases | Variants run per case |
|---|---|---|
| `upstream` | real upstream bug fixes from small pure-Python repos (cachetools, boltons, tabulate, toolz, packaging, more-itertools, click) | `real` (the true fix), `wrong` (a hand-constructed plausible-but-wrong patch) |
| `swebench_lite` | 12 real SWE-bench Lite sympy instances (instance data fetched from the Hugging Face datasets-server) | `real` (the gold source patch), `nofix` (no patch submitted; Nemotron writes the fix; the instance's own FAIL_TO_PASS tests are the oracle and are never shown to the model) |

Dropped before running, with reasons recorded in the output: cachetools-221, boltons-4457decc, boltons-8177b933.
The wrong patches are constructed by hand, not agent output. Two of them (cachetools-423, click-3360) are **contested**:
a second reviewer judged them semantically equivalent to the real fix and I judge them wrong, so every wrong-fix number is
reported with and without them.

Models: `nvidia/Nemotron-3-Ultra-550b-a55b` writes proof tests and fixes; `nvidia/Nemotron-3_5-Lightning` builds the repo
map and does reproduction triage.

## Baselines

| Baseline | Metric | Benchmark | Source |
|---|---|---|---|
| Otter (GPT-4o) | 31.4% fail-to-pass (Otter++: 37.0%) | TDD-Bench-Verified, 449 issues | https://arxiv.org/abs/2502.05368 |
| AssertFlip | 43.6% fail-to-pass (189/433) | SWT-Bench-Verified | https://arxiv.org/abs/2507.17542 |

Not like-for-like: different benchmarks, and Latch's "proven" additionally needs a green repo suite and a revert check.

## `latch/runs/eval-summary.json` schema (version 1; see version 2 below)

Written by `python3 -m latch.loop.eval.run_eval run ...` (or rebuilt with `... run_eval summarize latch/runs/eval-DATE.json`).
Per-case receipts are copied to `latch/runs/eval/<case>-<variant>.json` (`variant` is `real`, `wrong` or `nofix`). Every path
in the file is relative to the repo root. A value that is unknown is `null`, never `0`.

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-30T09:00:00Z",
  "source_run": "2026-10-30",              // the date in latch/runs/eval-DATE.json
  "models": {...}, "max_iterations": 3,

  "suites": {                               // headline: real fixes, split by suite
    "upstream":      {"n": 9, "proven": 0, "proven_rate": 0.0, "errors": 0, "not_run": 0},
    "swebench_lite": {"n": 12, "proven": 0, "proven_rate": 0.0, "errors": 0, "not_run": 0,
      "nemotron_fix": {                     // the nofix variant: Nemotron writes the fix itself
        "n": 12, "gate_open": 0, "oracle_pass": 0,
        "green_but_wrong": ["sympy-NNNNN"], // gate open but the oracle fails: the gate was fooled; listed, never hidden
        "note": "..."}}
  },                                        // n counts real-variant runs that executed (errors included); not_run is separate

  "wrong_fixes": {                          // constructed wrong patches given to the gate
    "n": 0, "caught": 0,                    // caught = gate shut at iteration 0, before any repair; runs that errored are NOT counted
    "rule": "...",
    "without_contested": {"n": 0, "caught": 0},
    "contested_cases": ["cachetools-423", "click-3360"], "contested_note": "...",
    "false_accepts": ["case-id"],           // wrong patch accepted at iteration 0
    "errors": 0, "not_run": 0,
    "repaired_by_loop": {"n": 0, "oracle_pass": 0}   // loop turned shut into open; oracle_pass = repair also passes the real test
  },

  "median_wall_s": 0.0,                     // over every run that executed
  "median_cost_usd": 0.0,                   // over runs with a known cost (an upper bound: cached-token discounts are not applied)
  "runs_with_known_cost": 0, "runs": 0,

  "validator_rejections": {"n": 0, "runs_affected": 0, "note": "...",   // vacuous / malformed proof tests the harness threw out
    "items": [{"case": "", "variant": "", "attempt": 1, "rejection": "", "completion_id": "", "receipt": ""}]},
  "abstentions": {"n": 0, "note": "...",     // gate stayed shut and Latch gave up, or triage said "did not reproduce"
    "items": [{"case": "", "variant": "", "kind": "triage_not_reproduced|gave_up", "reason": "", "receipt": ""}]},
  "failures": {"n": 0, "items": [{"case": "", "variant": "", "reason": "", "receipt": null}]},   // errors, shown not hidden
  "not_run": [{"case": "", "variant": "real|wrong|nofix|null", "reason": ""}],                    // never omitted

  "baselines": [{"name": "Otter (GPT-4o)", "metric": "", "value": 0.314, "benchmark": "", "source_url": "", "note": ""},
                {"name": "AssertFlip", "value": 0.436, "source_url": "..."}],
  "comparison": "one sentence vs Otter and AssertFlip, with the small-sample caveat",
  "caveat": "sample-size caveat string",

  "featured_wrong_fix_receipt": "latch/runs/eval/<case>-wrong.json",  // a real NOT PROVEN receipt for a wrong patch; null if none exists
  "featured_wrong_fix_note": "NOT PROVEN: ...",    // says so honestly if the receipt is a shut-then-repaired run

  "cases": [{                               // one row per case x variant, every case listed
    "case": "", "suite": "upstream|swebench_lite", "variant": "real|wrong|nofix", "repo": "", "title": "", "contested": false,
    "status": "ran|not run",
    "outcome": "proven|gave_up|false_accept|repaired|repaired_but_oracle_fails|shut_gave_up|nemotron_fix_correct|green_but_wrong|error|null",
    "verdict": "gate_open|gave_up|error", "reason": "", "wall_s": 0.0, "cost_usd": 0.0, "iterations_used": 0,
    "gate_open_at_iteration_0": false, "completion_ids": {}, "receipt": "latch/runs/eval/<case>-<variant>.json", "links": {}
  }]
}
```

Receipts contain `model_calls[]` (role, model, tokens, latency, completion id, cost), `steps[]`, `revert_check` and the repo map.

## Schema version 2 (additive over version 1)

`schema_version` is 2. Every v1 key above is still written with the same meaning, with **one exception**: `cases[].verdict` is now the
Latch *named verdict* (one of `INVALID_TEST`, `FLAKY`, `NO_REGRESSION_FOUND`, `FIX_FAILS_TEST`, `MUTATION_SURVIVED`, `VALIDATED`; see
`latch/verdict.py`); the v1 loop verdict (`gate_open|gave_up|error`) moved to `cases[].loop_verdict`. The named verdict is the verdict of
the change as submitted (iteration 0, before any repair), so a wrong patch reads `FIX_FAILS_TEST` and a repaired one is still shown by
`outcome`. If a receipt has no named verdict, the harness derives it with `decide_verdict` from the receipt's own evidence
(`verdict_source: "derived"`); a receipt that carries one is used as is (`"receipt"`).

New per-case keys (`null` when unknown, never `0`): `verdict_reason`, `verdict_source`, `flaky` (the receipt's `flaky` dict:
`{ran, runs, base_fail_rate, head_pass_rate, flake_rate, flaky, outcomes, note}`), `mutation {killed, total, kill_rate}` and
`mutation_source`, `fail_on_base`, `pass_on_head`, `fail_to_pass`, `suite_green_on_head`, `wrong_patch_rejected`, `prompt_tokens`,
`completion_tokens`, `model_calls`, `tokens_by_role`, `loop_verdict`. `cost_usd` and `wall_s` come from receipt `model_calls` and the run.

New top-level keys:

```jsonc
{
  "verdicts": {"INVALID_TEST": 0, "FLAKY": 0, "NO_REGRESSION_FOUND": 0, "FIX_FAILS_TEST": 0, "MUTATION_SURVIVED": 0, "VALIDATED": 0},
  "flaky": {"n_cases_checked": 0, "n_flaky": 0, "median_flake_rate": null},   // runs whose receipt has flaky.ran
  "mode": "live|dry-run", "fixture": false,    // dry-run = stubbed output, never a result; written only under latch/runs/eval-dryrun/
  "latch_git_sha": "", "dropped_cases": [{"id": "", "reason": ""}],
  "benchmark": {"runs": 0, "real_validated": {"k": 0, "n": 0, "rate": null}, "real_fail_on_base": {}, "real_fail_to_pass": {},
                "wrong_patch_rejection": {"k": 0, "n": 0, "rate": null, "without_contested": {}}, "nofix_gate_open": {},
                "gate_accepted_but_oracle_fails": {"n": 0, "cases": []}, "mutation": {"pooled_kill_rate": null},
                "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "wall_s": {"total": 0.0, "median": 0.0}},
  "slopgate_comparison": {"slopgate": {...}, "latch": {...}, "caveat": "..."},   // Slopgate's numbers as its repo states them, with links
  "oracle_baseline": null,                     // embeds latch/runs/eval-oracle-baseline.json when present
  "manifest": null                             // compact view of latch/loop/eval/manifest.json when present
}
```

### Slopgate comparison

Slopgate (https://github.com/agno-nymous/slopgate; results https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md,
run 2026-10-25) injects slop into 15 SWE-bench Lite instances, flags 41 of 45 items (91%), proves a one-click fix for 14 of the 41 (34%),
broke 0 hidden tests and cost $1.16. Latch's table is parallel in shape (dataset, items, flagged, proven, broke a hidden test, cost) but
not in meaning: Slopgate proves a slop rewrite keeps behavior, Latch proves a PR's fix is correct. Mapping: flagged is wrong patches
rejected, proven is real fixes `VALIDATED`, broke a hidden test is gate-accepted patches the oracle rejects. Slopgate was not re-run.

### Commands

```
latch eval run --dry-run                 # stubbed model output, spends nothing; writes latch/runs/eval-dryrun/ (git-ignored)
latch eval oracle                        # oracle baseline (no model), real git + pytest, $0
latch eval manifest --write | --check    # pin models, prompt hashes, dataset revision, repo SHAs, Latch SHA
latch eval report [--summary F] [--out F]
# LIVE (spends Token Factory credit; do not run without it):
LATCH_EVAL_ROOT=/Volumes/PortableSSD/nvdia/loop latch eval run --jobs 3 --max-iterations 3
```

A live run writes `latch/runs/eval-DATE.json`, `latch/runs/eval/<case>-<variant>.json`, `latch/runs/eval-summary.json` and
`latch/runs/eval-report.md`. `latch eval summarize latch/runs/eval-DATE.json` rebuilds the last two.
