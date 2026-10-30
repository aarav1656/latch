"""Per-call model accounting for receipts: role, model, tokens, latency, completion id, estimated cost.

Every model call a Latch run makes goes through ModelCalls.ask(role), so the receipt can say which Nemotron
model did which job and what it cost. Tokens come from the `usage` object Token Factory returns; if a
call has no usage (a stub in tests, or the server omitted it) tokens and cost are null, never guessed.
"""

import time

from .run import LIGHTNING, MODEL, call_model

ROLES = ("repo_map", "triage", "test_writer", "fixer")

# Token Factory's published list prices, USD per 1M tokens (input, output). Cached-input discounts are not
# applied, so the estimate is an upper bound. Read on 2026-10-30 from the Token Factory model catalog:
#   nvidia/Nemotron-3-Ultra-550b-a55b: input 1, cached input 0.12, output 3
#   nvidia/Nemotron-3_5-Lightning:     input 0.06, cached input 0.03, output 0.24
PRICES_SOURCE_URL = "https://tokenfactory.nebius.com/model-catalog.md"
PRICES_USD_PER_MILLION = {MODEL: (1.00, 3.00), LIGHTNING: (0.06, 0.24)}


def estimate_cost(model, prompt_tokens, completion_tokens):
    """USD for one call from the published prices, or None when the price or a token count is unknown."""
    price = PRICES_USD_PER_MILLION.get(model)
    if price is None or prompt_tokens is None or completion_tokens is None:
        return None
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 6)


def total_cost(calls):
    """Sum of the known per-call costs; None when no call has a known cost."""
    known = [c["cost_usd"] for c in calls if c.get("cost_usd") is not None]
    return round(sum(known), 6) if known else None


class ModelCalls:
    """Wraps a call_model-compatible function and records one entry per call in `self.calls`.

    uses_meta: pass `meta=` to the function so it reports token usage (true for the real call_model; stubs
    do not take it, so their calls record latency only). on_call(entry) is invoked after every call.
    """

    def __init__(self, fn=None, on_retry=None, uses_meta=None, on_call=None):
        self.fn = fn or call_model
        self.uses_meta = (fn is None) if uses_meta is None else uses_meta
        self.on_retry = on_retry
        self.on_call = on_call
        self.calls = []

    def ask(self, role):
        if role not in ROLES:
            raise ValueError(f"unknown model role {role!r}")

        def call(key, user, model=MODEL, **kwargs):
            meta = {}
            if self.uses_meta:
                kwargs["meta"] = meta
                if self.on_retry:
                    kwargs["on_retry"] = self.on_retry
            started = time.monotonic()
            status, content, completion_id = self.fn(key, user, model=model, **kwargs)
            prompt_tokens, completion_tokens = meta.get("prompt_tokens"), meta.get("completion_tokens")
            entry = {
                "role": role,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": meta.get("latency_ms", int((time.monotonic() - started) * 1000)),
                "completion_id": completion_id,
                "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
                "status": status,
            }
            self.calls.append(entry)
            if self.on_call:
                self.on_call(entry)
            return status, content, completion_id

        return call

    def summary(self):
        return {"model_calls": list(self.calls), "model_cost_usd": total_cost(self.calls),
                "model_prices_source": PRICES_SOURCE_URL}
