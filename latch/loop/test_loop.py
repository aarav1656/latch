"""Offline tests: the model is a stub, git and pytest are real.

Run from the repo root:  python3 -m unittest latch.loop.test_loop -v   or   python -m pytest latch
"""

import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from latch.loop import ALLOWED_MODELS, DEFAULT_MODEL, LoopError, run_loop
from latch.loop import core
from latch.loop.cli import main as cli_main

_SHIM = tempfile.TemporaryDirectory(prefix="latch-test-shim-")
_SAVED_ENV = {}


def setUpModule():
    """Hermetic tooling: `python3` on PATH is the interpreter running the tests (it has pytest), whatever the
    container or venv looks like, and the demo repo cache lives in a temp dir, not in ~/.cache."""
    shim = Path(_SHIM.name) / "python3"
    shim.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n")
    shim.chmod(0o755)
    for name in ("PATH", "LATCH_LOOP_CACHE"):
        _SAVED_ENV[name] = os.environ.get(name)
    os.environ["PATH"] = _SHIM.name + os.pathsep + os.environ.get("PATH", "")
    os.environ["LATCH_LOOP_CACHE"] = str(Path(_SHIM.name) / "cache")


def tearDownModule():
    for name, value in _SAVED_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _SHIM.cleanup()


DEMO = Path(__file__).resolve().parent / "demo"
ISSUE = (DEMO / "issue.txt").read_text()

GOOD_TEST = '''```python
def test_back_to_back_not_conflict_or_merged():
    from bookings import find_conflicts, merge_bookings
    assert find_conflicts([(540, 600), (600, 660)]) == []
    assert find_conflicts([(600, 660), (540, 600)]) == []
    assert find_conflicts([(540, 600), (570, 630)]) == [((540, 600), (570, 630))]
    assert merge_bookings([(540, 600), (600, 660)]) == [(540, 600), (600, 660)]
    assert merge_bookings([(540, 600), (570, 630)]) == [(540, 630)]
```'''

PASSING_ON_BASE_TEST = "def test_always_green():\n    from bookings import merge_bookings\n    assert merge_bookings([(1, 2)]) == [(1, 2)]\n"
IMPORT_ERROR_TEST = "def test_broken():\n    import nonexistent_module_xyz\n"

FIXED_BOOKINGS = (DEMO / "head" / "bookings.py").read_text().replace(
    "if merged and start <= merged[-1][1]:", "if merged and start < merged[-1][1]:"
)


def file_block(path, body):
    return f"=== FILE: {path} ===\n{body}=== END FILE ==="


def make_repo(root):
    repo = Path(root) / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}

    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, env=env, check=True).stdout.strip()

    g("init", "-q")
    shas = []
    for label in ("base", "head"):
        for f in (DEMO / label).glob("*.py"):
            (repo / f.name).write_text(f.read_text())
        g("add", "-A")
        g("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", label)
        shas.append(g("rev-parse", "HEAD"))
    return repo, shas[0], shas[1]


class Stub:
    """Scripted model. `fixes` is the list of replies for the fix agent, one per call."""

    def __init__(self, test=GOOD_TEST, triage="REPRODUCES: the merge still joins touching bookings.", fixes=(), status=200):
        self.test, self.triage, self.fixes, self.status = test, triage, list(fixes), status
        self.calls = []
        self.map_calls = []  # repo-map calls are tracked apart so the per-role call counts below stay readable

    def __call__(self, key, user, model=None, system=None, max_tokens=None, prose=False):
        if "map a Python repository" in (system or ""):
            self.map_calls.append({"model": model, "user": user})
            if self.status != 200:
                return self.status, None, None
            return 200, "bookings.py: overlaps, merge_bookings, nonexistent_name\nghost.py: x", f"cmpl-map-{len(self.map_calls)}"
        self.calls.append({"model": model, "user": user, "key": key})
        if self.status != 200:
            return self.status, None, None
        n = len(self.calls)
        if "test_" in system and "Write one self-contained" in system:
            return 200, self.test, f"cmpl-test-{n}"
        if "triage" in system:
            return 200, self.triage, f"cmpl-triage-{n}"
        reply = self.fixes.pop(0) if self.fixes else "no idea"
        return 200, reply, f"cmpl-fix-{n}"

    def fix_calls(self):
        return [c for c in self.calls if c["model"] in ALLOWED_MODELS and "coding agent" in c["user"] or False]


class LoopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo, self.base, self.head = make_repo(self._tmp.name)
        self.events = []

    def run_it(self, stub, **kw):
        kw.setdefault("receipt_path", str(Path(self._tmp.name) / "receipt.json"))
        return run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append, model_fn=stub, **kw)

    def types(self):
        return [e["type"] for e in self.events if e["type"] not in ("step", "model_call")]

    def test_shut_then_loop_opens_the_gate(self):
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(len(receipt["iterations"]), 1)
        it = receipt["iterations"][0]
        self.assertEqual(it["verdict"], "gate_open")
        self.assertEqual(it["model"], DEFAULT_MODEL)
        self.assertEqual(it["completion_id"], "cmpl-fix-3")
        self.assertIn("-        if merged and start <= merged[-1][1]:", it["diff"])
        self.assertIn("+        if merged and start < merged[-1][1]:", it["diff"])
        self.assertIn("passed", it["pytest_output"])
        self.assertTrue(receipt["initial"]["head_suite_green"])
        self.assertFalse(receipt["initial"]["gate_open"])
        self.assertEqual(self.types(), ["started", "proof_test", "gate_shut", "triage", "iteration_started",
                                         "model_response", "patch_applied", "iteration_result", "gate_open"])
        saved = json.loads(Path(receipt["receipt_path"]).read_text())
        self.assertEqual(saved["gate"], "gate_open")
        self.assertEqual(self.events[-1]["receipt"]["run_id"], receipt["run_id"])
        self.assertEqual(self.events[-1]["receipt_path"], receipt["receipt_path"])
        self.assertTrue(self.base != self.head)

    def test_very_long_proof_test_name_is_still_a_base_assertion(self):
        # Regression: pytest drops " - <msg>" from the FAILED line on long names; the loop must not give up.
        name = "test_" + "back_to_back_bookings_must_not_be_merged_or_reported_as_conflicts_" * 2
        long_test = GOOD_TEST.replace(GOOD_TEST.split("def ")[1].split("(")[0], name, 1)
        receipt = self.run_it(Stub(test=long_test, fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(receipt["initial"]["base_proof"]["failure_type"], "assertion")

    def test_case_note_lands_in_receipt_and_started_event(self):
        note = "Constructed regression case: hand-written partial fix modelled on common agent behaviour, not an upstream bug."
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), case_note=note)
        self.assertEqual(receipt["case_note"], note)
        self.assertEqual(self.events[0]["case_note"], note)
        self.assertEqual(core.DEMO_LABEL, note)

    def test_inspect_final_runs_on_the_final_code_and_never_changes_the_verdict(self):
        seen = []

        def inspect(directory):
            seen.append((Path(directory) / "bookings.py").read_text())
            return {"ok": True}

        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), inspect_final=inspect)
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(receipt["inspection"], {"ok": True})
        self.assertEqual(seen, [FIXED_BOOKINGS])

        def boom(directory):
            raise RuntimeError("nope")

        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), inspect_final=boom)
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertIn("nope", receipt["inspection"]["error"])

    def test_event_envelope(self):
        self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(self.events[0]["type"], "started")
        for key in ("repo", "base", "head", "issue", "test_command"):
            self.assertIn(key, self.events[0])
        for e in self.events:
            self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
            self.assertEqual(e["run_id"], self.events[0]["run_id"])
            json.dumps(e)

    def test_gives_up_after_max_iterations_when_agent_keeps_failing(self):
        head_src = (DEMO / "head" / "bookings.py").read_text()
        wrongs = [file_block("bookings.py", head_src + f"\n# attempt {n}\n") for n in range(3)]
        stub = Stub(fixes=wrongs)
        receipt = self.run_it(stub, max_iterations=2)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual([i["verdict"] for i in receipt["iterations"]], ["gate_shut", "gate_shut"])
        self.assertIn("still shut after 2", receipt["reason"])
        self.assertEqual(self.events[-1]["type"], "gave_up")

    def test_model_cannot_edit_tests_to_get_green(self):
        cheat = file_block("test_bookings.py", "def test_x():\n    assert True\n")
        receipt = self.run_it(Stub(fixes=[cheat]), max_iterations=1)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual(receipt["iterations"][0]["verdict"], "invalid_patch")
        self.assertIn("may not edit tests", receipt["iterations"][0]["detail"])

    def test_path_traversal_and_new_files_rejected(self):
        for path in ("../evil.py", "newfile.py"):
            receipt = self.run_it(Stub(fixes=[file_block(path, "x = 1\n")]), max_iterations=1)
            self.assertEqual(receipt["iterations"][0]["verdict"], "invalid_patch", path)

    def test_regression_in_repo_suite_keeps_gate_shut(self):
        # Fixes the issue but breaks the overlapping case the repo suite covers.
        broken = FIXED_BOOKINGS.replace("max(merged[-1][1], end)", "end")
        broken = broken.replace("a[0] < b[1] and b[0] < a[1]", "False")
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", broken)]), max_iterations=1)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertIn("REPO SUITE FAILED", receipt["iterations"][0]["pytest_output"])

    def test_gate_open_without_loop_when_head_is_already_correct(self):
        stub = Stub()
        # Judge the corrected code as the head by making a third commit.
        (self.repo / "bookings.py").write_text(FIXED_BOOKINGS)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
        subprocess.run(["git", "-C", str(self.repo), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qam", "good"], env=env, check=True)
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        receipt = run_loop(self.repo, self.base, head, ISSUE, model_fn=stub, on_event=self.events.append)
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(receipt["iterations"], [])
        self.assertEqual(len(stub.calls), 1)  # only the proof-test generation

    def test_proof_test_that_passes_on_base_proves_nothing(self):
        receipt = self.run_it(Stub(test=PASSING_ON_BASE_TEST))
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertIn("does not reproduce", receipt["reason"])
        self.assertEqual(receipt["iterations"], [])

    def test_tautological_proof_test_is_rejected_before_it_runs(self):
        tautology = "def test_nothing():\n    from bookings import merge_bookings\n    v = merge_bookings([(1, 2)])\n    assert v == v\n"
        stub = Stub(test=tautology)
        receipt = self.run_it(stub)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual(receipt["verdict"], "INVALID_TEST")
        self.assertIn("rejected as vacuous twice", receipt["reason"])
        self.assertIn("tautolog", receipt["reason"])
        self.assertEqual(receipt["iterations"], [])
        self.assertFalse(receipt["tautology"]["ok"])
        self.assertTrue(receipt["tautology"]["checked"])
        self.assertIn("tautology check", receipt["verdict_reason"])
        self.assertEqual([a["valid"] for a in receipt["proof_test_attempts"]], [False, False])

    def test_provided_tautological_proof_test_is_rejected(self):
        receipt = self.run_it(Stub(), proof_test="def test_nothing():\n    assert len('ab') == 2\n")
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual(receipt["verdict"], "INVALID_TEST")
        self.assertFalse(receipt["tautology"]["ok"])

    def test_good_proof_test_records_the_tautology_check(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["verdict"], "VALIDATED")
        self.assertTrue(receipt["tautology"]["checked"])
        self.assertTrue(receipt["tautology"]["ok"])
        self.assertIn("merge_bookings", receipt["tautology"]["asserted_symbols"])

    def test_import_error_is_not_patched(self):
        receipt = self.run_it(Stub(test=IMPORT_ERROR_TEST))
        self.assertEqual(receipt["gate"], "gave_up")  # base fails with ModuleNotFoundError, not an assertion
        self.assertEqual(receipt["iterations"], [])

    def test_lightning_triage_fails_closed(self):
        stub = Stub(triage="NOT_REPRODUCES: this is an ImportError in the harness.",
                    fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertIn("triage", receipt["reason"])
        self.assertEqual(receipt["iterations"], [])
        self.assertEqual(receipt["triage"]["model"], "nvidia/Nemotron-3_5-Lightning")
        self.assertEqual(len(stub.calls), 2)  # test generation + triage, no patch call

    def test_receipt_lists_every_model_call_by_role_with_ids(self):
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        roles = [(c["role"], c["model"], c["completion_id"]) for c in receipt["model_calls"]]
        self.assertEqual(roles, [("repo_map", "nvidia/Nemotron-3_5-Lightning", "cmpl-map-1"),
                                 ("test_writer", core.ULTRA, "cmpl-test-1"),
                                 ("triage", "nvidia/Nemotron-3_5-Lightning", "cmpl-triage-2"),
                                 ("fixer", DEFAULT_MODEL, "cmpl-fix-3")])
        self.assertTrue(all(c["cost_usd"] is None and isinstance(c["latency_ms"], int) for c in receipt["model_calls"]))
        self.assertIsNone(receipt["model_cost_usd"])  # a stub reports no usage, so no cost is invented
        self.assertIn("tokenfactory.nebius.com", receipt["model_prices_source"])
        self.assertEqual([e["role"] for e in self.events if e["type"] == "model_call"],
                         ["repo_map", "test_writer", "triage", "fixer"])

    def test_repo_map_is_validated_and_fed_to_the_test_writer(self):
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["repo_map"]["status"], "ok")
        self.assertEqual([f["path"] for f in receipt["repo_map"]["files"]], ["bookings.py"])
        self.assertIn("ghost.py", receipt["repo_map"]["dropped"])  # unknown files from the model are dropped
        prompt = stub.calls[0]["user"]
        self.assertIn("Repo map", prompt)
        self.assertIn("merge_bookings", prompt)
        self.assertNotIn("nonexistent_name", prompt)

    def test_failed_repo_map_does_not_block_the_run(self):
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        orig = stub.__call__

        class Down(Stub):
            def __call__(self, key, user, model=None, system=None, **kw):
                if "map a Python repository" in (system or ""):
                    return 503, None, None
                return orig(key, user, model=model, system=system, **kw)

        receipt = self.run_it(Down(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(receipt["repo_map"]["status"], "unavailable")

    def test_step_events_are_emitted_in_order_and_saved(self):
        seen = []
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), on_step_event=seen.append)
        started = [e["step"] for e in seen if e["status"] == "started"]
        self.assertEqual(started, ["fetch", "repo_map", "test_writer", "base_run", "head_run", "triage", "fix", "flake_check", "revert_check", "mutation_check"])
        self.assertEqual(seen[-1]["step"], "verdict")
        self.assertEqual(receipt["steps"], seen)
        self.assertEqual([e["step"] for e in self.events if e["type"] == "step"], [e["step"] for e in seen])
        self.assertTrue(all(e["status"] in ("started", "done", "failed") for e in seen))

    def test_revert_check_runs_after_the_gate_opens_and_is_in_the_receipt(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        rc = receipt["revert_check"]
        self.assertTrue(rc["ran"] and rc["ok"])
        self.assertEqual([m["name"] for m in rc["mutants"]], ["revert_fix_to_base", "restore_submitted_patch"])
        self.assertTrue(all(m["failed_as_expected"] for m in rc["mutants"]))

    def test_gate_stays_shut_when_the_proof_test_survives_the_revert(self):
        from unittest import mock
        bad = {"ran": True, "ok": False, "mutants": [], "summary": "the proof test did NOT fail on the mutant(s) revert_fix_to_base"}
        with mock.patch.object(core, "revert_check", return_value=bad):
            receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertIn("revert", receipt["reason"])
        self.assertEqual([e["type"] for e in self.events if e["type"] in ("gate_shut", "gave_up")][-2:], ["gate_shut", "gave_up"])

    def test_revert_check_can_be_disabled(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), revert=False, repo_map=False)
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertFalse(receipt["revert_check"]["ran"])
        self.assertNotIn("repo_map", [c["role"] for c in receipt["model_calls"]])

    def test_unclear_triage_fails_closed(self):
        receipt = self.run_it(Stub(triage="hmm hard to say"))
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual(receipt["triage"]["verdict"], "unclear")

    def test_api_error_emits_error_and_raises(self):
        with self.assertRaises(LoopError):
            self.run_it(Stub(status=429))
        self.assertEqual(self.types(), ["started", "error"])
        self.assertIn("HTTP 429", self.events[-1]["reason"])
        self.assertEqual(json.loads(Path(self.events[-1]["receipt_path"]).read_text())["gate"], "error")

    def test_vacuous_proof_test_is_retried_once_then_used(self):
        class Vacuous(Stub):
            first = True

            def __call__(self, key, user, model=None, system=None, max_tokens=None, prose=False):
                if self.first and "Write one self-contained" in (system or ""):
                    self.first = False
                    self.calls.append({"model": model, "user": user, "key": key})
                    return 200, "def test_vacuous():\n    ...\n", "cmpl-vac"
                return super().__call__(key, user, model=model, system=system, max_tokens=max_tokens, prose=prose)

        stub = Vacuous(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["gate"], "gate_open")
        attempts = receipt["proof_test_attempts"]
        self.assertEqual([a["valid"] for a in attempts], [False, True])
        self.assertEqual(attempts[0]["completion_id"], "cmpl-vac")
        self.assertIn("placeholder", attempts[0]["rejection"])
        self.assertIn("REJECTED", stub.calls[1]["user"])
        self.assertEqual(receipt["proof_test"]["completion_id"], attempts[1]["completion_id"])
        self.assertEqual(self.types().count("proof_test_attempt"), 1)  # only the rejection is an extra event

    def test_vacuous_twice_gives_up_without_patching(self):
        stub = Stub(test="def test_nothing():\n    pass\n", fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertIn("vacuous twice", receipt["reason"])
        self.assertEqual(len(receipt["proof_test_attempts"]), 2)
        self.assertEqual(receipt["iterations"], [])
        self.assertEqual(len(stub.calls), 2)  # two generations, no triage, no patch
        self.assertIsNone(receipt["initial"])

    def test_provided_vacuous_proof_test_is_rejected(self):
        stub = Stub()
        receipt = self.run_it(stub, proof_test="def test_x():\n    ...\n")
        self.assertEqual(receipt["gate"], "gave_up")
        self.assertEqual(stub.calls, [])

    def test_transient_model_errors_are_retried_and_logged_in_the_receipt(self):
        from unittest import mock
        real = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        calls = {"n": 0}

        def fake_call_model(key, user, model=None, system=None, max_tokens=None, prose=False, on_retry=None, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # the triage call: the connection drops once, then the retry succeeds
                on_retry({"attempt": 1, "attempts": 3, "status": None,
                          "error": "RemoteDisconnected: Remote end closed connection", "will_retry": True, "delay": 1.5})
            return real(key, user, model=model, system=system, max_tokens=max_tokens, prose=prose)

        with mock.patch.object(core, "call_model", fake_call_model), mock.patch.object(core, "load_key", lambda: "k"):
            receipt = run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append,
                               receipt_path=str(Path(self._tmp.name) / "r.json"))
        self.assertEqual(receipt["gate"], "gate_open")
        self.assertEqual(receipt["model_retries"][0]["error"], "RemoteDisconnected: Remote end closed connection")
        self.assertIn("model_retry", self.types())

    def test_exhausted_retries_fail_closed_with_an_error(self):
        from unittest import mock

        def always_down(key, user, model=None, system=None, max_tokens=None, prose=False, on_retry=None, **kw):
            for n in (1, 2, 3):
                on_retry({"attempt": n, "attempts": 3, "status": None, "error": "ConnectionResetError: x",
                          "will_retry": n < 3, "delay": 1.0})
            return None, None, None

        with mock.patch.object(core, "call_model", always_down), mock.patch.object(core, "load_key", lambda: "k"):
            with self.assertRaises(LoopError):
                run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append,
                         receipt_path=str(Path(self._tmp.name) / "r.json"))
        # the repo-map call (context only, tolerated) retries 3 times, then the test-writer call 3 more times
        self.assertEqual(self.types().count("model_retry"), 6)
        self.assertEqual(self.events[-1]["type"], "error")

    def test_missing_key_is_an_error(self):
        saved = core.load_key
        core.load_key = lambda: None
        try:
            with self.assertRaises(LoopError):
                run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append)
        finally:
            core.load_key = saved
        self.assertEqual(self.events[-1]["type"], "error")
        self.assertIn("NEBIUS_API_KEY", self.events[-1]["reason"])

    def test_unknown_ref_is_an_error(self):
        with self.assertRaises(LoopError):
            run_loop(self.repo, "nope", self.head, ISSUE, on_event=self.events.append, model_fn=Stub())
        self.assertEqual(self.events[-1]["type"], "error")

    def test_model_allow_list(self):
        self.assertEqual(ALLOWED_MODELS, ("nvidia/Nemotron-3-Ultra-550b-a55b", "nvidia/Nemotron-3_5-Lightning"))
        for bad in ("nvidia/nemotron-3-super-120b-a12b", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "gpt-4"):
            with self.assertRaises(ValueError):
                run_loop(self.repo, self.base, self.head, ISSUE, model=bad, model_fn=Stub())
        self.assertEqual(self.events, [])
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub, model="nvidia/Nemotron-3_5-Lightning")
        self.assertEqual(receipt["iterations"][0]["model"], "nvidia/Nemotron-3_5-Lightning")
        self.assertIn("def test_back_to_back", receipt["proof_test"]["source"])
        self.assertEqual(receipt["proof_test"]["generated_by"], DEFAULT_MODEL)

    def test_long_text_is_truncated_with_flag(self):
        big = "x" * 50000
        text, cut = core.clip(big)
        self.assertTrue(cut)
        self.assertLess(len(text), 21000)
        event = core._clip_fields({"type": "t", "pytest_output": big}, ("pytest_output",))
        self.assertTrue(event["truncated"])
        self.assertEqual(event["truncated_fields"], ["pytest_output"])
        small = core._clip_fields({"type": "t", "pytest_output": "ok"}, ("pytest_output",))
        self.assertNotIn("truncated", small)

    def test_source_repo_is_untouched(self):
        before = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        after = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        self.assertNotIn("start < merged", (self.repo / "bookings.py").read_text())

    def test_parse_files_handles_fences_and_think(self):
        text = "<think>=== FILE: a.py ===\nno\n=== END FILE ===</think>\n=== FILE: b.py ===\n```python\nx = 1\n```\n=== END FILE ==="
        self.assertEqual(core.parse_files(text), {"b.py": "x = 1\n"})


