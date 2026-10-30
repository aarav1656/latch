"""Survivor-driven test strengthening (latch.strengthen, wired into latch.prove and latch.loop.core).

Offline: the model is a stub; git, pytest and the AST mutation check are real. The invariants under test:
only an actual mutation failure triggers ONE test-writer retry; the retry prompt carries the survivors' diffs; the
new test goes through the whole gate again; the 0.6 bar never moves; anything short of a full pass keeps the
original MUTATION_SURVIVED verdict.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch import strengthen
from latch.loop import run_loop
from latch.loop.test_loop import FIXED_BOOKINGS, GOOD_TEST, ISSUE, PASSING_ON_BASE_TEST, Stub, file_block, make_repo
from latch.prove import prove

# Passes the gate (red on base, green on the fix) but only pins merge_bookings; most mutants of overlaps() survive.
WEAK_TEST = '''def test_weak_merge_only():
    from bookings import merge_bookings
    assert merge_bookings([(540, 600), (600, 660)]) == [(540, 600), (600, 660)]
'''
# Reds on the fixed code: it asserts the old (buggy) merge behaviour, so it can never be adopted.
FAILS_ON_FIX_TEST = '''def test_expects_the_bug():
    from bookings import merge_bookings
    assert merge_bookings([(540, 600), (600, 660)]) == [(540, 600), (600, 660)]
    assert merge_bookings([(540, 600), (570, 630)]) == [(540, 600), (570, 630)]
'''


_SHIM = tempfile.TemporaryDirectory()
_SAVED_ENV = {}


def setUpModule():
    """Own hermetic `python3` shim (test_loop's is torn down when that module finishes) and demo cache."""
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


class WriterStub(Stub):
    """Test-writer replies come from `tests`, one per call (the last one repeats); other roles behave like Stub."""

    def __init__(self, tests, **kw):
        super().__init__(**kw)
        self.tests = list(tests)
        self.writer_prompts = []

    def __call__(self, key, user, model=None, system=None, max_tokens=None, prose=False):
        if "test_" in (system or "") and "Write one self-contained" in system:
            self.writer_prompts.append(user)
            reply = self.tests.pop(0) if len(self.tests) > 1 else self.tests[0]
            self.calls.append({"model": model, "user": user, "key": key})
            return 200, reply, f"cmpl-test-{len(self.writer_prompts)}"
        return super().__call__(key, user, model, system, max_tokens, prose)


def passing(kill_rate=0.6, killed=3, total=5):
    return {"ran": True, "ok": True, "killed": killed, "total": total, "kill_rate": kill_rate, "threshold": 0.6,
            "mutants": [], "note": "ok", "incomplete": False}


class HelperTests(unittest.TestCase):
    MUTANTS = [
        {"id": "m1", "killed": True, "operator": "o", "file": "a.py", "line": 1, "what": "w", "diff": "d"},
        {"id": "m2", "killed": False, "operator": "o", "file": "a.py", "line": 2, "what": "w2", "diff": "d2"},
        {"id": "m3", "killed": False, "not_run": True, "operator": "o", "file": "a.py", "line": 3, "what": "w", "diff": "d"},
        {"id": "m4", "killed": False, "error": "OSError: x", "operator": "o", "file": "a.py", "line": 4, "what": "w", "diff": "d"},
        {"id": "m5", "killed": True, "timed_out": True, "operator": "o", "file": "a.py", "line": 5, "what": "w", "diff": "d"},
    ]

    def test_only_mutants_that_ran_and_survived_are_survivors(self):
        found = strengthen.survivors({"mutants": self.MUTANTS})
        self.assertEqual([m["id"] for m in found], ["m2"])
        self.assertEqual(set(found[0]), {"id", "operator", "file", "line", "what", "diff"})

    def test_trigger_is_an_actual_failure_with_a_measured_rate_and_a_survivor(self):
        failing = {"ok": False, "kill_rate": 0.4, "killed": 2, "total": 5, "mutants": self.MUTANTS}
        self.assertTrue(strengthen.eligible(failing))
        # exactly at the bar, or one mutant above it, is a pass and never a trigger
        self.assertFalse(strengthen.eligible({**failing, "ok": True, "kill_rate": 0.6}))
        self.assertFalse(strengthen.eligible({**failing, "ok": True, "kill_rate": 0.8}))
        self.assertFalse(strengthen.eligible({**failing, "incomplete": True}))        # budget ran out: not a verdict
        self.assertFalse(strengthen.eligible({**failing, "kill_rate": None}))         # the check could not measure anything
        self.assertFalse(strengthen.eligible({**failing, "mutants": []}))             # nothing to learn from
        self.assertFalse(strengthen.eligible(None))

    def test_prompt_carries_what_and_diff_of_every_survivor_and_the_old_test(self):
        found = strengthen.survivors({"mutants": self.MUTANTS})
        text = strengthen.addendum("def test_old(): pass", {"killed": 1, "total": 5, "threshold": 0.6}, found)
        for needle in ("m2", "a.py:2", "w2", "d2", "def test_old(): pass", "ALSO fails on each surviving mutant"):
            self.assertIn(needle, text)


class LoopStrengtheningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo, self.base, self.head = make_repo(self._tmp.name)
        self.events = []

    def run_it(self, stub, **kw):
        kw.setdefault("receipt_path", str(Path(self._tmp.name) / "receipt.json"))
        kw.setdefault("fixes", None)
        kw.pop("fixes")
        return run_loop(self.repo, self.base, self.head, ISSUE, on_event=self.events.append, model_fn=stub, **kw)

    def stub(self, tests):
        return WriterStub(tests, fixes=[file_block("bookings.py", FIXED_BOOKINGS)])

    def step_names(self):
        return [(e["step"], e["status"]) for e in self.events if e["type"] == "step"]

    def test_a_weak_test_gets_one_retry_with_the_survivors_and_the_whole_gate_reruns(self):
        stub = self.stub([WEAK_TEST, GOOD_TEST])
        receipt = self.run_it(stub)
        self.assertEqual((receipt["gate"], receipt["verdict"]), ("gate_open", "VALIDATED"))
        self.assertEqual(len(stub.writer_prompts), 2)                       # one original call, ONE retry
        self.assertNotIn("STRENGTHENING ROUND", stub.writer_prompts[0])
        retry = stub.writer_prompts[1]
        self.assertIn("STRENGTHENING ROUND", retry)
        self.assertIn("test_weak_merge_only", retry)                         # the previous test is shown
        before = receipt["mutation"]["strengthened"]["survivors_before"]
        self.assertTrue(before)
        for survivor in before:                                              # what + diff of every survivor is in the prompt
            self.assertIn(survivor["what"], retry)
            self.assertIn(survivor["diff"].strip().splitlines()[-1], retry)
        info = receipt["mutation"]["strengthened"]
        self.assertEqual((info["attempted"], info["outcome"], info["threshold"]), (True, "adopted", 0.6))
        self.assertLess(info["kill_rate_before"], 0.6)
        self.assertGreaterEqual(info["kill_rate_after"], 0.6)
        self.assertEqual(receipt["mutation"]["kill_rate"], info["kill_rate_after"])
        self.assertEqual(receipt["mutation"]["threshold"], 0.6)             # the bar never moved
        self.assertEqual(receipt["proof_test"]["name"], "test_back_to_back_not_conflict_or_merged")
        self.assertTrue(receipt["proof_test"]["strengthened"])
        self.assertEqual([a.get("strengthening", False) for a in receipt["proof_test_attempts"]], [False, True])
        self.assertIn("after one strengthening round", receipt["verdict_reason"])
        self.assertEqual(receipt["mutation"]["mutants"][0]["file"], "bookings.py")

    def test_the_new_test_goes_through_every_stage_again(self):
        self.run_it(self.stub([WEAK_TEST, GOOD_TEST]))
        names = self.step_names()
        at = names.index(("strengthen", "started"))
        later = names[at:]
        for stage in ("base_run", "head_run", "flake_check", "revert_check", "mutation_check"):
            self.assertIn((stage, "done"), later, stage)
        self.assertEqual(names[-2:], [("strengthen", "done"), ("verdict", "done")])
        started = [e for e in self.events if e["type"] == "step" and e["step"] == "strengthen" and e["status"] == "started"][0]
        self.assertEqual(started["detail"]["kill_rate_before"], 0.2)
        self.assertEqual(started["detail"]["total"], 5)
        self.assertEqual([e["type"] for e in self.events].count("proof_test"), 2)
        self.assertEqual([e for e in self.events if e["type"] == "gate_shut" and "mutation" in e["reason"]], [])

    def test_the_cap_is_one_round_and_a_second_failure_stays_failed(self):
        stub = self.stub([WEAK_TEST, WEAK_TEST])
        receipt = self.run_it(stub)
        self.assertEqual((receipt["gate"], receipt["verdict"]), ("gave_up", "MUTATION_SURVIVED"))
        self.assertEqual(len(stub.writer_prompts), 2)
        info = receipt["mutation"]["strengthened"]
        self.assertEqual(info["outcome"], "still_surviving")
        self.assertLess(info["kill_rate_after"], 0.6)
        self.assertIn("after one strengthening round", receipt["verdict_reason"])
        self.assertEqual([e["type"] for e in self.events if e["type"] == "gate_shut" and "mutation" in e["reason"]], ["gate_shut"])
        self.assertEqual(sum(1 for e in self.events if e["type"] == "step" and e["step"] == "strengthen" and e["status"] == "started"), 1)

    def test_a_passing_check_never_triggers_it_not_even_exactly_at_the_bar(self):
        for rate, killed in ((0.6, 3), (0.8, 4)):
            stub = self.stub([GOOD_TEST])
            with mock.patch("latch.mutate.run_mutation", return_value=passing(rate, killed)):
                receipt = self.run_it(stub)
            self.assertEqual(receipt["verdict"], "VALIDATED")
            self.assertEqual(len(stub.writer_prompts), 1)
            self.assertNotIn("strengthened", receipt["mutation"])
            self.assertNotIn("strengthen", [name for name, _ in self.step_names()])

    def test_an_unmeasured_or_incomplete_check_is_not_a_trigger(self):
        broken = {"ran": False, "ok": False, "killed": 0, "total": 0, "kill_rate": None, "threshold": 0.6,
                  "mutants": [], "note": "could not run"}
        stub = self.stub([GOOD_TEST])
        with mock.patch("latch.mutate.run_mutation", return_value=broken):
            receipt = self.run_it(stub)
        self.assertEqual(receipt["verdict"], "MUTATION_SURVIVED")
        self.assertEqual(len(stub.writer_prompts), 1)
        self.assertEqual(receipt["mutation"]["strengthened"]["attempted"], False)

    def test_it_can_be_turned_off(self):
        stub = self.stub([WEAK_TEST, GOOD_TEST])
        receipt = self.run_it(stub, strengthen=False)
        self.assertEqual(receipt["verdict"], "MUTATION_SURVIVED")
        self.assertEqual(len(stub.writer_prompts), 1)
        self.assertEqual(receipt["mutation"]["strengthened"], {"attempted": False, "reason": "strengthening is off"})

    def test_a_supplied_proof_test_is_never_rewritten(self):
        stub = self.stub([GOOD_TEST])
        receipt = self.run_it(stub, proof_test=WEAK_TEST)
        self.assertEqual(receipt["verdict"], "MUTATION_SURVIVED")
        self.assertEqual(len(stub.writer_prompts), 0)
        self.assertIn("supplied", receipt["mutation"]["strengthened"]["reason"])

    def test_a_stronger_test_that_is_not_red_on_base_is_dropped_and_the_original_verdict_stands(self):
        receipt = self.run_it(self.stub([WEAK_TEST, PASSING_ON_BASE_TEST]))
        self.assertEqual((receipt["gate"], receipt["verdict"]), ("gave_up", "MUTATION_SURVIVED"))
        info = receipt["mutation"]["strengthened"]
        self.assertEqual(info["outcome"], "kept_original")
        self.assertIn("base", info["reason"])
        self.assertEqual(receipt["proof_test"]["name"], "test_weak_merge_only")  # the original test and its evidence stay
        self.assertEqual(receipt["mutation"]["kill_rate"], info["kill_rate_before"])
        self.assertNotIn("strengthening round", receipt["verdict_reason"])

    def test_a_stronger_test_that_fails_on_the_fixed_code_is_dropped(self):
        receipt = self.run_it(self.stub([WEAK_TEST, FAILS_ON_FIX_TEST]))
        self.assertEqual(receipt["verdict"], "MUTATION_SURVIVED")
        info = receipt["mutation"]["strengthened"]
        self.assertEqual(info["outcome"], "kept_original")
        self.assertIn("fixed code", info["reason"])

    def test_the_already_passing_path_strengthens_too(self):
        # head already fixes the issue: no fix iterations, the mutation gate sits on the first gate_open
        fixed = Path(self._tmp.name) / "fixed"
        repo, base, head = make_fixed_repo(fixed)
        stub = WriterStub([WEAK_TEST, GOOD_TEST])
        receipt = run_loop(repo, base, head, ISSUE, model_fn=stub, on_event=self.events.append,
                           receipt_path=str(fixed / "r.json"))
        self.assertEqual((receipt["gate"], receipt["verdict"], receipt["iterations"]), ("gate_open", "VALIDATED", []))
        self.assertEqual(receipt["mutation"]["strengthened"]["outcome"], "adopted")
        self.assertEqual(len(stub.writer_prompts), 2)


class DevEventLabelTests(unittest.TestCase):
    """Every event of a dev (non-Nebius) run names its provider and says dev_only, not just the first one."""

    def events_for(self, provider):
        env = {k: v for k, v in os.environ.items() if k not in ("LATCH_PROVIDER", "OPENROUTER_API_KEY", "NEBIUS_API_KEY")}
        if provider:
            env["LATCH_PROVIDER"] = provider
            env["OPENROUTER_API_KEY"] = "test-openrouter-key"
        events = []
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, env, clear=True):
            repo, base, head = make_repo(temp)
            run_loop(repo, base, head, ISSUE, model_fn=WriterStub([GOOD_TEST], fixes=[file_block("bookings.py", FIXED_BOOKINGS)]),
                     on_event=events.append, mutation=False, flake_runs=1)
        return events

    def test_dev_run_labels_every_event(self):
        events = self.events_for("openrouter")
        self.assertGreater(len(events), 10)
        for event in events:
            self.assertEqual((event.get("provider"), event.get("dev_only")), ("openrouter", True), event["type"])

    def test_nebius_events_are_unchanged(self):
        for event in self.events_for(None):
            self.assertNotIn("dev_only", event)


