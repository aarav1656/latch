"""The fix loop.

Gate: the generated proof test must FAIL on the base (buggy) revision and PASS on the
revision under test, and the repo's own suite must stay green. The harness decides; the model
only proposes source rewrites. The proof test is generated once and frozen, so the agent can
never edit its way to green by touching the test.
"""

import datetime
import difflib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from ..harness.parse import extract_test_function
from ..modelcalls import PRICES_SOURCE_URL, ModelCalls, total_cost
from ..prove import (PYTEST_ENV, TRIAGE_SYSTEM, ModelRequestError, archive, expected_base_failure,
                     generate_proof_test, git, limit_resources, proven, run_test, run_triage, validate_proof_test)
from ..repomap import build_repo_map
from ..revert import changed_files, is_test_path, revert_check
from ..run import LIGHTNING, MODEL, call_model, load_key
from ..steps import StepLog
from ..verdict import step_detail, verdict_fields

ULTRA = MODEL
DEFAULT_MODEL = ULTRA
ALLOWED_MODELS = (ULTRA, LIGHTNING)
TEST_FILE = "latch_issue_test.py"
TEXT_LIMIT = 20 * 1024
SOURCE_LIMIT = 60 * 1024
DEMO_DIR = Path(__file__).resolve().parent / "demo"

TEST_SYSTEM = (
    "Write one self-contained Python pytest function named test_... that asserts the "
    "issue's expected behavior. Put imports inside it. Output no prose. It must fail on the "
    "buggy base and pass on a correct fix."
)
FIX_SYSTEM = (
    "You are a careful coding agent repairing a bug fix that is wrong. A frozen regression "
    "test written from the issue fails on the current code. Rewrite the non-test source files "
    "so the issue is fixed everywhere it appears, without breaking the existing tests. Never "
    "edit tests. Reply with no prose, only complete replacement files, each in exactly this "
    "format:\n=== FILE: path/relative/to/repo/root.py ===\n<entire new file contents>\n=== END FILE ==="
)


class LoopError(RuntimeError):
    """Infrastructure failure. The loop fails closed and reports `reason`."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clip(text, limit=TEXT_LIMIT):
    """Return (text, truncated). Keeps the head and the tail, where pytest puts its summary."""
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    if len(text) <= limit:
        return text, False
    keep = limit // 2
    return text[:keep] + "\n...[truncated]...\n" + text[-keep:], True


def _clip_fields(data, fields):
    out = dict(data)
    cut = []
    for name in fields:
        if name in out and isinstance(out[name], str):
            out[name], flag = clip(out[name])
            if flag:
                cut.append(name)
    if cut:
        out["truncated"] = True
        out["truncated_fields"] = cut
    return out


def _clip_result(result):
    """pytest result dict -> receipt form with a combined `output` string."""
    output, flag = clip((result.get("stdout") or "") + (result.get("stderr") or ""))
    out = {"returncode": result["returncode"], "output": output}
    if flag:
        out["truncated"] = True
    return out


def _run_suite(snapshot, command):
    """Run the repo's own suite (no extra file args). Mirrors prove.run_test's sandboxing."""
    home = snapshot / ".latch-suite-home"
    home.mkdir(exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    env["HOME"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(snapshot), str(snapshot / "src")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(PYTEST_ENV)
    try:
        r = subprocess.run(command, cwd=snapshot, env=env, capture_output=True, text=True, timeout=300,
                           preexec_fn=limit_resources)
    except (OSError, subprocess.SubprocessError) as error:
        raise LoopError(f"could not run the repo test suite: {error}")
    return {"returncode": r.returncode, "stdout": r.stdout[-12000:], "stderr": r.stderr[-12000:]}


def _clean(snapshot):
    for name in (".latch-home", ".latch-suite-home", ".pytest_cache"):
        shutil.rmtree(snapshot / name, ignore_errors=True)
    for cache in snapshot.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _run_proof(snapshot, command):
    _clean(snapshot)
    try:
        result = run_test(snapshot, command)
    except (OSError, subprocess.SubprocessError) as error:
        raise LoopError(f"could not run the proof test: {error}")
    _clean(snapshot)
    return result


def _source_files(snapshot):
    files = {}
    total = 0
    for path in sorted(snapshot.rglob("*.py")):
        rel = path.relative_to(snapshot).as_posix()
        if is_test_path(rel) or rel.startswith(".") or "/." in rel or "site-packages" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        total += len(text)
        if total > SOURCE_LIMIT:
            break
        files[rel] = text
    return files


def parse_files(text):
    """Extract {path: contents} from `=== FILE: p ===` blocks. Tolerates <think> and code fences."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    found = {}
    pattern = re.compile(r"^=== FILE:\s*(.+?)\s*===[ \t]*\n(.*?)^=== END FILE ===", re.DOTALL | re.MULTILINE)
    for m in pattern.finditer(text):
        body = m.group(2)
        fenced = re.match(r"\s*```[^\n]*\n(.*?)\n?```\s*$", body, re.DOTALL)
        if fenced:
            body = fenced.group(1) + "\n"
        found[m.group(1).strip().strip("`")] = body
    return found


