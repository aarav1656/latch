# Latch eval report

Generated 2026-10-30T13:29:09Z. Schema 2. Latch `324f08d5208fc91e8ac558a00f6c71f13a7e0b77`.

## Comparison with Slopgate

Slopgate's column is quoted from its own repo (https://github.com/agno-nymous/slopgate; results file https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md, run 2026-10-25); Latch did not re-run it.

| | Slopgate (its own numbers) | Latch (this eval) |
|---|---|---|
| Task | removes injected code slop (redundant checks, wrappers, dead code, duplicates) and proves the rewrite keeps behavior | proves a PR's fix is correct: a model-written test fails on base, passes on head, the repo suite stays green, and the test fails again with the fix reverted |
| Dataset | 15 SWE-bench Lite instances from 7 repositories | 0 SWE-bench Lite instances (1 repository, sympy) plus 5 upstream bug fixes |
| Items tested | 45 injected slop items | 10 runs: real fixes, hand-built wrong patches, and no-fix (the model writes the patch) |
| Flagged / caught | 41/45 (91%) injected slop items flagged | 4/5 (80%) wrong patches with the gate shut before any repair (only 4/5 by a valid proof test, FIX_FAILS_TEST; the rest had an INVALID_TEST proof test) |
| Proven | 14/41 (34%) flagged items got a proven one-click fix | 5/5 (100%) real fixes VALIDATED (red on base, green on head, suite green, revert check) |
| Broke a hidden test | 0 of the 14 proven fixes | 1 gate-accepted patches the oracle (the upstream tests) rejects |
| Judge | the hidden SWE-bench tests of each instance, never shown to the gate | the upstream fix's own tests (upstream cases) or the instance's FAIL_TO_PASS tests (SWE-bench Lite), never shown to the model |
| Cost | $1.16 total for the run | $0.43 total over 10 runs ($0.043 per run), from receipt model_calls |

These two benchmarks measure different tasks, so the columns are parallel in shape, not in meaning. Slopgate removes injected slop and proves the rewrite keeps behavior; Latch proves that a PR's fix is correct. Slopgate's numbers are quoted from its own repo (link above), not re-run by Latch. The datasets, the instances and the judges differ, and Latch's instance set is smaller and pools hand-built wrong patches with real fixes.

## Named verdicts

| Verdict | Runs |
|---|---|
| INVALID_TEST | 0 |
| FLAKY | 0 |
| NO_REGRESSION_FOUND | 0 |
| FIX_FAILS_TEST | 4 |
| MUTATION_SURVIVED | 0 |
| VALIDATED | 6 |

Flaky check: 6 runs checked, 0 flaky, median flake rate 0.0.

## Totals

| Measure | Value |
|---|---|
| Runs (errors, not run) | 10 (0, 32) |
| Real fixes VALIDATED | 5/5 (100%) |
| Proof test fails on base (real fixes) | 5/5 (100%) |
| Fail-to-pass (fails on base and passes on head) | 5/5 (100%) |
| Wrong patches where the gate shut (any reason, including an INVALID_TEST proof test) | 4/5 (80%) |
| ... without the contested cases | 3/4 (75%) |
| Wrong patches failed by a valid proof test (verdict FIX_FAILS_TEST) | 4/5 (80%) |
| ... without the contested cases | 3/4 (75%) |
| No-fix runs where the gate opened | not run |
| Gate-accepted but oracle rejects | 1 |
| Mutation kill rate (pooled) | 1.0 (17/17 mutants) |
| Tokens (prompt / completion) | 147020 / 153292 |
| Cost | $0.4309 |
| Wall time (total / median per run) | 905.0 s / 79.8 s |

## Test repair

Run `ab-super`: the one-round test repair was on. It fired in 0 run(s) (one extra test-writer call each), the repaired test was adopted in 0, no longer errored in 0, and was rejected (original kept) in 0. A repaired test goes through the whole gate; thresholds are unchanged.

## Oracle baseline (no model)

Upstream tests on base, real and wrong, no LLM, $0: fails on base 21/21 (100%), passes on real fix 21/21 (100%), rejects wrong patch 9/9 (100%). The answer key the model never sees; kept cases were selected for this property.

## Baselines from the literature

| Baseline | Metric | Value | Benchmark | Source |
|---|---|---|---|---|
| Otter (GPT-4o) | fail-to-pass rate | 31.4% | TDD-Bench-Verified (449 issues) | https://arxiv.org/abs/2502.05368 |
| AssertFlip | fail-to-pass rate | 43.6% | SWT-Bench-Verified (433 issues) | https://arxiv.org/abs/2507.17542 |

