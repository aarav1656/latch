"""Offline tests: `--tag` writes a second eval run beside the first and never over it; the test-repair flag reaches run_one; the diff."""

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch import provider as providers
from latch.loop.eval import run_eval
from latch.loop.eval.cases import CASES
from latch.loop.eval.rundiff import diff_summaries, render_diff
from latch.loop.eval.test_provider_dev import clean_env, fake_row


class TagLayoutTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "latch" / "runs").mkdir(parents=True)
        self.case = next(c for c in CASES if not c.get("swe"))
        self.seen = []

        def fake_run_one(c, v, n, d, test_repair=True):
            self.seen.append((c["id"], v, test_repair, str(d)))
            row = fake_row(c, v, providers.current())
            Path(d).mkdir(parents=True, exist_ok=True)
            (Path(d) / f"{c['id']}.{v}.json").write_text("{}")
            row["receipt"] = str(Path(d) / f"{c['id']}.{v}.json")
            row["test_repair"] = {"attempted": v == "real", "side": "base", "outcome": "adopted", "ok": True, "error_before": "E NameError"}
            return row

        for patch in (mock.patch.object(run_eval, "REPO_ROOT", self.root), mock.patch.object(run_eval, "ROOT", Path(self._tmp.name) / "evalroot"),
                      mock.patch.object(run_eval, "base_sha", return_value="b" * 40), mock.patch.object(run_eval, "links", return_value={}),
                      mock.patch.object(run_eval, "oracle_files", return_value=[]), mock.patch.object(run_eval, "test_command", return_value="pytest"),
                      mock.patch.object(run_eval, "run_one", side_effect=fake_run_one)):
            patch.start()
            self.addCleanup(patch.stop)
        self.date = datetime.date.today().isoformat()
        self.runs = self.root / "latch" / "runs"

    def run_main(self, *extra):
        with mock.patch("sys.stderr"), mock.patch("builtins.print"):
            return run_eval.main(["run", "--only", self.case["id"], "--skip-validate", "--jobs", "1", *extra])

    def seed_first_run(self):
        sentinels = {self.runs / f"eval-{self.date}.json": "FIRST-DOC", self.runs / "eval-summary.json": "FIRST-SUMMARY",
                     self.runs / "eval-report.md": "FIRST-REPORT", self.runs / "eval" / "x-real.json": "FIRST-RECEIPT"}
        for path, text in sentinels.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return sentinels

    def test_tagged_run_writes_beside_the_first_run_and_never_touches_it(self):
        sentinels = self.seed_first_run()
        with clean_env():
            self.assertEqual(self.run_main("--tag", "repair"), 0)
        for path, text in sentinels.items():
            self.assertEqual(path.read_text(), text, path)
        for name in (f"eval-{self.date}-repair.json", "eval-summary-repair.json", "eval-report-repair.md", "eval-repair/" + f"{self.case['id']}-real.json"):
            self.assertTrue((self.runs / name).exists(), name)
        self.assertEqual(sorted(p.name for p in (self.runs / "eval").iterdir()), ["x-real.json"])
        doc = json.loads((self.runs / f"eval-{self.date}-repair.json").read_text())
        self.assertEqual((doc["tag"], doc["test_repair_enabled"]), ("repair", True))
        self.assertTrue(all(str(r["receipt"]).startswith("latch/runs/eval-repair/") for r in doc["runs"]))
        summary = json.loads((self.runs / "eval-summary-repair.json").read_text())
        self.assertEqual(summary["run"], {"date": self.date, "tag": "repair", "label": "repair", "test_repair_enabled": True})
        self.assertEqual(summary["test_repair"]["attempted"], 1)
        self.assertEqual(summary["test_repair"]["ok"], 1)
        self.assertTrue(all("evalroot" in d and d.endswith(f"{self.date}-repair") for *_, d in self.seen))

    def test_an_untagged_run_refuses_to_replace_a_finished_run(self):
        sentinels = self.seed_first_run()
        with clean_env():
            with self.assertRaisesRegex(SystemExit, "already exists"):
                self.run_main()
        for path, text in sentinels.items():
            self.assertEqual(path.read_text(), text)
        self.assertEqual(self.seen, [])

    def test_untagged_first_run_still_uses_the_original_names(self):
        with clean_env():
            self.assertEqual(self.run_main(), 0)
        self.assertTrue((self.runs / "eval-summary.json").exists() and (self.runs / "eval-report.md").exists())
        self.assertTrue((self.runs / f"eval-{self.date}.json").exists())
        self.assertIsNone(json.loads((self.runs / "eval-summary.json").read_text())["run"]["tag"])

    def test_bad_tags_are_refused(self):
        with clean_env():
            for tag in ("../x", "Repair", "a b", ""):
                if tag:
                    with self.assertRaises(SystemExit):
                        self.run_main("--tag", tag)

    def test_no_test_repair_reaches_every_run_and_the_doc(self):
        with clean_env():
            self.assertEqual(self.run_main("--tag", "off", "--no-test-repair"), 0)
        self.assertTrue(self.seen and all(flag is False for _, _, flag, _ in self.seen))
        self.assertFalse(json.loads((self.runs / f"eval-{self.date}-off.json").read_text())["test_repair_enabled"])

    def test_default_has_the_repair_on(self):
        with clean_env():
            self.run_main("--tag", "on")
        self.assertTrue(all(flag is True for _, _, flag, _ in self.seen))

    def test_summarize_on_a_tagged_doc_writes_the_tagged_files(self):
        doc = {"provider": "nebius", "date": "2026-10-30", "tag": "repair", "runs": [], "models": {}, "summary": {"dropped_cases": []}}
        with clean_env(), mock.patch("sys.stderr"):
            run_eval.write_eval_summary(doc, [])
        self.assertEqual(sorted(p.name for p in self.runs.iterdir()), ["eval-report-repair.md", "eval-summary-repair.json"])

    def test_dev_provider_tag_stays_under_dev(self):
        with clean_env(LATCH_PROVIDER="openrouter"):
            self.assertEqual(self.run_main("--tag", "repair"), 0)
        files = sorted(str(p.relative_to(self.runs)) for p in self.runs.rglob("*") if p.is_file())
        self.assertTrue(files and all(f.startswith("dev/") for f in files), files)
        self.assertIn("dev/eval-summary-openrouter-repair.json", files)
        self.assertIn("dev/eval-report-openrouter-repair.md", files)

    def test_paths_for_the_documented_layout(self):
        paths = run_eval.run_paths("2026-10-30", "nebius", "repair")
        rel = {k: str(Path(v).relative_to(run_eval.REPO_ROOT)) for k, v in paths.items() if k != "receipts"}
        self.assertEqual(rel, {"out": "latch/runs/eval-2026-10-30-repair.json", "publish": "latch/runs/eval-repair",
                               "summary": "latch/runs/eval-summary-repair.json", "report": "latch/runs/eval-report-repair.md"})
        first = run_eval.run_paths("2026-10-30", "nebius", None)
        self.assertEqual(str(Path(first["summary"]).relative_to(run_eval.REPO_ROOT)), "latch/runs/eval-summary.json")
        self.assertNotEqual(first["receipts"], paths["receipts"])


