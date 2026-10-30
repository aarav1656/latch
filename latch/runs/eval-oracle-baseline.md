## oracle baseline (no model)

Run 2026-10-30T05:20:15+00:00. No model, no Token Factory call: $0.00, 185.1 s wall. Real git and pytest.

| Measure | Result |
|---|---|
| Cases checked | 21 (0 errors) |
| Oracle fails on base | 21/21 (100%) |
| Oracle passes on the real fix | 21/21 (100%) |
| Oracle rejects the wrong patch (upstream cases) | 9/9 (100%) |
| Oracle separates real from wrong (upstream cases) | 9/9 (100%) |

These tests are the upstream answer key that Latch never shows the model. The kept cases were selected for this property, so the oracle separates real from wrong by construction; the number is the reference the gate is judged against, not a Latch result.

Cases dropped before any run (reported, not hidden):

- `cachetools-221`: no usable constructed wrong patch: the fix changes an expiry-boundary comparison that the repo's own suite pins in many places, so the only plausible mutation (`<` to `<=` in expire()) turns the base suite red (14 failures). A wrong patch that keeps the suite green could not be built honestly.
- `boltons-4457decc`: the repo's own pytest_ignore_collect hook defeats --ignore, so the old-commit suite cannot be run cheaply
- `boltons-8177b933`: same as boltons-4457decc

| Case | Fails on base | Passes on real | Fails on wrong | Wall s |
|---|---|---|---|---|
| cachetools-423 | yes | yes | yes | 13.2 |
| boltons-319 | yes | yes | yes | 9.7 |
| tabulate-180 | yes | yes | yes | 6.8 |
| tabulate-190 | yes | yes | yes | 8.3 |
| toolz-602 | yes | yes | yes | 9.0 |
| packaging-810 | yes | yes | yes | 85.4 |
| more-itertools-409 | yes | yes | yes | 11.6 |
| click-3360 | yes | yes | yes | 25.3 |
| click-3019 | yes | yes | yes | 15.8 |
| sympy-21612 | yes | yes | n/a | 25.5 |
| sympy-21614 | yes | yes | n/a | 18.6 |
| sympy-21627 | yes | yes | n/a | 33.9 |
| sympy-21847 | yes | yes | n/a | 26.6 |
| sympy-22005 | yes | yes | n/a | 32.6 |
| sympy-22714 | yes | yes | n/a | 35.9 |
| sympy-24066 | yes | yes | n/a | 32.4 |
| sympy-24213 | yes | yes | n/a | 33.3 |
| sympy-24909 | yes | yes | n/a | 27.6 |
| sympy-21055 | yes | yes | n/a | 36.6 |
| sympy-20590 | yes | yes | n/a | 21.4 |
| sympy-23262 | yes | yes | n/a | 24.5 |
