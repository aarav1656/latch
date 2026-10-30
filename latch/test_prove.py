import http.client
import io
import json
import subprocess
import urllib.error
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch.prove import (ModelRequestError, archive, expected_base_failure, generate_proof_test, limit_resources,
                         needs_test_repair, proven, prove, repair_proof_test, run_test, test_error_excerpt as error_excerpt_of,
                         validate_proof_test)


class ProofClassifierTests(unittest.TestCase):
    def test_bug_fails_before_and_passes_after(self):
        output = "________ test_issue ________\nE       AssertionError: wrong value\nFAILED latch_issue_test.py::test_issue - AssertionError: wrong value\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertTrue(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, "test_issue"))

    def test_both_pass_is_not_a_proof(self):
        result = {"returncode": 0, "stdout": "", "stderr": ""}
        self.assertFalse(proven(result, result, "test_issue"))

    def test_fixed_revision_must_pass(self):
        result = {"returncode": 1, "stdout": "________ test_issue ________\nE       AssertionError\nFAILED latch_issue_test.py::test_issue - AssertionError\n", "stderr": ""}
        self.assertFalse(proven(result, result, "test_issue"))

    def test_only_base_passing_is_not_a_proof(self):
        result = {"returncode": 0, "stdout": "", "stderr": ""}
        self.assertFalse(proven(result, {"returncode": 1, "stdout": "", "stderr": ""}, "test_issue"))

    def test_unclassified_crash_does_not_count_as_bug_failure(self):
        output = "________ test_issue ________\nCaptured stdout call\nLatch expected the issue operation to succeed:\nE       NameError: pytest missing\nFAILED latch_issue_test.py::test_issue - NameError: pytest missing\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertFalse(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, "test_issue"))

    def test_an_unrelated_assertion_does_not_count(self):
        output = "________ test_other ________\nE       AssertionError\nFAILED latch_issue_test.py::test_other - AssertionError\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertFalse(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, "test_issue"))

    def test_explicit_unexpected_exception_failure_counts(self):
        output = "________ test_issue ________\nE           Failed: Latch expected the issue operation to succeed: ValueError\nFAILED latch_issue_test.py::test_issue - Failed...\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertTrue(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, "test_issue"))

    def test_failure_classifier_selects_only_known_failure_summaries(self):
        output = "________ test_issue ________\nE       AssertionError: wrong value\nFAILED latch_issue_test.py::test_issue - AssertionError: wrong value\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertEqual(expected_base_failure(result, "test_issue"), "assertion")
        result["stdout"] = "________ test_issue ________\nE           Failed: Latch expected the issue operation to succeed: ValueError\nFAILED latch_issue_test.py::test_issue - Failed...\n"
        self.assertEqual(expected_base_failure(result, "test_issue"), "unexpected-operation")
        result["stdout"] = "________ test_issue ________\nE       NameError: pytest missing\nFAILED latch_issue_test.py::test_issue - NameError: pytest missing\n"
        self.assertIsNone(expected_base_failure(result, "test_issue"))

    def test_pytest_raises_that_did_not_raise_is_a_behavior_failure_not_an_error(self):
        # toolz-602: the writer wrapped the operation in pytest.raises(LookupError); on base it returned normally.
        output = ("________ test_issue ________\nlatch_issue_test.py:35: in test_issue\n    with pytest.raises(LookupError):\n"
                  "E   Failed: DID NOT RAISE <class 'LookupError'>\nFAILED latch_issue_test.py::test_issue - Failed: DID NOT RAISE\n")
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertEqual(expected_base_failure(result, "test_issue"), "assertion")
        self.assertTrue(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, "test_issue"))
        result["stdout"] = output.replace("DID NOT RAISE <class 'LookupError'>", "DID NOT WARN. No warnings of type")
        self.assertEqual(expected_base_failure(result, "test_issue"), "assertion")
        # other pytest.fail messages are still not behavior failures
        result["stdout"] = output.replace("DID NOT RAISE <class 'LookupError'>", "something else")
        self.assertIsNone(expected_base_failure(result, "test_issue"))

    def test_long_test_name_without_summary_message_is_still_an_assertion(self):
        # pytest drops " - <msg>" from the FAILED summary line when a long name overflows 80 columns
        name = "test_" + "merging_overlapping_bookings_keeps_the_longest_end_date_" * 2
        output = f"{'_' * 9} {name} {'_' * 9}\nE   assert 3 == 4\n\n=== short test summary info ===\nFAILED latch_issue_test.py::{name}\n"
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertEqual(expected_base_failure(result, name), "assertion")
        self.assertTrue(proven(result, {"returncode": 0, "stdout": "", "stderr": ""}, name))

    def test_plain_assert_line_counts_and_is_tied_to_the_named_test(self):
        output = ("________ test_other ________\nE   assert 1 == 2\n"
                  "________ test_issue ________\nE   NameError: name 'x' is not defined\n")
        result = {"returncode": 1, "stdout": output, "stderr": ""}
        self.assertEqual(expected_base_failure(result, "test_other"), "assertion")
        self.assertIsNone(expected_base_failure(result, "test_issue"))

    def test_setup_or_collection_errors_have_no_failure_section(self):
        for output in ("_ ERROR at setup of test_issue _\nE   assert False\n",
                       "_ ERROR collecting latch_issue_test.py _\nE   AssertionError\n"):
            result = {"returncode": 1, "stdout": output, "stderr": ""}
            self.assertIsNone(expected_base_failure(result, "test_issue"))

    def test_real_pytest_run_with_a_very_long_test_name_is_classified(self):
        name = "test_" + "a_long_generated_regression_test_name_" * 3
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)
            (snapshot / "latch_issue_test.py").write_text(f"def {name}():\n    assert 1 == 2\n")
            result = run_test(snapshot, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
        self.assertNotEqual(result["returncode"], 0)
        self.assertEqual(expected_base_failure(result, name), "assertion")

    def test_resource_limits_do_not_break_a_normal_subprocess(self):
        r = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True,
                           timeout=30, preexec_fn=limit_resources)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"))

    def test_archive_materializes_the_requested_commit_without_checkout_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            snapshot = Path(temp) / "snapshot"
            repo.mkdir()
            snapshot.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            identity = ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "user.name=Latch", "-c", "user.email=latch@example.test"]
            subprocess.run([*identity, "commit", "--allow-empty", "-qm", "initial"], check=True)
            (repo / "app.py").write_text("value = 1\n")
            subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
            subprocess.run([*identity, "commit", "-qm", "add app"], check=True)
            head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            archive(repo, head, snapshot)
            self.assertEqual((snapshot / "app.py").read_text(), "value = 1\n")
            self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True), "")


