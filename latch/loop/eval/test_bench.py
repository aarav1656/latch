"""Offline tests for the benchmark layer: named verdicts, metrics, totals, the summary contract, the report, the dry run, the oracle
baseline and the manifest. Fixtures only: no models, no network, no git clones."""

import json
import tempfile
import unittest
from pathlib import Path

from latch.loop.eval import bench, compare, fixture, manifest, oracle, report
from latch.loop.eval.cases import CASES, DROPPED
from latch.loop.eval.cli import main as eval_main, run_dry
from latch.loop.eval.summary import SCHEMA_VERSION, build_summary
from latch.verdict import VERDICTS


def red(name="test_x"):
    return {"returncode": 1, "output": f"___ {name} ___\nE   AssertionError: boom\n1 failed"}


GREEN = {"returncode": 0, "output": "1 passed"}


def receipt(base=None, head=None, suite=GREEN, **extra):
    r = {"proof_test": {"name": "test_x"}, "initial": {"base_proof": base or red(), "head_proof": head or GREEN, "head_suite": suite,
                                                       "base_red": (base or red())["returncode"] != 0,
                                                       "head_suite_green": suite["returncode"] == 0}, "verdict": "gate_open"}
    r.update(extra)
    return r


class NamedVerdictTests(unittest.TestCase):
    def test_validated_when_red_green_suite_ok_and_revert_ok(self):
        v, reason, source = bench.named_verdict(receipt(revert_check={"ok": True, "summary": "ok"}))
        self.assertEqual((v, source), ("VALIDATED", "derived"))
        self.assertTrue(reason)

    def test_head_still_red_is_fix_fails_test(self):
        self.assertEqual(bench.named_verdict(receipt(head=red()))[0], "FIX_FAILS_TEST")

    def test_passing_on_base_is_no_regression_found(self):
        self.assertEqual(bench.named_verdict(receipt(base=GREEN, head=None))[0], "NO_REGRESSION_FOUND")

    def test_failing_without_an_assertion_is_invalid_test(self):
        crash = {"returncode": 2, "output": "ImportError: no module named nothing\n"}
        self.assertEqual(bench.named_verdict(receipt(base=crash))[0], "INVALID_TEST")

    def test_flaky_receipt_wins_over_everything_below_it(self):
        flaky = {"ran": True, "runs": 5, "flaky": True, "flake_rate": 0.2}
        self.assertEqual(bench.named_verdict(receipt(flaky=flaky))[0], "FLAKY")

    def test_receipt_verdict_is_used_when_present(self):
        v, _, source = bench.named_verdict({"verdict": "MUTATION_SURVIVED", "verdict_reason": "r"})
        self.assertEqual((v, source), ("MUTATION_SURVIVED", "receipt"))

    def test_error_or_no_proof_test_has_no_verdict(self):
        self.assertEqual(bench.named_verdict({"verdict": "error"}), (None, None, None))
        self.assertEqual(bench.named_verdict({}), (None, None, None))


