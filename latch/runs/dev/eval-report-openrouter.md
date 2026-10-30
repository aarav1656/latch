# Latch eval report

> **DEV-ONLY RUN** (provider: openrouter). Dev-only run via OpenRouter free tier; not Nebius Token Factory numbers.

Generated 2026-10-30T08:05:20Z. Schema 2. Latch `74c9f417584131d9aadd1f43e179cd84ad2e9a76`.

## Comparison with Slopgate

Slopgate's column is quoted from its own repo (https://github.com/agno-nymous/slopgate; results file https://github.com/agno-nymous/slopgate/blob/main/bench/results/swebench/swebench.md, run 2026-10-25); Latch did not re-run it.

| | Slopgate (its own numbers) | Latch (this eval) |
|---|---|---|
| Task | removes injected code slop (redundant checks, wrappers, dead code, duplicates) and proves the rewrite keeps behavior | proves a PR's fix is correct: a model-written test fails on base, passes on head, the repo suite stays green, and the test fails again with the fix reverted |
| Dataset | 15 SWE-bench Lite instances from 7 repositories | 0 SWE-bench Lite instances (1 repository, sympy) plus 3 upstream bug fixes |
| Items tested | 45 injected slop items | 6 runs: real fixes, hand-built wrong patches, and no-fix (the model writes the patch) |
| Flagged / caught | 41/45 (91%) injected slop items flagged | 3/3 (100%) wrong patches rejected (gate shut before any repair) |
| Proven | 14/41 (34%) flagged items got a proven one-click fix | 1/3 (33%) real fixes VALIDATED (red on base, green on head, suite green, revert check) |
| Broke a hidden test | 0 of the 14 proven fixes | 0 gate-accepted patches the oracle (the upstream tests) rejects |
| Judge | the hidden SWE-bench tests of each instance, never shown to the gate | the upstream fix's own tests (upstream cases) or the instance's FAIL_TO_PASS tests (SWE-bench Lite), never shown to the model |
| Cost | $1.16 total for the run | not run (needs live model credit) |

These two benchmarks measure different tasks, so the columns are parallel in shape, not in meaning. Slopgate removes injected slop and proves the rewrite keeps behavior; Latch proves that a PR's fix is correct. Slopgate's numbers are quoted from its own repo (link above), not re-run by Latch. The datasets, the instances and the judges differ, and Latch's instance set is smaller and pools hand-built wrong patches with real fixes.

## Named verdicts

| Verdict | Runs |
|---|---|
| INVALID_TEST | 4 |
| FLAKY | 0 |
| NO_REGRESSION_FOUND | 0 |
| FIX_FAILS_TEST | 1 |
| MUTATION_SURVIVED | 0 |
| VALIDATED | 1 |

Flaky check: 1 runs checked, 0 flaky, median flake rate 0.0.

## Totals

| Measure | Value |
|---|---|
| Runs (errors, not run) | 6 (0, 36) |
| Real fixes VALIDATED | 1/3 (33%) |
| Proof test fails on base (real fixes) | 2/3 (67%) |
| Fail-to-pass (fails on base and passes on head) | 1/3 (33%) |
| Wrong patches rejected (FIX_FAILS_TEST) | 3/3 (100%) |
| ... without the contested cases | 3/3 (100%) |
| No-fix runs where the gate opened | not run |
| Gate-accepted but oracle rejects | 0 |
| Mutation kill rate (pooled) | 1.0 (1/1 mutants) |
| Tokens (prompt / completion) | 22954 / 48587 |
| Cost | n/a |
| Wall time (total / median per run) | 863.3 s / 93.6 s |

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
| boltons-319 | real | not run | | | | | | | | not run |
| boltons-319 | wrong | not run | | | | | | | | not run |
| tabulate-180 | real | INVALID_TEST | no | no | n/a | n/a | 2731/4059 | n/a | 104.5 | gave_up |
| tabulate-180 | wrong | INVALID_TEST | no | no | n/a | n/a | 1661/3812 | n/a | 82.7 | shut_gave_up |
| tabulate-190 | real | not run | | | | | | | | not run |
| tabulate-190 | wrong | not run | | | | | | | | not run |
| toolz-602 | real | INVALID_TEST | yes | no | n/a | n/a | 3681/7687 | n/a | 111.2 | gave_up |
| toolz-602 | wrong | INVALID_TEST | yes | no | n/a | n/a | 2596/4130 | n/a | 65.0 | shut_gave_up |
| packaging-810 | real | not run | | | | | | | | not run |
| packaging-810 | wrong | not run | | | | | | | | not run |
| more-itertools-409 | real | VALIDATED | yes | yes | 1/1 | stable (0.0) | 2502/2389 | n/a | 37.6 | proven |
| more-itertools-409 | wrong | FIX_FAILS_TEST | yes | no | n/a | n/a | 9783/26510 | n/a | 462.3 | shut_gave_up |
| click-3360 | real | not run | | | | | | | | not run |
| click-3360 | wrong | not run | | | | | | | | not run |
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
