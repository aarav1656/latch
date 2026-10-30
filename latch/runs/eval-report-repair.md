# Latch eval report

Generated 2026-10-30T10:52:23Z. Schema 2. Latch `b4924a53212190bea971bfcb0001e5451dd16c33`.

## Comparison with Slopgate

Slopgate's column is quoted from its own repo (https://github.com/agno-nymous/slopgate; results file https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md, run 2026-10-25); Latch did not re-run it.

| | Slopgate (its own numbers) | Latch (this eval) |
|---|---|---|
| Task | removes injected code slop (redundant checks, wrappers, dead code, duplicates) and proves the rewrite keeps behavior | proves a PR's fix is correct: a model-written test fails on base, passes on head, the repo suite stays green, and the test fails again with the fix reverted |
| Dataset | 15 SWE-bench Lite instances from 7 repositories | 12 SWE-bench Lite instances (1 repository, sympy) plus 9 upstream bug fixes |
| Items tested | 45 injected slop items | 42 runs: real fixes, hand-built wrong patches, and no-fix (the model writes the patch) |
| Flagged / caught | 41/45 (91%) injected slop items flagged | 9/9 (100%) wrong patches with the gate shut before any repair (only 6/9 by a valid proof test, FIX_FAILS_TEST; the rest had an INVALID_TEST proof test) |
| Proven | 14/41 (34%) flagged items got a proven one-click fix | 10/21 (48%) real fixes VALIDATED (red on base, green on head, suite green, revert check) |
| Broke a hidden test | 0 of the 14 proven fixes | 0 gate-accepted patches the oracle (the upstream tests) rejects |
| Judge | the hidden SWE-bench tests of each instance, never shown to the gate | the upstream fix's own tests (upstream cases) or the instance's FAIL_TO_PASS tests (SWE-bench Lite), never shown to the model |
| Cost | $1.16 total for the run | $2.22 total over 42 runs ($0.053 per run), from receipt model_calls |

These two benchmarks measure different tasks, so the columns are parallel in shape, not in meaning. Slopgate removes injected slop and proves the rewrite keeps behavior; Latch proves that a PR's fix is correct. Slopgate's numbers are quoted from its own repo (link above), not re-run by Latch. The datasets, the instances and the judges differ, and Latch's instance set is smaller and pools hand-built wrong patches with real fixes.

## Named verdicts

| Verdict | Runs |
|---|---|
| INVALID_TEST | 14 |
| FLAKY | 0 |
| NO_REGRESSION_FOUND | 1 |
| FIX_FAILS_TEST | 16 |
| MUTATION_SURVIVED | 1 |
| VALIDATED | 10 |

Flaky check: 12 runs checked, 0 flaky, median flake rate 0.0.

## Totals

| Measure | Value |
|---|---|
| Runs (errors, not run) | 42 (0, 0) |
| Real fixes VALIDATED | 10/21 (48%) |
| Proof test fails on base (real fixes) | 14/21 (67%) |
| Fail-to-pass (fails on base and passes on head) | 11/21 (52%) |
| Wrong patches where the gate shut (any reason, including an INVALID_TEST proof test) | 9/9 (100%) |
| ... without the contested cases | 7/7 (100%) |
| Wrong patches failed by a valid proof test (verdict FIX_FAILS_TEST) | 6/9 (67%) |
| ... without the contested cases | 5/7 (71%) |
| No-fix runs where the gate opened | 0/12 (0%) |
| Gate-accepted but oracle rejects | 0 |
| Mutation kill rate (pooled) | 0.903 (28/31 mutants) |
| Tokens (prompt / completion) | 916474 / 528877 |
| Cost | $2.2239 |
| Wall time (total / median per run) | 3537.5 s / 76.0 s |

## Test repair

