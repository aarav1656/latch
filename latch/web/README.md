# Latch web

A maintainer pastes a GitHub pull request URL and gets the issue-anchored proof
receipt in the browser: the linked issue, the test the model wrote from the issue
alone, and whether that test fails on the base commit and passes on the PR head.
A secondary **Fix loop** tab replays (or live-runs) the `latch/loop` demo.

Stdlib only. No build step. Python 3.10+ to run the tests, **3.12 in the image**.

## Run it

```bash
# from the repository root
python3 -m latch.web.app                      # http://localhost:8080
PORT=9000 LATCH_LIVE=0 python3 -m latch.web.app   # cached receipts only, no model calls
python3 -m unittest latch.web.test_app latch.test_prove latch.test_github_pr
```

The first screen shows the recorded Click receipt immediately, with no click and
no network. The UI stays fully usable with `LATCH_LIVE=0`: pasting a PR that has a
cached receipt returns it, anything else says why a live run is unavailable.

## API

| Method and path | What |
| --- | --- |
| `POST /api/proof` | `{"pull_request_url": "...", "live": false}`. Returns a cached receipt (200) or a job (202). `live: true` forces a fresh run. |
| `GET /api/proof/<id>/events` | Server-sent events: `step`, `queue`, `receipt`, `error`. Replays history, honors `Last-Event-ID`, keepalive every 5 s. |
| `GET /api/proof/<id>` | Job status as JSON (polling fallback). |
| `GET /r/<owner>/<repo>/<pr>` | Shareable page for a cached receipt. `/api/receipt/<owner>/<repo>/<pr>` is the JSON. |
| `GET /api/example` | The recorded Click receipt. |
| `POST /api/loop`, `GET /api/loop/<id>[/events]`, `GET /api/loop/example` | The Fix loop tab (live run or recorded replay). Same limits as proofs. |
| `GET /api/config`, `GET /healthz` | Public limits and live state; liveness. |

Failures are JSON `{"error": {"code", "message"}}` with a human reason. The server fails
closed: if it cannot prove something it says so and never shows a made-up result.

## Configuration (environment variables)

