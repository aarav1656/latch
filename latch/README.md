# Latch

Latch is the gate on an agent pull request. The shipped tests stay green when the annual discount boundary moves from `>=` to `>`. Lightning names the test that cannot fail. Ultra writes the test that can. The harness runs both.

## Run

`NEBIUS_API_KEY` is read from the environment, or from its export line in `~/.zshrc`.

```
python3 latch/serve.py
```

Open http://127.0.0.1:4173/ and press Run the gate. The padlock reads Open only when the new test fails with AssertionError on the changed line and passes after that line is restored.

## What the gate checks

`latch/fixture/billing.py` discounts an annual plan at 10 seats. `test_suite.py` checks a monthly plan, 12 annual seats, and 3 annual seats. `test_ten_seats_ran` calls `discount_applies(10, True)` and asserts the value is itself, so the boundary change leaves the suite green.

The proof is `latch/runs/latest.json`. Ultra `nvidia/Nemotron-3-Ultra-550b-a55b` returned HTTP 200, completion `chatcmpl-87fee6d9c6662143`, and wrote `test_ten_seats_annual_discount`. Lightning `nvidia/Nemotron-3_5-Lightning` named `test_ten_seats_ran`.

## Prove a real issue fix

`python3 -m latch.prove` accepts a local Python repository, the buggy and fixed commit refs, and the issue report. It asks Nemotron Ultra for one regression test, runs it against temporary archives of both commits, and writes a JSON receipt. The source checkout is not modified. See the root README for the Click issue #3298 example and setup command.

The live Click receipt at `latch/runs/click-3298.json` records the generated test against `semver.Version(1, 0, 0)`, an issue-specific failure on base `04ef3a6f473deb2499721a8d11f92a7d2c0912f2`, and a pass on fix `d340b0c1202284a1b9d0ca892549208527d586ce`.

## License

MIT. See `LICENSE`.
