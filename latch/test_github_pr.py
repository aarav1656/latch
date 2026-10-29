import unittest

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


if __name__ == "__main__":
    unittest.main()
