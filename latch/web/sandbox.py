"""Sandboxed test execution for the hosted Latch app.

`SandboxRunner` is passed to `latch.prove.prove(..., runner=...)`. It runs the
generated test against one snapshot in a child process that:

* gets a freshly built environment (nothing is inherited, so NEBIUS_API_KEY,
  GITHUB_TOKEN and every other secret in the server's environment are absent),
* runs in its own session/process group with a temporary HOME,
* is limited with RLIMIT_CPU / AS / NPROC / FSIZE / NOFILE / CORE,
* is killed (whole process group) when its wall-clock budget runs out,
* has its stdout/stderr written to size-capped files rather than pipes,
* optionally runs in an empty network namespace for the test phase
  (`unshare --net`, only when the host allows it).

Setup (venv + dependency install) and test have separate timeouts.
"""

import os
import resource
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

OUTPUT_LIMIT = 12000
STANDARD_PATH = "/usr/local/bin:/usr/bin:/bin"


class SandboxTimeout(RuntimeError):
    """A sandboxed phase exceeded its wall-clock budget."""

    def __init__(self, phase, seconds):
        super().__init__(f"The {phase} step exceeded its {int(seconds)} second limit")
        self.phase = phase
        self.seconds = seconds


class SandboxError(RuntimeError):
    """The test environment could not be prepared."""


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def drop_dumpable():
    """Make this process non-dumpable so same-uid children cannot read
    /proc/<pid>/environ (where the server's secrets live) or ptrace it."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_DUMPABLE = 4
        return libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except Exception:
        return False


class SandboxConfig:
    def __init__(self, **overrides):
        self.setup_timeout = _int_env("LATCH_SETUP_TIMEOUT", 240)
        self.test_timeout = _int_env("LATCH_TEST_TIMEOUT", 120)
        self.install = os.environ.get("LATCH_SANDBOX_INSTALL", "auto")  # auto | none
        self.install_deps = os.environ.get("LATCH_INSTALL_DEPS", "1") != "0"
        cache = os.environ.get("LATCH_UV_CACHE", "/opt/latch/uv-cache")
        self.uv_cache = cache if os.path.isdir(cache) else None
        self.net_isolation = os.environ.get("LATCH_SANDBOX_NET", "auto")  # auto | off
        self.nproc_headroom = _int_env("LATCH_SANDBOX_NPROC_HEADROOM", 256)
        self.setup_mem_mb = _int_env("LATCH_SETUP_MEM_MB", 4096)
        self.test_mem_mb = _int_env("LATCH_TEST_MEM_MB", 2048)
        self.setup_fsize_mb = _int_env("LATCH_SETUP_FSIZE_MB", 512)
        self.test_fsize_mb = _int_env("LATCH_TEST_FSIZE_MB", 64)
        for key, value in overrides.items():
            if not hasattr(self, key):
                raise TypeError(f"unknown sandbox option: {key}")
            setattr(self, key, value)


_NET_OK = None


def net_namespace_available():
    global _NET_OK
    if _NET_OK is None:
        unshare = shutil.which("unshare")
        if not unshare:
            _NET_OK = False
        else:
            try:
                probe = subprocess.run(
                    [unshare, "--net", "--map-root-user", "true"],
                    capture_output=True,
                    timeout=10,
                )
                _NET_OK = probe.returncode == 0
            except (OSError, subprocess.SubprocessError):
                _NET_OK = False
    return _NET_OK


def _uid_task_count():
    """Tasks (processes and threads) currently owned by our uid, so RLIMIT_NPROC
    can be set to 'what we already have' plus headroom."""
    uid = os.getuid()
    count = 0
    if not os.path.isdir("/proc/self/task"):
        return None  # no /proc (macOS): the per-uid count is unknowable, so no NPROC limit
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.stat(f"/proc/{entry}").st_uid == uid:
                    count += len(os.listdir(f"/proc/{entry}/task"))
            except OSError:
                continue
    except OSError:
        return 0
    return count


def _limiter(cpu_seconds, mem_bytes, nproc, fsize_bytes):
    def apply():
        def cap(which, value):
            try:
                _, hard = resource.getrlimit(which)
                if hard != resource.RLIM_INFINITY:
                    value = min(value, hard)
                resource.setrlimit(which, (value, value))
            except (ValueError, OSError):
                pass

        cap(resource.RLIMIT_CORE, 0)
        cap(resource.RLIMIT_CPU, cpu_seconds)
        cap(resource.RLIMIT_AS, mem_bytes)
        cap(resource.RLIMIT_FSIZE, fsize_bytes)
        cap(resource.RLIMIT_NOFILE, 1024)
        if nproc:
            cap(resource.RLIMIT_NPROC, nproc)

    return apply


def _kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _tail(path, limit=OUTPUT_LIMIT):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit * 4))
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")[-limit:]


class SandboxRunner:
    """Callable with the `runner(snapshot, command) -> result` contract of prove()."""

    description = "Latch sandbox: isolated subprocess, stripped env, rlimits, process-group kill"

    def __init__(self, config=None, progress=None):
        self.config = config or SandboxConfig()
        self.progress = progress or (lambda message: None)
        self.notes = []
        use_net = self.config.net_isolation == "auto" and net_namespace_available()
        self.network_isolated = use_net
        self.description = (
            "Latch sandbox: stripped env, rlimits, process-group kill"
            + (", network namespace for the test phase" if use_net else "")
        )

    def _nproc_limit(self):
        headroom = self.config.nproc_headroom
        current = _uid_task_count() if headroom else None
        return (current + headroom) if current is not None else 0

    # -- environment -----------------------------------------------------
    def _env(self, snapshot, home, venv=None, setup=False):
        path_parts = []
        if venv:
            path_parts.append(str(venv / "bin"))
        uv = shutil.which("uv")
        if setup and uv:
            path_parts.append(os.path.dirname(uv))
        path_parts.append(os.path.dirname(sys.executable))
        path_parts.append(STANDARD_PATH)
        env = {
            "PATH": os.pathsep.join(dict.fromkeys(path_parts)),
            "HOME": str(home),
            "TMPDIR": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": os.pathsep.join([str(snapshot), str(snapshot / "src")]),
            "GIT_TERMINAL_PROMPT": "0",
            "CI": "1",
            "COLUMNS": "200",  # pytest truncates "FAILED ... - msg" at the terminal width when not a tty
        }
        if setup:
            env.update(
                {
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "PIP_NO_INPUT": "1",
                    "UV_NO_CONFIG": "1",
                    "UV_PYTHON_DOWNLOADS": "never",
                    "UV_LINK_MODE": "copy",
                    "UV_CACHE_DIR": str(home / "uv-cache"),
                }
            )
        return env

    # -- process helper ---------------------------------------------------
    def _run(self, argv, cwd, env, timeout, phase, mem_mb, fsize_mb, tag):
        cfg = self.config
        out_path, err_path = Path(cwd) / f".latch-{tag}.out", Path(cwd) / f".latch-{tag}.err"
        limiter = _limiter(
            cpu_seconds=int(timeout) + 5,
            mem_bytes=mem_mb * 1024 * 1024,
            nproc=self._nproc_limit(),
            fsize_bytes=fsize_mb * 1024 * 1024,
        )
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                    preexec_fn=limiter,
                    close_fds=True,
                )
            except OSError as error:
                raise SandboxError(f"could not start {argv[0]}: {error}") from error
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc.pid)
                proc.wait()
                raise SandboxTimeout(phase, timeout)
            finally:
                _kill_group(proc.pid)  # reap stragglers the test left behind
        return proc.returncode, _tail(out_path), _tail(err_path)

    # -- setup ------------------------------------------------------------
    def _setup(self, snapshot, home, label):
        cfg = self.config
        deadline = time.monotonic() + cfg.setup_timeout
        venv = snapshot / ".latch-venv"
        ready = venv / ".latch-ready"
        if ready.is_file() and (venv / "bin" / "python").exists():
            # The rerun and mutation checks run the test again in the same snapshot: reuse its environment
            # instead of paying for the install on every run.
            self.progress(f"Reusing the test environment on {label}")
            return venv
        env = self._env(snapshot, home, setup=True)
        if cfg.uv_cache:
            shutil.copytree(cfg.uv_cache, home / "uv-cache", symlinks=True, dirs_exist_ok=True)
        uv = shutil.which("uv")

        def step(argv, what, required):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise SandboxTimeout("setup", cfg.setup_timeout)
            code, out, err = self._run(
                argv, snapshot, env, remaining, "setup", cfg.setup_mem_mb, cfg.setup_fsize_mb, "setup"
            )
            if code != 0:
                detail = (err or out).strip().splitlines()[-1:] or [""]
                if required:
                    raise SandboxError(f"Could not prepare the test environment ({what}): {detail[0]}")
                self.notes.append(f"{label}: {what} failed ({detail[0][:120]})")
                self.progress(f"{what} failed on {label}; continuing with the source tree on PYTHONPATH")
            return code == 0

        python = str(venv / "bin" / "python")
        if uv:
            step([uv, "venv", "--python", sys.executable, str(venv)], "create venv", True)
            install = [uv, "pip", "install", "--python", python]
        else:
            step([sys.executable, "-m", "venv", str(venv)], "create venv", True)
            install = [python, "-m", "pip", "install", "-q"]
        step([*install, "pytest", "semver"], "install pytest", True)
        if cfg.install_deps:
            for name in ("requirements.txt", "requirements-dev.txt"):
                if (snapshot / name).is_file():
                    step([*install, "-r", name], f"install {name}", False)
        if any((snapshot / name).exists() for name in ("pyproject.toml", "setup.py", "setup.cfg")):
            flags = [] if cfg.install_deps else ["--no-deps"]
            step([*install, *flags, "-e", "."], "install project", False)
        try:
            ready.write_text("ok\n")
        except OSError:
            pass
        return venv

    # -- the runner contract ---------------------------------------------
    def __call__(self, snapshot, command):
        snapshot = Path(snapshot)
        cfg = self.config
        label = snapshot.name
        home = snapshot / ".latch-home"
        home.mkdir(exist_ok=True)
        venv = None
        if cfg.install != "none":
            self.progress(f"Preparing test environment on {label}")
            venv = self._setup(snapshot, home, label)
        argv = list(command) + ["latch_issue_test.py"]
        if venv and argv[0] in ("python", "python3", sys.executable):
            argv[0] = str(venv / "bin" / "python")
        env = self._env(snapshot, home, venv=venv)
        if "pytest" in argv:
            # The PR controls conftest.py, pytest.ini/addopts and any plugin on the path. Run the
            # generated test with all of those off so they cannot rewrite the outcome we report.
            config = home / "latch-pytest.ini"
            config.write_text("[pytest]\n")
            at = argv.index("pytest") + 1
            argv[at:at] = [
                "--noconftest", "-p", "no:cacheprovider", "-c", str(config), "--rootdir", str(snapshot),
                "-rf", "--tb=short",  # same output shape as prove.run_test, which classifies the base failure from it
            ]
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        if self.network_isolated:
            argv = ["unshare", "--net", "--map-root-user", "--", *argv]
        self.progress(f"Running the generated test on {label}")
        code, out, err = self._run(
            argv, snapshot, env, cfg.test_timeout, "test", cfg.test_mem_mb, cfg.test_fsize_mb, "test"
        )
        return {"returncode": code, "stdout": out, "stderr": err}