class ProveRunnerTests(unittest.TestCase):
    def make_repo(self, root):
        repo = Path(root) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        identity = ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "user.name=Latch", "-c", "user.email=latch@example.test"]
        (repo / "app.py").write_text("def double(x):\n    return x + x + 1\n")
        subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
        subprocess.run([*identity, "commit", "-qm", "bug"], check=True)
        (repo / "app.py").write_text("def double(x):\n    return x + x\n")
        subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
        subprocess.run([*identity, "commit", "-qm", "fix"], check=True)
        return repo

    def test_custom_runner_replaces_the_default_test_execution(self):
        generated = "def test_double():\n    from app import double\n    assert double(2) == 4\n"
        fail = "________ test_double ________\nE       AssertionError\nFAILED latch_issue_test.py::test_double - AssertionError\n"
        calls = []

        def runner(snapshot, command):
            calls.append((snapshot.name, list(command), (snapshot / "latch_issue_test.py").exists()))
            if snapshot.name in ("base", "revert-fix"):  # the revert check runs the proof test on the unfixed tree
                return {"returncode": 1, "stdout": fail, "stderr": ""}
            return {"returncode": 0, "stdout": "1 passed", "stderr": ""}

        runner.description = "unit-test runner"
        steps = []
        with tempfile.TemporaryDirectory() as temp:
            repo = self.make_repo(temp)
            receipt = Path(temp) / "receipt.json"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch(
                "latch.prove.call_model", return_value=(200, generated, "cmpl-1")
            ), mock.patch("latch.prove.run_test", side_effect=AssertionError("default runner used")):
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt, on_step=steps.append, runner=runner, flake_runs=1, mutation=False)
            saved = json.loads(receipt.read_text())
        self.assertEqual([c[0] for c in calls], ["base", "head", "revert-fix"])
        self.assertTrue(all(c[1] == ["python3", "-m", "pytest", "-q"] and c[2] for c in calls))
        self.assertTrue(result["proven"])
        self.assertEqual(saved["test_runner"], "unit-test runner")
        self.assertEqual(steps, ["model", "base-test", "head-test", "receipt"])  # legacy string callback unchanged
        self.assertTrue(saved["revert_check"]["ok"])

    def test_default_behaviour_is_unchanged_without_a_runner(self):
        generated = "def test_double():\n    from app import double\n    assert double(2) == 4\n"
        outcome = {"returncode": 0, "stdout": "", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp:
            repo = self.make_repo(temp)
            receipt = Path(temp) / "receipt.json"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch(
                "latch.prove.call_model", return_value=(200, generated, "cmpl-1")
            ), mock.patch("latch.prove.run_test", return_value=outcome) as default_run:
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt, flake_runs=1)
        self.assertNotIn("test_runner", result)
        self.assertEqual(default_run.call_count, 2)
        self.assertTrue(all(call.kwargs == {"isolate": False} for call in default_run.call_args_list))


