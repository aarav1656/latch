"""Model provider switch: Nebius Token Factory (the default, and the only source of published numbers) or OpenRouter (dev only).

    LATCH_PROVIDER=nebius       https://api.tokenfactory.nebius.com/v1, NEBIUS_API_KEY, the Nemotron ids in latch.run
    LATCH_PROVIDER=openrouter   https://openrouter.ai/api/v1, OPENROUTER_API_KEY (environment only), the free Nemotron variants

OpenRouter exists so development can go on while Token Factory credit is unavailable. Its output is rate limited
free-tier output and is never a Token Factory number: every receipt carries `provider`, every model_calls[] entry
records the provider and the resolved model id, and a run on any provider other than nebius writes only under
latch/runs/dev/ (see `dev_path` and `guard_public_path`), so it can never feed the site or the README.
Only Ultra and Lightning are ever used; there is no mapping for any other model.
"""

import os
from pathlib import Path

NEBIUS, OPENROUTER = "nebius", "openrouter"
PROVIDERS = (NEBIUS, OPENROUTER)
ENV_VAR = "LATCH_PROVIDER"

NEBIUS_URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
URLS = {NEBIUS: NEBIUS_URL, OPENROUTER: OPENROUTER_URL}
KEY_ENV = {NEBIUS: "NEBIUS_API_KEY", OPENROUTER: "OPENROUTER_API_KEY"}

# canonical (Token Factory) id -> OpenRouter id. These are reasoning models: the free variants are slow and
# rate limited, so OpenRouter calls get a larger token floor and a patient 429 backoff (see latch.run.call_model).
OPENROUTER_MODELS = {
    "nvidia/Nemotron-3-Ultra-550b-a55b": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/Nemotron-3_5-Lightning": "nvidia/nemotron-3.5-lightning:free",
}
OPENROUTER_MIN_TOKENS = 16384
OPENROUTER_ATTEMPTS = 6
OPENROUTER_BASE_DELAY = 4.0
OPENROUTER_MAX_DELAY = 60.0

DEV_DIR = Path("latch") / "runs" / "dev"
DEV_NOTE = "Dev-only run via OpenRouter free tier; not Nebius Token Factory numbers."


def current():
    """The active provider: $LATCH_PROVIDER, default nebius. Raises ValueError for anything else."""
    value = (os.environ.get(ENV_VAR) or NEBIUS).strip().lower()
    if value not in PROVIDERS:
        raise ValueError(f"{ENV_VAR} must be one of {', '.join(PROVIDERS)}, not {value!r}")
    return value


def set_provider(name):
    """Select the provider for this process (the --provider flag): same effect as exporting LATCH_PROVIDER."""
    if name:
        if name.lower() not in PROVIDERS:
            raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}, not {name!r}")
        os.environ[ENV_VAR] = name.lower()
    return current()


def take_flag(argv):
    """Pull `--provider X` / `--provider=X` out of argv, apply it with set_provider, return the remaining argv.
    Raises ValueError for a bad provider or a missing value. Without the flag, $LATCH_PROVIDER decides."""
    rest, value, i = [], None, 0
    argv = list(argv)
    while i < len(argv):
        a = argv[i]
        if not isinstance(a, str):
            rest.append(a)
            i += 1
            continue
        if a == "--provider":
            if i + 1 >= len(argv):
                raise ValueError("--provider needs a value: " + " | ".join(PROVIDERS))
            value, i = argv[i + 1], i + 2
            continue
        if a.startswith("--provider="):
            value, i = a.split("=", 1)[1], i + 1
            continue
        rest.append(a)
        i += 1
    set_provider(value)
    current()
    return rest


def is_dev(provider=None):
    return (provider or current()) != NEBIUS


def url(provider=None):
    return URLS[provider or current()]


def key_env(provider=None):
    return KEY_ENV[provider or current()]


def resolve_model(model, provider=None):
    """The id the provider knows for a canonical Latch model id. Refuses anything that is not Ultra or Lightning."""
    provider = provider or current()
    if provider == NEBIUS:
        return model
    try:
        return OPENROUTER_MODELS[model]
    except KeyError:
        raise ValueError(f"no {provider} mapping for model {model!r}; only Ultra and Lightning are used") from None


def max_tokens_for(max_tokens, provider=None):
    """Reasoning models spend tokens thinking before they answer: raise the floor on OpenRouter, never lower a request."""
    return max(max_tokens or 0, OPENROUTER_MIN_TOKENS) if (provider or current()) == OPENROUTER else max_tokens


def label(provider=None):
    return {NEBIUS: "Nebius", OPENROUTER: "OpenRouter"}[provider or current()]


def not_configured(provider=None):
    return f"{key_env(provider)} is not configured"


def dev_path(path):
    """Re-home a public output path (latch/runs/<name>) under latch/runs/dev/ for non-nebius providers, with a -openrouter suffix."""
    p = Path(path)
    return p.parent / "dev" / f"{p.stem}-{current()}{p.suffix}"


def check_write(path, provider=None):
    """A non-nebius run may write under latch/runs/ only inside latch/runs/dev/. Returns `path`; raises ValueError otherwise.

    Nebius runs are unrestricted. The check looks at the resolved path for a `latch/runs/<x>` pair, wherever the
    repository checkout lives, so ../ tricks and absolute paths are covered too.
    """
    provider = provider or current()
    if path is None or provider == NEBIUS:
        return path
    parts = Path(path).resolve().parts
    for i in range(len(parts) - 2):
        if parts[i] == "latch" and parts[i + 1] == "runs" and parts[i + 2] != "dev":
            raise ValueError(f"refusing to write {path}: a {provider} run is dev-only and may only write under latch/runs/dev/")
    return path


def mark_dev(document, provider=None):
    """Add provider (and, for a dev provider, dev_only + the note) to a summary-like dict, in place."""
    provider = provider or current()
    document["provider"] = provider
    if provider != NEBIUS:
        document["dev_only"] = True
        document["note"] = DEV_NOTE
    return document