def apply_files(work, files):
    """Validate and write model-proposed files. Returns (unified_diff, changed_paths) or raises ValueError."""
    if not files:
        raise ValueError("model returned no `=== FILE:` blocks")
    root = work.resolve()
    plan = []
    for rel, body in files.items():
        target = (root / rel).resolve()
        if root not in target.parents:
            raise ValueError(f"path escapes the repo: {rel}")
        if not target.is_file():
            raise ValueError(f"model may only rewrite existing files, not create {rel}")
        if is_test_path(Path(rel).as_posix()) or Path(rel).name == TEST_FILE:
            raise ValueError(f"model may not edit tests: {rel}")
        if not rel.endswith(".py"):
            raise ValueError(f"only Python source files can be rewritten: {rel}")
        plan.append((rel, target, target.read_text(encoding="utf-8", errors="replace"), body))
    diff = []
    changed = []
    for rel, target, old, new in plan:
        if old == new:
            continue
        changed.append(rel)
        diff.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
        target.write_text(new, encoding="utf-8")
    if not changed:
        raise ValueError("model's files are identical to the current code")
    return "".join(diff), changed


def validate_model(model, name="model"):
    if model not in ALLOWED_MODELS:
        raise ValueError(f"{name} must be one of {', '.join(ALLOWED_MODELS)}; got {model!r}")
    return model