| Name | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8080` | Listen port (binds `0.0.0.0`). |
| `LATCH_DATA` | `latch/web/.data` (`/data` in the image) | Receipt cache, usage counter, loop cache. |
| `NEBIUS_API_KEY` | unset | Model key. Without it live runs are off and cached receipts still work. **Read only from the environment when `LATCH_LOCAL_KEY_FALLBACK=0`** (the image default). |
| `GITHUB_TOKEN` | unset | Optional. Raises the GitHub API limit from 60/h to 5000/h. Never reaches PR code. |
| `LATCH_LIVE` | `1` | `0` disables live runs. |
| `LATCH_MAX_LIVE_RUNS_PER_DAY` | `50` | Global daily spend cap (UTC day, persisted). At the cap the app falls back to cached receipts with a message. |
| `LATCH_RATE_LIMIT` / `LATCH_RATE_WINDOW` | `3` / `3600` | Live runs per IP per window. |
| `LATCH_QUEUE_MAX` | `5` | Waiting jobs. One job runs at a time; a full queue returns 503 with the reason. |
| `LATCH_SUBMIT_RATE_PER_MIN` | `20` | Submissions per IP per minute (cheap abuse guard). |
| `LATCH_SETUP_TIMEOUT` / `LATCH_TEST_TIMEOUT` | `240` / `120` | Seconds for dependency install and for the test, enforced separately. |
| `LATCH_SETUP_MEM_MB` / `LATCH_TEST_MEM_MB` | `4096` / `2048` | Address-space limits. |
| `LATCH_SANDBOX_NET` | `auto` | `auto` runs the test phase under `unshare --net` when the host allows it; `off` disables. |
| `LATCH_INSTALL_DEPS` | `1` | `0` skips installing the PR's own requirements. |
| `LATCH_UV_CACHE` | `/opt/latch/uv-cache` | Prewarmed uv cache, copied per run. |
| `LATCH_LOOP` / `LATCH_LOOP_TIMEOUT` / `LATCH_LOOP_CACHE` | `1` / `240` / `$LATCH_DATA/loop-cache` | Fix loop live runs. |
| `LATCH_TRUST_PROXY` | `1` | Use the last `X-Forwarded-For` entry as the client IP (set `0` if not behind a proxy). |
| `LATCH_LOCAL_KEY_FALLBACK` | `1` locally, `0` in the image | `1` lets `latch.run.load_key` fall back to an `export NEBIUS_API_KEY=` line in `~/.zshrc`. |

## Why `latch-proof.json` said `proven: false` with return code -15

Not Python 3.14. The saved test replays correctly (fails on base, passes on head) on
3.12 and on 3.14 when run outside `mini`. A return code of -15 with empty output means
the isolated `mini safe-in` process received SIGTERM: the sandbox was torn down or timed
out before the test produced a result. That is a harness outcome, not a test result.
The hosted app avoids it by running the test in its own sandbox with a separate, explicit
timeout. A timeout is reported as "the test step exceeded its N second limit", never as
`proven: false`. The image pins Python 3.12 and the PR-URL path (`latch/github_pr.py`)
now proves Click #3299 on it.

## Isolation, honestly

PR code is untrusted. What the sandbox (`sandbox.py`, passed to `prove(..., runner=...)`) does:

* **Fresh environment.** Nothing is inherited, so `NEBIUS_API_KEY` and `GITHUB_TOKEN` are absent
  from PR code. Temporary `HOME`, minimal `PATH`.
* **Process isolation.** Own session and process group; the whole group is killed on timeout and
  after each phase. Output goes to size-capped files, not pipes.
* **Resource limits.** `RLIMIT_CPU`, `AS`, `FSIZE`, `NOFILE`, `CORE`, and `NPROC` set to the uid's
  current task count plus headroom (a fork bomb hits the limit instead of the host). `NPROC` is Linux-only: macOS has no per-uid task count, so there it is skipped.
* **Server not readable.** The server calls `prctl(PR_SET_DUMPABLE, 0)`, so same-uid children
  cannot read `/proc/<pid>/environ` or ptrace it. The same is done for the Fix loop launcher.
* **Network.** The test phase runs under `unshare --net --map-root-user` when the host allows it.
  The setup phase (venv and dependency install) needs the network and has it.
* **Proof integrity.** The generated test runs with `--noconftest`, an empty pytest config, no
  cacheprovider and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, so a PR's `conftest.py`, `addopts` or plugins
  cannot rewrite the pytest outcome. The PR's own library code still runs in the test process, so a
  hostile PR could in principle fake a result from inside the import; a trusted out-of-process
  verifier is the real fix.
* **Clean checkout.** Base and head are fetched shallow by exact SHA into a temp repo, tested from
  per-commit snapshots, and the temp dir is deleted afterwards. Per-run uv cache copy, so one PR
  cannot poison another.
* **Container.** The image runs as uid 10001, with no secrets baked in, code root-owned and read-only,
  only `/data` writable.
* **Web surface.** CSP `script-src 'self'`; untrusted text is inserted with `textContent`; links are
  limited to `https://github.com`; the boot JSON escapes `< > &`.

What it does **not** do (hooks still needed in `prove.py` for stronger isolation):

* It is thread-based with per-stage timeouts, not a VM or gVisor. A kernel exploit or a
  dependency's setup script that abuses the network during setup is outside this model.
* Same-uid PR code can still read anything the server's uid can read on disk (receipts are public
  anyway). On a developer laptop with the key in `~/.zshrc`, that file is readable by PR code: only
  run the hosted app locally against PRs you trust, or set `LATCH_LOCAL_KEY_FALLBACK=0` and pass
  the key by environment.
* The rate limits and the daily cap are held by one server process. The cap counter is persisted
  across restarts, but the per-IP windows are in memory (a restart resets them), and running more than
  one replica needs a shared atomic store (SQLite) first. Deploy one instance.
* `X-Forwarded-For` trust: with `LATCH_TRUST_PROXY=1` the last entry is used as the client IP. That is
  right behind a proxy that appends the peer address; if the host passes client headers through
  unchanged, set `LATCH_TRUST_PROXY=0`.
