import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from run import message_text


class TestProse(unittest.TestCase):
    def test_sentence_beats_reasoning_trace(self):
        text = message_text(
            {
                "content": "The test test_ten_seats_ran still passes.",
                "reasoning_content": "Here's a thinking process: long trace",
            },
            prose=True,
        )
        self.assertEqual(text, "The test test_ten_seats_ran still passes.")

    def test_empty_content_does_not_surface_the_trace(self):
        text = message_text(
            {
                "content": "",
                "reasoning_content": "Here's a thinking process: the test is a tautology",
            },
            prose=True,
        )
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
