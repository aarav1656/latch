# Latch eval report

Generated 2026-10-30T08:36:40Z. Schema 2. Latch `74c9f417584131d9aadd1f43e179cd84ad2e9a76`.

## Comparison with Slopgate

Slopgate's column is quoted from its own repo (https://github.com/agno-nymous/slopgate; results file https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md, run 2026-10-25); Latch did not re-run it.

| | Slopgate (its own numbers) | Latch (this eval) |
|---|---|---|
| Task | removes injected code slop (redundant checks, wrappers, dead code, duplicates) and proves the rewrite keeps behavior | proves a PR's fix is correct: a model-written test fails on base, passes on head, the repo suite stays green, and the test fails again with the fix reverted |
| Dataset | 15 SWE-bench Lite instances from 7 repositories | 12 SWE-bench Lite instances (1 repository, sympy) plus 9 upstream bug fixes |
| Items tested | 45 injected slop items | 42 runs: real fixes, hand-built wrong patches, and no-fix (the model writes the patch) |
| Flagged / caught | 41/45 (91%) injected slop items flagged | 8/9 (89%) wrong patches with the gate shut before any repair (only 3/9 by a valid proof test, FIX_FAILS_TEST; the rest had an INVALID_TEST proof test) |
| Proven | 14/41 (34%) flagged items got a proven one-click fix | 7/21 (33%) real fixes VALIDATED (red on base, green on head, suite green, revert check) |
| Broke a hidden test | 0 of the 14 proven fixes | 1 gate-accepted patches the oracle (the upstream tests) rejects |
| Judge | the hidden SWE-bench tests of each instance, never shown to the gate | the upstream fix's own tests (upstream cases) or the instance's FAIL_TO_PASS tests (SWE-bench Lite), never shown to the model |
| Cost | $1.16 total for the run | $1.38 total over 42 runs ($0.033 per run), from receipt model_calls |

These two benchmarks measure different tasks, so the columns are parallel in shape, not in meaning. Slopgate removes injected slop and proves the rewrite keeps behavior; Latch proves that a PR's fix is correct. Slopgate's numbers are quoted from its own repo (link above), not re-run by Latch. The datasets, the instances and the judges differ, and Latch's instance set is smaller and pools hand-built wrong patches with real fixes.

## Named verdicts

| Verdict | Runs |
|---|---|
| INVALID_TEST | 23 |
| FLAKY | 0 |
| NO_REGRESSION_FOUND | 1 |
| FIX_FAILS_TEST | 10 |
| MUTATION_SURVIVED | 0 |
| VALIDATED | 8 |

Flaky check: 9 runs checked, 0 flaky, median flake rate 0.0.

## Totals