class MetricTests(unittest.TestCase):
    def test_kill_rate_prefers_mutation_then_revert_check(self):
        self.assertEqual(bench.kill_rate({"mutation": {"killed": 3, "total": 4, "kill_rate": 0.75}}), (3, 4, 0.75, "mutation"))
        rc = {"revert_check": {"mutants": [{"failed_as_expected": True}, {"failed_as_expected": False}]}}
        self.assertEqual(bench.kill_rate(rc), (1, 2, 0.5, "revert_check"))
        self.assertEqual(bench.kill_rate({}), (None, None, None, None))

    def test_token_totals_sum_calls_and_roles(self):
        calls = [{"role": "fixer", "prompt_tokens": 10, "completion_tokens": 2, "cost_usd": 0.5},
                 {"role": "fixer", "prompt_tokens": 5, "completion_tokens": 1, "cost_usd": 0.25}, {"role": "triage", "prompt_tokens": 1}]
        t = bench.token_totals({"model_calls": calls})
        self.assertEqual((t["prompt_tokens"], t["completion_tokens"], t["calls"]), (16, 3, 3))
        self.assertEqual(t["by_role"]["fixer"]["calls"], 2)
        self.assertEqual(bench.token_totals({})["prompt_tokens"], None)

    def test_case_metrics_contract_keys(self):
        r = receipt(revert_check={"ok": True, "mutants": [{"failed_as_expected": True}]}, flaky={"ran": True, "flaky": False, "flake_rate": 0.0})
        m = bench.case_metrics("real", {"outcome": "proven", "wall_seconds": 12.0}, r)
        self.assertEqual(m["verdict"], "VALIDATED")
        self.assertEqual(m["mutation"], {"killed": 1, "total": 1, "kill_rate": 1.0})
        self.assertEqual(m["flaky"], r["flaky"])
        self.assertTrue(m["fail_to_pass"])
        self.assertEqual(m["wall_s"], 12.0)

    def test_wrong_patch_rejected_flag(self):
        self.assertTrue(bench.case_metrics("wrong", {"outcome": "shut_gave_up"}, {})["wrong_patch_rejected"])
        self.assertFalse(bench.case_metrics("wrong", {"outcome": "false_accept"}, {})["wrong_patch_rejected"])
        self.assertIsNone(bench.case_metrics("wrong", {"outcome": "error"}, {})["wrong_patch_rejected"])

    def test_verdict_counts_cover_all_six_and_skip_errors(self):
        rows = [{"status": "ran", "outcome": "proven", "verdict": "VALIDATED"}, {"status": "ran", "outcome": "proven", "verdict": "VALIDATED"},
                {"status": "ran", "outcome": "error", "verdict": None}, {"status": "not run", "verdict": None}]
        counts = bench.verdict_counts(rows)
        self.assertEqual(set(counts), set(VERDICTS))
        self.assertEqual(counts["VALIDATED"], 2)
        self.assertEqual(sum(counts.values()), 2)

    def test_flaky_totals(self):
        rows = [{"status": "ran", "flaky": {"ran": True, "flaky": True, "flake_rate": 0.4}},
                {"status": "ran", "flaky": {"ran": True, "flaky": False, "flake_rate": 0.0}},
                {"status": "ran", "flaky": {"ran": True, "flaky": False, "flake_rate": 0.2}},
                {"status": "ran", "flaky": {"ran": False}}, {"status": "ran", "flaky": None}]
        self.assertEqual(bench.flaky_totals(rows), {"n_cases_checked": 3, "n_flaky": 1, "median_flake_rate": 0.2})
        self.assertEqual(bench.flaky_totals([]), {"n_cases_checked": 0, "n_flaky": 0, "median_flake_rate": None})


class FixtureSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc, cls.receipts = fixture.make_fixture(CASES)
        cls.summary = build_summary(doc, CASES, cls.receipts.get, dropped=DROPPED, mode="dry-run", latch_git_sha="abc")

    def test_schema_and_mode(self):
        s = self.summary
        self.assertEqual(s["schema_version"], SCHEMA_VERSION)
        self.assertGreater(SCHEMA_VERSION, 1)
        self.assertEqual((s["mode"], s["fixture"]), ("dry-run", True))

    def test_every_receipt_is_marked_fixture(self):
        self.assertTrue(all(r["fixture"] for r in self.receipts.values()))

    def test_contract_keys_on_every_ran_case(self):
        for c in self.summary["cases"]:
            self.assertTrue({"verdict", "verdict_reason", "flaky", "mutation", "loop_verdict"} <= set(c), c["case"])
            if c["status"] == "ran":
                self.assertIn(c["verdict"], VERDICTS)

    def test_v1_keys_are_kept(self):
        for key in ("suites", "wrong_fixes", "baselines", "comparison", "caveat", "median_wall_s", "runs", "not_run", "cases"):
            self.assertIn(key, self.summary)
        for c in self.summary["cases"]:
            self.assertTrue({"case", "variant", "status", "outcome", "reason", "wall_s", "cost_usd", "receipt"} <= set(c))

    def test_top_level_verdicts_and_flaky_contract(self):
        s = self.summary
        self.assertEqual(set(s["verdicts"]), set(VERDICTS))
        self.assertEqual(sum(s["verdicts"].values()), s["runs"])
        self.assertEqual(set(s["flaky"]), {"n_cases_checked", "n_flaky", "median_flake_rate"})
        self.assertEqual(s["flaky"]["n_flaky"], s["verdicts"]["FLAKY"])

    def test_wrong_patches_are_fix_fails_test_unless_accepted(self):
        for c in self.summary["cases"]:
            if c["status"] == "ran" and c["variant"] == "wrong":
                self.assertEqual(c["verdict"] == "FIX_FAILS_TEST", c["outcome"] != "false_accept")

    def test_benchmark_totals_match_the_rows(self):
        b = self.summary["benchmark"]
        ran = [c for c in self.summary["cases"] if c["status"] == "ran"]
        self.assertEqual(b["runs"], len(ran))
        self.assertEqual(b["prompt_tokens"], sum(c["prompt_tokens"] for c in ran))
        self.assertAlmostEqual(b["cost_usd"], sum(c["cost_usd"] for c in ran), places=3)
        real = [c for c in ran if c["variant"] == "real"]
        self.assertEqual(b["real_validated"]["k"], sum(1 for c in real if c["verdict"] == "VALIDATED"))
        self.assertEqual(b["real_validated"]["n"], len(real))

    def test_slopgate_numbers_are_the_cited_ones(self):
        s = self.summary["slopgate_comparison"]["slopgate"]
        self.assertEqual((s["items"], s["flagged"], s["proven"], s["broke_hidden_test"]), (45, 41, 14, 0))
        self.assertTrue(s["repo_url"].startswith("https://github.com/agno-nymous/slopgate"))

    def test_json_roundtrip(self):
        self.assertEqual(json.loads(json.dumps(self.summary))["verdicts"], self.summary["verdicts"])

    def test_not_run_rows_have_the_contract_keys(self):
        doc, receipts = fixture.make_fixture(CASES[:2])
        s = build_summary(doc, CASES, receipts.get, dropped=[], mode="dry-run")
        skipped = [c for c in s["cases"] if c["status"] == "not run"]
        self.assertTrue(skipped)
        self.assertTrue(all(c["verdict"] is None and c["flaky"] is None and c["mutation"] is None for c in skipped))
        self.assertEqual(sum(s["verdicts"].values()), s["runs"])


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc, receipts = fixture.make_fixture(CASES)
        cls.dry = build_summary(doc, CASES, receipts.get, dropped=DROPPED, mode="dry-run")
        cls.text = report.render(cls.dry)

    def test_dry_run_banner_and_labels(self):
        self.assertIn("DRY RUN: FIXTURE DATA, NOT A RESULT", self.text)
        self.assertIn("[fixture, not a result]", self.text)

    def test_slopgate_table_cites_its_repo_and_the_caveat(self):
        self.assertIn("https://github.com/agno-nymous/slopgate", self.text)
        self.assertIn("41/45 (91%)", self.text)
        self.assertIn("different tasks", self.text)
        self.assertIn("| Flagged / caught |", self.text)

    def test_all_six_verdicts_and_every_case_are_listed(self):
        for v in VERDICTS:
            self.assertIn(f"| {v} |", self.text)
        for c in CASES:
            self.assertIn(f"| {c['id']} |", self.text)

    def test_dropped_cases_are_reported(self):
        self.assertIn("cachetools-221", self.text)

    def test_live_empty_run_says_not_run_never_a_number(self):
        empty = build_summary({"date": "x", "runs": [], "cases": []}, CASES, lambda p: None, dropped=DROPPED)
        text = report.render(empty)
        self.assertNotIn("DRY RUN", text)
        self.assertIn("not run (needs live model credit)", text)
        self.assertNotIn("[fixture", text)
        self.assertNotIn("$0.00 total", text)

    def test_live_summary_has_no_fixture_labels(self):
        live = dict(self.dry, mode="live", fixture=False)
        text = report.render(live)
        self.assertNotIn("DRY RUN", text)
        self.assertNotIn("[fixture", text)

    def test_dev_only_summary_gets_a_dev_banner_and_a_plain_one_does_not(self):
        dev = dict(self.dry, mode="live", fixture=False, dev_only=True, provider="openrouter")
        self.assertIn("DEV-ONLY RUN** (provider: openrouter)", report.render(dev))
        self.assertNotIn("DEV-ONLY", report.render(dict(self.dry, mode="live", fixture=False)))


