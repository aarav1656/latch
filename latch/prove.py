import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from .run import MODEL, call_model, load_key
from .harness.parse import extract_test_function


_SECTION_END = re.compile(r"(?m)^(?:_{3,} .+ _{3,}|={3,} .+ ={3,})$")


def expected_base_failure(base_result, test_name):
    """Classify why the proof test failed, from the failure section pytest prints for that test.

    The old version required the summary line `FAILED latch_issue_test.py::<name> - <msg>`, but pytest
    drops ` - <msg>` when a long test name overflows the terminal width (80 columns on a non-tty), so
    long names were wrongly classified as "not an assertion failure". The failure section
    (`____ test_name ____` up to the next section header) and its `E   ` lines do not depend on width.
    A test that errors in setup/collection has no such section (`ERROR at ...` headers), so it is never
    classified as a behavior failure. Returns "assertion", "unexpected-operation" or None.
    """
    output = base_result["stdout"] + base_result["stderr"]
    header = re.search(rf"(?m)^_{{2,}}\s+{re.escape(test_name)}\s+_{{2,}}$", output)
    if not header:
        return None
    rest = output[header.end():]
    end = _SECTION_END.search(rest)
    failure = rest[:end.start()] if end else rest
    errors = [line for line in failure.splitlines() if line.startswith("E ")]
    if any(re.match(r"E\s+Failed: Latch expected the issue operation to succeed:", line) for line in errors):
        return "unexpected-operation"
    if any(re.match(r"E\s+(AssertionError\b|assert\b)", line) for line in errors):
        return "assertion"
    return None


_FAIL_CALLS = {"raises", "fail", "warns"}


