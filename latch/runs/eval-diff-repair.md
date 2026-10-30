# Latch eval: before / after

Before: `eval-summary.json` (Latch `74c9f417584131d9aadd1f43e179cd84ad2e9a76`). After: `eval-summary-repair.json` (tag `repair`, Latch `96eb8d57512dfb20646f47aa602669b81e4d8236`).

| Measure | Before | After |
|---|---|---|
| Real fixes VALIDATED | 7/21 | 10/21 |
| INVALID_TEST runs | 23 | 14 |
| Wrong patches failed by a valid test | 3 | 6 |
| False accepts | ['packaging-810'] | [] |
| Cost | 1.3823 | 2.2239 |
| Test repairs attempted (worked) | None | 17 (5) |

| Case | Variant | Before | After | Test repair |
|---|---|---|---|---|
| boltons-319 | real | INVALID_TEST | VALIDATED * |  |
| boltons-319 | wrong | INVALID_TEST | FIX_FAILS_TEST * |  |
| cachetools-423 | real | INVALID_TEST | INVALID_TEST | adopted |
| cachetools-423 | wrong | INVALID_TEST | INVALID_TEST |  |
| click-3019 | real | INVALID_TEST | INVALID_TEST | adopted |
| click-3019 | wrong | INVALID_TEST | FIX_FAILS_TEST * |  |
| click-3360 | real | VALIDATED | VALIDATED |  |
| click-3360 | wrong | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| more-itertools-409 | real | INVALID_TEST | VALIDATED * |  |
| more-itertools-409 | wrong | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| packaging-810 | real | VALIDATED | VALIDATED |  |
| packaging-810 | wrong | VALIDATED | FIX_FAILS_TEST * |  |
| sympy-20590 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| sympy-20590 | real | VALIDATED | VALIDATED |  |
| sympy-21055 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| sympy-21055 | real | VALIDATED | VALIDATED |  |
| sympy-21612 | nofix | INVALID_TEST | INVALID_TEST | adopted |
| sympy-21612 | real | INVALID_TEST | INVALID_TEST | adopted |
| sympy-21614 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST | adopted |
| sympy-21614 | real | VALIDATED | VALIDATED |  |
| sympy-21627 | nofix | INVALID_TEST | FIX_FAILS_TEST * |  |
| sympy-21627 | real | NO_REGRESSION_FOUND | NO_REGRESSION_FOUND |  |
| sympy-21847 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| sympy-21847 | real | VALIDATED | VALIDATED | adopted |
| sympy-22005 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| sympy-22005 | real | INVALID_TEST | VALIDATED * |  |
| sympy-22714 | nofix | INVALID_TEST | FIX_FAILS_TEST * | adopted |
| sympy-22714 | real | INVALID_TEST | INVALID_TEST | adopted |
| sympy-23262 | nofix | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| sympy-23262 | real | INVALID_TEST | INVALID_TEST |  |
| sympy-24066 | nofix | INVALID_TEST | INVALID_TEST | adopted |
| sympy-24066 | real | INVALID_TEST | INVALID_TEST | adopted |
| sympy-24213 | nofix | INVALID_TEST | INVALID_TEST | adopted |
| sympy-24213 | real | INVALID_TEST | INVALID_TEST | adopted |
| sympy-24909 | nofix | INVALID_TEST | FIX_FAILS_TEST * |  |
| sympy-24909 | real | FIX_FAILS_TEST | FIX_FAILS_TEST | adopted |
| tabulate-180 | real | INVALID_TEST | MUTATION_SURVIVED * | adopted |
| tabulate-180 | wrong | INVALID_TEST | INVALID_TEST | adopted |
| tabulate-190 | real | VALIDATED | VALIDATED |  |
| tabulate-190 | wrong | FIX_FAILS_TEST | FIX_FAILS_TEST |  |
| toolz-602 | real | INVALID_TEST | INVALID_TEST | adopted |
| toolz-602 | wrong | INVALID_TEST | INVALID_TEST | adopted |

\* verdict changed. The first run is reported unchanged. Rates over a few single runs with a non-deterministic model carry wide uncertainty; a verdict that changed between runs is not by itself an effect of the repair.