def run_loop(
    repo,
    base,
    head,
    issue,
    test_command="python3 -m pytest -q",
    max_iterations=3,
    model=DEFAULT_MODEL,
    receipt_path=None,
    on_event=None,
    proof_test=None,
    model_fn=None,
    run_id=None,
    test_model=ULTRA,
    source_label=None,
    case_note=None,
    triage=True,
    inspect_final=None,
    on_step_event=None,
    revert=True,
    repo_map=True,
):
    """Run the fix loop and return the receipt dict (`receipt["gate"]` is "gate_open", "gave_up" or "error";
    `receipt["verdict"]` is the named verdict from latch.verdict, or None on an infrastructure error).

    repo/base/head: a git repo and two revisions: `base` is the buggy revision, `head` is the
        submitted (wrong) fix. The repo is never modified; revisions are archived to temp dirs.
    issue: the issue text, the independent statement of expected behavior.
    on_event(dict): called with every event (started, proof_test, gate_shut, iteration_started,
        model_response, patch_applied, iteration_result, gate_open | gave_up | error).
    proof_test: optional pytest function source to use instead of generating one with Ultra.
    case_note: optional free-text label stored in the receipt and the started event (the demo uses it
        to say it is a constructed case).
    triage: when True (default), Nemotron Lightning reads the failure first and the loop gives up,
        without patching, if it is an environment/import error or does not reproduce the issue.
    inspect_final(dir): optional read-only hook called with the final code directory when the gate
        opens; its return value is stored in receipt["inspection"] (the eval uses it as an oracle).
        It never influences the verdict.
    on_step_event(dict): {step, status: started|done|failed, ts, detail} for fetch, repo_map, test_writer, base_run,
        head_run, triage, fix, revert_check and verdict; the same dicts are emitted as `step` events.
    revert: after the gate opens, revert the fix (and, if the loop rewrote files, restore the submitted patch) and
        require the proof test to fail again; if it does not, the gate stays shut (gave_up).
    repo_map: Nemotron Lightning builds a compact repo map that goes into Ultra's test-writing prompt.
    model_fn: optional replacement for latch.run.call_model(key, user, model=, system=, max_tokens=)
        returning (status, content, completion_id). Used by the offline tests.
    Raises ValueError for bad arguments (before any event) and LoopError for infra failure
    (after an `error` event has been emitted and, when possible, an error receipt written).
    """
    validate_model(model)
    validate_model(test_model, "test_model")
    if max_iterations < 0 or max_iterations > 10:
        raise ValueError("max_iterations must be between 0 and 10")
    if not str(issue).strip():
        raise ValueError("issue text must be non-empty")
    command = shlex.split(test_command)
    if not command:
        raise ValueError("test command cannot be empty")

    run_id = run_id or uuid.uuid4().hex[:12]
    events = []

    def emit(type_, **fields):
        event = _clip_fields({"type": type_, "ts": now(), "run_id": run_id, **fields},
                             ("issue", "diff", "pytest_output", "test", "output", "reason", "model_text"))
        events.append(event)
        if on_event:
            on_event(event)
        return event

    def step_sink(event):
        emit("step", **{k: v for k, v in event.items() if k != "ts"})
        if on_step_event:
            on_step_event(event)

    steps = StepLog(step_sink)

    def on_retry(info):
        receipt.setdefault("model_retries", []).append({**info, "ts": now()})
        emit("model_retry", **info)

    calls = ModelCalls(model_fn or call_model, on_retry=on_retry, uses_meta=model_fn is None,
                       on_call=lambda entry: emit("model_call", **entry))

    receipt = {
        "run_id": run_id,
        "repo": str(source_label or Path(repo).name),
        "base": base,
        "head": head,
        "issue": str(issue).strip(),
        "test_command": command,
        "model": model,
        "test_model": test_model,
        "max_iterations": max_iterations,
        "triage": LIGHTNING if triage else None,
        "started_at": now(),
        "proof_test": None,
        "initial": None,
        "iterations": [],
        "gate": "error",      # the loop's own outcome: gate_open | gave_up | error
        "verdict": None,      # the named verdict (VALIDATED, NO_REGRESSION_FOUND, ...), decided by latch.verdict
        "reason": None,
    }
    ev = {"patch_loop": False}  # facts for latch.verdict.decide_verdict, filled in as the run goes
    receipt["issue"], issue_cut = clip(receipt["issue"])

    def finish(verdict, reason, type_=None, code_error=None):
        receipt["gate"] = verdict
        receipt["reason"] = reason
        receipt["finished_at"] = now()
        if verdict == "error":  # infrastructure failure: no named verdict (the run proved nothing)
            receipt.update(verdict=None, verdict_reason=reason, proven=False,
                           base_sha=receipt.get("base"), head_sha=receipt.get("head"))
        else:
            receipt.update(verdict_fields(ev, receipt.get("base"), receipt.get("head")))
        if not steps.has("verdict"):
            steps.done("verdict", step_detail(receipt) if receipt["verdict"] else
                       {"verdict": None, "reason": reason})
        receipt["model_calls"] = list(calls.calls)
        receipt["model_cost_usd"] = total_cost(calls.calls)
        receipt["model_prices_source"] = PRICES_SOURCE_URL
        receipt["steps"] = steps.events
        receipt["final_iteration"] = len(receipt["iterations"])
        path = None
        if receipt_path:
            path = str(Path(receipt_path))
            try:
                import json
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            except OSError as error:
                path = None
                if verdict != "error":
                    return finish("error", f"could not write receipt: {error}", "error")
        receipt["receipt_path"] = path
        emit(type_ or verdict, reason=reason, receipt=receipt, receipt_path=path)
        return receipt

    def inspect(directory):
        if inspect_final is None:
            return
        try:
            receipt["inspection"] = inspect_final(directory)
        except Exception as error:  # the hook is informational and must not change the verdict
            receipt["inspection"] = {"error": f"{type(error).__name__}: {error}"}

    def fail(reason):
        finish("error", reason, "error")
        raise LoopError(reason)

    if case_note:
        receipt["case_note"] = str(case_note)
    started = {"repo": receipt["repo"], "base": base, "head": head, "issue": receipt["issue"],
               "test_command": command, "model": model, "test_model": test_model,
               "max_iterations": max_iterations}
    if case_note:
        started["case_note"] = receipt["case_note"]
    if issue_cut:
        started["truncated"] = True
    emit("started", **started)

    try:
        key = None
        if model_fn is None:
            key = load_key()
            if not key:
                fail("NEBIUS_API_KEY is not configured")
        steps.started("fetch", {"base": base, "head": head})
        repo = Path(repo).resolve()
        if not repo.is_dir():
            steps.failed("fetch", "repo is not a directory")
            fail(f"repo is not a directory: {repo}")
        commits = []
        for ref in (base, head):
            checked = git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
            if checked.returncode:
                steps.failed("fetch", f"unknown commit ref: {ref}")
                fail(f"unknown commit ref: {ref}")
            commits.append(checked.stdout.strip())
        base_commit, head_commit = commits
        receipt["base"], receipt["head"] = base_commit, head_commit
        diff = git(repo, "diff", "--no-ext-diff", "--unified=30", base_commit, head_commit)
        if diff.returncode:
            fail(diff.stderr.strip() or "could not read the diff")
        agent_diff = diff.stdout

        with tempfile.TemporaryDirectory(prefix="latch-loop-") as temp:
            root = Path(temp)
            base_dir, work, submitted_dir = root / "base", root / "work", root / "submitted"
            for directory in (base_dir, work, submitted_dir):
                directory.mkdir()
            try:
                archive(repo, base_commit, base_dir)
                archive(repo, head_commit, work)
                archive(repo, head_commit, submitted_dir)  # pristine copy of the submitted code for the revert check
                source_changes = changed_files(repo, base_commit, head_commit)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                steps.failed("fetch", str(error))
                fail(f"could not archive revisions: {error}")
            steps.done("fetch", {"base": base_commit[:12], "head": head_commit[:12],
                                 "changed_files": [p for _, p in source_changes][:20]})

            # 1. The proof test: generated once from the issue, then frozen.
            if proof_test:
                function = extract_test_function(proof_test)
                reason = validate_proof_test(function)
                attempts = [{"attempt": 1, "completion_id": None, "valid": reason is None, "rejection": reason,
                             "source": function[:4000]}]
                if reason:
                    function = None
                generated = {"generated_by": "provided", "completion_id": None}
            else:
                map_result = {"status": "skipped"}
                if repo_map:
                    steps.started("repo_map", {"model": LIGHTNING})
                    try:
                        map_result = build_repo_map(calls.ask("repo_map"), key, base_dir, receipt["issue"],
                                                    [p for _, p in source_changes if p.endswith(".py")])
                    except (OSError, ValueError) as error:  # context only: never blocks the run
                        map_result = {"status": "unavailable", "detail": f"{type(error).__name__}: {error}"}
                    (steps.done if map_result["status"] == "ok" else steps.failed)(
                        "repo_map", {"files": [f["path"] for f in map_result.get("files", [])],
                                     "dropped": map_result.get("dropped", []), "detail": map_result.get("detail")})
                    receipt["repo_map"] = {k: v for k, v in map_result.items() if k != "reply"}
                map_text = map_result.get("text") or ""
                steps.started("test_writer", {"model": test_model})
                prompt = (
                    "Create exactly one self-contained pytest test function named test_... and no prose. "
                    "Put every import inside the test function. Use the issue report as the independent "
                    "expected behavior and cover every case the issue names, not only what the diff touches: "
                    "the diff is a submitted fix that may be incomplete. The test must fail on the buggy base "
                    "revision and pass on a correct fix. Do not test the diff mechanically.\n\n"
                    + (f"Repo map (files and symbols that exist in the base revision, picked by Nemotron Lightning "
                       f"and checked against the code; import only names listed here or from the issue):\n{map_text}\n\n"
                       if map_text else "")
                    + f"Issue report:\n{receipt['issue']}\n\nSubmitted diff (base -> head):\n{clip(agent_diff)[0]}"
                )
                try:
                    function, attempts = generate_proof_test(
                        calls.ask("test_writer"), key, prompt, TEST_SYSTEM, test_model, 8192)
                except ModelRequestError as error:
                    receipt["proof_test_attempts"] = error.attempts
                    steps.failed("test_writer", f"HTTP {error.status}")
                    fail(f"Nebius test-generation request failed: HTTP {error.status}")
                generated = {"generated_by": test_model, "completion_id": attempts[-1]["completion_id"]}
            receipt["proof_test_attempts"] = attempts
            if not proof_test:
                (steps.done if function is not None else steps.failed)(
                    "test_writer", {"attempts": len(attempts), "completion_id": attempts[-1]["completion_id"]})
            for item in attempts:
                if not item["valid"]:  # the normal event sequence is unchanged; only rejections add an event
                    emit("proof_test_attempt", **{k: item[k] for k in ("attempt", "completion_id", "valid", "rejection")})
            if function is None:
                last = attempts[-1]
                ev["rejected"] = last["rejection"]
                if last["rejection"] == "the reply contained no test_ function":
                    return finish("gave_up", "model returned no test function; nothing to prove with")
                return finish("gave_up", f"the proof test was rejected as vacuous"
                                         f"{' twice' if len(attempts) > 1 else ''}: {last['rejection']}; "
                                         "nothing to judge the fix with")
            name_match = re.match(r"\s*def\s+(test_\w+)", function)
            if not name_match:
                fail("proof test has no test_ function")
            test_name = name_match.group(1)
            test_source = f"import pytest\n\n{function.rstrip()}\n"
            ev["test_name"] = test_name
            receipt["proof_test"] = {"name": test_name, "source": clip(test_source)[0], **generated}
            emit("proof_test", name=test_name, test=test_source, **generated)

            # 2. The proof test must go red on the bug (base). Otherwise it proves nothing.
            (base_dir / TEST_FILE).write_text(test_source, encoding="utf-8")
            steps.started("base_run")
            base_result = _run_proof(base_dir, command)
            base_kind = expected_base_failure(base_result, test_name)
            base_red = base_result["returncode"] != 0 and base_kind is not None
            steps.done("base_run", {"returncode": base_result["returncode"], "failure_type": base_kind,
                                    "red": base_red})
            steps.started("head_run")
            suite_before = _run_suite(work, command)
            _clean(work)
            (work / TEST_FILE).write_text(test_source, encoding="utf-8")
            head_result = _run_proof(work, command)
            (work / TEST_FILE).unlink()
            head_ok = proven(base_result, head_result, test_name)
            suite_green = suite_before["returncode"] == 0
            ev.update(base=base_result, head=head_result, suite_ok=suite_green)
            steps.done("head_run", {"proof_returncode": head_result["returncode"],
                                    "suite_returncode": suite_before["returncode"], "gate_open": bool(head_ok and suite_green)})
            receipt["initial"] = {
                "base_proof": {**_clip_result(base_result), "failure_type": base_kind},
                "head_proof": _clip_result(head_result),
                "head_suite": _clip_result(suite_before),
                "base_red": base_red,
                "head_suite_green": suite_green,
                "gate_open": bool(head_ok and suite_green),
            }
            if not base_red:
                emit("gate_shut", iteration=0, reason="proof test does not fail on base with an assertion",
                     base_red=False, head_suite_green=suite_green,
                     pytest_output=base_result["stdout"] + base_result["stderr"])
                return finish("gave_up", "proof test does not reproduce the issue on the base revision "
                                         "(no assertion failure), so it cannot judge the fix")
            def revert_gate(loop_files=None):
                """Revert the fix; the proof test must fail again, or the gate stays shut."""
                if not revert:
                    receipt["revert_check"] = ev["revert"] = {"ran": False, "skipped": "revert check disabled"}
                    return True
                steps.started("revert_check")
                try:
                    result = revert_check(
                        lambda directory: _run_proof(directory, command), test_name, test_source, TEST_FILE,
                        work, base_dir, source_changes, root / "mutants", is_test_path,
                        loop_files=loop_files, submitted_tree=submitted_dir if loop_files else None)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    result = {"ran": False, "ok": False, "mutants": [], "error": f"{type(error).__name__}: {error}",
                              "summary": "the revert check could not run, so the gate stays shut"}
                receipt["revert_check"] = ev["revert"] = result
                (steps.done if result["ok"] else steps.failed)("revert_check", result["summary"])
                if not result["ok"]:
                    emit("gate_shut", iteration=len(receipt["iterations"]), reason="revert check failed: " + result["summary"],
                         base_red=True, head_suite_green=True)
                return result["ok"]

            if head_ok and suite_green:
                emit("gate_check", iteration=0, base_red=True, head_suite_green=True)
                if not revert_gate():
                    return finish("gave_up", "the proof test still passed after the fix was reverted, so it does not "
                                             "isolate the fix: " + receipt["revert_check"]["summary"])
                inspect(work)
                return finish("gate_open", "the submitted fix already passes the proof test; no loop needed")
            why = ("proof test fails on the submitted fix" if not head_ok else "the repo's own suite fails on the submitted fix")
            emit("gate_shut", iteration=0, reason=why, base_red=True,
                 head_suite_green=suite_green, head_proof_green=head_result["returncode"] == 0,
                 pytest_output=head_result["stdout"] + head_result["stderr"])

            # 2b. Fail closed: a red test caused by the environment is not evidence about the issue.
            head_failure = failing_text = (head_result["stdout"] + head_result["stderr"]) if not head_ok else (
                suite_before["stdout"] + suite_before["stderr"])
            if not head_ok:
                kind = expected_base_failure(head_result, test_name)
                receipt["initial"]["head_failure_type"] = kind
                if kind is None and head_result["returncode"] != 0:
                    emit("triage", verdict="not_reproduced", model=None,
                         reason="the proof test fails on the submitted code for a reason other than an assertion (import, collection or runtime error)")
                    return finish("gave_up", "proof test fails on the submitted code with something other than an "
                                             "assertion (import/collection/environment error); not patching")
            if triage:
                steps.started("triage", {"model": LIGHTNING})
                t_status, t_record = run_triage(calls.ask("triage"), None if model_fn else key, receipt["issue"],
                                                test_source, clip(failing_text, 6000)[0])
                if t_status != 200:
                    steps.failed("triage", f"HTTP {t_status}")
                    fail(f"Nebius triage request failed: HTTP {t_status}")
                t_verdict, t_text, t_cid = t_record["verdict"], t_record["text"], t_record["completion_id"]
                receipt["triage"] = t_record
                steps.done("triage", {"verdict": t_verdict, "completion_id": t_cid})
                emit("triage", model=LIGHTNING, completion_id=t_cid, verdict=t_verdict, reason=t_text[:1000])
                if t_verdict != "reproduced":
                    ev["triage_blocked"] = f"Lightning triage did not confirm the failure reproduces the issue ({t_verdict})"
                    return finish("gave_up", f"Lightning triage did not confirm the failure reproduces the issue "
                                             f"({t_verdict}): {t_text[:300]}; not patching")

            # 3. The loop.
            failing = head_result if not head_ok else suite_before
            current_failure = failing["stdout"] + failing["stderr"]
            history = []
            loop_files = []
            for i in range(1, max_iterations + 1):
                emit("iteration_started", iteration=i, model=model)
                steps.started("fix", {"iteration": i, "model": model})
                sources = _source_files(work)
                attempts = "".join(
                    f"\nAttempt {n} ({h['verdict']}): {h['summary']}" for n, h in enumerate(history, 1)
                ) or " none yet"
                user = (
                    f"Issue report (expected behavior):\n{receipt['issue']}\n\n"
                    f"The submitted diff (base -> current code):\n{clip(agent_diff)[0]}\n\n"
                    f"Frozen regression test (do not edit):\n{test_source}\n"
                    f"Failure output on the current code:\n{clip(current_failure, 8000)[0]}\n\n"
                    f"Earlier repair attempts:{attempts}\n\n"
                    "Current source files:\n"
                    + "".join(f"=== FILE: {p} ===\n{t}=== END FILE ===\n" for p, t in sources.items())
                    + "\nReturn the complete replacement for every file you change."
                )
                status, content, cid = calls.ask("fixer")(key, user, model=model, system=FIX_SYSTEM, max_tokens=8192)
                if status != 200 or not content:
                    steps.failed("fix", {"iteration": i, "detail": f"HTTP {status}"})
                    receipt["iterations"].append({"iteration": i, "model": model, "completion_id": cid,
                                                   "diff": "", "pytest_output": "", "verdict": "error",
                                                   "detail": f"HTTP {status}"})
                    fail(f"Nebius fix request failed on iteration {i}: HTTP {status}")
                emit("model_response", iteration=i, model=model, completion_id=cid, model_text=content)
                record = {"iteration": i, "model": model, "completion_id": cid, "diff": "",
                          "changed_files": [], "pytest_output": "", "verdict": None}
                try:
                    patch_diff, changed = apply_files(work, parse_files(content))
                except ValueError as error:
                    steps.failed("fix", {"iteration": i, "detail": str(error)})
                    record.update(verdict="invalid_patch", detail=str(error))
                    history.append({"verdict": "invalid_patch", "summary": str(error)})
                    receipt["iterations"].append(record)
                    emit("iteration_result", **record)
                    continue
                record["diff"], diff_cut = clip(patch_diff)
                record["changed_files"] = changed
                loop_files += [f for f in changed if f not in loop_files]
                if diff_cut:
                    record["truncated"] = True
                emit("patch_applied", iteration=i, diff=patch_diff, changed_files=changed)
                steps.done("fix", {"iteration": i, "completion_id": cid, "changed_files": changed})

                ev["patch_loop"] = True
                suite = _run_suite(work, command)
                _clean(work)
                (work / TEST_FILE).write_text(test_source, encoding="utf-8")
                proof = _run_proof(work, command)
                (work / TEST_FILE).unlink()
                suite_ok = suite["returncode"] == 0
                ev.update(head=proof, suite_ok=suite_ok)
                gate = proven(base_result, proof, test_name) and suite_ok
                combined = proof["stdout"] + proof["stderr"]
                if not suite_ok:
                    combined = "REPO SUITE FAILED:\n" + suite["stdout"] + suite["stderr"] + "\n" + combined
                record["pytest_output"], out_cut = clip(combined)
                record["proof_returncode"] = proof["returncode"]
                record["suite_returncode"] = suite["returncode"]
                if out_cut:
                    record["truncated"] = True
                record["verdict"] = "gate_open" if gate else "gate_shut"
                history.append({"verdict": record["verdict"], "summary": clip(combined, 600)[0].strip().splitlines()[-1] if combined.strip() else ""})
                current_failure = combined
                receipt["iterations"].append(record)
                emit("iteration_result", **record)
                if gate:
                    if not revert_gate(loop_files):
                        return finish("gave_up", "the proof test still passed after the fix was reverted, so it does not "
                                                 "isolate the fix: " + receipt["revert_check"]["summary"])
                    inspect(work)
                    return finish("gate_open", f"harness watched the proof test go red on base and green after iteration {i}, with the repo suite green")
            return finish("gave_up", f"gate still shut after {max_iterations} iteration(s); the harness never saw the proof test pass with the repo suite green")
    except LoopError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        fail(f"{type(error).__name__}: {error}")


