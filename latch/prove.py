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

from . import provider as providers
from .run import LIGHTNING, MODEL, call_model, load_key
from .harness.parse import extract_test_function
from .flake import clean_snapshot, flake_check
from .verdict import FLAKE_RUNS, INVALID_TEST, VALIDATED, decide_verdict, step_detail, verdict_fields


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
    # `with pytest.raises(X):` around code that returned normally: pytest reports `Failed: DID NOT RAISE <class X>`
    # (or DID NOT WARN). That is a behavior mismatch on the code under test, exactly like a failed assert.
    if any(re.match(r"E\s+Failed: DID NOT (RAISE|WARN)\b", line) for line in errors):
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


def _unchecked_tautology():
    return {"checked": False, "changed_symbols": [], "asserted_symbols": [], "ok": True,
            "reason": "not checked: no proof test reached the tautology check"}


def tautology_check_for(changed, repo_modules=None):
    """extra_check for generate_proof_test: the AST tautology check against the symbols the diff changed."""
    from .tautology import check_tautology, rejection_reason

    def extra_check(function):
        result = check_tautology(function, changed, repo_modules)
        return rejection_reason(result), result

    return extra_check


def _stricter(prompt, reason, previous):
    return (
        f"{prompt}\n\nYOUR PREVIOUS ANSWER WAS REJECTED BEFORE IT WAS RUN: {reason}.\n"
        f"Previous answer:\n{previous[:3000]}\n\n"
        "Write a different test now. Its body must perform the issue's operation and contain at least one real "
        "`assert` on the observable result (never `assert True`, `...` or `pass`), or `with pytest.raises(...)`, "
        "or a `pytest.fail(...)` call in the branch that catches the operation's exception. No placeholders, no prose. "
        "At least one assertion must depend on the value or behavior of the code the diff changed, reached through the "
        "API the issue names; never compare a value with itself or assert only on constants or on values the test built."
    )