Run `repair`: the one-round test repair was on. It fired in 17 run(s) (one extra test-writer call each), the repaired test was adopted in 17, no longer errored in 5, and was rejected (original kept) in 0. A repaired test goes through the whole gate; thresholds are unchanged.

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
| cachetools-423 | real | INVALID_TEST | no | yes | n/a | n/a | 5817/2145 | $0.008114 | 18.6 | gave_up |
| cachetools-423 | wrong | INVALID_TEST | yes | no | n/a | n/a | 4262/4143 | $0.005638 | 28.0 | shut_gave_up |
| boltons-319 | real | VALIDATED | yes | yes | 5/5 | stable (0.0) | 4608/3844 | $0.01087 | 98.3 | proven |
| boltons-319 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 51550/20799 | $0.104615 | 103.1 | shut_gave_up |
| tabulate-180 | real | MUTATION_SURVIVED | yes | yes | 2/5 | stable (0.0) | 7478/7867 | $0.027846 | 60.5 | gave_up |
| tabulate-180 | wrong | INVALID_TEST | no | no | n/a | n/a | 2692/4839 | $0.013981 | 24.2 | shut_gave_up |
| tabulate-190 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 2816/3413 | $0.009369 | 19.4 | proven |
| tabulate-190 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 10276/28101 | $0.088115 | 135.6 | shut_gave_up |
| toolz-602 | real | INVALID_TEST | yes | no | n/a | n/a | 6633/5413 | $0.018903 | 30.1 | gave_up |
| toolz-602 | wrong | INVALID_TEST | yes | no | n/a | n/a | 4148/3786 | $0.011545 | 23.9 | shut_gave_up |
| packaging-810 | real | VALIDATED | yes | yes | 4/4 | stable (0.0) | 5853/3322 | $0.010707 | 68.0 | proven |
| packaging-810 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 59259/28506 | $0.136702 | 154.8 | shut_gave_up |
| more-itertools-409 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 2420/1634 | $0.003986 | 16.7 | proven |
| more-itertools-409 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 27222/15031 | $0.066433 | 110.8 | shut_gave_up |
| click-3360 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 6249/2569 | $0.008726 | 29.7 | proven |
| click-3360 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 50484/26675 | $0.119868 | 102.8 | shut_gave_up |
| click-3019 | real | INVALID_TEST | no | no | n/a | n/a | 11039/2828 | $0.014006 | 25.3 | gave_up |
| click-3019 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 52998/30562 | $0.135753 | 128.8 | shut_gave_up |
| sympy-21612 | real | INVALID_TEST | no | no | n/a | n/a | 5321/8132 | $0.02436 | 78.6 | gave_up |
| sympy-21612 | nofix | INVALID_TEST | no | no | n/a | n/a | 4189/5957 | $0.016447 | 57.4 | gave_up |
| sympy-21614 | real | VALIDATED | yes | yes | 2/2 | stable (0.0) | 3551/1463 | $0.002674 | 72.1 | proven |
| sympy-21614 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 50870/30893 | $0.135408 | 154.0 | gave_up |
| sympy-21627 | real | NO_REGRESSION_FOUND | no | yes | n/a | stable (0.0) | 4857/4675 | $0.013503 | 69.0 | gave_up |
| sympy-21627 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 49823/25510 | $0.116098 | 125.2 | gave_up |
| sympy-21847 | real | VALIDATED | yes | yes | 4/4 | stable (0.0) | 6568/7751 | $0.024257 | 131.9 | proven |
| sympy-21847 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 54276/23039 | $0.1145 | 114.8 | gave_up |
| sympy-22005 | real | VALIDATED | yes | yes | 2/2 | stable (0.0) | 4517/2172 | $0.005181 | 113.4 | proven |
| sympy-22005 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 52820/27938 | $0.127024 | 122.1 | gave_up |
| sympy-22714 | real | INVALID_TEST | no | yes | n/a | n/a | 6025/8953 | $0.027217 | 71.9 | gave_up |
| sympy-22714 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 55761/29461 | $0.133801 | 137.9 | gave_up |
| sympy-24066 | real | INVALID_TEST | no | yes | n/a | n/a | 5051/4239 | $0.012373 | 73.5 | gave_up |
| sympy-24066 | nofix | INVALID_TEST | no | no | n/a | n/a | 3752/2876 | $0.006993 | 59.8 | gave_up |
| sympy-24213 | real | INVALID_TEST | no | no | n/a | n/a | 5550/3996 | $0.01216 | 54.5 | gave_up |
| sympy-24213 | nofix | INVALID_TEST | no | no | n/a | n/a | 4206/4120 | $0.011196 | 48.1 | gave_up |
| sympy-24909 | real | FIX_FAILS_TEST | yes | no | n/a | n/a | 62362/27165 | $0.134748 | 139.4 | gave_up |
| sympy-24909 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 52446/24520 | $0.117936 | 115.2 | gave_up |
| sympy-21055 | real | VALIDATED | yes | yes | 5/5 | stable (0.0) | 4155/2221 | $0.005429 | 114.3 | proven |
| sympy-21055 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 50107/24833 | $0.116107 | 124.6 | gave_up |
| sympy-20590 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 3513/2239 | $0.004989 | 62.9 | proven |
| sympy-20590 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 48895/27105 | $0.122144 | 127.8 | gave_up |
| sympy-23262 | real | INVALID_TEST | yes | no | n/a | n/a | 4971/6305 | $0.011871 | 70.5 | gave_up |
| sympy-23262 | nofix | FIX_FAILS_TEST | yes | no | n/a | n/a | 57084/27837 | $0.132292 | 120.0 | gave_up |

## Dropped before any run

- `cachetools-221`: no usable constructed wrong patch: the fix changes an expiry-boundary comparison that the repo's own suite pins in many places, so the only plausible mutation (`<` to `<=` in expire()) turns the base suite red (14 failures). A wrong patch that keeps the suite green could not be built honestly.
- `boltons-4457decc`: the repo's own pytest_ignore_collect hook defeats --ignore, so the old-commit suite cannot be run cheaply
- `boltons-8177b933`: same as boltons-4457decc
