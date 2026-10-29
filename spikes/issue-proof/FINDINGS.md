# Issue anchored proof spike

## Claim

For Click issue #3298, a test generated with Nebius Nemotron 3 Ultra and run against the real reported base and fix revisions will fail on base with the reported `ValueError` and pass on the fix in under 10 seconds after dependencies are installed.

## Result

CONFIRMED. Nemotron 3 Ultra returned completion `chatcmpl-87fee6d9c6662143` for the generated test. The exact same pytest test used Click's `CliRunner` and `semver==3.0.4` against archived source at base `04ef3a6f473deb2499721a8d11f92a7d2c0912f2` and fix `d340b0c1202284a1b9d0ca892549208527d586ce`.

On the buggy base, pytest failed because Click help exited with `ValueError(' is not valid SemVer string')`. On the fixed head, pytest passed. Runtime was 0.03s and 0.02s respectively inside the Mac mini isolated VM. The result distinguishes the two revisions and matches the issue's reported behavior.

The implemented CLI was then run end to end against the same Click commits. Nebius completion `chatcmpl-99d6e5a92020c804` generated a test using the actual `semver.Version(1, 0, 0)` type. In the Mac mini isolated VM, base returned 1 with the generated test's explicit unexpected-operation failure; head returned 0. The CLI wrote `latch/runs/click-3298.json` with `proven: true`.

## Reproduction command

From the prepared spike directory on the isolated Mac mini VM:

```sh
python3 -m venv .venv && .venv/bin/pip install -q pytest semver==3.0.4
PYTHONPATH=base/src .venv/bin/pytest -q proof/test_latch_issue.py
PYTHONPATH=head/src .venv/bin/pytest -q proof/test_latch_issue.py
```

Observed result: `BASE_RC=1 HEAD_RC=0`.

## Sources

- Issue: https://github.com/pallets/click/issues/3298
- Fix: https://github.com/pallets/click/pull/3299
- Base commit: https://github.com/pallets/click/tree/04ef3a6f473deb2499721a8d11f92a7d2c0912f2
- Fixed commit: https://github.com/pallets/click/tree/d340b0c1202284a1b9d0ca892549208527d586ce

## Caveat

The test is grounded in a maintainer-reported issue and distinguishes the real source revisions, but the model generated only one case. Latch must preserve the independent issue text as the oracle and reject generated tests that do not fail base and pass head. The isolated spike used installed Python dependencies; it did not attempt arbitrary repository setup.