def generate_proof_test(ask, key, prompt, system, model, max_tokens, what="Nebius test-generation", extra_check=None):
    """Ask the model for a proof test; reject vacuous ones; retry once with a stricter prompt.

    `ask` has the latch.run.call_model signature. Returns (function_source_or_None, attempts). Every attempt is
    recorded as {attempt, completion_id, valid, rejection, source}; the function is None when both attempts were
    rejected (the caller fails closed). Raises ModelRequestError when the model call itself fails.
    `extra_check(function_source) -> (rejection_or_None, info)` runs after validate_proof_test (the deterministic
    tautology check); `info` is stored on the attempt as `tautology`, and a rejection triggers the same retry.
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
        tautology = None
        if reason is None and extra_check is not None:
            reason, tautology = extra_check(function)
        attempts.append({"attempt": number, "completion_id": completion_id, "valid": reason is None,
                         "rejection": reason, "source": (function or content)[:4000],
                         **({"tautology": tautology} if tautology is not None else {})})
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


def run_test(snapshot, command, isolate=False, timeout=300):
    home = snapshot / ".latch-home"
    home.mkdir(exist_ok=True)  # reruns (flake check) reuse the snapshot
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
            timeout=timeout,
            preexec_fn=limit_resources,
        )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


TRIAGE_SYSTEM = ("You triage test failures. Reply with REPRODUCES or NOT_REPRODUCES on the first line, "
                 "then one short sentence.")


def run_triage(ask, key, issue, test_source, failure_text, where="the submitted code", model=None):
    """Nemotron Lightning reads a failing run and says whether it shows the issue's behavior.

    Returns (status, record); record is {model, completion_id, verdict, text} with verdict reproduced |
    not_reproduced | unclear, or None when the call failed.
    """
    from .run import LIGHTNING

    model = model or LIGHTNING
    user = (
        f"Issue report:\n{issue}\n\nRegression test:\n{test_source}\n"
        f"pytest output on {where}:\n{failure_text[-6000:]}\n\n"
        "Does this failure show the issue's reported behavior is still wrong in the code "
        "(an assertion about behavior), as opposed to an environment, import, syntax or test-harness "
        "problem? Answer with exactly one first line: REPRODUCES or NOT_REPRODUCES, then one short "
        "sentence of reason."
    )
    status, text, completion_id = ask(key, user, model=model, system=TRIAGE_SYSTEM, max_tokens=2048, prose=True)
    if status != 200:
        return status, None
    text = (text or "").strip()
    m = re.search(r"\b(NOT_REPRODUCES|REPRODUCES)\b", text)
    verdict = ("not_reproduced" if m.group(1) == "NOT_REPRODUCES" else "reproduced") if m else "unclear"
    return 200, {"model": model, "completion_id": completion_id, "verdict": verdict, "text": text[:1000]}


def prove(repo, base, head, issue, test_command, receipt, on_step=None, isolate_tests=False, runner=None,
          on_step_event=None, revert=True, triage=True, repo_map=True, flake_runs=FLAKE_RUNS,
          mutation=True, strengthen=True):
    """Prove that a change fixes an issue: a generated test must fail on base and pass on head.

    on_step(name): legacy string callback (fetching ... receipt), unchanged.
    on_step_event(dict): {step, status: started|done|failed, ts, detail} for fetch, repo_map, test_writer,
        base_run, head_run, triage, revert_check and verdict.
    runner(snapshot: Path, command: list[str]) -> {returncode, stdout, stderr} replaces run_test for each
        snapshot (used by hosted deployments to sandbox PR code); the revert check uses it too.
    revert: after the gate looks open, revert the fix and require the proof test to fail again (fail closed).
    mutation: after the revert check, run the proof test against up to 5 AST mutants of the changed lines; a kill rate
        below 60% is MUTATION_SURVIVED (fail closed). False skips it.
    strengthen: when the mutation check really fails (MUTATION_SURVIVED), the test writer gets ONE retry with the
        surviving mutants' diffs; the new test goes through the whole gate again (the bar stays at 60%, the harness
        decides). Recorded as mutation.strengthened and as a `strengthen` step. False skips the retry.
    flake_runs: run the proof test this many times on base and on head (default 5, at most 10, 1 turns the check
        off). Any inconsistent side gives the FLAKY verdict. No model calls.
    triage / repo_map: the Lightning calls (an advisory read of the base failure; the repo map that feeds the
        test-writing prompt). repo_map failure never blocks a run; triage never changes `proven`.
    """
    from .modelcalls import PRICES_SOURCE_URL, ModelCalls, total_cost
    from .repomap import build_repo_map
    from . import strengthen as strengthening
    from .revert import changed_files, is_test_path, revert_check
    from .steps import StepLog
    from .tautology import safe_changed_symbols

    def step(name):
        if on_step:
            on_step(name)

    steps = StepLog(on_step_event)
    retries = []
    calls = ModelCalls(call_model, on_retry=retries.append, uses_meta=True)

    repo = Path(repo).resolve()
    if not repo.is_dir() or not issue.strip():
        raise ValueError("repo must be a directory and issue text must be non-empty")
    if len(issue) > 20000:
        raise ValueError("issue text exceeds the 20,000 character input limit")
    command = shlex.split(test_command)
    if not command:
        raise ValueError("test command cannot be empty")
    providers.check_write(receipt)  # a dev provider (openrouter) may only write under latch/runs/dev/
    steps.started("fetch", {"base": base, "head": head})
    try:
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
            raise RuntimeError(providers.not_configured())
    except Exception as error:
        steps.failed("fetch", str(error))
        raise
    steps.done("fetch", {"base": base_commit[:12], "head": head_commit[:12], "changed_python_files": paths[:20]})

    def write_receipt(result):
        if providers.is_dev():
            result.update(dev_only=True, note=providers.DEV_NOTE)
        result.update(provider=providers.current(), model_calls=list(calls.calls), model_cost_usd=total_cost(calls.calls),
                      model_prices_source=PRICES_SOURCE_URL, steps=steps.events)
        output = Path(receipt)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        step("receipt")
        return result

    with tempfile.TemporaryDirectory(prefix="latch-proof-") as temp:
        root = Path(temp)
        base_dir, head_dir = root / "base", root / "head"
        base_dir.mkdir()
        head_dir.mkdir()
        archive(repo, base_commit, base_dir)
        archive(repo, head_commit, head_dir)
        # Which symbols the diff changed (and their callers): the proof test must assert on them. Never raises;
        # when it cannot tell, the check is skipped (checked=False) rather than guessed.
        changed_syms = safe_changed_symbols(repo, base_commit, head_commit, head_dir)

        map_result = {"status": "skipped"}
        if repo_map:
            steps.started("repo_map", {"model": LIGHTNING})
            try:
                map_result = build_repo_map(calls.ask("repo_map"), key, base_dir, issue.strip(), paths)
            except (OSError, ValueError) as error:  # context only: never blocks the proof
                map_result = {"status": "unavailable", "detail": f"{type(error).__name__}: {error}"}
            (steps.done if map_result["status"] == "ok" else steps.failed)(
                "repo_map", {"files": [f["path"] for f in map_result.get("files", [])],
                             "dropped": map_result.get("dropped", []), "detail": map_result.get("detail")})

        step("model")
        steps.started("test_writer", {"model": MODEL})
        map_text = map_result.get("text") or ""
        prompt = (
            "Create exactly one self-contained pytest test function named test_... and no prose. "
            "Put every import inside the test function. Use the issue report as the "
            "independent expected behavior. Use actual issue-named library types, not stand-ins. "
            "Assert that the reported correct behavior occurs. "
            "If that operation raises an exception, catch it and call pytest.fail with a message "
            "starting exactly 'Latch expected the issue operation to succeed:'. The test must fail "
            "on the buggy base revision and pass on the "
            "fixed head revision. Do not expect the bug as correct behavior or test the diff mechanically.\n\n"
            + (f"Repo map (files and symbols that exist in the base revision, picked by Nemotron Lightning and "
               f"checked against the code; import only names listed here or from the issue):\n{map_text}\n\n"
               if map_text else "")
            + f"Issue report:\n{issue.strip()}\n\nPython diff:\n{diff.stdout}"
        )
        system = (
            "Write one self-contained Python pytest function named test_... that asserts the "
            "issue's expected behavior, using actual issue-named library types rather than "
            "stand-ins. If the operation raises, catch it and call pytest.fail with a message "
            "starting exactly 'Latch expected the issue operation to succeed:'. It must fail "
            "on the bug and pass on the fix. Put imports inside it. Output no prose."
        )
        try:
            function, test_attempts = generate_proof_test(
                calls.ask("test_writer"), key, prompt, system, MODEL, 2048, extra_check=tautology_check_for(changed_syms))
        except ModelRequestError as error:
            steps.failed("test_writer", f"HTTP {error.status}")
            raise RuntimeError(f"{providers.label()} model request failed: HTTP {error.status}") from None
        base_info = {"repo": repo.name, "base": base_commit, "head": head_commit, "issue": issue.strip(),
                     "test_command": command, "model": MODEL, "repo_map": {k: v for k, v in map_result.items() if k != "reply"}}
        if function is None:
            # Fail closed: both generations were vacuous, so nothing was run and nothing is proven.
            steps.failed("test_writer", test_attempts[-1]["rejection"])
            reason = "the generated test was rejected as vacuous twice: " + test_attempts[-1]["rejection"]
            tautology = test_attempts[-1].get("tautology")
            rejected_by_tautology = bool(tautology and tautology.get("checked") and tautology.get("ok") is False)
            decided = verdict_fields({"tautology": tautology} if rejected_by_tautology
                                     else {"rejected": test_attempts[-1]["rejection"]}, base_commit, head_commit)
            steps.done("verdict", step_detail(decided))
            return write_receipt({
                **decided,
                **base_info,
                "tautology": tautology or _unchecked_tautology(),
                "completion_id": test_attempts[-1]["completion_id"], "test": None,
                "base_result": None, "head_result": None, "test_name": None,
                "base_failure_type": None, "base_failure_is_expected": False, "proven": False,
                "rejected_test_reason": test_attempts[-1]["rejection"], "why_not_proven": reason,
                "revert_check": {"ran": False, "skipped": "no proof test"},
                "test_attempts": test_attempts, "model_retries": retries,
            })
        steps.done("test_writer", {"attempts": len(test_attempts), "completion_id": test_attempts[-1]["completion_id"]})
        completion_id = test_attempts[-1]["completion_id"]
        test_name = re.match(r"\s*def\s+(test_\w+)", function).group(1)

        test_source = f"import pytest\n\n{function.rstrip()}\n"
        for snapshot in (base_dir, head_dir):
            (snapshot / "latch_issue_test.py").write_text(test_source, encoding="utf-8")
        execute = runner if runner is not None else (
            lambda snapshot, argv: run_test(snapshot, argv, isolate=isolate_tests)
        )
        step("base-test")
        steps.started("base_run")
        base_result = execute(base_dir, command)
        base_kind = expected_base_failure(base_result, test_name)
        steps.done("base_run", {"returncode": base_result["returncode"], "failure_type": base_kind})
        step("head-test")
        steps.started("head_run")
        head_result = execute(head_dir, command)
        steps.done("head_run", {"returncode": head_result["returncode"]})
        is_proven = proven(base_result, head_result, test_name)

        triage_record = None
        if triage and base_kind is not None:
            steps.started("triage", {"model": LIGHTNING})
            tri_status, triage_record = run_triage(calls.ask("triage"), key, issue.strip(), test_source,
                                                   base_result["stdout"] + base_result["stderr"], "the base revision")
            if triage_record is None:
                steps.failed("triage", f"HTTP {tri_status}")
            else:
                triage_record["advisory"] = True
                steps.done("triage", {"verdict": triage_record["verdict"], "completion_id": triage_record["completion_id"]})

        flake_result = None
        if flake_runs is None or flake_runs > 1:
            pre_verdict, _ = decide_verdict({"base": base_result, "head": head_result, "test_name": test_name})
            if pre_verdict != INVALID_TEST:  # an invalid test is not worth rerunning; every other outcome must be stable
                steps.started("flake_check", {"runs": flake_runs})
                rerun = lambda snapshot: (lambda: (clean_snapshot(snapshot), execute(snapshot, command))[1])
                flake_result = flake_check(rerun(base_dir), rerun(head_dir), base_result["returncode"] == 0,
                                           head_result["returncode"] == 0, flake_runs)
                (steps.failed if flake_result["flaky"] else steps.done)(
                    "flake_check", {k: flake_result[k] for k in ("runs", "flaky", "flake_rate", "base_fail_rate", "head_pass_rate")})
        gate_ok = is_proven and not (flake_result and flake_result["flaky"])

        revert_result = {"ran": False, "skipped": "the gate is not open"}
        why_not = None
        if gate_ok and revert:
            steps.started("revert_check")
            try:
                source_changes = changed_files(repo, base_commit, head_commit)
                revert_result = revert_check(
                    lambda directory: execute(directory, command), test_name, test_source, "latch_issue_test.py",
                    head_dir, base_dir, source_changes, root / "mutants", is_test_path)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                revert_result = {"ran": False, "ok": False, "mutants": [], "error": f"{type(error).__name__}: {error}",
                                 "summary": "the revert check could not run, so the gate stays shut"}
            (steps.done if revert_result["ok"] else steps.failed)("revert_check", revert_result["summary"])
            if not revert_result["ok"]:
                is_proven = False
        elif gate_ok:
            revert_result = {"ran": False, "skipped": "revert check disabled"}

        mutation_result = None
        if is_proven and mutation:
            from .mutate import RUN_TIMEOUT, mutation_detail, run_mutation, time_budget_for
            steps.started("mutation_check")
            mutant_timeout = 300 if isolate_tests else RUN_TIMEOUT  # isolated runs install a venv first
            mutant_run = ((lambda directory: execute(directory, command)) if runner is not None else
                          (lambda directory: run_test(directory, command, isolate=isolate_tests, timeout=mutant_timeout)))
            try:
                mutation_changes = changed_files(repo, base_commit, head_commit)
                mutation_result = run_mutation(mutant_run, head_dir, base_dir, mutation_changes, test_source,
                                               "latch_issue_test.py", root / "mutations", is_test_path,
                                               time_budget=time_budget_for(runner is not None))
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                mutation_result = {"ran": False, "mutants": [], "killed": 0, "total": 0, "kill_rate": None, "ok": False,
                                   "threshold": 0.6, "note": f"{type(error).__name__}: {error}"}
            (steps.done if mutation_result["ok"] else steps.failed)("mutation_check", mutation_detail(mutation_result))

        if mutation_result is not None and strengthen and gate_ok and strengthening.eligible(mutation_result):
            first_mutation = mutation_result
            found = strengthening.survivors(first_mutation)
            record = strengthening.new_record(first_mutation, found, test_name)
            steps.started("strengthen", {"survivors": len(found), "killed": first_mutation["killed"],
                                         "total": first_mutation["total"], "kill_rate_before": first_mutation["kill_rate"]})

            def settle(outcome, reason, after=None, new_completion_id=None):
                target = after if after is not None else first_mutation
                target["strengthened"] = strengthening.finish(record, outcome, reason, after, new_completion_id)
                (steps.done if outcome == "adopted" else steps.failed)("strengthen", {
                    "outcome": outcome, "reason": reason, "kill_rate_before": first_mutation["kill_rate"],
                    "kill_rate_after": after["kill_rate"] if after is not None else None})
                return target

            try:
                new_function, new_attempts = generate_proof_test(
                    calls.ask("test_writer"), key, prompt + strengthening.addendum(test_source, first_mutation, found),
                    system, MODEL, 2048, extra_check=tautology_check_for(changed_syms))
            except ModelRequestError as error:
                new_function, new_attempts = None, [{"completion_id": None, "rejection": f"HTTP {error.status}"}]
            new_completion_id = new_attempts[-1]["completion_id"]
            record["completion_id"] = new_completion_id
            new_name_match = re.match(r"\s*def\s+(test_\w+)", new_function) if new_function else None
            if not new_name_match:
                settle("kept_original", "the stronger test was not produced: " + str(new_attempts[-1].get("rejection")))
            else:
                new_name = new_name_match.group(1)
                new_source = f"import pytest\n\n{new_function.rstrip()}\n"
                for snapshot in (base_dir, head_dir):
                    (snapshot / "latch_issue_test.py").write_text(new_source, encoding="utf-8")
                steps.started("base_run")
                new_base = execute(base_dir, command)
                new_kind = expected_base_failure(new_base, new_name)
                steps.done("base_run", {"returncode": new_base["returncode"], "failure_type": new_kind})
                steps.started("head_run")
                new_head = execute(head_dir, command)
                steps.done("head_run", {"returncode": new_head["returncode"]})
                refusal = None
                if not proven(new_base, new_head, new_name):
                    refusal = "the stronger test is not red on base and green on head"
                new_flake = None
                if refusal is None and (flake_runs is None or flake_runs > 1):
                    steps.started("flake_check", {"runs": flake_runs})
                    rerun = lambda snapshot: (lambda: (clean_snapshot(snapshot), execute(snapshot, command))[1])
                    new_flake = flake_check(rerun(base_dir), rerun(head_dir), new_base["returncode"] == 0,
                                            new_head["returncode"] == 0, flake_runs)
                    (steps.failed if new_flake["flaky"] else steps.done)(
                        "flake_check", {k: new_flake[k] for k in ("runs", "flaky", "flake_rate", "base_fail_rate", "head_pass_rate")})
                    if new_flake["flaky"]:
                        refusal = "the stronger test is flaky"
                new_revert = {"ran": False, "skipped": "revert check disabled"}
                if refusal is None and revert:
                    steps.started("revert_check")
                    try:
                        new_revert = revert_check(
                            lambda directory: execute(directory, command), new_name, new_source, "latch_issue_test.py",
                            head_dir, base_dir, changed_files(repo, base_commit, head_commit), root / "mutants-strengthened",
                            is_test_path)
                    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                        new_revert = {"ran": False, "ok": False, "mutants": [], "error": f"{type(error).__name__}: {error}",
                                      "summary": "the revert check could not run, so the gate stays shut"}
                    (steps.done if new_revert["ok"] else steps.failed)("revert_check", new_revert["summary"])
                    if not new_revert["ok"]:
                        refusal = "the stronger test does not isolate the fix: " + str(new_revert["summary"])
                if refusal is not None:
                    for snapshot in (base_dir, head_dir):  # back to the original test; its verdict stands
                        (snapshot / "latch_issue_test.py").write_text(test_source, encoding="utf-8")
                    settle("kept_original", refusal)
                else:
                    steps.started("mutation_check")
                    try:
                        new_mutation = run_mutation(mutant_run, head_dir, base_dir, mutation_changes, new_source,
                                                    "latch_issue_test.py", root / "mutations-strengthened", is_test_path,
                                                    time_budget=time_budget_for(runner is not None))
                    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                        new_mutation = {"ran": False, "mutants": [], "killed": 0, "total": 0, "kill_rate": None, "ok": False,
                                        "threshold": 0.6, "note": f"{type(error).__name__}: {error}"}
                    (steps.done if new_mutation["ok"] else steps.failed)("mutation_check", mutation_detail(new_mutation))
                    # The new test went through every stage, so it (and its evidence) is the one the harness judges.
                    test_source, test_name, base_result, head_result, base_kind = new_source, new_name, new_base, new_head, new_kind
                    flake_result, revert_result, completion_id = new_flake, new_revert, new_completion_id
                    test_attempts = test_attempts + [{**item, "strengthening": True} for item in new_attempts]
                    is_proven = new_mutation["ok"]
                    mutation_result = settle("adopted" if new_mutation["ok"] else "still_surviving",
                                             None if new_mutation["ok"] else "the stronger test still killed too few mutants",
                                             new_mutation, new_completion_id)
        elif mutation_result is not None and not mutation_result["ok"]:
            mutation_result["strengthened"] = strengthening.not_attempted(
                "strengthening is off" if not strengthen
                else "the proof test is flaky, which decides the verdict before the mutation check does" if not gate_ok
                else "no measured kill rate with a surviving mutant to learn from")

    decided = verdict_fields(
        {"base": base_result, "head": head_result, "test_name": test_name, "revert": revert_result,
         "tautology": test_attempts[-1].get("tautology") or _unchecked_tautology(), "flaky": flake_result, "mutation": mutation_result},
        base_commit, head_commit)
    is_proven = decided["proven"]  # derived: proven == (verdict == VALIDATED)
    why_not = None if is_proven else decided["verdict_reason"]

    result = {
        **base_info,
        **decided,
        "completion_id": completion_id,
        "test": test_source,
        "base_result": base_result,
        "head_result": head_result,
        "test_name": test_name,
        "base_failure_type": base_kind,
        "base_failure_is_expected": base_kind is not None,
        "tautology": test_attempts[-1].get("tautology") or _unchecked_tautology(),
        "proven": is_proven,
        "revert_check": revert_result,
        "triage": triage_record,
        "test_attempts": test_attempts,
        "model_retries": retries,
    }
    if why_not:
        result["why_not_proven"] = why_not
    if runner is not None:
        result["test_runner"] = getattr(runner, "description", "custom runner")
    steps.done("verdict", step_detail(decided))
    return write_receipt(result)


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