NAME_ERROR_OUT = ("________ test_double ________\n\ndef test_double():\n    from app import double\n>       assert double(2) == want\n"
                  "E       NameError: name 'want' is not defined\n\nlatch_issue_test.py:3: NameError\n"
                  "=========== short test summary info ===========\nFAILED latch_issue_test.py::test_double - NameError\n")
ASSERT_OUT = ("________ test_double ________\n\nE       AssertionError: assert 5 == 4\n\n"
              "=========== short test summary info ===========\nFAILED latch_issue_test.py::test_double - AssertionError\n")


class TestErrorExcerptTests(unittest.TestCase):
    def test_keeps_the_e_lines_and_the_test_frame_and_drops_library_frames(self):
        out = ("________ test_x ________\n\ndef test_x():\n>       go()\n\nlatch_issue_test.py:5: in test_x\n    go()\n"
               "/venv/lib/site-packages/lib.py:10: in go\n    secret_library_line()\nE   RuntimeError: boom\n\n"
               "=========== short test summary info ===========\nFAILED x - RuntimeError\n")
        text = error_excerpt_of({"stdout": out, "stderr": ""}, "test_x")
        self.assertIn("E   RuntimeError: boom", text)
        self.assertIn("latch_issue_test.py:5: in test_x", text)
        self.assertNotIn("secret_library_line", text)
        self.assertNotIn("short test summary", text)

    def test_is_capped(self):
        out = "________ test_x ________\n" + "".join(f"E   line {i} {'x' * 80}\n" for i in range(200))
        self.assertLessEqual(len(error_excerpt_of({"stdout": out, "stderr": ""}, "test_x")), 1500)
        self.assertLessEqual(len(error_excerpt_of({"stdout": out, "stderr": ""}, "test_x", cap=100)), 100)

    def test_collection_error_without_a_test_section_falls_back_to_the_output_tail(self):
        out = "ImportError while importing test module\n" + "y" * 5000
        text = error_excerpt_of({"stdout": out, "stderr": ""}, "test_x")
        self.assertEqual(len(text), 1500)

    def test_needs_repair_only_for_errors_not_assertions_or_green_runs(self):
        err = {"returncode": 1, "stdout": NAME_ERROR_OUT, "stderr": ""}
        fail = {"returncode": 1, "stdout": ASSERT_OUT, "stderr": ""}
        green = {"returncode": 0, "stdout": "1 passed", "stderr": ""}
        self.assertEqual(needs_test_repair(err, green, "test_double")[0], "base")
        self.assertEqual(needs_test_repair(fail, err, "test_double")[0], "head")
        self.assertIsNone(needs_test_repair(fail, green, "test_double"))
        self.assertIsNone(needs_test_repair(green, green, "test_double"))  # NO_REGRESSION_FOUND is not repaired
        self.assertIsNone(needs_test_repair(fail, fail, "test_double"))    # FIX_FAILS_TEST is not repaired


