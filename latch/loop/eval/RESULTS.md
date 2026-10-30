# Latch evaluation

**Status: results pending.** No model credit was available when this was written (Token Factory returned HTTP 402
`credit_balance_exhausted`), so no eval has run and there are no numbers here. `latch/runs/eval-summary.json` does not
exist yet and will only be written by a real run. This file currently documents the method and the output schema;
the results section is added after the run.

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

## `latch/runs/eval-summary.json` schema (version 1)

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