Small sample: the cases here are few, single runs, with an LLM that is not deterministic, so the rates carry wide uncertainty. The wrong patches are constructed by hand (not agent output). The baselines use different benchmarks and a different, weaker success condition (fail-to-pass only, no revert check, no wrong-patch test), so the numbers are not directly comparable.

## Per case

| Case | Variant | Verdict | Fail on base | Pass on head | Mutation | Flaky | Tokens in/out | Cost | Wall s | Outcome |
|---|---|---|---|---|---|---|---|---|---|---|
| cachetools-423 | real | not run | | | | | | | | not run |
| cachetools-423 | wrong | not run | | | | | | | | not run |
| boltons-319 | real | VALIDATED | yes | yes | 5/5 | stable (0.0) | 4608/3532 | $0.003262 | 88.1 | proven |
| boltons-319 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 42085/30877 | $0.116525 | 136.0 | shut_gave_up |
| tabulate-180 | real | not run | | | | | | | | not run |
| tabulate-180 | wrong | not run | | | | | | | | not run |
| tabulate-190 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 5985/16360 | $0.015624 | 68.6 | proven |
| tabulate-190 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 10747/34495 | $0.089339 | 155.8 | shut_gave_up |
| toolz-602 | real | not run | | | | | | | | not run |
| toolz-602 | wrong | not run | | | | | | | | not run |
| packaging-810 | real | VALIDATED | yes | yes | 4/4 | stable (0.0) | 5853/4142 | $0.004224 | 57.7 | proven |
| packaging-810 | wrong | VALIDATED | yes | yes | 5/5 | stable (0.0) | 3847/4170 | $0.003649 | 71.6 | false_accept |
| more-itertools-409 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 2420/2107 | $0.001816 | 21.3 | proven |
| more-itertools-409 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 14096/31567 | $0.091145 | 128.4 | shut_gave_up |
| click-3360 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 6249/4267 | $0.004425 | 39.5 | proven |
| click-3360 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 51130/21775 | $0.100898 | 138.0 | shut_gave_up |
| click-3019 | real | not run | | | | | | | | not run |
| click-3019 | wrong | not run | | | | | | | | not run |
| sympy-21612 | real | not run | | | | | | | | not run |
| sympy-21612 | nofix | not run | | | | | | | | not run |
| sympy-21614 | real | not run | | | | | | | | not run |
| sympy-21614 | nofix | not run | | | | | | | | not run |
| sympy-21627 | real | not run | | | | | | | | not run |
| sympy-21627 | nofix | not run | | | | | | | | not run |
| sympy-21847 | real | not run | | | | | | | | not run |
| sympy-21847 | nofix | not run | | | | | | | | not run |
| sympy-22005 | real | not run | | | | | | | | not run |
| sympy-22005 | nofix | not run | | | | | | | | not run |
| sympy-22714 | real | not run | | | | | | | | not run |
| sympy-22714 | nofix | not run | | | | | | | | not run |
| sympy-24066 | real | not run | | | | | | | | not run |
| sympy-24066 | nofix | not run | | | | | | | | not run |
| sympy-24213 | real | not run | | | | | | | | not run |
| sympy-24213 | nofix | not run | | | | | | | | not run |
| sympy-24909 | real | not run | | | | | | | | not run |
| sympy-24909 | nofix | not run | | | | | | | | not run |
| sympy-21055 | real | not run | | | | | | | | not run |
| sympy-21055 | nofix | not run | | | | | | | | not run |
| sympy-20590 | real | not run | | | | | | | | not run |
| sympy-20590 | nofix | not run | | | | | | | | not run |
| sympy-23262 | real | not run | | | | | | | | not run |
| sympy-23262 | nofix | not run | | | | | | | | not run |

## Dropped before any run

- `cachetools-221`: no usable constructed wrong patch: the fix changes an expiry-boundary comparison that the repo's own suite pins in many places, so the only plausible mutation (`<` to `<=` in expire()) turns the base suite red (14 failures). A wrong patch that keeps the suite green could not be built honestly.
- `boltons-4457decc`: the repo's own pytest_ignore_collect hook defeats --ignore, so the old-commit suite cannot be run cheaply
- `boltons-8177b933`: same as boltons-4457decc
