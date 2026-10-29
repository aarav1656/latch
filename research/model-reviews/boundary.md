# Latch harness boundary

## Only false-success path

The harness can report success without Ultra writing the assertion only if the assertion enters the test file from another source, such as harness code, a fixture, or a pre-existing test, while the run is still attributed to Ultra.

## Mandatory refusals

- Refuse any harness or fixture that hardcodes or injects `assert admits(10, 10) is True`.
- Refuse a target whose existing tests already exercise and reject the `>=` to `>` boundary flip.
- Refuse a run without evidence that `nvidia/Nemotron-3-Ultra-550b-a55b` was invoked through Nebius Token Factory and returned the assertion used.
- Refuse success unless the harness-run kill test fails with the flipped operator and passes after restoring the original operator.

## Judge boundary

For a hackathon judge, the required runtime call remains Ultra on Token Factory, and Flawd does not make that call.