class LoopVerdictTests(unittest.TestCase):
    setUp = LoopTests.setUp
    run_it = LoopTests.run_it

    def test_gate_open_after_repair_is_validated(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual((receipt["gate"], receipt["verdict"], receipt["proven"]), ("gate_open", "VALIDATED", True))
        self.assertEqual(receipt["base_sha"], receipt["base"])
        self.assertEqual(receipt["head_sha"], receipt["head"])
        final = [e for e in self.events if e["type"] == "step" and e["step"] == "verdict"][-1]
        self.assertEqual(final["detail"], {"verdict": "VALIDATED", "reason": receipt["verdict_reason"]})
        self.assertEqual(json.loads(Path(receipt["receipt_path"]).read_text())["verdict"], "VALIDATED")

    def test_the_loop_runs_real_mutants_of_the_fix_and_records_them(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        mutation = receipt["mutation"]
        self.assertTrue(mutation["ran"] and mutation["ok"])
        self.assertGreaterEqual(mutation["total"], 1)
        self.assertGreaterEqual(mutation["kill_rate"], 0.6)
        self.assertEqual({m["file"] for m in mutation["mutants"]}, {"bookings.py"})
        steps = [(e["step"], e["status"]) for e in self.events if e["type"] == "step"]
        self.assertLess(steps.index(("revert_check", "done")), steps.index(("mutation_check", "started")))
        done = [e for e in self.events if e["type"] == "step" and e["step"] == "mutation_check" and e["status"] == "done"]
        self.assertEqual(done[0]["detail"], {"killed": mutation["killed"], "total": mutation["total"], "kill_rate": mutation["kill_rate"]})
        self.assertIn("mutants", receipt["verdict_reason"])
        self.assertFalse(any((self.repo / name).exists() for name in ("latch_issue_test.py",)))  # the source repo is untouched

    def test_surviving_mutants_shut_the_gate_with_mutation_survived(self):
        from unittest import mock
        weak = {"ran": True, "ok": False, "killed": 1, "total": 5, "kill_rate": 0.2, "threshold": 0.6,
                "mutants": [{"id": "m2", "killed": False, "file": "bookings.py", "line": 12, "what": "x", "operator": "return_none"}],
                "note": "1/5 mutants of the changed lines were killed by the frozen proof test (needs 60%)"}
        with mock.patch("latch.mutate.run_mutation", return_value=weak):
            receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual((receipt["gate"], receipt["verdict"], receipt["proven"]), ("gave_up", "MUTATION_SURVIVED", False))
        self.assertIn("kill rate 20%", receipt["verdict_reason"])
        self.assertEqual([e["type"] for e in self.events if e["type"] in ("gate_shut", "gave_up")][-2:], ["gate_shut", "gave_up"])
        failed = [e for e in self.events if e["type"] == "step" and e["step"] == "mutation_check" and e["status"] == "failed"]
        self.assertEqual(failed[0]["detail"], {"killed": 1, "total": 5, "kill_rate": 0.2})

    def test_mutation_can_be_turned_off(self):
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), mutation=False)
        self.assertEqual((receipt["verdict"], receipt.get("mutation")), ("VALIDATED", None))
        self.assertNotIn("mutation_check", [e["step"] for e in self.events if e["type"] == "step"])

    def test_named_verdicts_for_each_way_to_give_up(self):
        green = self.run_it(Stub(test=PASSING_ON_BASE_TEST))
        self.assertEqual((green["verdict"], green["proven"]), ("NO_REGRESSION_FOUND", False))
        self.assertEqual(self.run_it(Stub(test=IMPORT_ERROR_TEST))["verdict"], "INVALID_TEST")
        self.assertEqual(self.run_it(Stub(test="def test_x():\n    pass\n"))["verdict"], "INVALID_TEST")
        triage = self.run_it(Stub(triage="NOT_REPRODUCES: environment error.", fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(triage["verdict"], "INVALID_TEST")
        head_src = (DEMO / "head" / "bookings.py").read_text()
        shut = self.run_it(Stub(fixes=[file_block("bookings.py", head_src + "\n# again\n")]), max_iterations=1)
        self.assertEqual((shut["gate"], shut["verdict"]), ("gave_up", "FIX_FAILS_TEST"))
        broken = self.run_it(Stub(fixes=[file_block("bookings.py", "def broken(:\n")]), max_iterations=1)
        self.assertEqual(broken["verdict"], "FIX_FAILS_TEST")

    def test_a_proof_test_that_survives_the_revert_is_mutation_survived(self):
        # The test also passes on the reverted code only if it is not tied to the fix; fake it with a stub revert result.
        from unittest import mock
        survived = {"ran": True, "ok": False, "mutants": [], "summary": "the proof test did NOT fail on the mutant(s) revert_fix_to_base"}
        with mock.patch.object(core, "revert_check", return_value=survived):
            receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual((receipt["gate"], receipt["verdict"], receipt["proven"]), ("gave_up", "MUTATION_SURVIVED", False))

    def _flaky_proof_test(self, bad_call):
        counter = Path(self._tmp.name) / "counter"
        return (
            "def test_back_to_back_flaky():\n"
            "    import pathlib\n"
            "    from bookings import find_conflicts\n"
            f"    p = pathlib.Path({str(counter)!r})\n"
            "    n = int(p.read_text()) if p.exists() else 0\n"
            "    p.write_text(str(n + 1))\n"
            f"    assert find_conflicts([(540, 600), (600, 660)]) == [] and n != {bad_call}\n"
        )

    def _correct_head(self):
        (self.repo / "bookings.py").write_text(FIXED_BOOKINGS)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
        subprocess.run(["git", "-C", str(self.repo), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                        "commit", "-qam", "good"], env=env, check=True)
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def test_a_proof_test_that_flips_on_a_rerun_is_flaky(self):
        head = self._correct_head()
        # call 0 = base, 1 = head, 2-5 = base reruns, 6-9 = head reruns: the second head rerun (call 7) fails.
        receipt = run_loop(self.repo, self.base, head, ISSUE, model_fn=Stub(), proof_test=self._flaky_proof_test(7),
                           on_event=self.events.append)
        self.assertEqual((receipt["gate"], receipt["verdict"], receipt["proven"]), ("gave_up", "FLAKY", False))
        self.assertTrue(receipt["flaky"]["flaky"])
        self.assertEqual(receipt["flaky"]["head_pass_rate"], 0.8)
        self.assertEqual(receipt["flaky"]["runs"], 5)
        self.assertIn("flaky", receipt["reason"])
        steps = [(e["step"], e["status"]) for e in self.events if e["type"] == "step"]
        self.assertIn(("flake_check", "failed"), steps)
        self.assertNotIn("revert_check", [s for s, _ in steps])  # stops before the revert check

    def test_a_stable_proof_test_passes_the_flake_gate_and_flake_runs_one_skips_it(self):
        head = self._correct_head()
        receipt = run_loop(self.repo, self.base, head, ISSUE, model_fn=Stub(), proof_test=self._flaky_proof_test(999),
                           on_event=self.events.append, mutation=False)
        self.assertEqual((receipt["verdict"], receipt["flaky"]["flaky"], receipt["flaky"]["runs"]), ("VALIDATED", False, 5))
        off = run_loop(self.repo, self.base, head, ISSUE, model_fn=Stub(), proof_test=self._flaky_proof_test(999), flake_runs=1, mutation=False)
        self.assertEqual((off["verdict"], off["flaky"]["ran"]), ("VALIDATED", False))

    def test_a_base_that_sometimes_passes_is_flaky_not_no_regression(self):
        counter = Path(self._tmp.name) / "c2"
        test = ("def test_sometimes():\n    import pathlib\n    from bookings import merge_bookings\n"
                f"    p = pathlib.Path({str(counter)!r})\n"
                "    n = int(p.read_text()) if p.exists() else 0\n    p.write_text(str(n + 1))\n"
                "    assert merge_bookings([(1, 2)]) == [(1, 2)] and n != 2\n")  # passes on the base run (0) and the head run (1), fails on the first base rerun (2)
        receipt = run_loop(self.repo, self.base, self.head, ISSUE, model_fn=Stub(), proof_test=test)
        self.assertEqual((receipt["gate"], receipt["verdict"]), ("gave_up", "FLAKY"))
        self.assertEqual(receipt["flaky"]["outcomes"]["head_passed"], [])  # base-only check on this exit
        always_green = run_loop(self.repo, self.base, self.head, ISSUE, model_fn=Stub(), proof_test=PASSING_ON_BASE_TEST)
        self.assertEqual(always_green["verdict"], "NO_REGRESSION_FOUND")

    def test_infrastructure_error_has_no_named_verdict(self):
        with self.assertRaises(LoopError):
            self.run_it(Stub(status=500))
        saved = json.loads((Path(self._tmp.name) / "receipt.json").read_text())
        self.assertEqual((saved["gate"], saved["verdict"], saved["proven"]), ("error", None, False))


class CliTests(unittest.TestCase):
    def test_rejects_disallowed_model(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli_main(["demo", "--model", "nvidia/nemotron-3-super-120b-a12b"])
        self.assertEqual(code, 64)

    def test_missing_key_emits_error_event_and_exits_2(self):
        saved = core.load_key
        core.load_key = lambda: None
        out = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = cli_main(["demo", "--run-id", "t1"])
        finally:
            core.load_key = saved
        self.assertEqual(code, 2)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([l["type"] for l in lines if l["type"] != "step"], ["started", "error"])
        self.assertTrue(all(l["run_id"] == "t1" for l in lines))


class TimelineTests(unittest.TestCase):
    """The human timeline is driven by the same events the JSONL carries."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo, self.base, self.head = make_repo(self._tmp.name)

    def timeline(self, **kw):
        from latch.loop.human import Timeline, submitted_diff
        out = io.StringIO()
        return out, Timeline(out, color=kw.pop("color", False), diff_text=submitted_diff(self.repo, self.base, self.head), **kw)

    def test_gate_shut_triage_patch_gate_open_in_order(self):
        out, tl = self.timeline()
        run_loop(self.repo, self.base, self.head, ISSUE, on_event=tl, model_fn=Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        text = out.getvalue()
        order = ["Issue: Back-to-back bookings", "Submitted change:", "Proof test frozen", "GATE SHUT", "Lightning triage: reproduced",
                 "Ultra writes a patch (iteration 1)", "+        if merged and start < merged[-1][1]:", "pass: ", "GATE OPEN"]
        positions = [text.find(item) for item in order]
        self.assertNotIn(-1, positions, text)
        self.assertEqual(positions, sorted(positions), text)
        self.assertIn("repo_map", text)
        self.assertIn("cmpl-fix-3", text)
        self.assertNotIn("\x1b[", text)

    def test_color_and_gave_up(self):
        out, tl = self.timeline(color=True)
        run_loop(self.repo, self.base, self.head, ISSUE, on_event=tl, model_fn=Stub(fixes=["no idea"]), max_iterations=1)
        text = out.getvalue()
        self.assertIn("\x1b[31m", text)
        self.assertNotIn("GATE OPEN", text)
        self.assertIn("GATE SHUT", text)

    def test_cli_human_flag_prints_timeline_and_jsonl_flag_prints_json(self):
        saved = core.load_key
        core.load_key = lambda: None
        try:
            for flag, expect_json in (("--human", False), ("--jsonl", True)):
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(io.StringIO()):
                    self.assertEqual(cli_main(["demo", flag, "--no-color"]), 2)
                first = out.getvalue().splitlines()[0]
                self.assertEqual(first.startswith("{"), expect_json, first)
        finally:
            core.load_key = saved


class ProviderReceiptTests(unittest.TestCase):
    """The provider switch at the loop boundary: offline, model_fn stub, no network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo, self.base, self.head = make_repo(self._tmp.name)
        self.events = []

    def run_it(self, stub, **kw):
        kw.setdefault("receipt_path", str(Path(self._tmp.name) / "receipt.json"))
        return run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append, model_fn=stub, **kw)

    def provider_env(self, **kw):
        from unittest import mock
        clean = {k: v for k, v in os.environ.items() if k not in ("LATCH_PROVIDER", "OPENROUTER_API_KEY", "NEBIUS_API_KEY")}
        clean.update(kw)
        patch = mock.patch.dict(os.environ, clean, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_default_provider_is_nebius_in_receipt_and_every_call(self):
        self.provider_env()
        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["provider"], "nebius")
        self.assertEqual(self.events[0]["provider"], "nebius")
        self.assertTrue(receipt["model_calls"])
        self.assertEqual({c["provider"] for c in receipt["model_calls"]}, {"nebius"})
        self.assertTrue({c["model"] for c in receipt["model_calls"]} <= set(ALLOWED_MODELS) | {core.LIGHTNING})
        self.assertEqual(json.loads(Path(receipt["receipt_path"]).read_text())["provider"], "nebius")

    def test_openrouter_receipt_records_provider_and_resolved_free_models_with_no_cost(self):
        self.provider_env(LATCH_PROVIDER="openrouter")
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        path = Path(self._tmp.name) / "latch" / "runs" / "dev" / "loop-demo-openrouter.json"
        receipt = self.run_it(stub, receipt_path=str(path))
        self.assertEqual(receipt["provider"], "openrouter")
        self.assertEqual(receipt["gate"], "gate_open")
        calls = receipt["model_calls"]
        self.assertEqual({c["provider"] for c in calls}, {"openrouter"})
        self.assertEqual({c["model"] for c in calls},
                         {"nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-lightning:free"})
        self.assertEqual([c["cost_usd"] for c in calls], [None] * len(calls))
        self.assertIsNone(receipt["model_cost_usd"])
        # the stub (the model_fn seam) still sees the canonical ids: the mapping happens in the call layer
        self.assertTrue(all(c["model"] in ALLOWED_MODELS or c["model"] == core.LIGHTNING for c in stub.calls))
        self.assertEqual(json.loads(path.read_text())["provider"], "openrouter")

    def test_openrouter_refuses_a_public_receipt_path(self):
        self.provider_env(LATCH_PROVIDER="openrouter")
        for bad in ("latch/runs/loop-demo.json", "latch/runs/eval/x-real.json", "latch/runs/eval-summary.json"):
            with self.assertRaisesRegex(ValueError, "dev-only"):
                self.run_it(Stub(), receipt_path=bad)
        self.assertEqual(self.events, [])

    def test_openrouter_missing_key_names_openrouter(self):
        self.provider_env(LATCH_PROVIDER="openrouter", NEBIUS_API_KEY="nb")
        saved = core.load_key
        core.load_key = lambda: None
        try:
            with self.assertRaises(LoopError):
                run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append)
        finally:
            core.load_key = saved
        self.assertIn("OPENROUTER_API_KEY is not configured", self.events[-1]["reason"])

    def test_cli_provider_flag_and_bad_provider(self):
        self.provider_env()
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli_main(["run", "--provider", "bogus", "--repo", self.repo, "--base", self.base, "--head", self.head,
                                       "--issue", "x"]), 64)
        self.assertIn("provider", err.getvalue())


if __name__ == "__main__":
    unittest.main()