def demo_cache_dir():
    return Path(os.environ.get("LATCH_LOOP_CACHE") or Path.home() / ".cache" / "latch-loop") / "demo-bookings"


def prepare_demo(force=False):
    """Pre-warm the demo: build the git repo (base + agent head commits) and check tooling.

    Does no model calls and caches no model output, so a later timed run includes every API call.
    Returns {"repo", "base", "head", "issue", "checks"}.
    """
    issue = (DEMO_DIR / "issue.txt").read_text(encoding="utf-8")
    repo = demo_cache_dir()
    if force and repo.exists():
        shutil.rmtree(repo)
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_AUTHOR_NAME": "latch", "GIT_AUTHOR_EMAIL": "latch@example.invalid",
               "GIT_COMMITTER_NAME": "latch", "GIT_COMMITTER_EMAIL": "latch@example.invalid",
               "GIT_AUTHOR_DATE": "2026-10-29T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-29T00:00:00Z"}

        def g(*args):
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)

        g("init", "-q")
        for label in ("base", "head"):
            for old in repo.iterdir():
                if old.name != ".git":
                    old.unlink()
            for src in (DEMO_DIR / label).iterdir():
                if src.suffix == ".py":
                    shutil.copy(src, repo / src.name)
            g("add", "-A")
            g("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m",
              "base: buggy booking helpers" if label == "base" else "constructed partial fix: back-to-back bookings")
            g("tag", "-f", f"latch-demo-{label}")
    rev = lambda tag: subprocess.run(["git", "-C", str(repo), "rev-parse", f"{tag}^{{commit}}"],
                                     capture_output=True, text=True, check=True).stdout.strip()
    base, head = rev("latch-demo-base"), rev("latch-demo-head")
    checks = {"git": bool(shutil.which("git")), "pytest": False, "api_key": bool(load_key())}
    probe = subprocess.run(["python3", "-m", "pytest", "--version"], capture_output=True, text=True)
    checks["pytest"] = probe.returncode == 0
    if not checks["pytest"]:
        raise LoopError("pytest is not installed for python3 (pip install pytest)")
    return {"repo": str(repo), "base": base, "head": head, "issue": issue, "checks": checks}


DEMO_LABEL = ("Constructed regression case: hand-written partial fix modelled on common agent behaviour, "
              "not an upstream bug.")


def run_demo(**kwargs):
    """Run the bundled constructed demo (latch/loop/demo/): base commit, hand-written partial fix, issue text.

    Uses the repo built by prepare_demo() (building it first if needed). Accepts run_loop's kwargs.
    """
    prep = prepare_demo()
    kwargs.setdefault("source_label", "latch-loop-demo/bookings (constructed)")
    kwargs.setdefault("case_note", DEMO_LABEL)
    return run_loop(prep["repo"], prep["base"], prep["head"], prep["issue"], **kwargs)