class RepairProofTestUnit(unittest.TestCase):
    def ask_returning(self, content, status=200):
        calls = []

        def ask(key, user, model=None, system=None, max_tokens=None):
            calls.append(user)
            return status, content, "cmpl-r"

        return ask, calls

    def test_exactly_one_call_with_the_original_prompt_and_the_tests_own_error(self):
        ask, calls = self.ask_returning("def test_double():\n    from app import double\n    assert double(2) == 4\n")
        function, attempt = repair_proof_test(ask, "k", "ORIGINAL PROMPT", "S", "m", 100, "def test_double(): bad", "base", "E  NameError")
        self.assertIn("double(2) == 4", function)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("ORIGINAL PROMPT"))
        self.assertIn("E  NameError", calls[0])
        self.assertTrue(attempt["test_repair"] and attempt["valid"])

    def test_a_vacuous_repair_is_rejected_without_a_second_call(self):
        ask, calls = self.ask_returning("def test_double():\n    pass\n")
        function, attempt = repair_proof_test(ask, "k", "P", "S", "m", 100, "prev", "base", "E x")
        self.assertIsNone(function)
        self.assertFalse(attempt["valid"])
        self.assertEqual(len(calls), 1)

    def test_a_failed_call_raises(self):
        ask, _ = self.ask_returning(None, status=503)
        with self.assertRaises(ModelRequestError):
            repair_proof_test(ask, "k", "P", "S", "m", 100, "prev", "base", "E x")


class ProveRepairTests(unittest.TestCase):
    """prove(): the same one-round repair through the web/CLI path."""

    make_repo = ProveRunnerTests.make_repo

    def run_prove(self, replies, **kw):
        queue = list(replies)
        users = []

        def fake_model(key, user, model=None, system=None, max_tokens=None, **_):
            users.append(user)
            return 200, queue.pop(0) if len(queue) > 1 else queue[0], f"cmpl-{len(users)}"

        def runner(snapshot, command):
            source = (snapshot / "latch_issue_test.py").read_text()
            if "want" in source:
                return {"returncode": 1, "stdout": NAME_ERROR_OUT, "stderr": ""}
            if snapshot.name == "base" or snapshot.name == "revert-fix":
                return {"returncode": 1, "stdout": ASSERT_OUT, "stderr": ""}
            return {"returncode": 0, "stdout": "1 passed", "stderr": ""}

        runner.description = "unit-test runner"
        steps = []
        with tempfile.TemporaryDirectory() as temp:
            repo = self.make_repo(temp)
            receipt = Path(temp) / "receipt.json"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch("latch.prove.call_model", side_effect=fake_model):
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt, runner=runner,
                               on_step_event=steps.append, flake_runs=1, mutation=False, repo_map=False, triage=False, **kw)
        return result, users, steps

    BAD = "def test_double():\n    from app import double\n    assert double(2) == want\n"
    GOOD = "def test_double():\n    from app import double\n    assert double(2) == 4\n"

    def test_errored_test_is_repaired_once_and_adopted(self):
        result, users, steps = self.run_prove([self.BAD, self.GOOD])
        repair = result["test_repair"]
        self.assertEqual((repair["attempted"], repair["ok"], repair["outcome"], repair["side"]), (True, True, "adopted", "base"))
        self.assertIn("NameError", repair["error_before"])
        self.assertTrue(result["proven"])
        self.assertEqual(len(users), 2)
        self.assertTrue(users[1].startswith(users[0]))
        self.assertNotIn("diff --git", users[1][len(users[0]):])
        self.assertEqual([s["status"] for s in steps if s["step"] == "test_repair"], ["started", "done"])

    def test_disabled_flag_makes_no_second_call(self):
        result, users, steps = self.run_prove([self.BAD, self.GOOD], test_repair=False)
        self.assertFalse(result["test_repair"]["attempted"])
        self.assertFalse(result["proven"])
        self.assertEqual(len(users), 1)
        self.assertEqual([s for s in steps if s["step"] == "test_repair"], [])

    def test_repair_that_still_errors_is_not_repeated(self):
        result, users, _ = self.run_prove([self.BAD, self.BAD.replace("def test_double", "def test_double_again")])
        self.assertEqual((result["test_repair"]["ok"], result["test_repair"]["outcome"]), (False, "adopted"))
        self.assertIn("NameError", result["test_repair"]["error_after"])
        self.assertFalse(result["proven"])
        self.assertEqual(len(users), 2)

    def test_assertion_failing_test_is_not_repaired(self):
        result, users, _ = self.run_prove(["def test_double():\n    from app import double\n    assert double(2) == 5\n"])
        self.assertFalse(result["test_repair"]["attempted"])
        self.assertEqual(len(users), 1)


