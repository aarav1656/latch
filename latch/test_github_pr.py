import tempfile
import unittest
from unittest import mock

from latch import github_pr
from latch.github_pr import linked_issue, parse_pull_request_url


class PullRequestInputTests(unittest.TestCase):
    def test_parses_public_pull_request_url(self):
        self.assertEqual(
            parse_pull_request_url("https://github.com/pallets/click/pull/3299"),
            ("pallets", "click", 3299),
        )

    def test_rejects_non_github_and_decorated_urls(self):
        for url in (
            "http://github.com/pallets/click/pull/3299",
            "https://github.com.attacker.test/pallets/click/pull/3299",
            "https://github.com/pallets/click/pull/3299?x=1",
            "https://github.com/pallets/click/issues/3299",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_pull_request_url(url)

    def test_requires_exactly_one_same_repository_closing_issue(self):
        self.assertEqual(linked_issue("Fixes #3298", "pallets/click"), 3298)
        for body in (
            "A pull request without a linked issue",
            "Fixes pallets/other#3298",
            "Fixes #3298 and closes #3297",
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                linked_issue(body, "pallets/click")


class StepEventForwardingTests(unittest.TestCase):
    SHA = "a" * 40

    def run_with(self, **kwargs):
        pull = {"base": {"repo": {"full_name": "o/r"}, "sha": self.SHA, "ref": "main"},
                "head": {"repo": {"full_name": "o/r"}, "sha": "b" * 40, "ref": "fix"},
                "body": "Fixes #1", "title": "t"}
        issue = {"title": "bug", "body": "text", "html_url": "https://github.com/o/r/issues/1"}
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(github_pr, "github_get", side_effect=[pull, issue]), \
                mock.patch.object(github_pr, "git"), \
                mock.patch.object(github_pr.subprocess, "run"), \
                mock.patch.object(github_pr, "prove", return_value={"proven": True}) as fake:
            github_pr.run_pull_request("https://github.com/o/r/pull/2", f"{temp}/receipt.json", "pytest", **kwargs)
        return fake.call_args.kwargs

    def test_on_step_event_is_forwarded_to_prove(self):
        sink = lambda event: None
        self.assertIs(self.run_with(on_step_event=sink)["on_step_event"], sink)

    def test_default_keeps_the_old_behaviour(self):
        kwargs = self.run_with()
        self.assertIsNone(kwargs["on_step_event"])
        self.assertIsNone(kwargs["runner"])
        self.assertTrue(kwargs["isolate_tests"])


if __name__ == "__main__":
    unittest.main()