class DiffTests(unittest.TestCase):
    def summary(self, verdict, tag, repair=None):
        return {"run": {"date": "2026-10-30", "tag": tag, "label": tag or "first", "test_repair_enabled": bool(tag)}, "latch_git_sha": "abc",
                "verdicts": {"INVALID_TEST": 1 if verdict == "INVALID_TEST" else 0},
                "wrong_fixes": {"caught_by_valid_test": {"caught": 3}, "false_accepts": ["packaging-810"]},
                "benchmark": {"cost_usd": 1.38}, "test_repair": {"attempted": 1 if repair else 0, "ok": 1 if repair else 0},
                "cases": [{"case": "c1", "variant": "real", "status": "ran", "verdict": verdict, "outcome": "proven" if verdict == "VALIDATED" else "gave_up",
                           "receipt": "latch/runs/eval/c1-real.json", "test_repair": repair}]}

    def test_before_after_pairs_and_changed_flag(self):
        diff = diff_summaries(self.summary("INVALID_TEST", None), self.summary("VALIDATED", "repair", {"attempted": True, "outcome": "adopted"}),
                              "eval-summary.json", "eval-summary-repair.json")
        self.assertEqual(diff["headline"]["real_validated"], {"before": "0/1", "after": "1/1"})
        self.assertEqual(diff["headline"]["invalid_test"], {"before": 1, "after": 0})
        case = diff["cases"][0]
        self.assertEqual((case["verdict_before"], case["verdict_after"], case["changed"], case["test_repair"]), ("INVALID_TEST", "VALIDATED", True, "adopted"))
        text = render_diff(diff)
        self.assertIn("INVALID_TEST | VALIDATED *", text)
        self.assertIn("eval-summary-repair.json", text)
        json.dumps(diff)


if __name__ == "__main__":
    unittest.main()
