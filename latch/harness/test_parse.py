import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse import extract_function, extract_test_function


class ExtractFunctionTest(unittest.TestCase):
    def test_fenced_function_extracts(self):
        text = "```python\ndef test_boundary():\n    assert discount_applies(10, True) is True\n```"
        self.assertEqual(
            extract_function(text),
            "def test_boundary():\n    assert discount_applies(10, True) is True",
        )

    def test_unspaced_call_extracts(self):
        text = "def t():\n    assert discount_applies(10,True) is True\n"
        self.assertIn("discount_applies(10,True)", extract_function(text))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            extract_function("")

    def test_function_without_call_raises(self):
        text = "```python\ndef test_other():\n    assert discount_applies(5, True) is False\n```"
        with self.assertRaises(ValueError):
            extract_function(text)

    def test_trailing_prose_is_dropped(self):
        text = "def t():\n    assert discount_applies(10, True) is True\n\nThis checks the boundary."
        self.assertNotIn("boundary", extract_function(text))

    def test_issue_test_does_not_require_fixture_function(self):
        text = "```python\ndef test_issue():\n    assert True\n```"
        self.assertEqual(extract_test_function(text), "def test_issue():\n    assert True")

    def test_issue_test_requires_pytest_name(self):
        with self.assertRaises(ValueError):
            extract_test_function("def helper():\n    assert True")


if __name__ == "__main__":
    unittest.main()
