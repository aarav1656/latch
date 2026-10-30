"""Offline tests for eval-summary.json: synthetic eval documents, no models, no network."""

import json
import tempfile
import unittest
from pathlib import Path

from latch.loop.eval import run_eval
from latch.loop.eval.summary import BASELINES, CONTESTED, build_summary

CASES = [
    {"id": "up-a", "repo": "o/a", "title": "A"}, {"id": "cachetools-423", "repo": "o/c", "title": "C"},
    {"id": "up-b", "repo": "o/b", "title": "B"}, {"id": "click-3360", "repo": "o/k", "title": "K"},
    {"id": "sw-1", "repo": "sympy/sympy", "title": "S1", "swe": True}, {"id": "sw-2", "repo": "sympy/sympy", "title": "S2", "swe": True},
    {"id": "notrun", "repo": "o/n", "title": "N"},
]


def run(case, variant, outcome, wall=10.0, **extra):
    return {"case": case, "variant": variant, "outcome": outcome, "verdict": extra.pop("verdict", "gate_open"),
            "reason": extra.pop("reason", "r"), "wall_seconds": wall, "label": variant, "receipt": f"/x/{case}-{variant}.json",
            "iterations_used": 0, "gate_open_at_iteration_0": outcome == "false_accept", "completion_ids": {}, **extra}


RUNS = [
    run("up-a", "real", "proven", 20), run("up-a", "wrong", "shut_gave_up", 40, verdict="gave_up", reason="gate still shut after 3 iteration(s)"),
    run("cachetools-423", "real", "proven", 30), run("cachetools-423", "wrong", "false_accept", 12),
    run("up-b", "real", "gave_up", 15, verdict="gave_up", reason="Lightning triage did not confirm", triage_verdict="not_reproduced"),
    run("up-b", "wrong", "repaired", 50),
    run("click-3360", "real", "error", 5, verdict="error", reason="HTTP 500"), run("click-3360", "wrong", "error", 6, verdict="error", reason="HTTP 500"),
    run("sw-1", "real", "proven", 60), run("sw-1", "nofix", "green_but_wrong", 70),
    run("sw-2", "real", "gave_up", 80, verdict="gave_up"), run("sw-2", "nofix", "nemotron_fix_correct", 90),
]
RECEIPTS = {
    "/x/up-a-real.json": {"model_cost_usd": 0.01, "proof_test_attempts": [{"attempt": 1, "valid": False, "rejection": "vacuous", "completion_id": "c1"},
                                                                         {"attempt": 2, "valid": True}]},
    "/x/up-b-real.json": {"model_cost_usd": 0.03, "triage": {"verdict": "not_reproduced"}},
    "/x/up-a-wrong.json": {"model_cost_usd": None},
    "/x/up-b-wrong.json": {"model_cost_usd": 0.05},
}
DOC = {"date": "2026-10-30", "runs": RUNS, "cases": [], "models": {}, "max_iterations": 3}


def build(**kw):
    return build_summary(DOC, CASES, RECEIPTS.get, dropped=kw.get("dropped", []), generated_at="2026-10-30T00:00:00Z")


