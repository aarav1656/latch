"""Offline tests: the model is a stub, git and pytest are real.

Run from the repo root:  python3 -m unittest latch.loop.test_loop -v
"""

import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from latch.loop import ALLOWED_MODELS, DEFAULT_MODEL, LoopError, run_loop
from latch.loop import core
from latch.loop.cli import main as cli_main

DEMO = Path(__file__).resolve().parent / "demo"
ISSUE = (DEMO / "issue.txt").read_text()

GOOD_TEST = '''```python
def test_back_to_back_not_conflict_or_merged():
    from bookings import find_conflicts, merge_bookings
    assert find_conflicts([(540, 600), (600, 660)]) == []
    assert merge_bookings([(540, 600), (600, 660)]) == [(540, 600), (600, 660)]
    assert merge_bookings([(540, 600), (570, 630)]) == [(540, 630)]
```'''

PASSING_ON_BASE_TEST = "def test_always_green():\n    assert 1 + 1 == 2\n"
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

    def __call__(self, key, user, model=None, system=None, max_tokens=None, prose=False):
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
        return [e["type"] for e in self.events]

    def test_shut_then_loop_opens_the_gate(self):
        stub = Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["verdict"], "gate_open")
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
        self.assertEqual(saved["verdict"], "gate_open")
        self.assertEqual(self.events[-1]["receipt"]["run_id"], receipt["run_id"])
        self.assertEqual(self.events[-1]["receipt_path"], receipt["receipt_path"])
        self.assertTrue(self.base != self.head)

    def test_very_long_proof_test_name_is_still_a_base_assertion(self):
        # Regression: pytest drops " - <msg>" from the FAILED line on long names; the loop must not give up.
        name = "test_" + "back_to_back_bookings_must_not_be_merged_or_reported_as_conflicts_" * 2
        long_test = GOOD_TEST.replace(GOOD_TEST.split("def ")[1].split("(")[0], name, 1)
        receipt = self.run_it(Stub(test=long_test, fixes=[file_block("bookings.py", FIXED_BOOKINGS)]))
        self.assertEqual(receipt["verdict"], "gate_open")
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
        self.assertEqual(receipt["verdict"], "gate_open")
        self.assertEqual(receipt["inspection"], {"ok": True})
        self.assertEqual(seen, [FIXED_BOOKINGS])

        def boom(directory):
            raise RuntimeError("nope")

        receipt = self.run_it(Stub(fixes=[file_block("bookings.py", FIXED_BOOKINGS)]), inspect_final=boom)
        self.assertEqual(receipt["verdict"], "gate_open")
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
        self.assertEqual(receipt["verdict"], "gave_up")
        self.assertEqual([i["verdict"] for i in receipt["iterations"]], ["gate_shut", "gate_shut"])
        self.assertIn("still shut after 2", receipt["reason"])
        self.assertEqual(self.events[-1]["type"], "gave_up")

    def test_model_cannot_edit_tests_to_get_green(self):
        cheat = file_block("test_bookings.py", "def test_x():\n    assert True\n")
        receipt = self.run_it(Stub(fixes=[cheat]), max_iterations=1)
        self.assertEqual(receipt["verdict"], "gave_up")
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
        self.assertEqual(receipt["verdict"], "gave_up")
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
        self.assertEqual(receipt["verdict"], "gate_open")
        self.assertEqual(receipt["iterations"], [])
        self.assertEqual(len(stub.calls), 1)  # only the proof-test generation

    def test_proof_test_that_passes_on_base_proves_nothing(self):
        receipt = self.run_it(Stub(test=PASSING_ON_BASE_TEST))
        self.assertEqual(receipt["verdict"], "gave_up")
        self.assertIn("does not reproduce", receipt["reason"])
        self.assertEqual(receipt["iterations"], [])

    def test_import_error_is_not_patched(self):
        receipt = self.run_it(Stub(test=IMPORT_ERROR_TEST))
        self.assertEqual(receipt["verdict"], "gave_up")  # base fails with ModuleNotFoundError, not an assertion
        self.assertEqual(receipt["iterations"], [])

    def test_lightning_triage_fails_closed(self):
        stub = Stub(triage="NOT_REPRODUCES: this is an ImportError in the harness.",
                    fixes=[file_block("bookings.py", FIXED_BOOKINGS)])
        receipt = self.run_it(stub)
        self.assertEqual(receipt["verdict"], "gave_up")
        self.assertIn("triage", receipt["reason"])
        self.assertEqual(receipt["iterations"], [])
        self.assertEqual(receipt["triage"]["model"], "nvidia/Nemotron-3_5-Lightning")
        self.assertEqual(len(stub.calls), 2)  # test generation + triage, no patch call

    def test_unclear_triage_fails_closed(self):
        receipt = self.run_it(Stub(triage="hmm hard to say"))
        self.assertEqual(receipt["verdict"], "gave_up")
        self.assertEqual(receipt["triage"]["verdict"], "unclear")

    def test_api_error_emits_error_and_raises(self):
        with self.assertRaises(LoopError):
            self.run_it(Stub(status=429))
        self.assertEqual(self.types(), ["started", "error"])
        self.assertIn("HTTP 429", self.events[-1]["reason"])
        self.assertEqual(json.loads(Path(self.events[-1]["receipt_path"]).read_text())["verdict"], "error")

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
        self.assertEqual([l["type"] for l in lines], ["started", "error"])
        self.assertTrue(all(l["run_id"] == "t1" for l in lines))


if __name__ == "__main__":
    unittest.main()