class ValidatorTests(unittest.TestCase):
    def check(self, source):
        return validate_proof_test(source)

    def test_real_tests_pass(self):
        self.assertIsNone(self.check("def test_a():\n    from m import f\n    assert f(1) == 2\n"))
        self.assertIsNone(self.check("def test_a():\n    import pytest\n    with pytest.raises(KeyError):\n        {}['x']\n"))
        self.assertIsNone(self.check(
            "def test_a():\n    import pytest\n    try:\n        f()\n    except Exception as e:\n"
            "        pytest.fail('Latch expected the issue operation to succeed: %r' % e)\n"))
        self.assertIsNone(self.check("def test_a():\n    raise AssertionError('bad')\n"))
        self.assertIsNone(self.check('def test_a():\n    """doc"""\n    from pytest import raises\n    with raises(ValueError):\n        int("x")\n'))

    def test_placeholder_bodies_are_rejected(self):
        for body in ("    ...\n", "    pass\n", "    ...\n    pass\n", '    """only a docstring"""\n',
                     '    """doc"""\n    ...\n'):
            reason = self.check("def test_a():\n" + body)
            self.assertIsNotNone(reason, body)
            self.assertRegex(reason, "empty|placeholder")

    def test_tests_that_cannot_fail_are_rejected(self):
        self.assertIn("no real check", self.check("def test_a():\n    from m import f\n    f(1)\n"))
        self.assertIn("no real check", self.check("def test_a():\n    assert True\n"))
        self.assertIn("no real check", self.check("def test_a():\n    assert 1\n"))
        self.assertIn("no real check", self.check("def test_a():\n    x = 1\n    print(x)\n"))

    def test_unparseable_or_missing_function_is_rejected(self):
        self.assertIn("not valid Python", self.check("def test_a(:\n    assert 1 == 1\n"))
        self.assertIn("no top-level test_", self.check("def helper():\n    assert 1 == 2\n"))


