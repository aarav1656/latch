"""Job queue, rate limits, spend cap and error mapping for the hosted app."""

import collections
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .sandbox import SandboxConfig, SandboxError, net_namespace_available, SandboxRunner, SandboxTimeout
from .store import make_envelope, utc_iso

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_COMMAND = "python3 -m pytest -q"
STEP_ALIASES = {"generating-test": "model"}
STEP_ORDER = ["fetching", "fetching-commits", "model", "base-test", "head-test", "receipt"]


class ApiError(Exception):
    def __init__(self, code, status, message, **extra):
        super().__init__(message)
        self.code, self.status, self.message, self.extra = code, status, message, extra

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


# Nebius Token Factory answers HTTP 402 (credit_balance_exhausted) when the account is out of credits.
CREDITS_REASON = "Live runs are paused: model credits exhausted. Showing saved receipts."

_RULES = [
    ("Enter a public GitHub pull request URL", "bad_url", 400),
    ("does not close an issue in its repository", "no_closing_issue", 422),
    ("closes an issue in another repository", "cross_repo_issue", 422),
    ("closes more than one issue", "multiple_issues", 422),
    ("was not found", "not_found", 404),
    ("head repository is unavailable", "head_unavailable", 422),
    ("too long for one proof run", "issue_too_long", 422),
    ("no changed Python files", "no_python_changes", 422),
    ("selected Python diff is empty", "no_python_changes", 422),
    ("Python diff exceeds", "diff_too_large", 422),
    ("rate limit or access policy", "github_rate_limited", 503),
    ("Could not reach the GitHub API", "github_unreachable", 502),
    ("NEBIUS_API_KEY is not configured", "live_disabled", 503),
    ("HTTP 402", "credits_exhausted", 503),
    ("credit_balance_exhausted", "credits_exhausted", 503),
    ("credits exhausted", "credits_exhausted", 503),
    ("Nebius model request failed", "model_error", 502),
    ("no function in text", "model_bad_output", 502),
    ("oversized response", "github_error", 502),
]
_HUMAN = {
    "bad_url": "Enter a public GitHub pull request URL, like https://github.com/pallets/click/pull/3299.",
    "no_closing_issue": "This pull request does not close an issue in its own repository (add 'Fixes #123' to its description). Latch needs the issue as the expected behavior.",
    "cross_repo_issue": "This pull request closes an issue in a different repository. Latch only supports same-repository issues.",
    "multiple_issues": "This pull request closes more than one issue. Latch needs exactly one issue as its oracle.",
    "not_found": "GitHub could not find that pull request or its linked issue. Is the repository public?",
    "head_unavailable": "The pull request's head repository is unavailable (deleted fork?).",
    "issue_too_long": "The linked issue is too long for one proof run (20,000 character limit).",
    "no_python_changes": "This pull request changes no Python files. Latch proves Python bug fixes only.",
    "diff_too_large": "The Python diff is too large for one proof run (40,000 character limit).",
    "github_rate_limited": "GitHub rate-limited this server. Try again in a few minutes, or open a cached receipt.",
    "github_unreachable": "Could not reach the GitHub API. Try again shortly.",
    "live_disabled": "Live proof runs are not configured on this server. Cached receipts are still available.",
    "credits_exhausted": CREDITS_REASON,
    "model_error": "The Nemotron model request on Nebius Token Factory failed. Nothing was proven; try again shortly.",
    "model_bad_output": "The model did not return a usable test function, so nothing was proven. Try again.",
    "github_error": "GitHub returned an unusable response.",
}


_PRIVATE_PATH = re.compile(r"/(?:tmp|var|private|home|Users|opt|data|app|root)(?:/[^\s'\"):,;]+)+")


def redact(text):
    """Public error detail must not reveal server filesystem paths."""
    return _PRIVATE_PATH.sub("<path>", text)