def _is_failure_call(node):
    """pytest.raises(...) / pytest.fail(...) / pytest.warns(...), also when imported by name."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _FAIL_CALLS and isinstance(func.value, ast.Name) and func.value.id == "pytest"
    return isinstance(func, ast.Name) and func.id in _FAIL_CALLS


def _constant_truthy(node):
    return isinstance(node, ast.Constant) and bool(node.value)


def validate_proof_test(source):
    """Static check of a generated proof test. Returns None when it can judge a fix, else the rejection reason.

    A test passes this check only if it has a real body and can actually fail on the issue: at least one
    `assert` that is not a constant truth (`assert True`), a `pytest.raises` / `pytest.warns` block, a
    `pytest.fail(...)` call (the explicit unexpected-operation failure), or `raise AssertionError`.
    An empty body, `...` or `pass` only, is rejected: it passes on any code, so it proves nothing.
    """
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError as error:
        return f"the test is not valid Python ({error.msg}, line {error.lineno})"
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name.startswith("test_")]
    if not functions:
        return "no top-level test_ function"
    function = functions[0]
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]  # docstring
    if not body:
        return "the test body is empty"
    if all(isinstance(n, ast.Pass) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                      and n.value.value is Ellipsis) for n in body):
        return "the test body is only `...` or `pass`, a placeholder that passes on any code"
    for node in ast.walk(function):
        if isinstance(node, ast.Assert) and not _constant_truthy(node.test):
            return None
        if _is_failure_call(node):
            return None
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "AssertionError":
                return None
    return ("the test has no real check: it needs an `assert` on the observable result (not `assert True`), "
            "a `pytest.raises` block, or a `pytest.fail` call, so it cannot fail on the bug")


class ModelRequestError(RuntimeError):
    def __init__(self, what, status, attempts):
        super().__init__(f"{what} request failed: HTTP {status}")
        self.status, self.attempts = status, attempts


def _stricter(prompt, reason, previous):
    return (
        f"{prompt}\n\nYOUR PREVIOUS ANSWER WAS REJECTED BEFORE IT WAS RUN: {reason}.\n"
        f"Previous answer:\n{previous[:3000]}\n\n"
        "Write a different test now. Its body must perform the issue's operation and contain at least one real "
        "`assert` on the observable result (never `assert True`, `...` or `pass`), or `with pytest.raises(...)`, "
        "or a `pytest.fail(...)` call in the branch that catches the operation's exception. No placeholders, no prose."
    )


def generate_proof_test(ask, key, prompt, system, model, max_tokens, what="Nebius test-generation"):
    """Ask the model for a proof test; reject vacuous ones; retry once with a stricter prompt.

    `ask` has the latch.run.call_model signature. Returns (function_source_or_None, attempts). Every attempt is
    recorded as {attempt, completion_id, valid, rejection, source}; the function is None when both attempts were
    rejected (the caller fails closed). Raises ModelRequestError when the model call itself fails.
    """
    attempts = []
    user = prompt
    for number in (1, 2):
        status, content, completion_id = ask(key, user, model=model, system=system, max_tokens=max_tokens)
        if status != 200 or not content:
            raise ModelRequestError(what, status, attempts)
        try:
            function = extract_test_function(content)
            reason = validate_proof_test(function)
        except ValueError:
            function, reason = None, "the reply contained no test_ function"
        attempts.append({"attempt": number, "completion_id": completion_id, "valid": reason is None,
                         "rejection": reason, "source": (function or content)[:4000]})
        if reason is None:
            return function, attempts
        user = _stricter(prompt, reason, function or content)
    return None, attempts


# Every pytest run of proof tests / suites uses the same env so output does not depend on the terminal.
PYTEST_ENV = {"COLUMNS": "200", "PYTEST_ADDOPTS": "-rf --tb=short"}


def limit_resources():
    """preexec_fn for subprocesses that run model-written or PR code: best-effort resource limits.

    CPU seconds and written-file size are limited everywhere; address space and process count only on
    Linux, where setrlimit enforces them reliably (on macOS RLIMIT_AS is not enforced and RLIMIT_NPROC is
    per-user, so a low value would break the whole session). Wall-clock timeouts are set by the callers.
    """
    import resource

    limits = [(resource.RLIMIT_CPU, 240), (resource.RLIMIT_FSIZE, 256 * 1024 * 1024),
              (resource.RLIMIT_CORE, 0)]
    if sys.platform.startswith("linux"):
        limits += [(resource.RLIMIT_AS, 8 * 1024 ** 3), (resource.RLIMIT_NPROC, 1024)]
    for which, value in limits:
        try:
            _, hard = resource.getrlimit(which)
            resource.setrlimit(which, (value if hard == resource.RLIM_INFINITY else min(value, hard), hard))
        except (ValueError, OSError):
            pass


def proven(base_result, head_result, test_name):
    base_output = base_result["stdout"] + base_result["stderr"]
    return (
        base_result["returncode"] != 0
        and head_result["returncode"] == 0
        and test_name in base_output
        and expected_base_failure(base_result, test_name) is not None
    )


def git(repo, *args, timeout=30):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout
    )


def archive(repo, ref, target):
    data = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", ref],
        stdout=subprocess.PIPE,
        check=True,
        timeout=60,
        cwd=target,
    ).stdout
    subprocess.run(
        ["tar", "-xf", "-", "-C", str(target)], input=data, check=True, timeout=60
    )


def run_test(snapshot, command, isolate=False):
    home = snapshot / ".latch-home"
    home.mkdir()
    env = {
        name: os.environ[name]
        for name in ("PATH", "LANG", "LC_ALL", "TMPDIR")
        if name in os.environ
    }
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(snapshot), str(snapshot / "src")])
    env.update(PYTEST_ENV)
    if isolate:
        mini = shutil.which("mini")
        if not mini:
            raise RuntimeError("mini safe-in is required to run pull request code")
        setup = [
            "python3 -m venv .latch-venv",
            ".latch-venv/bin/pip install pytest semver",
            "if [ -f requirements.txt ]; then .latch-venv/bin/pip install -r requirements.txt; fi",
            "if [ -f requirements-dev.txt ]; then .latch-venv/bin/pip install -r requirements-dev.txt; fi",
            "if [ -f pyproject.toml ] || [ -f setup.py ]; then .latch-venv/bin/pip install -e .; fi",
            f"COLUMNS=200 PYTEST_ADDOPTS='-rf --tb=short' .latch-venv/bin/{shlex.join(command)} latch_issue_test.py",
        ]
        result = subprocess.run(
            [mini, "safe-in", str(snapshot), " && ".join(setup)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    else:
        result = subprocess.run(
            [*command, "latch_issue_test.py"],
            cwd=snapshot,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            preexec_fn=limit_resources,
        )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


def prove(repo, base, head, issue, test_command, receipt, on_step=None, isolate_tests=False, runner=None):
    # runner(snapshot: Path, command: list[str]) -> {returncode, stdout, stderr}
    # replaces run_test for each snapshot (used by hosted deployments to sandbox PR code).
    def step(name):
        if on_step:
            on_step(name)

    repo = Path(repo).resolve()
    if not repo.is_dir() or not issue.strip():
        raise ValueError("repo must be a directory and issue text must be non-empty")
    if len(issue) > 20000:
        raise ValueError("issue text exceeds the 20,000 character input limit")
    commits = []
    for ref in (base, head):
        checked = git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        if checked.returncode:
            raise ValueError(f"unknown commit ref: {ref}")
        commits.append(checked.stdout.strip())
    base_commit, head_commit = commits
    changed = git(repo, "diff", "--name-only", "--diff-filter=ACMR", base_commit, head_commit)
    if changed.returncode:
        raise RuntimeError(changed.stderr.strip() or "could not inspect revision diff")
    paths = [p for p in changed.stdout.splitlines() if p.endswith(".py")]
    if not paths:
        raise ValueError("the selected revisions have no changed Python files")
    diff = git(
        repo, "diff", "--no-ext-diff", "--unified=60", base_commit, head_commit, "--", *paths
    )
    if diff.returncode:
        raise RuntimeError(diff.stderr.strip() or "could not read Python diff")
    if not diff.stdout.strip():
        raise ValueError("the selected Python diff is empty")
    if len(diff.stdout) > 40000:
        raise ValueError("Python diff exceeds the 40,000 character model input limit")

    key = load_key()
    if not key:
        raise RuntimeError("NEBIUS_API_KEY is not configured")
    step("model")
    prompt = (
        "Create exactly one self-contained pytest test function named test_... and no prose. "
        "Put every import inside the test function. Use the issue report as the "
        "independent expected behavior. Use actual issue-named library types, not stand-ins. "
        "Assert that the reported correct behavior occurs. "
        "If that operation raises an exception, catch it and call pytest.fail with a message "
        "starting exactly 'Latch expected the issue operation to succeed:'. The test must fail "
        "on the buggy base revision and pass on the "
        "fixed head revision. Do not expect the bug as correct behavior or test the diff mechanically.\n\n"
        f"Issue report:\n{issue.strip()}\n\nPython diff:\n{diff.stdout}"
    )
    retries = []
    system = (
        "Write one self-contained Python pytest function named test_... that asserts the "
        "issue's expected behavior, using actual issue-named library types rather than "
        "stand-ins. If the operation raises, catch it and call pytest.fail with a message "
        "starting exactly 'Latch expected the issue operation to succeed:'. It must fail "
        "on the bug and pass on the fix. Put imports inside it. Output no prose."
    )

    def ask(*args, **kwargs):
        return call_model(*args, on_retry=retries.append, **kwargs)

    try:
        function, test_attempts = generate_proof_test(ask, key, prompt, system, MODEL, 2048)
    except ModelRequestError as error:
        raise RuntimeError(f"Nebius model request failed: HTTP {error.status}") from None
    if function is None:
        # Fail closed: both generations were vacuous, so nothing was run and nothing is proven.
        result = {
            "repo": repo.name, "base": base_commit, "head": head_commit, "issue": issue.strip(),
            "test_command": shlex.split(test_command), "model": MODEL,
            "completion_id": test_attempts[-1]["completion_id"], "test": None,
            "base_result": None, "head_result": None, "test_name": None,
            "base_failure_type": None, "base_failure_is_expected": False, "proven": False,
            "rejected_test_reason": test_attempts[-1]["rejection"],
            "why_not_proven": "the generated test was rejected as vacuous twice: " + test_attempts[-1]["rejection"],
            "test_attempts": test_attempts, "model_retries": retries,
        }
        output = Path(receipt)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        step("receipt")
        return result
    completion_id = test_attempts[-1]["completion_id"]
    test_name = re.match(r"\s*def\s+(test_\w+)", function).group(1)

    command = shlex.split(test_command)
    if not command:
        raise ValueError("test command cannot be empty")
    with tempfile.TemporaryDirectory(prefix="latch-proof-") as temp:
        root = Path(temp)
        base_dir, head_dir = root / "base", root / "head"
        base_dir.mkdir()
        head_dir.mkdir()
        archive(repo, base_commit, base_dir)
        archive(repo, head_commit, head_dir)
        test_source = f"import pytest\n\n{function.rstrip()}\n"
        for snapshot in (base_dir, head_dir):
            (snapshot / "latch_issue_test.py").write_text(test_source, encoding="utf-8")
        execute = runner if runner is not None else (
            lambda snapshot, argv: run_test(snapshot, argv, isolate=isolate_tests)
        )
        step("base-test")
        base_result = execute(base_dir, command)
        step("head-test")
        head_result = execute(head_dir, command)

    result = {
        "repo": repo.name,
        "base": base_commit,
        "head": head_commit,
        "issue": issue.strip(),
        "test_command": command,
        "model": MODEL,
        "completion_id": completion_id,
        "test": test_source,
        "base_result": base_result,
        "head_result": head_result,
        "test_name": test_name,
        "base_failure_type": expected_base_failure(base_result, test_name),
        "base_failure_is_expected": expected_base_failure(base_result, test_name) is not None,
        "proven": proven(base_result, head_result, test_name),
        "test_attempts": test_attempts,
        "model_retries": retries,
    }
    if runner is not None:
        result["test_runner"] = getattr(runner, "description", "custom runner")
    output = Path(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    step("receipt")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prove an issue-specific regression across two Git revisions"
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--test-command", default="python3 -m pytest -q")
    parser.add_argument("--receipt", default="latch/runs/latest-proof.json")
    args = parser.parse_args(argv)
    try:
        result = prove(args.repo, args.base, args.head, args.issue, args.test_command, args.receipt)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Latch proof failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"proven": result["proven"], "receipt": args.receipt, "completion_id": result["completion_id"]}))
    return 0 if result["proven"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
