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
                         proven, prove, run_test, validate_proof_test)


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
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt, on_step=steps.append, runner=runner)
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
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q", receipt)
        self.assertNotIn("test_runner", result)
        self.assertEqual(default_run.call_count, 2)
        self.assertTrue(all(call.kwargs == {"isolate": False} for call in default_run.call_args_list))


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