def classify(error):
    """Map an exception from the proof pipeline to an ApiError with a human reason."""
    if isinstance(error, ApiError):
        return error
    if isinstance(error, SandboxTimeout):
        return ApiError(
            "timeout", 504,
            f"The {error.phase} step ran out of time ({int(error.seconds)} s), so nothing was proven.",
        )
    if isinstance(error, subprocess.TimeoutExpired):
        return ApiError("timeout", 504, "A git or network step timed out, so nothing was proven.")
    if isinstance(error, SandboxError):
        return ApiError("environment_error", 500, f"{error} Nothing was proven.")
    if isinstance(error, subprocess.CalledProcessError):
        return ApiError(
            "fetch_failed", 502,
            "Could not fetch the pull request's commits from GitHub (deleted branch or private fork?).",
        )
    text = str(error)
    for needle, code, status in _RULES:
        if needle in text:
            return ApiError(code, status, _HUMAN.get(code, redact(text)), detail=redact(text)[:300])
    return ApiError("internal_error", 500, "Unexpected error while proving this pull request.", detail=redact(text)[:300])


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self, **overrides):
        self.live = os.environ.get("LATCH_LIVE", "1") != "0"
        self.rate_limit = _env_int("LATCH_RATE_LIMIT", 3)
        self.rate_window = _env_int("LATCH_RATE_WINDOW", 3600)
        self.daily_cap = _env_int("LATCH_MAX_LIVE_RUNS_PER_DAY", 50)
        self.queue_max = _env_int("LATCH_QUEUE_MAX", 5)
        self.job_ttl = _env_int("LATCH_JOB_TTL", 3600)
        self.loop = os.environ.get("LATCH_LOOP", "1") != "0"
        self.loop_timeout = _env_int("LATCH_LOOP_TIMEOUT", 240)
        self.submit_rate = _env_int("LATCH_SUBMIT_RATE_PER_MIN", 20)
        # LATCH_CREDITS_EXHAUSTED=1: the model account is known to be out of credits (HTTP 402). Live runs stay
        # off from the first request, with the calm credits note, and every saved receipt keeps working.
        self.credits_exhausted = os.environ.get("LATCH_CREDITS_EXHAUSTED", "0") == "1"
        self.credit_pause_s = _env_int("LATCH_CREDIT_PAUSE_S", 600)  # live mode stays off this long after a 402
        for key, value in overrides.items():
            if not hasattr(self, key):
                raise TypeError(f"unknown option: {key}")
            setattr(self, key, value)


