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

## License

MIT. See `LICENSE`.