class GenerationRetryTests(unittest.TestCase):
    GOOD = "def test_x():\n    assert 1 + 1 == 3\n"

    def scripted(self, *replies):
        calls = []
        queue = list(replies)

        def ask(key, user, model=None, system=None, max_tokens=None):
            calls.append(user)
            content = queue.pop(0)
            return (200, content, f"cmpl-{len(calls)}") if content is not None else (503, None, None)

        return ask, calls

    def test_vacuous_then_valid_retries_once_with_the_reason(self):
        ask, calls = self.scripted("def test_x():\n    ...\n", self.GOOD)
        function, attempts = generate_proof_test(ask, "k", "PROMPT", "S", "m", 100)
        self.assertEqual(function.strip(), self.GOOD.strip())
        self.assertEqual([a["valid"] for a in attempts], [False, True])
        self.assertEqual([a["completion_id"] for a in attempts], ["cmpl-1", "cmpl-2"])
        self.assertIn("placeholder", attempts[0]["rejection"])
        self.assertEqual(calls[0], "PROMPT")
        self.assertIn("REJECTED", calls[1])
        self.assertIn("placeholder", calls[1])

    def test_vacuous_twice_fails_closed_after_exactly_two_calls(self):
        ask, calls = self.scripted("def test_x():\n    pass\n", "def test_x():\n    assert True\n", self.GOOD)
        function, attempts = generate_proof_test(ask, "k", "P", "S", "m", 100)
        self.assertIsNone(function)
        self.assertEqual(len(calls), 2)
        self.assertEqual([a["valid"] for a in attempts], [False, False])

    def test_model_failure_raises(self):
        ask, _ = self.scripted(None)
        with self.assertRaises(ModelRequestError) as caught:
            generate_proof_test(ask, "k", "P", "S", "m", 100)
        self.assertEqual(caught.exception.status, 503)

    def test_prove_records_both_attempts_and_fails_closed_without_running_tests(self):
        replies = iter([(200, "def test_x():\n    ...\n", "c1"), (200, "def test_x():\n    pass\n", "c2")])

        def scripted(key, user, model=None, system=None, **kw):
            if "map a Python repository" in (system or ""):
                return 503, None, None  # the repo map is context only; its failure must not block the run
            return next(replies)

        with tempfile.TemporaryDirectory() as temp:
            repo = ProveRunnerTests().make_repo(temp)
            receipt = Path(temp) / "r.json"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch(
                "latch.prove.call_model", side_effect=scripted
            ), mock.patch("latch.prove.run_test", side_effect=AssertionError("nothing may run")):
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt)
            saved = json.loads(receipt.read_text())
        self.assertFalse(result["proven"])
        self.assertEqual(len(saved["test_attempts"]), 2)
        self.assertIn("rejected as vacuous twice", saved["why_not_proven"])
        self.assertIsNone(saved["base_result"])


