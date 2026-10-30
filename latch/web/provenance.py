"""Which recorded output the site may show.

Development-only output (an OpenRouter dev run, a dry-run fixture) must never reach a visitor as a Latch result.
Two guards, both fail-closed:

* `is_dev_path`: anything under latch/runs/dev/ or latch/runs/eval-dryrun* is never read.
* `is_dev_output`: a receipt, envelope, eval summary, event or case that says `dev_only: true`, or names a `provider`
  other than Token Factory / Nebius, is rejected. A record that names no provider at all (every receipt recorded
  before the field existed) is accepted; the field only ever disqualifies.
"""

from pathlib import Path

ALLOWED_PROVIDERS = frozenset({"tokenfactory", "nebius"})
BLOCKED_RUN_DIRS = ("dev", "eval-dryrun")


def is_dev_path(path):
    """True for a path inside latch/runs/dev or latch/runs/eval-dryrun*. Only the part after `runs` is judged."""
    parts = [p.lower() for p in Path(str(path)).parts]
    if "runs" not in parts:
        return False
    tail = parts[len(parts) - parts[::-1].index("runs"):]
    return any(p == "dev" or p.startswith("eval-dryrun") for p in tail)


def _marked(node):
    if not isinstance(node, dict):
        return False
    if node.get("dev_only") is True:
        return True
    provider = node.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower().replace(" ", "").replace("_", "").replace("-", "") not in ALLOWED_PROVIDERS
    return provider is not None and not isinstance(provider, str)


def is_dev_output(obj):
    """True when `obj` (or its meta / receipt / manifest / model calls / cases) is marked dev-only or has a foreign provider."""
    if not isinstance(obj, dict):
        return False
    if _marked(obj):
        return True
    for key in ("meta", "receipt", "manifest"):
        if _marked(obj.get(key)):
            return True
    receipt = obj.get("receipt") if isinstance(obj.get("receipt"), dict) else obj
    calls = receipt.get("model_calls")
    if isinstance(calls, list) and any(_marked(i) for i in calls):
        return True
    cases = obj.get("cases")
    if isinstance(cases, list):
        for case in cases:
            if _marked(case):
                return True
            inner = case.get("model_calls") if isinstance(case, dict) else None
            if isinstance(inner, list) and any(_marked(i) for i in inner):
                return True
    return False
