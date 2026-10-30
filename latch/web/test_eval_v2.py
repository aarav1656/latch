"""Eval summary schema v2 and the hard rules about what the site may show.

1. The oracle answer key (latch/runs/eval-oracle-baseline.*) is never shown as a Latch or Nemotron result.
2. latch/runs/eval-dryrun/ and latch/runs/dev/ are never read, and never reach the Docker image.
3. A receipt or summary with dev_only=true, or a provider other than Token Factory / Nebius, is rejected.
4. The site reads these paths from latch/runs/, none by glob.
"""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch.web import app as web_app
from latch.web import provenance, store
from latch.web.test_app import Harness, receipt
from latch.web.test_verdict import BASE, STATIC, seed, verdict_receipt

WEB = Path(__file__).parent
SIX = ("INVALID_TEST", "FLAKY", "NO_REGRESSION_FOUND", "FIX_FAILS_TEST", "MUTATION_SURVIVED", "VALIDATED")
SHA = "0cfb12e" + "a" * 33


def v2_summary(**over):
    verdicts = {c: 0 for c in SIX}
    verdicts.update({"FIX_FAILS_TEST": 2, "VALIDATED": 1})
    summary = {
        "schema_version": 2, "mode": "live", "fixture": False, "latch_git_sha": SHA,
        "featured_wrong_fix_receipt": "latch/runs/eval/wrong.json",
        "verdicts": verdicts,
        "flaky": {"n_cases_checked": 3, "n_flaky": 0, "median_flake_rate": 0.0},
        "benchmark": {"runs": 3, "errors": 0, "not_run": 1,
                      "real_validated": {"k": 1, "n": 1, "rate": 1.0},
                      "wrong_patch_rejection": {"k": 2, "n": 2, "rate": 1.0, "without_contested": {"k": 1, "n": 1, "rate": 1.0}},
                      "nofix_gate_open": {"k": 0, "n": 0, "rate": None},
                      "gate_accepted_but_oracle_fails": {"n": 0, "cases": [], "note": ""},
                      "mutation": {"runs_with_data": 1, "mutants_killed": 5, "mutants_total": 6, "pooled_kill_rate": 0.833, "mean_kill_rate": 0.833}},
        "slopgate_comparison": {"slopgate": {}, "latch": {}, "caveat": "different tasks"},
        "oracle_baseline": {"n": 21, "passed": 21, "note": "no-model answer key"},
        "manifest": {"path": "latch/loop/eval/manifest.json"},
        "dropped_cases": [{"id": "sympy-9999", "reason": "dataset row failed the validator"}],
        "cases": [
            {"case": "wrong-1", "variant": "wrong", "status": "ran", "outcome": "rejected", "verdict": "FIX_FAILS_TEST", "verdict_source": "derived",
             "verdict_reason": "the proof test fails on the change under test too", "loop_verdict": "gave_up", "flaky": None, "mutation": None},
            {"case": "real-1", "variant": "real", "status": "ran", "outcome": "proven", "verdict": "VALIDATED", "verdict_source": "receipt",
             "verdict_reason": "red on base, green on head", "loop_verdict": "gate_open", "flaky": None, "mutation": {"killed": 5, "total": 6, "kill_rate": 0.833}},
            {"case": "real-2", "variant": "real", "status": "not run", "verdict": None, "verdict_reason": None, "loop_verdict": None, "flaky": None, "mutation": None},
        ],
    }
    summary.update(over)
    return summary


