# latch/web second-opinion review (2026-10-29)

Scope sent to the tools: `latch/web/` source, `latch/prove.py` and `latch/github_pr.py`, copied to a clean
temp dir. No secrets, shell profiles or other repo content were passed.

## Tools used

| Tool | Use | Result |
| --- | --- | --- |
| `codex exec -s read-only` | Security review: sandbox escape, secret leakage, fail-closed, rate limit and spend cap | 6 findings, below |
| `~/agent-config/frontend/slop-check.sh latch/web/static` | UI slop gate | PASS |
| `anti-ai-slop-frontend` skill | Ban-list scan of the static UI | No tells found; no UI changes |
| `design-taste-frontend` skill | Outline read only | The UI already follows DESIGN.md (Cobalt tokens, Space Grotesk / Source Sans 3 / JetBrains Mono, no Inter), so no change |

Not used: `chatgpt`, qwen38, claude CLI.

## Codex findings and what changed

1. **High, PR code can forge a result through pytest hooks (conftest, addopts, plugins).** Fixed in part:
   `sandbox.py` now runs the generated test with `--noconftest`, `-p no:cacheprovider`, an empty `-c` config,
   `--rootdir` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Test added (a hostile conftest and addopts no longer
   change the outcome). Replayed the recorded Click test offline on both commits: base fails, head passes.
   Not fixed: PR library code runs inside the test process. Documented in the README.
2. **High, daily cap is process-local.** Not changed. The deployment is one process; README says to deploy one
   instance and that replicas need a shared atomic store.
3. **Medium, per-IP windows reset on restart.** Not changed; documented. The daily cap itself persists.
4. **Medium, error detail exposes server paths.** Fixed: `redact()` strips `/tmp`, `/Users`, `/home`, `/app`,
   `/data` and similar paths from public error text. Test added.
5. **Medium, X-Forwarded-For trust.** Not changed; `LATCH_TRUST_PROXY=0` exists and the README explains when to use it.
6. **Low, access log includes query strings.** Fixed: the log line drops the query string.

Codex confirmed: PR subprocesses get a rebuilt environment without `NEBIUS_API_KEY` or `GITHUB_TOKEN`, the server
drops dumpability, GitHub hosts are fixed to `api.github.com` and `github.com`.
