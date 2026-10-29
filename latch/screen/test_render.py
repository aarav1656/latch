import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from latch.screen.render import render


class TestRender(unittest.TestCase):
    def test_open_and_shut_states(self):
        open_doc = render(
            {
                "weak_green": True,
                "mutant_still_green": True,
                "kill_failed": True,
                "restored_passed": True,
                "assertion": "assert result == 42",
            }
        )
        shut_doc = render(
            {
                "weak_green": True,
                "mutant_still_green": True,
                "kill_failed": False,
                "restored_passed": True,
                "assertion": "assert result is not None",
            }
        )

        self.assertIn('id="latch">Open<', open_doc)
        self.assertIn('id="latch">Shut<', shut_doc)

        for doc in (open_doc, shut_doc):
            self.assertNotIn("gradient", doc.lower())
            self.assertIsNone(re.search(r"\bInter\b", doc))

    def test_shut_shows_reason_and_http(self):
        doc = render(
            {
                "weak_green": False,
                "mutant_still_green": False,
                "kill_failed": False,
                "restored_passed": False,
                "assertion": "",
                "reason": "timeout",
                "http_status": 401,
            }
        )
        self.assertIn('id="latch">Shut<', doc)
        self.assertIn('id="reason">timeout<', doc)
        self.assertIn('id="http">401<', doc)


if __name__ == "__main__":
    unittest.main()