class SummaryTests(unittest.TestCase):
    def test_schema_2_keeps_the_loop_verdict_under_loop_verdict(self):
        out = build()
        self.assertEqual(out["schema_version"], 2)
        by = {(c["case"], c["variant"]): c for c in out["cases"]}
        self.assertEqual(by[("up-b", "real")]["loop_verdict"], "gave_up")
        self.assertIn(by[("up-a", "real")]["verdict"], (None, *__import__("latch.verdict", fromlist=["VERDICTS"]).VERDICTS))
        self.assertEqual(set(out["verdicts"]), set(__import__("latch.verdict", fromlist=["VERDICTS"]).VERDICTS))

    def test_suites_are_split_with_counts_and_rates(self):
        s = build()["suites"]
        self.assertEqual({k: s["upstream"][k] for k in ("n", "proven", "errors", "not_run")}, {"n": 4, "proven": 2, "errors": 1, "not_run": 1})
        self.assertEqual(s["upstream"]["proven_rate"], 0.5)
        self.assertEqual((s["swebench_lite"]["n"], s["swebench_lite"]["proven"], s["swebench_lite"]["proven_rate"]), (2, 1, 0.5))
        fix = s["swebench_lite"]["nemotron_fix"]
        self.assertEqual((fix["n"], fix["gate_open"], fix["oracle_pass"], fix["green_but_wrong"]), (2, 2, 1, ["sw-1"]))

    def test_wrong_fixes_with_and_without_contested(self):
        w = build()["wrong_fixes"]
        self.assertEqual((w["n"], w["caught"]), (3, 2))                      # errors are not counted as caught
        self.assertEqual((w["without_contested"]["n"], w["without_contested"]["caught"]), (2, 2))
        self.assertEqual(w["false_accepts"], ["cachetools-423"])
        self.assertEqual(w["contested_cases"], ["cachetools-423"])           # click-3360's wrong run errored, so it is not in the count
        self.assertEqual(w["errors"], 1)
        self.assertEqual(w["repaired_by_loop"], {"n": 1, "oracle_pass": 1})
        self.assertEqual(set(CONTESTED), {"cachetools-423", "click-3360"})

    def test_medians_and_cost_unknown_excluded(self):
        s = build()
        self.assertEqual(s["median_wall_s"], 35.0)                           # median of the 12 wall times
        self.assertEqual(s["median_cost_usd"], 0.03)                         # 0.01, 0.03, 0.05 only; unknown is not zero
        self.assertEqual(s["runs_with_known_cost"], 3)

    def test_judge_inputs_validator_abstentions_failures_not_run(self):
        s = build(dropped=[{"id": "cachetools-221", "reason": "no honest wrong patch"}])
        self.assertEqual(s["validator_rejections"]["n"], 1)
        self.assertEqual(s["validator_rejections"]["items"][0]["rejection"], "vacuous")
        kinds = {(a["case"], a["variant"]): a["kind"] for a in s["abstentions"]["items"]}
        self.assertEqual(kinds[("up-b", "real")], "triage_not_reproduced")
        self.assertEqual(kinds[("up-a", "wrong")], "gave_up")
        self.assertEqual(s["failures"]["n"], 2)
        not_run = {(n["case"], n["variant"]) for n in s["not_run"]}
        self.assertIn(("notrun", "real"), not_run)
        self.assertIn(("cachetools-221", None), not_run)
        dup = build(dropped=[{"id": "notrun", "reason": ["base not red"]}, {"id": "notrun", "reason": "dup"}])
        self.assertEqual(sum(1 for n in dup["not_run"] if n["case"] == "notrun"), 2)      # real + wrong rows, once each
        self.assertIn("base not red", [n for n in dup["not_run"] if n["case"] == "notrun"][0]["reason"])
        rows = {(r["case"], r["variant"]): r for r in s["cases"]}
        self.assertEqual(rows[("notrun", "real")]["status"], "not run")
        self.assertEqual(len(s["cases"]), 14)                                  # every case x variant is listed
        self.assertTrue(rows[("cachetools-423", "wrong")]["contested"])

    def test_baselines_caveat_comparison_and_featured_receipt(self):
        s = build()
        self.assertEqual({b["name"].split()[0]: b["value"] for b in s["baselines"]}, {"Otter": 0.314, "AssertFlip": 0.436})
        self.assertTrue(all(b["source_url"].startswith("https://arxiv.org/abs/") for b in BASELINES))
        self.assertIn("Small sample", s["caveat"])
        self.assertIn("31.4%", s["comparison"])
        self.assertIn("43.6%", s["comparison"])
        self.assertIn("small-sample", s["comparison"])
        self.assertEqual(s["featured_wrong_fix_receipt"], "/x/up-a-wrong.json")   # a wrong patch whose gate stayed shut
        self.assertIn("NOT PROVEN", s["featured_wrong_fix_note"])

    def test_featured_falls_back_to_a_repaired_wrong_patch_and_says_so(self):
        runs = [r for r in RUNS if r["outcome"] != "shut_gave_up"]
        s = build_summary({**DOC, "runs": runs}, CASES, RECEIPTS.get)
        self.assertEqual(s["featured_wrong_fix_receipt"], "/x/up-b-wrong.json")
        self.assertIn("repaired", s["featured_wrong_fix_note"])

    def test_json_serialisable_and_no_placeholders_without_runs(self):
        json.dumps(build())
        empty = build_summary({"runs": [], "cases": []}, CASES)
        self.assertEqual(empty["suites"]["upstream"]["proven_rate"], None)
        self.assertEqual(empty["median_wall_s"], None)
        self.assertIsNone(empty["featured_wrong_fix_receipt"])
        self.assertIn("n/a", empty["comparison"])

    def test_publish_receipts_copies_and_relativises(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.json"
            src.write_text("{}")
            dest = Path(tmp) / "eval"
            doc = {"runs": [{"case": "c", "variant": "wrong", "receipt": str(src)}, {"case": "d", "variant": "real", "receipt": "/nope.json"}]}
            run_eval.publish_receipts(doc, dest)
            self.assertTrue((dest / "c-wrong.json").exists())
            self.assertEqual(doc["runs"][1]["receipt"], None)


class NoPlaceholderTest(unittest.TestCase):
    def test_no_summary_file_is_committed_before_a_real_run(self):
        # eval-summary.json must only ever come from a real run; the schema lives in RESULTS.md
        path = Path(run_eval.REPO_ROOT) / "latch" / "runs" / "eval-summary.json"
        results = (Path(run_eval.__file__).parent / "RESULTS.md").read_text()
        self.assertTrue(path.exists() is False or '"schema_version"' in path.read_text())
        self.assertIn("eval-summary.json` schema", results)


if __name__ == "__main__":
    unittest.main()