def make_fixed_repo(root):
    """The demo repo with a third commit holding the complete fix; returns (repo, base, fixed_head)."""
    root.mkdir(parents=True, exist_ok=True)
    repo, base, _ = make_repo(root)
    (repo / "bookings.py").write_text(FIXED_BOOKINGS)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "commit", "-qam", "good"], env=env, check=True)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return repo, base, head


class ProveStrengtheningTests(unittest.TestCase):
    def run_prove(self, tests, **kw):
        replies = list(tests)
        prompts = []

        def scripted(key, user, model=None, system=None, **extra):
            if "map a Python repository" in (system or ""):
                return 503, None, None
            if "triage" in (system or ""):
                return 200, "REPRODUCES: yes", "c-triage"
            prompts.append(user)
            reply = replies.pop(0) if len(replies) > 1 else replies[0]
            return 200, reply, f"c{len(prompts)}"

        with tempfile.TemporaryDirectory() as temp:
            repo, base, head = make_fixed_repo(Path(temp) / "fx")
            receipt = Path(temp) / "r.json"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch("latch.prove.call_model", side_effect=scripted):
                result = prove(repo, base, head, ISSUE, "python3 -m pytest -q", receipt, **kw)
            saved = json.loads(receipt.read_text())
        return result, saved, prompts

    def test_weak_then_strong_is_validated_and_recorded(self):
        result, saved, prompts = self.run_prove([WEAK_TEST, GOOD_TEST])
        self.assertEqual((saved["verdict"], saved["proven"]), ("VALIDATED", True))
        self.assertEqual(len(prompts), 2)
        self.assertIn("STRENGTHENING ROUND", prompts[1])
        info = saved["mutation"]["strengthened"]
        self.assertEqual((info["attempted"], info["outcome"], info["threshold"]), (True, "adopted", 0.6))
        self.assertLess(info["kill_rate_before"], 0.6)
        self.assertGreaterEqual(saved["mutation"]["kill_rate"], 0.6)
        self.assertEqual(saved["test_name"], "test_back_to_back_not_conflict_or_merged")
        self.assertIn("test_back_to_back", saved["test"])
        self.assertEqual([a.get("strengthening", False) for a in saved["test_attempts"]], [False, True])
        steps = [(s["step"], s["status"]) for s in saved["steps"]]
        at = steps.index(("strengthen", "started"))
        for stage in ("base_run", "head_run", "flake_check", "revert_check", "mutation_check"):
            self.assertIn((stage, "done"), steps[at:], stage)
        self.assertIn("after one strengthening round", saved["verdict_reason"])

    def test_cap_of_one_and_second_failure_stays_failed(self):
        result, saved, prompts = self.run_prove([WEAK_TEST, WEAK_TEST])
        self.assertEqual((saved["verdict"], saved["proven"]), ("MUTATION_SURVIVED", False))
        self.assertEqual(len(prompts), 2)
        self.assertEqual(saved["mutation"]["strengthened"]["outcome"], "still_surviving")

    def test_a_pass_at_the_bar_does_not_trigger(self):
        with mock.patch("latch.mutate.run_mutation", return_value=passing(0.6, 3)):
            result, saved, prompts = self.run_prove([GOOD_TEST])
        self.assertEqual(saved["verdict"], "VALIDATED")
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("strengthened", saved["mutation"])

    def test_off_switch_and_a_rejected_retry_keep_the_original_verdict(self):
        _, saved, prompts = self.run_prove([WEAK_TEST, GOOD_TEST], strengthen=False)
        self.assertEqual((saved["verdict"], len(prompts)), ("MUTATION_SURVIVED", 1))
        self.assertEqual(saved["mutation"]["strengthened"]["attempted"], False)
        _, saved, prompts = self.run_prove([WEAK_TEST, PASSING_ON_BASE_TEST])
        self.assertEqual(saved["verdict"], "MUTATION_SURVIVED")
        self.assertEqual(saved["mutation"]["strengthened"]["outcome"], "kept_original")
        self.assertEqual(saved["test_name"], "test_weak_merge_only")


if __name__ == "__main__":
    unittest.main()
