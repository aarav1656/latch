"""Offline tests: an eval run on a dev provider (openrouter) writes only under latch/runs/dev/, marked dev_only. No network, no models."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch import provider as providers
from latch.loop.eval import run_eval
from latch.loop.eval.cases import CASES

NOTE = "Dev-only run via OpenRouter free tier; not Nebius Token Factory numbers."


def clean_env(**kw):
    env = {k: v for k, v in os.environ.items() if k not in ("LATCH_PROVIDER", "OPENROUTER_API_KEY", "NEBIUS_API_KEY")}
    env.update(kw)
    return mock.patch.dict(os.environ, env, clear=True)


def fake_row(case, variant, provider):
    return {"case": case["id"], "variant": variant, "label": variant, "outcome": "proven" if variant == "real" else "shut_gave_up",
            "verdict": "gate_open" if variant == "real" else "gave_up", "reason": "r", "wall_seconds": 1.0, "provider": provider,
            "receipt": None, "iterations_used": 0, "completion_ids": {}}


class EvalDevRoutingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        self.case = next(c for c in CASES if not c.get("swe"))
        for patch in (mock.patch.object(run_eval, "REPO_ROOT", self.root), mock.patch.object(run_eval, "ROOT", Path(self._tmp.name) / "evalroot"),
                      mock.patch.object(run_eval, "base_sha", return_value="b" * 40), mock.patch.object(run_eval, "links", return_value={}),
                      mock.patch.object(run_eval, "oracle_files", return_value=[]), mock.patch.object(run_eval, "test_command", return_value="pytest"),
                      mock.patch.object(run_eval, "run_one", side_effect=lambda c, v, n, d: fake_row(c, v, providers.current()))):
            patch.start()
            self.addCleanup(patch.stop)

    def runs_files(self):
        runs = self.root / "latch" / "runs"
        return sorted(str(p.relative_to(runs)) for p in runs.rglob("*") if p.is_file()) if runs.exists() else []

    def run_main(self, *extra):
        with mock.patch("sys.stderr"), mock.patch("builtins.print"):
            return run_eval.main(["run", "--only", self.case["id"], "--skip-validate", "--jobs", "1", *extra])

    def test_openrouter_run_writes_only_under_runs_dev_and_marks_dev_only(self):
        with clean_env(LATCH_PROVIDER="openrouter"):
            self.assertEqual(self.run_main(), 0)
        files = self.runs_files()
        self.assertTrue(files)
        self.assertTrue(all(f.startswith("dev/") for f in files), files)
        self.assertIn("dev/eval-summary-openrouter.json", files)
        self.assertIn("dev/eval-report-openrouter.md", files)
        self.assertFalse((self.root / "latch" / "runs" / "eval-summary.json").exists())
        self.assertFalse((self.root / "latch" / "runs" / "eval").exists())
        summary = json.loads((self.root / "latch" / "runs" / "dev" / "eval-summary-openrouter.json").read_text())
        self.assertEqual((summary["provider"], summary["dev_only"], summary["note"]), ("openrouter", True, NOTE))
        self.assertEqual(summary["models"]["triage"], "nvidia/nemotron-3.5-lightning:free")
        self.assertIn("openrouter", (self.root / "latch" / "runs" / "dev" / "eval-report-openrouter.md").name)
        doc = json.loads(next(p for p in (self.root / "latch" / "runs" / "dev").glob("eval-20*-openrouter.json")).read_text())
        self.assertEqual((doc["provider"], doc["dev_only"], doc["note"]), ("openrouter", True, NOTE))
        self.assertEqual({r["provider"] for r in doc["runs"]}, {"openrouter"})

    def test_nebius_run_keeps_the_public_paths(self):
        with clean_env():
            self.assertEqual(self.run_main(), 0)
        files = self.runs_files()
        self.assertIn("eval-summary.json", files)
        self.assertIn("eval-report.md", files)
        self.assertFalse(any(f.startswith("dev/") for f in files), files)
        summary = json.loads((self.root / "latch" / "runs" / "eval-summary.json").read_text())
        self.assertEqual(summary["provider"], "nebius")
        self.assertNotIn("dev_only", summary)

    def test_openrouter_cannot_be_pointed_at_a_public_path(self):
        with clean_env(LATCH_PROVIDER="openrouter"):
            for flag in ("latch/runs/eval-2026.json", str(self.root / "latch" / "runs" / "eval-summary.json")):
                with self.assertRaisesRegex(ValueError, "dev-only"):
                    self.run_main("--out", flag)
            doc = {"provider": "openrouter", "runs": [], "date": "d"}
            with self.assertRaisesRegex(ValueError, "dev-only"):
                run_eval.write_eval_summary(doc, path=self.root / "latch" / "runs" / "eval-summary.json")
            with self.assertRaisesRegex(ValueError, "dev-only"):
                run_eval.publish_receipts(doc, dest=self.root / "latch" / "runs" / "eval")
        self.assertEqual(self.runs_files(), [])

    def test_summarize_follows_the_documents_provider_not_the_environment(self):
        doc = {"provider": "openrouter", "dev_only": True, "date": "d", "runs": [], "models": {}, "summary": {"dropped_cases": []}}
        with clean_env():  # env says nebius, the document says openrouter: still dev-only
            with mock.patch("sys.stderr"):
                run_eval.write_eval_summary(doc, [])
        self.assertEqual(self.runs_files(), ["dev/eval-report-openrouter.md", "dev/eval-summary-openrouter.json"])


if __name__ == "__main__":
    unittest.main()


class RunOneReceiptShapeTests(unittest.TestCase):
    """run_one must cope with a receipt whose "triage" is still the model id (a str): the loop stops before triage when the head already passes."""

    def row_for(self, triage):
        case = next(c for c in CASES if not c.get("swe"))
        receipt = {"gate": "gate_open", "verdict": "VALIDATED", "reason": "r", "provider": "openrouter", "triage": triage,
                   "proof_test": {"completion_id": "gen-1", "name": "t"}, "iterations": [], "model_calls": [], "initial": {}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(run_eval, "run_loop", return_value=receipt), mock.patch.object(run_eval, "clone_dir", return_value=Path(tmp)), \
                mock.patch.object(run_eval, "base_sha", return_value="b" * 40), mock.patch.object(run_eval, "issue_text", return_value="issue"), \
                mock.patch.object(run_eval, "test_command", return_value="pytest"), \
                mock.patch.object(run_eval, "oracle_check", return_value={"oracle_pass": True}):
            return run_eval.run_one(case, "real", 1, tmp)

    def test_triage_model_id_string_does_not_crash(self):
        row = self.row_for("nvidia/Nemotron-3_5-Lightning")
        self.assertIsNone(row["completion_ids"]["triage"])
        self.assertEqual(row["completion_ids"]["proof_test"], "gen-1")

    def test_triage_none_and_dict(self):
        self.assertIsNone(self.row_for(None)["triage_verdict"])
        row = self.row_for({"completion_id": "gen-9", "verdict": "reproduced"})
        self.assertEqual((row["completion_ids"]["triage"], row["triage_verdict"]), ("gen-9", "reproduced"))


class SummaryTriageShapeTests(unittest.TestCase):
    def test_gave_up_receipt_with_triage_model_id_string(self):
        from latch.loop.eval.fixture import make_fixture
        from latch.loop.eval.summary import build_summary

        cases = [c for c in CASES if not c.get("swe")][:1]
        doc, receipts = make_fixture(cases)
        stub = {k: dict(v, triage="nvidia/Nemotron-3_5-Lightning") if isinstance(v, dict) else v for k, v in receipts.items()}
        for row in doc["runs"]:
            row.update(outcome="gave_up", verdict="gave_up")
        summary = build_summary(doc, CASES, stub.get, dropped=[], root=Path("."), mode="dry-run")
        self.assertTrue(summary)
