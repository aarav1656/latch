import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch.prove import archive, expected_base_failure, limit_resources, proven, prove, run_test


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
            if snapshot.name == "base":
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
        self.assertEqual([c[0] for c in calls], ["base", "head"])
        self.assertTrue(all(c[1] == ["python3", "-m", "pytest", "-q"] and c[2] for c in calls))
        self.assertTrue(result["proven"])
        self.assertEqual(saved["test_runner"], "unit-test runner")
        self.assertEqual(steps, ["model", "base-test", "head-test", "receipt"])

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


if __name__ == "__main__":
    unittest.main()