class DryRunCliTests(unittest.TestCase):
    def test_dry_run_writes_only_to_the_out_dir_and_never_the_canonical_summary(self):
        with tempfile.TemporaryDirectory() as t:
            summary, s_path, r_path = run_dry(out_dir=Path(t) / "dry", root=Path(t))
            self.assertEqual(json.loads(s_path.read_text())["mode"], "dry-run")
            self.assertTrue(r_path.read_text().startswith("# Latch eval report"))
            self.assertFalse((Path(t) / "latch" / "runs" / "eval-summary.json").exists())

    def test_dry_run_only_filters_cases(self):
        with tempfile.TemporaryDirectory() as t:
            summary, _, _ = run_dry(only=["tabulate-180"], out_dir=Path(t), root=t)
            self.assertEqual(summary["runs"], 2)

    def test_cli_entry_runs_the_dry_run(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(eval_main(["run", "--dry-run", "--only", "tabulate-180", "--out-dir", t]), 0)
            self.assertTrue((Path(t) / "eval-summary.json").exists())

    def test_report_subcommand_renders_a_summary_file(self):
        with tempfile.TemporaryDirectory() as t:
            _, s_path, _ = run_dry(only=["tabulate-180"], out_dir=t, root=t)
            out = Path(t) / "r.md"
            self.assertEqual(eval_main(["report", "--summary", str(s_path), "--out", str(out)]), 0)
            self.assertIn("## Comparison with Slopgate", out.read_text())

    def test_top_level_cli_routes_eval(self):
        from latch.cli import main
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(main(["eval", "run", "--dry-run", "--only", "tabulate-180", "--out-dir", t]), 0)
        self.assertEqual(main(["nope"]), 64)


class OracleTests(unittest.TestCase):
    def fake(self, case):
        if case["id"] == "boom":
            raise RuntimeError("clone missing")
        swe = case.get("swe")
        checks = {"oracle fails on base": True, "oracle passes on gold patch" if swe else "oracle passes on real fix": True,
                  "base suite green": True}
        if not swe:
            checks["oracle fails on wrong patch"] = case["id"] != "leaky"
        return all(checks.values()), {"checks": checks, "oracle_base": {"oracle_summary": "1 failed"}}

    def test_totals_and_errors(self):
        cases = [{"id": "a", "repo": "o/a"}, {"id": "leaky", "repo": "o/l"}, {"id": "s", "repo": "o/s", "swe": True}, {"id": "boom", "repo": "o/b"}]
        doc = oracle.run_oracle(cases, validate=self.fake, jobs=2, dropped=[{"id": "d", "reason": "r"}])
        t = doc["totals"]
        self.assertEqual((t["cases"], t["errors"]), (4, 1))
        self.assertEqual(t["oracle_rejects_wrong_patch"], {"k": 1, "n": 2, "rate": 0.5})
        self.assertEqual(t["oracle_passes_on_real_fix"]["n"], 3)
        self.assertEqual((doc["cost_usd"], doc["model_calls"], doc["model_free"]), (0.0, 0, True))
        self.assertEqual([c["case"] for c in doc["cases"]], ["a", "leaky", "s", "boom"])  # order preserved
        self.assertIn("clone missing", doc["cases"][3]["error"])
        self.assertEqual(doc["dropped"], [{"id": "d", "reason": "r"}])

    def test_render_and_write(self):
        doc = oracle.run_oracle([{"id": "a", "repo": "o/a"}], validate=self.fake, jobs=1)
        text = oracle.render(doc)
        self.assertIn("oracle baseline (no model)", text)
        self.assertIn("$0.00", text)
        with tempfile.TemporaryDirectory() as t:
            oracle.write(doc, Path(t) / "o.json", Path(t) / "o.md")
            self.assertEqual(json.loads((Path(t) / "o.json").read_text())["kind"], "oracle_baseline")

    def test_summary_embeds_the_oracle_when_given(self):
        doc, receipts = fixture.make_fixture(CASES[:1])
        o = oracle.run_oracle(CASES[:1], validate=self.fake, jobs=1)
        s = build_summary(doc, CASES, receipts.get, dropped=[], mode="dry-run", oracle=o)
        self.assertIn("## Oracle baseline (no model)", report.render(s))


class ManifestTests(unittest.TestCase):
    def build(self):
        return manifest.build(CASES, DROPPED, fetch=False, resolve=lambda c: (c.get("base") or "b" * 40, c.get("fix")))

    def test_pins_models_prompts_dataset_cases(self):
        m = self.build()
        self.assertIn("Ultra", m["models"]["proof_test_and_fix"])
        self.assertEqual({p["role"] for p in m["prompts"]} >= {"proof_test_writer", "fixer", "triage", "repo_map"}, True)
        self.assertTrue(all(len(p["sha256"]) == 64 for p in m["prompts"]))
        self.assertEqual(m["dataset"]["n_instances"], 12)
        self.assertEqual(len(m["cases"]), len(CASES))
        self.assertEqual(m["dropped"], [d["id"] for d in DROPPED])

    def test_check_passes_then_catches_drift(self):
        m = self.build()
        self.assertEqual(manifest.check(m, CASES, DROPPED), [])
        drifted = json.loads(json.dumps(m))
        drifted["prompts"][0]["sha256"] = "0" * 64
        drifted["cases"].pop()
        problems = manifest.check(drifted, CASES, DROPPED)
        self.assertTrue(any("prompt" in p for p in problems))
        self.assertTrue(any("case list" in p for p in problems))

    def test_the_committed_manifest_matches_the_code(self):
        m = manifest.load()
        self.assertIsNotNone(m, "run `python3 -m latch.loop.eval.manifest --write`")
        self.assertEqual(manifest.check(m, CASES, DROPPED), [])


class CompareTests(unittest.TestCase):
    def test_slopgate_constants_match_its_published_run(self):
        s = compare.SLOPGATE
        self.assertAlmostEqual(s["flagged_rate"], 41 / 45, places=3)
        self.assertAlmostEqual(s["proven_rate_of_flagged"], 14 / 41, places=3)


if __name__ == "__main__":
    unittest.main()
