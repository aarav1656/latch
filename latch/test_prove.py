import subprocess
import tempfile
import unittest
from pathlib import Path

from latch.prove import archive, expected_base_failure, proven


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


if __name__ == "__main__":
    unittest.main()