* The Fix loop runs model-written code under a stripped environment but without rlimits.
* `unshare --net --map-root-user` is **blocked inside a default Docker container** (Docker's seccomp
  profile denies `unshare`/`clone` with `CLONE_NEWUSER`). Tested on Colima: it fails as uid 10001 and as
  root. It works only with `--security-opt seccomp=unconfined` or `--cap-add SYS_ADMIN`, and never under
  QEMU amd64 emulation (`Invalid argument`). Nebius Serverless AI endpoint settings (image, ports, env,
  secrets, auth, platform) do not expose seccomp, capabilities or privileged mode, so expect no network
  namespace there. The server does not crash: at startup it logs `WARNING: network namespace isolation is
  unavailable here ...` and runs with the stripped env, rlimits and process-group kill; PR test code can
  then reach the network (it holds no secret: the env is stripped and the server process is non-dumpable).
  Set `LATCH_SANDBOX_NET=off` to silence the warning.
* A stronger design needs `prove.py` to accept a per-phase runner (setup and test separately) and a
  read-only snapshot, so a VM-backed runner can replace `SandboxRunner` unchanged.

## Deploy

`deploy.sh` is parameterized and was **not run** by the author. It never logs in: run
`nebius profile create` yourself first.

```bash
NEBIUS_PROJECT_ID=project-... NEBIUS_REGION=eu-north1 NEBIUS_SUBNET_ID=vpcsubnet-... \
NEBIUS_API_KEY=... GITHUB_TOKEN=... DRY_RUN=1 latch/web/deploy.sh   # print the mutating steps
latch/web/deploy.sh                    # registry (if missing) -> docker login -> buildx amd64 push -> endpoint -> HTTPS URL
latch/web/deploy.sh build              # build and push only
latch/web/deploy.sh vercel             # cached-receipts-only fallback (untested)
```

It uses `nebius ai endpoint create ... --platform cpu-d3 --preset 4vcpu-16gb --public
--container-port 8080 --auth none` so judges reach the URL with no token (`--auth none`
is also the default). Prefer `SECRET_SELECTOR=<MysteryBox secret>` over `NEBIUS_API_KEY`, which
stores the key in the endpoint spec. Per the Nebius docs the managed HTTPS URL comes from
`status.public_endpoints`; the script prints it. A public endpoint spends your key: keep
`LATCH_MAX_LIVE_RUNS_PER_DAY` low.

The container is persistent only if `/data` is mounted; without a volume the receipts cache
resets on restart (the recorded Click receipt is re-seeded on boot).

Build the image yourself, from the repo root:

```bash
docker buildx build --platform linux/amd64 -f latch/web/Dockerfile -t latch-web .
docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e GITHUB_TOKEN latch-web
```

Tested locally (Colima, amd64 under emulation, image about 415 MB on disk, 103 MB compressed): `/healthz`,
the cached first screen, a fail-closed daily cap, the per-IP limit (429 with `Retry-After`), bad URL,
not found, and "no linked issue" errors, and the sandboxed proof of the Click PR. Startup under emulation
takes about 15 s; a live Click run took about 90 s there (native amd64 is much faster).

Without `GITHUB_TOKEN`, GitHub allows 60 API calls per hour per egress IP, shared by every visitor and
every restart. When it is exhausted the app falls back to the saved receipt ("GitHub rate-limited this
server") and refuses new PRs. Set `GITHUB_TOKEN` on any public deployment.

Offline image: `docker save latch-web -o latch-web-amd64.tar`, then `docker load -i latch-web-amd64.tar`.

Disk note: keep Docker/Colima data and image tarballs on the external drive
(`/mnt/data/nvdia/latch/`), not the internal disk. exFAT: no repos or venvs there.

## Files

* `app.py`: HTTP server, routes, SSE, CSP.
* `service.py`: jobs, queue, rate limits, daily cap, proof and loop execution.
* `sandbox.py`: the sandbox runner. `store.py`: disk cache.
* `static/`: `index.html`, `app.css`, `app.js`, `loop.js`.
* `test_app.py`: tests (no network, no model).
* `Dockerfile`, `Dockerfile.dockerignore`, `deploy.sh`, `vercel/`.
