import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from latch.run import is_assertion_failure


class KillCheckTest(unittest.TestCase):
    def test_assertion_error_counts(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="AssertionError")
        self.assertTrue(is_assertion_failure(result))

    def test_crash_does_not_count(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="NameError")
        self.assertFalse(is_assertion_failure(result))

    def test_green_run_does_not_count(self):
        result = SimpleNamespace(returncode=0, stdout="AssertionError", stderr="")
        self.assertFalse(is_assertion_failure(result))


if __name__ == "__main__":
    unittest.main()