class TautologyWiringTests(unittest.TestCase):
    """The deterministic check runs before any test: a test that never asserts on the changed code is retried once
    with the reason, then fails closed as INVALID_TEST."""
    TAUTOLOGY = "def test_double():\n    from app import double\n    assert double(2) == double(2)\n"
    CONSTANT = "def test_double():\n    from app import double\n    assert 1 + 1 == 2\n"
    GOOD = "def test_double():\n    from app import double\n    assert double(2) == 4\n"

    def run_prove(self, replies, runner=None):
        replies = iter(replies)
        prompts = []

        def scripted(key, user, model=None, system=None, **kw):
            if "map a Python repository" in (system or ""):
                return 503, None, None
            prompts.append(user)
            return 200, next(replies, "REPRODUCES: yes"), f"c{len(prompts)}"

        with tempfile.TemporaryDirectory() as temp:
            repo = ProveRunnerTests().make_repo(temp)
            receipt = Path(temp) / "r.json"
            fail = {"returncode": 1, "stdout": "________ test_double ________\nE       AssertionError\nFAILED latch_issue_test.py::test_double - AssertionError\n", "stderr": ""}
            ok = {"returncode": 0, "stdout": "1 passed", "stderr": ""}

            def default_runner(snapshot, command):
                return fail if snapshot.name in ("base", "revert-fix") or snapshot.name.startswith("mutant-") else ok

            default_runner.description = "stub"
            with mock.patch("latch.prove.load_key", return_value="key"), mock.patch(
                "latch.prove.call_model", side_effect=scripted
            ):
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt,
                               runner=runner or default_runner)
            saved = json.loads(receipt.read_text())
        return result, saved, prompts

    def test_tautology_is_retried_once_with_the_reason_then_passes(self):
        result, saved, prompts = self.run_prove([self.TAUTOLOGY, self.GOOD])
        self.assertIn("REJECTED", prompts[1])
        self.assertIn("double", prompts[1])
        self.assertNotIn("REJECTED", prompts[0])
        self.assertEqual([a["valid"] for a in saved["test_attempts"]], [False, True])
        self.assertTrue(saved["tautology"]["checked"])
        self.assertTrue(saved["tautology"]["ok"])
        self.assertEqual(saved["tautology"]["asserted_symbols"], ["double"])
        self.assertEqual(saved["tautology"]["changed_symbols"], ["double"])
        self.assertTrue(result["proven"])

    def test_two_tautologies_fail_closed_as_invalid_test_without_running_tests(self):
        def never(*a, **k):
            raise AssertionError("nothing may run")

        result, saved, prompts = self.run_prove([self.TAUTOLOGY, self.CONSTANT], runner=never)
        self.assertFalse(saved["proven"])
        self.assertEqual(saved["verdict"], "INVALID_TEST")
        self.assertIn("rejected as vacuous twice", saved["why_not_proven"])
        self.assertFalse(saved["tautology"]["ok"])
        self.assertTrue(saved["tautology"]["checked"])
        self.assertIn("double", saved["tautology"]["reason"])
        self.assertIsNone(saved["base_result"])

    def test_undetermined_changes_do_not_block(self):
        unchecked = {"determined": False, "symbols": [], "affected": [], "files": [], "reason": "no diff"}
        with mock.patch("latch.tautology.safe_changed_symbols", return_value=unchecked):
            result, saved, prompts = self.run_prove([self.CONSTANT])
        self.assertFalse(any("REJECTED" in p for p in prompts))
        self.assertFalse(saved["tautology"]["checked"])
        self.assertTrue(saved["tautology"]["ok"])
        self.assertTrue(result["proven"])


class CallModelRetryTests(unittest.TestCase):
    def reply(self, text="hi"):
        body = json.dumps({"id": "cmpl-ok", "choices": [{"message": {"content": text}}]}).encode()
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    def call(self, effects, **kw):
        from latch import run
        sleeps, retries = [], []
        with mock.patch("latch.run.urllib.request.urlopen", side_effect=effects) as opened:
            out = run.call_model("k", "u", on_retry=retries.append, sleep=sleeps.append, jitter=lambda: 0.5, **kw)
        return out, sleeps, retries, opened

    def test_remote_disconnected_then_ok_retries_with_backoff(self):
        out, sleeps, retries, opened = self.call([
            http.client.RemoteDisconnected("Remote end closed connection without response"),
            ConnectionResetError("reset"),
            self.reply(),
        ])
        self.assertEqual(out, (200, "hi", "cmpl-ok"))
        self.assertEqual(sleeps, [1.5, 2.5])  # 1*2^0 + jitter, 1*2^1 + jitter
        self.assertEqual([r["will_retry"] for r in retries], [True, True])
        self.assertIn("RemoteDisconnected", retries[0]["error"])
        self.assertEqual(opened.call_args.kwargs["timeout"], 180)

    def test_status_429_and_5xx_are_retried_and_fail_closed_after_three_attempts(self):
        def http_error(code):
            return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))
        out, sleeps, retries, opened = self.call([http_error(429), http_error(502), http_error(503)])
        self.assertEqual(out, (503, None, None))
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual([r["will_retry"] for r in retries], [True, True, False])

    def test_timeout_is_transient_but_400_is_not(self):
        out, _, retries, opened = self.call([TimeoutError("timed out"), self.reply("x")], timeout=7)
        self.assertEqual(out[0], 200)
        self.assertEqual(len(retries), 1)
        self.assertEqual(opened.call_args.kwargs["timeout"], 7)
        out, sleeps, retries, opened = self.call([urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b""))])
        self.assertEqual(out, (400, None, None))
        self.assertEqual((sleeps, opened.call_count), ([], 1))


if __name__ == "__main__":
    unittest.main()