class RunsRoot:
    """A throwaway repo root with latch/runs/ in it, wired in through LATCH_EVAL_ROOT."""

    def __init__(self, test, summary=None, featured=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runs = self.root / "latch" / "runs"
        for sub in ("eval", "eval-dryrun", "dev"):
            (self.runs / sub).mkdir(parents=True)
        if summary is not None:
            (self.runs / "eval-summary.json").write_text(json.dumps(summary))
        if featured is not None:
            (self.runs / "eval" / "wrong.json").write_text(json.dumps(featured))
        patcher = mock.patch.dict(os.environ, {"LATCH_EVAL_ROOT": tmp.name})
        patcher.start()
        test.addCleanup(patcher.stop)


class SchemaV2Tests(unittest.TestCase):
    def test_v2_fields_reach_the_page_and_the_oracle_answer_key_does_not(self):
        RunsRoot(self, v2_summary(), verdict_receipt("FIX_FAILS_TEST"))
        body = Harness(self).get_json("/api/eval")[1]
        s = body["summary"]
        self.assertTrue(body["available"])
        self.assertEqual(s["verdicts"]["FIX_FAILS_TEST"], 2)
        self.assertEqual(s["latch_git_sha"], SHA)
        self.assertEqual(s["dropped_cases"], [{"id": "sympy-9999", "reason": "dataset row failed the validator"}])
        self.assertEqual(s["cases"][0]["loop_verdict"], "gave_up")
        self.assertEqual(s["cases"][0]["verdict_source"], "derived")
        self.assertNotIn("oracle_baseline", s)
        self.assertEqual(body["featured"]["meta"]["verdict_code"], "FIX_FAILS_TEST")

    def test_the_eval_script_renders_the_v2_fields_and_keeps_v1_support(self):
        js = (STATIC / "eval.js").read_text()
        for needle in ("s.verdicts", "latch_git_sha", "dropped_cases", "loop_verdict", "verdict_source", "derived from the receipt",
                       "benchmarkSection", "provenanceSection", "pooled_kill_rate", "bd.counts"):
            self.assertIn(needle, js, needle)
        # v1 put the loop's result in `verdict`; a value that is not one of the six falls back to the outcome text
        self.assertIn("VERDICTS[c.verdict]", js)
        # Slopgate's numbers measure a different task and are third-party; the page does not show them
        self.assertNotIn("slopgate", js.lower())

    def test_a_dry_run_or_fixture_summary_is_never_a_result(self):
        for over in ({"mode": "dry-run", "fixture": True}, {"fixture": True}, {"mode": "dry-run"}):
            RunsRoot(self, v2_summary(**over), verdict_receipt("FIX_FAILS_TEST"))
            body = Harness(self).get_json("/api/eval")[1]
            self.assertEqual(body["available"], False, over)
            self.assertNotIn("summary", body)

    def test_a_v1_summary_still_loads(self):
        v1 = {"schema_version": 1, "cases": [{"case": "a", "variant": "wrong", "status": "ran", "verdict": "gave_up", "outcome": "rejected"}]}
        RunsRoot(self, v1)
        body = Harness(self).get_json("/api/eval")[1]
        self.assertEqual(body["summary"], v1)


class OracleBaselineTests(unittest.TestCase):
    """HARD RULE 1: the no-model answer key is not a result. The site does not read it, serve it or draw it."""

    def test_no_server_code_reads_the_oracle_baseline_files(self):
        for path in WEB.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            self.assertNotIn("eval-oracle-baseline", path.read_text(), path.name)

    def test_no_page_or_script_mentions_the_oracle_baseline(self):
        for path in list(STATIC.glob("*")):
            if path.suffix in (".js", ".html", ".css"):
                text = path.read_text().lower()
                for needle in ("oracle_baseline", "oracle-baseline", "answer key", "upper bound by construction"):
                    self.assertNotIn(needle, text, f"{path.name}: {needle}")

    def test_the_api_strips_the_oracle_baseline_from_the_summary(self):
        RunsRoot(self, v2_summary(oracle_baseline={"n": 21, "passed": 21}), verdict_receipt("FIX_FAILS_TEST"))
        body = Harness(self).get_json("/api/eval")[1]
        self.assertNotIn("oracle_baseline", body["summary"])
        self.assertNotIn("oracle_baseline", json.dumps(body))

    def test_the_oracle_files_are_never_in_the_image(self):
        ignore = (WEB / "Dockerfile.dockerignore").read_text().splitlines()
        self.assertIn("latch/runs/eval-oracle-baseline.*", ignore)
        self.assertNotIn("!latch/runs/eval-oracle-baseline.json", ignore)


class DevOutputTests(unittest.TestCase):
    """HARD RULE 2: latch/runs/eval-dryrun/ and latch/runs/dev/ are never read, never shipped."""

    def test_is_dev_path(self):
        for bad in ("latch/runs/dev/x.json", "/repo/latch/runs/eval-dryrun/eval-summary.json", "latch/runs/eval-dryrun", "latch/runs/dev",
                    "/r/latch/runs/Dev/x.json", "latch/runs/eval-dryrun-2/x.json"):
            self.assertTrue(provenance.is_dev_path(bad), bad)
        for good in ("latch/runs/eval/wrong.json", "latch/runs/eval-summary.json", "latch/runs/click-3298.json", "/home/dev/app/.data/receipts/a.json"):
            self.assertFalse(provenance.is_dev_path(good), good)

    def test_the_featured_receipt_cannot_point_into_dev_or_dryrun(self):
        for sub in ("dev", "eval-dryrun"):
            root = RunsRoot(self, v2_summary(featured_wrong_fix_receipt=f"latch/runs/{sub}/wrong.json"))
            (root.runs / sub / "wrong.json").write_text(json.dumps(verdict_receipt("FIX_FAILS_TEST")))
            body = Harness(self).get_json("/api/eval")[1]
            self.assertTrue(body["available"])
            self.assertIsNone(body["featured"], sub)

    def test_serving_the_eval_page_opens_no_file_under_dev_or_dryrun(self):
        root = RunsRoot(self, v2_summary(), verdict_receipt("FIX_FAILS_TEST"))
        (root.runs / "dev" / "x.json").write_text("{}")
        (root.runs / "eval-dryrun" / "eval-summary.json").write_text(json.dumps(v2_summary(mode="dry-run")))
        opened = []
        real = Path.read_text

        def spy(self, *a, **k):
            opened.append(str(self))
            return real(self, *a, **k)

        with mock.patch.object(Path, "read_text", spy):
            h = Harness(self)
            h.get_json("/api/eval")
            h.get_json("/api/recent")
        touched = [p for p in opened if provenance.is_dev_path(p)]
        self.assertEqual(touched, [])

    def test_a_seed_receipt_under_runs_dev_is_not_loaded(self):
        root = RunsRoot(self)
        path = root.runs / "dev" / "click.json"
        path.write_text(json.dumps(receipt(BASE, "1" * 40)))
        self.assertIsNone(store.Store(root.root / "data", seed_receipt_path=path).example)

    def test_the_docker_context_excludes_dev_and_dryrun_output(self):
        ignore = (WEB / "Dockerfile.dockerignore").read_text().splitlines()
        for rule in ("latch/runs/dev", "latch/runs/dev/**", "latch/runs/eval-dryrun", "latch/runs/eval-dryrun/**"):
            self.assertIn(rule, ignore)
        self.assertIn("**", ignore)
        whitelist = [line for line in ignore if line.startswith("!latch/runs")]
        self.assertEqual(sorted(whitelist), sorted(["!latch/runs/click-3298.json", "!latch/runs/loop-demo-events.jsonl", "!latch/runs/eval-summary.json", "!latch/runs/eval/**"]))
        # the exclusions come after the whitelist, so they win
        self.assertGreater(ignore.index("latch/runs/dev"), max(ignore.index(line) for line in whitelist))

    def test_gitignore_keeps_dryrun_output_out_of_the_repo(self):
        text = (WEB.parent.parent / ".gitignore").read_text()
        self.assertIn("latch/runs/eval-dryrun/", text)


class ProviderTests(unittest.TestCase):
    """HARD RULE 2 (cont.): dev_only=true or a provider other than tokenfactory/nebius is rejected from the gallery and eval."""

    def test_is_dev_output(self):
        for bad in ({"dev_only": True}, {"provider": "openrouter"}, {"provider": "OpenRouter"}, {"provider": {"name": "x"}},
                    {"meta": {"provider": "openrouter"}}, {"receipt": {"dev_only": True}},
                    {"receipt": {"model_calls": [{"provider": "tokenfactory"}, {"provider": "openrouter"}]}},
                    {"cases": [{"case": "a"}, {"case": "b", "dev_only": True}]}):
            self.assertTrue(provenance.is_dev_output(bad), bad)
        for good in ({}, {"provider": "tokenfactory"}, {"provider": "Nebius"}, {"provider": "token_factory"}, {"provider": None},
                     {"dev_only": False, "provider": "nebius"}, {"receipt": {"model_calls": [{"provider": "nebius"}]}}, None, []):
            self.assertFalse(provenance.is_dev_output(good), good)

    def test_the_gallery_and_permalinks_skip_dev_receipts(self):
        h = Harness(self)
        seed(h, 61)  # a normal receipt, no provider recorded
        seed(h, 62, "VALIDATED", provider="tokenfactory")
        seed(h, 63, "VALIDATED", provider="openrouter")
        seed(h, 64, "VALIDATED", dev_only=True)
        listed = {i["number"] for i in h.get_json("/api/recent")[1]["items"]}
        self.assertTrue({61, 62} <= listed)
        self.assertFalse({63, 64} & listed)
        for number in (63, 64):
            self.assertIsNone(h.service.store.get_pr("acme/widgets", number))

    def test_eval_rejects_a_dev_summary_a_dev_case_and_a_dev_featured_receipt(self):
        RunsRoot(self, v2_summary(provider="openrouter"), verdict_receipt("FIX_FAILS_TEST"))
        self.assertEqual(Harness(self).get_json("/api/eval")[1]["available"], False)
        RunsRoot(self, v2_summary(dev_only=True), verdict_receipt("FIX_FAILS_TEST"))
        self.assertEqual(Harness(self).get_json("/api/eval")[1]["available"], False)
        dev_case = v2_summary()
        dev_case["cases"][1]["provider"] = "openrouter"
        RunsRoot(self, dev_case, verdict_receipt("FIX_FAILS_TEST"))
        self.assertEqual(Harness(self).get_json("/api/eval")[1]["available"], False)
        RunsRoot(self, v2_summary(), verdict_receipt("FIX_FAILS_TEST", provider="openrouter"))
        body = Harness(self).get_json("/api/eval")[1]
        self.assertTrue(body["available"])
        self.assertIsNone(body["featured"])
        RunsRoot(self, v2_summary(), verdict_receipt("FIX_FAILS_TEST", provider="nebius"))
        self.assertIsNotNone(Harness(self).get_json("/api/eval")[1]["featured"])

    def test_a_dev_loop_demo_is_not_served(self):
        h = Harness(self)
        events = [{"type": "start"}, {"type": "gate_open", "provider": "openrouter"}]
        text = "\n".join(json.dumps(e) for e in events)
        with mock.patch.object(Path, "read_text", lambda self, *a, **k: text):
            self.assertIsNone(h.service.loop_example())


class PathsTests(unittest.TestCase):
    """HARD RULE 3: every read of latch/runs/ is a fixed path. Nothing globs, lists or walks it."""

    READS = {
        "app.py": {"latch/runs/click-3298.json", "latch/runs/eval-summary.json", "latch/runs/eval"},
        "service.py": {"latch/runs/loop-demo-events.jsonl"},
    }

    def test_the_site_reads_a_fixed_list_of_paths_from_runs(self):
        found = {}
        for path in WEB.glob("*.py"):
            if path.name.startswith("test_") or path.name == "provenance.py":
                continue
            text = path.read_text()
            hits = set(re.findall(r'"latch"\s*/\s*"runs"\s*/\s*"([^"]+)"', text))
            if hits:
                found[path.name] = {"latch/runs/" + h for h in hits}
        self.assertEqual(found, self.READS)

    def test_nothing_globs_lists_or_walks_the_runs_directory(self):
        for path in WEB.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"\.(glob|rglob|iterdir|scandir)\(|os\.(listdir|walk)\(", line):
                    # the only directory listings: the receipt cache in the data dir, and /proc for the sandbox
                    self.assertTrue('"receipts"' in line or "/proc" in line, f"{path.name}:{n}: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
