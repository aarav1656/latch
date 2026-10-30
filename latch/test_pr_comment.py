"""Offline tests: the PR-comment renderer, the REST client (fake http) and the `latch` console entry point."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from latch import cli, pr_comment
from latch.pr_comment import MARKER, post_or_update_comment, render_comment

DEMO_RECEIPT = Path(__file__).resolve().parent / "runs" / "loop-demo.json"

CALLS = [
    {"role": "repo_map", "model": "nvidia/Nemotron-3_5-Lightning", "prompt_tokens": 400, "completion_tokens": 20,
     "latency_ms": 900, "completion_id": "cmpl-map-1", "cost_usd": 0.00003},
    {"role": "test_writer", "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "prompt_tokens": 1500, "completion_tokens": 300,
     "latency_ms": 6100, "completion_id": "cmpl-test-1", "cost_usd": 0.0024},
    {"role": "fixer", "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "prompt_tokens": None, "completion_tokens": None,
     "latency_ms": 5000, "completion_id": "cmpl-fix-1", "cost_usd": None},
]
REVERT_OK = {"ran": True, "ok": True, "mutants": [{"name": "revert_fix_to_base", "failed_again": True}], "summary": "ok"}


def loop_receipt(verdict="gate_open", iterations=1, reason="harness watched the proof test go red on base and green after iteration 1"):
    its = [{"iteration": i + 1, "verdict": "gate_open" if (verdict == "gate_open" and i == iterations - 1) else "gate_shut",
            "completion_id": f"cmpl-fix-{i + 1}", "diff": "--- a/x.py\n+++ b/x.py\n-    a <= b\n+    a < b\n"} for i in range(iterations)]
    return {"run_id": "r1", "repo": "bookings", "base": "a" * 40, "head": "b" * 40, "verdict": verdict, "reason": reason,
            "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "test_model": "nvidia/Nemotron-3-Ultra-550b-a55b",
            "case_note": "Constructed regression case: hand-written partial fix.",
            "proof_test": {"name": "test_back_to_back", "source": "def test_back_to_back():\n    assert 1 == 2\n", "completion_id": "cmpl-test-1"},
            "initial": {"base_proof": {"returncode": 1, "failure_type": "assertion"}, "head_proof": {"returncode": 1},
                        "head_suite": {"returncode": 0}},
            "iterations": its, "revert_check": REVERT_OK if verdict == "gate_open" else None,
            "triage": {"verdict": "reproduced"}, "model_calls": CALLS, "model_cost_usd": 0.00243,
            "model_prices_source": "https://tokenfactory.nebius.com/model-catalog.md"}


def prove_receipt(proven=True):
    r = {"repo": "r", "base": "c" * 40, "head": "d" * 40, "model": "nvidia/Nemotron-3-Ultra-550b-a55b", "completion_id": "cmpl-test-1",
         "test": "def test_x():\n    assert f() == 1\n", "test_name": "test_x", "base_failure_type": "assertion",
         "base_result": {"returncode": 1}, "head_result": {"returncode": 0 if proven else 1}, "proven": proven,
         "revert_check": REVERT_OK if proven else None, "triage": {"verdict": "reproduced", "advisory": True},
         "model_calls": CALLS, "model_cost_usd": None}
    if not proven:
        r["why_not_proven"] = "the test fails on head too, so nothing here proves the fix | maybe @someone"
    return r


class RenderTests(unittest.TestCase):
    def test_loop_repaired_receipt(self):
        body = render_comment(loop_receipt())
        self.assertTrue(body.startswith(MARKER))
        for expected in ("Gate open after 1 repair iteration", "`test_back_to_back`", "Base `aaaaaaaaaa` | FAILS (assertion)",
                         "Head `bbbbbbbbbb` | FAILS; repo suite passes", "Repair | 1 iteration(s)",
                         "proof test failed again on every mutant (revert_fix_to_base)", "Triage (Lightning) | reproduced",
                         "`Nemotron-3-Ultra-550b-a55b`", "cmpl-test-1", "cmpl-map-1", "cmpl-fix-1", "Constructed regression case",
                         "+    a < b", "Estimated model cost: $0.0024", "model-catalog.md"):
            self.assertIn(expected, body)
        self.assertNotIn("nvidia/", body)  # model names are shortened

    def test_loop_gate_open_at_iteration_zero(self):
        body = render_comment(loop_receipt(iterations=0))
        self.assertIn("Gate open: the submitted change is proven", body)
        self.assertNotIn("Repair |", body)

    def test_loop_gave_up_is_not_green(self):
        body = render_comment(loop_receipt("gave_up", 3, "gate still shut after 3 iteration(s)"))
        self.assertIn("❌ Gate shut", body)
        self.assertNotIn("✅", body)
        self.assertIn("Revert check | not run", body)
        self.assertNotIn("Patch that opened the gate", body)

    def test_loop_error_fails_closed(self):
        self.assertIn("Error: nothing proven", render_comment(loop_receipt("error", 0, "HTTP 402")))

    def test_prove_proven_and_not_proven(self):
        good, bad = render_comment(prove_receipt()), render_comment(prove_receipt(False))
        self.assertIn("✅ PROVEN", good)
        self.assertIn("Base `cccccccccc` | FAILS (assertion)", good)
        self.assertIn("Head `dddddddddd` | passes", good)
        self.assertIn("Cost unknown", good)
        self.assertIn("❌ NOT PROVEN", bad)
        self.assertNotIn("✅", bad)
        self.assertIn("\\|", bad)               # table-safe
        self.assertNotIn("@someone", bad)      # no pings from model-written text
        self.assertIn("(advisory)", bad)

    def test_revert_check_failure_and_missing_are_visible(self):
        r = prove_receipt()
        r["revert_check"] = {"ran": True, "ok": False, "mutants": [{"name": "revert_fix_to_base"}], "summary": "survived"}
        self.assertIn("did NOT fail on a mutant", render_comment(r))
        r["revert_check"] = {"ran": False, "skipped": "revert check disabled"}
        self.assertIn("not run (revert check disabled)", render_comment(r))
        r["revert_check"] = {"ran": False, "ok": False}
        self.assertIn("gate stays shut", render_comment(r))

    def test_oversized_receipt_is_truncated_under_the_github_limit(self):
        r = loop_receipt()
        r["proof_test"]["source"] = "x = 1\n" * 30000
        body = render_comment(r)
        self.assertLessEqual(len(body), pr_comment.LIMIT)
        self.assertIn("comment truncated", body)
        self.assertTrue(body.startswith(MARKER))

    def test_fence_survives_backticks_in_model_text(self):
        r = prove_receipt()
        r["test"] = "def test_x():\n    s = '```'\n"
        self.assertIn("````python", render_comment(r))

    def test_the_committed_demo_receipt_renders(self):
        body = render_comment(json.loads(DEMO_RECEIPT.read_text()), run_url="https://example.invalid/run/1")
        self.assertIn("Constructed regression case", body)
        self.assertIn("[Run](https://example.invalid/run/1)", body)


class FakeGitHub:
    def __init__(self, comments=()):
        self.comments, self.requests = list(comments), []

    def __call__(self, method, url, token, payload):
        self.requests.append((method, url, token, payload))
        if method == "GET":
            return 200, self.comments
        return (201 if method == "POST" else 200), {"id": 77, "html_url": "https://github.example/c/77"}


class PostTests(unittest.TestCase):
    BODY = MARKER + "\nhello\n"

    def test_creates_a_comment_when_none_has_the_marker(self):
        fake = FakeGitHub([{"id": 1, "body": "unrelated"}])
        result = post_or_update_comment("o/r", 5, self.BODY, token="t0k", http=fake)
        self.assertEqual(result["action"], "created")
        self.assertEqual([r[0] for r in fake.requests], ["GET", "POST"])
        self.assertTrue(fake.requests[1][1].endswith("/repos/o/r/issues/5/comments"))
        self.assertEqual(fake.requests[1][3], {"body": self.BODY})

    def test_updates_the_single_existing_comment(self):
        fake = FakeGitHub([{"id": 1, "body": "unrelated"}, {"id": 9, "body": MARKER + "\nold"}])
        result = post_or_update_comment("o/r", 5, self.BODY, token="t0k", http=fake)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(fake.requests[1][0], "PATCH")
        self.assertTrue(fake.requests[1][1].endswith("/repos/o/r/issues/comments/9"))
        self.assertEqual(len(fake.requests), 2)

    def test_dry_run_sends_nothing_and_needs_no_token(self):
        fake = FakeGitHub()
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch("urllib.request.urlopen") as urlopen:
            os.environ.pop("GITHUB_TOKEN", None)
            result = post_or_update_comment("o/r", 5, self.BODY, dry_run=True, http=fake)
        self.assertEqual(result["action"], "dry-run")
        self.assertEqual(fake.requests, [])
        urlopen.assert_not_called()

    def test_missing_token_and_failures_raise(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            with self.assertRaisesRegex(RuntimeError, "GITHUB_TOKEN"):
                post_or_update_comment("o/r", 5, self.BODY, http=FakeGitHub())
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            post_or_update_comment("o/r", 5, self.BODY, token="t", http=lambda *a: (403, None))
        with self.assertRaises(ValueError):
            post_or_update_comment("o/r", 5, "no marker", token="t", http=FakeGitHub())

    def test_token_comes_from_the_environment(self):
        fake = FakeGitHub()
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "from-env"}):
            post_or_update_comment("o/r", 5, self.BODY, http=fake)
        self.assertEqual(fake.requests[0][2], "from-env")


class ConsoleTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_comment_prints_the_markdown_and_posts_nothing_by_default(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            code, out, err = self.run_cli("comment", str(DEMO_RECEIPT), "--repo", "o/r", "--pr", "3")
        self.assertEqual(code, 0)
        self.assertIn(MARKER, out)
        self.assertIn("dry-run: GET", err)
        urlopen.assert_not_called()

    def test_post_requires_repo_pr_and_token_and_uses_the_client(self):
        self.assertEqual(self.run_cli("comment", str(DEMO_RECEIPT), "--post")[0], 64)
        fake = FakeGitHub()
        with mock.patch.object(pr_comment, "_http", fake), mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}):
            code, out, _ = self.run_cli("comment", str(DEMO_RECEIPT), "--post", "--repo", "o/r", "--pr", "3")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "created")
        self.assertEqual([r[0] for r in fake.requests], ["GET", "POST"])

    def test_dry_run_wins_over_post(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            code, out, _ = self.run_cli("comment", str(DEMO_RECEIPT), "--post", "--dry-run", "--repo", "o/r", "--pr", "3")
        self.assertEqual(code, 0)
        urlopen.assert_not_called()
        self.assertIn(MARKER, out)

    def test_bad_receipt_and_unknown_command(self):
        self.assertEqual(self.run_cli("comment", "/nonexistent.json")[0], 64)
        self.assertEqual(self.run_cli("bogus")[0], 64)
        self.assertEqual(self.run_cli()[0], 64)

    def test_prove_pr_comment_writes_markdown(self):
        receipt = prove_receipt()
        with tempfile.TemporaryDirectory() as tmp, mock.patch("latch.prove.prove", return_value=receipt) as prove:
            target = Path(tmp) / "c.md"
            code, out, _ = self.run_cli("prove", "--repo", "r", "--base", "a", "--head", "b", "--issue", "i",
                                        "--receipt", str(Path(tmp) / "r.json"), "--pr-comment", str(target))
            self.assertEqual(code, 0)
            self.assertIn("✅ PROVEN", target.read_text())
            self.assertTrue(prove.called)
            self.assertEqual(json.loads(out)["proven"], True)

    def test_prove_pr_comment_dash_goes_to_stdout_and_exit_1_when_not_proven(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("latch.prove.prove", return_value=prove_receipt(False)):
            code, out, err = self.run_cli("prove", "--repo", "r", "--base", "a", "--head", "b", "--issue", "i",
                                          "--receipt", str(Path(tmp) / "r.json"), "--pr-comment", "-")
        self.assertEqual(code, 1)
        self.assertIn("❌ NOT PROVEN", out)
        self.assertIn('"proven": false', err)


class ActionFileTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def load(self, rel):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        return yaml.safe_load((self.ROOT / rel).read_text())

    def test_composite_action_never_interpolates_expressions_into_shell(self):
        action = self.load(".github/actions/latch/action.yml")
        self.assertEqual(action["runs"]["using"], "composite")
        self.assertTrue(action["inputs"]["nebius-api-key"]["required"])
        for step in action["runs"]["steps"]:
            if "run" in step:
                self.assertNotIn("${{", step["run"], step.get("name"))
                self.assertEqual(step["shell"], "bash")

    def test_example_workflow_runs_on_pull_request_and_uses_the_action_with_a_secret(self):
        flow = self.load("latch/loop/github/latch.yml")
        self.assertIn("pull_request", flow[True])  # PyYAML reads the bare key `on` as True
        self.assertEqual(flow["permissions"]["pull-requests"], "write")
        uses = [s for s in flow["jobs"]["latch"]["steps"] if "latch/.github/actions/latch" in s.get("uses", "")]
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0]["with"]["nebius-api-key"], "${{ secrets.NEBIUS_API_KEY }}")


if __name__ == "__main__":
    unittest.main()