class DailyCap:
    """Global cap on live model runs per UTC day, persisted across restarts."""

    def __init__(self, path, limit, clock=time.time):
        self.path, self.limit, self.clock = Path(path), limit, clock
        self.lock = threading.Lock()

    def _today(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
            if data.get("date") == self._today():
                return int(data.get("count", 0))
        except (OSError, ValueError):
            pass
        return 0

    def used(self):
        with self.lock:
            return self._load()

    def remaining(self):
        return max(0, self.limit - self.used())

    def record(self):
        with self.lock:
            count = self._load() + 1
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": self._today(), "count": count}))
            os.replace(tmp, self.path)
            return count


class Job:
    def __init__(self, job_id, key, url, owner_repo, number, ip, kind="proof"):
        self.kind = kind
        self.id, self.key, self.url = job_id, key, url
        self.repo, self.number, self.ip = owner_repo, number, ip
        self.status = "queued"  # queued | running | done | error
        self.events = []
        self.cond = threading.Condition()
        self.result = None
        self.error = None
        self.created = time.time()
        self.finished = None
        self.step = None
        self.detail = None

    def emit(self, event, data):
        with self.cond:
            self.events.append({"id": len(self.events) + 1, "event": event, "data": data})
            self.cond.notify_all()

    def finish(self, status):
        with self.cond:
            self.status = status
            self.finished = time.time()
            self.cond.notify_all()

    @property
    def terminal(self):
        return self.status in ("done", "error")

    def wait(self, timeout=10):
        deadline = time.time() + timeout
        with self.cond:
            while not self.terminal:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self.cond.wait(remaining)
        return True


class Service:
    def __init__(self, store, data_dir, config=None, run_pr=None, resolve=None, key_present=None,
                 sandbox_config=None, runner_factory=None, clock=time.time, start_worker=True,
                 loop_argv="default", data_dir_loop=None):
        from latch import github_pr, run as latch_run

        self.store = store
        self.config = config or Config()
        self.clock = clock
        self.run_pr = run_pr or github_pr.run_pull_request
        self.resolve = resolve or self._resolve_github
        self.github = github_pr
        if key_present is None:
            # Hosted: the key comes only from the NEBIUS_API_KEY environment variable.
            # Local development may also use the ~/.zshrc export that latch.run.load_key reads.
            if os.environ.get("LATCH_LOCAL_KEY_FALLBACK", "1") == "0":
                key_present = lambda: bool(os.environ.get("NEBIUS_API_KEY"))
            else:
                key_present = lambda: bool(latch_run.load_key())
        self.key_present = key_present
        self.sandbox_config = sandbox_config or SandboxConfig()
        self.runner_factory = runner_factory or (
            lambda progress: SandboxRunner(self.sandbox_config, progress=progress)
        )
        self.data_dir = Path(data_dir)
        self.loop_argv = default_loop_argv() if loop_argv == "default" else loop_argv
        self.cap = DailyCap(Path(data_dir) / "usage.json", self.config.daily_cap, clock)
        self.lock = threading.RLock()
        self.hits = collections.defaultdict(collections.deque)
        self.submits = collections.defaultdict(collections.deque)
        self.jobs = collections.OrderedDict()
        self.queue = collections.deque()
        self.running = None
        self.credits_paused_until = 0.0
        self.qcond = threading.Condition()
        if start_worker:
            threading.Thread(target=self._worker, daemon=True, name="latch-worker").start()

    # -- status ------------------------------------------------------------
    def live_state(self):
        if not self.config.live:
            return {"enabled": False, "reason": "Live runs are switched off on this server (LATCH_LIVE=0). Cached receipts still work."}
        if not self.key_present():
            return {"enabled": False, "reason": "Live runs are not configured on this server. Cached receipts still work."}
        if self.config.credits_exhausted or self.credits_paused():
            return {"enabled": False, "reason": CREDITS_REASON}
        if self.cap.remaining() <= 0:
            return {"enabled": False, "reason": "The daily limit of live runs has been reached. Cached receipts still work; live runs reset at 00:00 UTC."}
        return {"enabled": True, "reason": None}

    def credits_paused(self):
        return self.clock() < self.credits_paused_until

    def pause_for_credits(self):
        """After an HTTP 402 serve saved receipts for a while instead of failing every judge's click."""
        self.credits_paused_until = self.clock() + max(0, self.config.credit_pause_s)

    def sandbox_status(self):
        """What isolation this process really has, for the startup log. Never raises."""
        want = self.sandbox_config.net_isolation == "auto"
        have = net_namespace_available() if want else False
        description = "stripped env, rlimits, process-group kill" + (", network namespace for the test phase" if have else "")
        warning = None
        if want and not have:
            warning = (
                "network namespace isolation is unavailable here (unshare --net --map-root-user failed; "
                "the container runtime blocks user namespaces). Falling back to env stripping, rlimits and a "
                "process-group kill; PR test code can reach the network. Set LATCH_SANDBOX_NET=off to silence this."
            )
        return {"network_isolated": have, "description": description, "warning": warning}

    def public_config(self):
        live = self.live_state()
        return {
            "live": live["enabled"],
            "live_reason": live["reason"],
            "live_paused_s": max(0, int(self.credits_paused_until - self.clock())) if self.credits_paused() else 0,
            "rate_limit": self.config.rate_limit,
            "rate_window_s": self.config.rate_window,
            "daily_remaining": self.cap.remaining() if self.config.live else 0,
            "queue_max": self.config.queue_max,
            "queued": len(self.queue),
            "busy": self.running is not None,
            "loop": {"available": self.loop_available(), "live": self.loop_available() and live["enabled"]},
        }

    # -- GitHub resolve ----------------------------------------------------
    def _resolve_github(self, url):
        gh = self.github
        owner, name, number = gh.parse_pull_request_url(url)
        pull = gh.github_get(f"/repos/{owner}/{name}/pulls/{number}")
        base_repo = pull["base"]["repo"]["full_name"]
        if not pull["head"].get("repo"):
            raise ValueError("The pull request head repository is unavailable")
        gh.linked_issue(pull.get("body"), base_repo)
        return {
            "repo": base_repo,
            "number": number,
            "base": pull["base"]["sha"],
            "head": pull["head"]["sha"],
            "title": pull.get("title"),
        }

    # -- submit ------------------------------------------------------------
    def _cached_response(self, envelope, note=None):
        meta = envelope["meta"]
        body = {"status": "cached", "cached": True, "receipt": envelope["receipt"], "meta": meta}
        if meta.get("repo") and meta.get("number"):
            body["permalink"] = f"/r/{meta['repo']}/{meta['number']}"
        if note:
            body["note"] = note
        return body

    def submit(self, url, ip, force=False):
        if not isinstance(url, str):
            raise ApiError("bad_url", 400, _HUMAN["bad_url"])
        url = url.strip()
        with self.lock:
            now = self.clock()
            recent = self.submits[ip]
            while recent and recent[0] <= now - 60:
                recent.popleft()
            if len(recent) >= self.config.submit_rate:
                raise ApiError("too_many_requests", 429, "Too many requests. Wait a minute and try again.", retry_after=60)
            recent.append(now)
        try:
            owner, name, number = self.github.parse_pull_request_url(url)
        except ValueError as error:
            raise classify(error)
        try:
            info = self.resolve(url)
        except Exception as error:
            problem = classify(error)
            fallback = self.store.get_pr(f"{owner}/{name}", number) if problem.code in ("github_rate_limited", "github_unreachable") else None
            if fallback:
                why = "GitHub rate-limited this server" if problem.code == "github_rate_limited" else "GitHub could not be reached"
                return self._cached_response(fallback, f"{why}, so this is the latest saved receipt.")
            raise problem
        cached = self.store.get(info["repo"], info["base"], info["head"])
        if cached and not force:
            return self._cached_response(cached)

        live = self.live_state()
        if not live["enabled"]:
            if cached:
                return self._cached_response(cached, live["reason"])
            pr_fallback = self.store.get_pr(info["repo"], info["number"])
            raise ApiError("live_disabled", 503, live["reason"], has_older_receipt=bool(pr_fallback))

        key = f"{info['repo']}@{info['base']}@{info['head']}".lower()
        job, existing = self._admit(
            key, ip, lambda: Job(uuid.uuid4().hex, key, url, info["repo"], info["number"], ip)
        )
        if existing:
            return {"status": "queued", "job_id": job.id, "cached": False, "deduplicated": True}
        job.emit("queued", {"position": self.position(job)})
        return {"status": "queued", "job_id": job.id, "cached": False, "position": self.position(job)}

    def _admit(self, key, ip, make_job):
        """Shared gate for every live run: dedupe, per-IP limit, daily cap, queue bound."""
        with self.lock:
            for job in self.jobs.values():
                if job.key == key and not job.terminal:
                    return job, True
            now = self.clock()
            hits = self.hits[ip]
            while hits and hits[0] <= now - self.config.rate_window:
                hits.popleft()
            if len(hits) >= self.config.rate_limit:
                retry = int(hits[0] + self.config.rate_window - now) + 1
                raise ApiError(
                    "rate_limited", 429,
                    f"Live runs are limited to {self.config.rate_limit} per hour per visitor. Try again in {max(1, retry // 60)} min; cached receipts are unlimited.",
                    retry_after=retry,
                )
            if self.cap.remaining() <= 0:
                raise ApiError("daily_cap", 503, self.live_state()["reason"] or "Daily limit reached.")
            with self.qcond:
                if len(self.queue) >= self.config.queue_max:
                    raise ApiError("queue_full", 503, f"{len(self.queue)} runs are already waiting. Try again in a minute; cached receipts are still available.", retry_after=60)
                job = make_job()
                hits.append(now)
                self.cap.record()
                self.jobs[job.id] = job
                self.queue.append(job)
                self.qcond.notify()
            self._gc()
        return job, False

    # -- fix loop ----------------------------------------------------------
    def loop_example(self):
        """The recorded real run (latch/runs/loop-demo-events.jsonl) as a list of events."""
        path = REPO_ROOT / "latch" / "runs" / "loop-demo-events.jsonl"
        try:
            events = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("{"):
                    events.append(json.loads(line))
        except (OSError, ValueError):
            return None
        if not events or events[-1].get("type") not in ("gate_open", "gave_up"):
            return None
        return {"source": "recorded", "events": events}

    def loop_available(self):
        return self.config.loop and self.loop_argv is not None

    def submit_loop(self, ip):
        if not self.loop_available():
            raise ApiError("loop_unavailable", 503, "The fix loop is not installed on this server. The recorded run is still available.")
        live = self.live_state()
        if not live["enabled"]:
            raise ApiError("live_disabled", 503, live["reason"])
        job, existing = self._admit("loop:demo", ip, lambda: Job(uuid.uuid4().hex, "loop:demo", "loop:demo", "loop", 0, ip, kind="loop"))
        if existing:
            return {"status": "queued", "job_id": job.id, "deduplicated": True}
        job.emit("queued", {"position": self.position(job)})
        return {"status": "queued", "job_id": job.id, "position": self.position(job)}

    def position(self, job):
        with self.qcond:
            if self.running is job:
                return 0
            try:
                return list(self.queue).index(job) + 1
            except ValueError:
                return 0

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def job_json(self, job):
        body = {
            "job_id": job.id, "status": job.status, "step": job.step, "detail": job.detail,
            "position": self.position(job), "pull_request_url": job.url,
        }
        if job.kind == "loop":
            body["events"] = [e["data"] for e in job.events if e["event"] == "loop"]
        if job.status == "done" and job.kind == "proof":
            body.update(receipt=job.result["receipt"], meta=job.result["meta"])
        if job.status == "done" and job.kind == "loop":
            body["verdict"] = job.result["verdict"]
        if job.status == "error":
            body.update(job.error.payload())
        return body

    def _gc(self):
        cutoff = self.clock() - self.config.job_ttl
        for job_id in [j.id for j in self.jobs.values() if j.terminal and (j.finished or 0) < cutoff]:
            self.jobs.pop(job_id, None)

    # -- worker --------------------------------------------------------------
    def _worker(self):
        while True:
            with self.qcond:
                while not self.queue:
                    self.qcond.wait()
                job = self.queue.popleft()
                self.running = job
            try:
                if self.credits_paused():  # queued before the 402 landed: do not spend another failing call
                    raise ApiError("credits_exhausted", 503, CREDITS_REASON)
                (self._execute_loop if job.kind == "loop" else self._execute)(job)
            except Exception as error:  # never let the worker die
                self._fail(job, error)
            finally:
                with self.qcond:
                    self.running = None

    def _fail(self, job, error):
        problem = classify(error)
        if problem.code == "credits_exhausted":
            self.pause_for_credits()
        job.error = problem
        job.emit("error", problem.payload()["error"])
        job.finish("error")

    def _execute(self, job):
        job.status = "running"
        started = time.time()

        def on_step(name):
            name = STEP_ALIASES.get(name, name)
            if name == job.step:
                return
            job.step = name
            job.emit("step", {"step": name, "index": STEP_ORDER.index(name) if name in STEP_ORDER else None})

        def progress(message):
            job.detail = message
            job.emit("detail", {"message": message})

        on_step("fetching")
        runner = self.runner_factory(progress)
        with tempfile.TemporaryDirectory(prefix="latch-job-") as temp:
            try:
                receipt = self.run_pr(
                    job.url, str(Path(temp) / "receipt.json"), TEST_COMMAND, on_step=on_step, runner=runner
                )
            except Exception as error:
                self._fail(job, error)
                return
        finished = time.time()
        envelope = make_envelope(
            receipt, "live", started, finished,
            extra={"runner": getattr(runner, "description", None), "sandbox_notes": getattr(runner, "notes", [])},
        )
        self.store.put(job.repo, job.number, envelope)
        job.result = envelope
        envelope["meta"]["permalink"] = f"/r/{job.repo}/{job.number}"
        job.emit("result", {"receipt": envelope["receipt"], "meta": envelope["meta"]})
        job.finish("done")

    def _execute_loop(self, job):
        """Run `python -m latch.loop demo` and relay its JSONL stdout as SSE `loop` events."""
        job.status = "running"
        job.step = "loop"
        env = loop_env(self.data_dir)
        proc = subprocess.Popen(
            self.loop_argv,
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
            bufsize=1,
        )
        timed_out = []

        def kill():
            timed_out.append(True)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        timer = threading.Timer(self.config.loop_timeout, kill)
        timer.start()
        final = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or "type" not in event:
                    continue
                job.emit("loop", event)
                if event["type"] in ("gate_open", "gave_up", "error"):
                    final = event
            proc.wait()
        finally:
            timer.cancel()
            proc.stdout.close()
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        if timed_out:
            return self._fail(job, ApiError("timeout", 504, f"The fix loop ran out of time ({self.config.loop_timeout} s)."))
        if final and final["type"] in ("gate_open", "gave_up"):
            job.result = {"verdict": final["type"], "receipt": final.get("receipt")}
            job.emit("done", {"verdict": final["type"]})
            return job.finish("done")
        message = (final or {}).get("reason") or "The fix loop stopped without a verdict."
        problem = classify(RuntimeError(message))
        if problem.code == "credits_exhausted":
            return self._fail(job, problem)
        code = "model_error" if "Nebius" in message or "API" in message else "loop_failed"
        self._fail(job, ApiError(code, 502, f"The fix loop stopped without a verdict: {message}"[:400]))


LOOP_LAUNCH = (
    "import runpy, sys\n"
    "from latch.web.sandbox import drop_dumpable\n"
    "drop_dumpable()  # same-uid code run by the loop cannot read this process's environment\n"
    "sys.argv = ['latch.loop'] + sys.argv[1:]\n"
    "runpy.run_module('latch.loop', run_name='__main__')\n"
)


def default_loop_argv():
    if not (REPO_ROOT / "latch" / "loop" / "core.py").exists():
        return None
    return [sys.executable, "-c", LOOP_LAUNCH, "demo"]


def loop_env(data_dir):
    """The loop needs the model key, nothing else. Its pytest children get their own stripped env."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(REPO_ROOT),
        "LATCH_LOOP_CACHE": str(Path(data_dir) / "loop-cache"),
        "GIT_TERMINAL_PROMPT": "0",
    }
    if os.environ.get("NEBIUS_API_KEY"):
        env["NEBIUS_API_KEY"] = os.environ["NEBIUS_API_KEY"]
        env["HOME"] = str(Path(data_dir) / "loop-home")
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    elif os.environ.get("HOME"):
        env["HOME"] = os.environ["HOME"]  # local development: load_key falls back to ~/.zshrc
    return env