| Measure | Value |
|---|---|
| Runs (errors, not run) | 42 (0, 0) |
| Real fixes VALIDATED | 7/21 (33%) |
| Proof test fails on base (real fixes) | 11/21 (52%) |
| Fail-to-pass (fails on base and passes on head) | 7/21 (33%) |
| Wrong patches where the gate shut (any reason, including an INVALID_TEST proof test) | 8/9 (89%) |
| ... without the contested cases | 6/7 (86%) |
| Wrong patches failed by a valid proof test (verdict FIX_FAILS_TEST) | 3/9 (33%) |
| ... without the contested cases | 2/7 (29%) |
| No-fix runs where the gate opened | 0/12 (0%) |
| Gate-accepted but oracle rejects | 1 |
| Mutation kill rate (pooled) | 1.0 (23/23 mutants) |
| Tokens (prompt / completion) | 590318 / 348296 |
| Cost | $1.3823 |
| Wall time (total / median per run) | 2803.4 s / 56.2 s |

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
| cachetools-423 | real | INVALID_TEST | no | yes | n/a | n/a | 3411/1710 | $0.004403 | 41.3 | gave_up |
| cachetools-423 | wrong | INVALID_TEST | no | no | n/a | n/a | 2937/1854 | $0.004358 | 30.9 | shut_gave_up |
| boltons-319 | real | INVALID_TEST | no | no | n/a | n/a | 4608/3488 | $0.009802 | 56.2 | gave_up |
| boltons-319 | wrong | INVALID_TEST | no | no | n/a | n/a | 3477/3011 | $0.007245 | 25.5 | shut_gave_up |
| tabulate-180 | real | INVALID_TEST | no | yes | n/a | n/a | 2527/1388 | $0.003458 | 23.7 | gave_up |
| tabulate-180 | wrong | INVALID_TEST | no | no | n/a | n/a | 3504/5947 | $0.018117 | 35.2 | shut_gave_up |
| tabulate-190 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 2816/3109 | $0.008457 | 29.7 | proven |
| tabulate-190 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 14683/28426 | $0.091999 | 94.9 | shut_gave_up |
| toolz-602 | real | INVALID_TEST | yes | no | n/a | n/a | 3579/4036 | $0.011718 | 16.8 | gave_up |
| toolz-602 | wrong | INVALID_TEST | yes | no | n/a | n/a | 2518/3603 | $0.009358 | 30.7 | shut_gave_up |
| packaging-810 | real | VALIDATED | yes | yes | 4/4 | stable (0.0) | 5853/2753 | $0.009 | 57.1 | proven |
| packaging-810 | wrong | VALIDATED | yes | yes | 5/5 | stable (0.0) | 3872/3121 | $0.008119 | 59.2 | false_accept |
| more-itertools-409 | real | INVALID_TEST | no | no | n/a | n/a | 2420/1347 | $0.003125 | 15.0 | gave_up |
| more-itertools-409 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 24939/20129 | $0.079398 | 112.5 | shut_gave_up |
| click-3360 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 6249/2059 | $0.007196 | 32.4 | proven |
| click-3360 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 48354/30802 | $0.130024 | 154.1 | shut_gave_up |
| click-3019 | real | INVALID_TEST | no | no | n/a | n/a | 6662/2011 | $0.007178 | 21.5 | gave_up |
| click-3019 | wrong | INVALID_TEST | n/a | n/a | n/a | n/a | 6510/7358 | $0.023064 | 28.3 | shut_gave_up |
| sympy-21612 | real | INVALID_TEST | no | no | n/a | n/a | 3846/4185 | $0.011044 | 52.1 | gave_up |
| sympy-21612 | nofix | INVALID_TEST | no | no | n/a | n/a | 3415/6968 | $0.018706 | 60.8 | gave_up |
| sympy-21614 | real | VALIDATED | yes | yes | 2/2 | stable (0.0) | 3551/1616 | $0.003133 | 80.3 | proven |
| sympy-21614 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 50133/21746 | $0.107746 | 109.2 | gave_up |
| sympy-21627 | real | NO_REGRESSION_FOUND | no | yes | n/a | stable (0.0) | 4855/5975 | $0.017401 | 82.2 | gave_up |
| sympy-21627 | nofix | INVALID_TEST | no | no | n/a | n/a | 3294/5200 | $0.01366 | 51.0 | gave_up |
| sympy-21847 | real | VALIDATED | yes | yes | 4/4 | stable (0.0) | 4239/5538 | $0.015289 | 103.0 | proven |
| sympy-21847 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 55445/14751 | $0.090038 | 100.2 | gave_up |
| sympy-22005 | real | INVALID_TEST | yes | no | n/a | n/a | 4517/2131 | $0.005058 | 56.3 | gave_up |
| sympy-22005 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 53650/26005 | $0.121524 | 145.8 | gave_up |
| sympy-22714 | real | INVALID_TEST | no | yes | n/a | n/a | 4398/4982 | $0.013677 | 56.8 | gave_up |
| sympy-22714 | nofix | INVALID_TEST | no | no | n/a | n/a | 3707/2564 | $0.005738 | 38.6 | gave_up |
| sympy-24066 | real | INVALID_TEST | no | yes | n/a | n/a | 3721/2868 | $0.00693 | 42.0 | gave_up |
| sympy-24066 | nofix | INVALID_TEST | no | no | n/a | n/a | 3067/2155 | $0.004145 | 41.7 | gave_up |
| sympy-24213 | real | INVALID_TEST | no | no | n/a | n/a | 3917/1864 | $0.004131 | 43.4 | gave_up |
| sympy-24213 | nofix | INVALID_TEST | no | no | n/a | n/a | 3191/3579 | $0.008558 | 51.4 | gave_up |
| sympy-24909 | real | FIX_FAILS_TEST | yes | no | n/a | n/a | 59097/31082 | $0.144046 | 160.4 | gave_up |
| sympy-24909 | nofix | INVALID_TEST | no | no | n/a | n/a | 3179/2217 | $0.004341 | 29.4 | gave_up |
| sympy-21055 | real | VALIDATED | yes | yes | 5/5 | stable (0.0) | 4155/1792 | $0.004142 | 112.5 | proven |
| sympy-21055 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 50975/16703 | $0.092701 | 95.5 | gave_up |
| sympy-20590 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 3513/2303 | $0.005181 | 67.8 | proven |
| sympy-20590 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 48805/26414 | $0.118375 | 165.8 | gave_up |
| sympy-23262 | real | INVALID_TEST | yes | no | n/a | n/a | 4949/4827 | $0.007435 | 58.0 | gave_up |
| sympy-23262 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 57780/24679 | $0.12331 | 134.2 | gave_up |

## Dropped before any run

- `cachetools-221`: no usable constructed wrong patch: the fix changes an expiry-boundary comparison that the repo's own suite pins in many places, so the only plausible mutation (`<` to `<=` in expire()) turns the base suite red (14 failures). A wrong patch that keeps the suite green could not be built honestly.
- `boltons-4457decc`: the repo's own pytest_ignore_collect hook defeats --ignore, so the old-commit suite cannot be run cheaply
- `boltons-8177b933`: same as boltons-4457decc
