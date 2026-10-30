"""Tests for the verdict and mutation display against latch-loop's DRAFT receipt contract.

The fixtures here are the only place the draft contract lives in latch/web. They stand in for receipts the
harness has not produced yet; once the final schema lands, adjust the builders below and nothing else.
Run from the repo root:  python3 -m unittest latch.web.test_verdict -v
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from latch.web import store
from latch.web.test_app import Harness, receipt

STATIC = Path(__file__).parent / "static"
BASE, HEAD = "b" * 40, "9" * 40
CODES = ("VALIDATED", "NO_REGRESSION_FOUND", "INVALID_TEST", "MUTATION_SURVIVED", "FLAKY")

DIFF = "--- a/widgets/price.py\n+++ b/widgets/price.py\n@@ -14,1 +14,1 @@\n-    return round(total + 0.005, 2)\n+    return round(total, 2)\n"


def mutant(i, killed, operator="constant_replace", file="widgets/price.py", line=14, output=None):
    return {"id": f"m{i}", "operator": operator, "file": file, "line": line, "diff": DIFF, "killed": killed,
            "output_excerpt": output or ("FAILED latch_issue_test.py::test_x - AssertionError" if killed else "1 passed in 0.03s")}


def mutation(flags):
    mutants = [mutant(i + 1, k, operator=("compare_op", "constant_replace", "arith_op", "negate_condition")[i % 4], line=14 + i)
               for i, k in enumerate(flags)]
    killed = sum(1 for k in flags if k)
    return {"mutants": mutants, "killed": killed, "total": len(flags), "kill_rate": killed / len(flags) if flags else 0}


REASONS = {
    "VALIDATED": "The test failed on base, passed on head, and killed 8 of 8 mutants.",
    "NO_REGRESSION_FOUND": "The test passed on both base and head, so it did not reproduce the issue.",
    "INVALID_TEST": "The test failed on base with an ImportError, not the behaviour in the issue.",
    "MUTATION_SURVIVED": "3 of 8 mutants survived: the test still passes when the fix is changed.",
    "FLAKY": "The test passed on head in 2 of 3 repeat runs.",
}


def verdict_receipt(code, **extra):
    """A receipt carrying the draft contract: verdict, verdict_reason, base_sha/head_sha, mutation, log excerpts."""
    r = receipt(BASE, HEAD, proven=(code == "VALIDATED"))
    r.update({"verdict": code, "verdict_reason": REASONS[code], "base_sha": BASE, "head_sha": HEAD})
    flags = {"VALIDATED": [True] * 8, "MUTATION_SURVIVED": [True, False, True, True, False, True, False, True]}.get(code)
    if flags:
        r["mutation"] = mutation(flags)
    if code == "NO_REGRESSION_FOUND":
        r["base_result"] = {"returncode": 0, "stdout": "1 passed in 0.03s", "stderr": ""}
    if code == "INVALID_TEST":
        r["base_result"] = {"returncode": 2, "stdout": "ImportError: cannot import name 'price_totl' from 'widgets.price'", "stderr": ""}
        r["base_failure_is_expected"] = False
    r["log_excerpts"] = [{"label": "base run", "text": "FAILED latch_issue_test.py::test_x - AssertionError"},
                         {"label": "head run", "text": "1 passed in 0.03s"}]
    r.update(extra)
    return r


def seed(h, number, code=None, **extra):
    """Store a receipt with the given verdict (or an old one without any) under acme/widgets#number."""
    head = f"{number:040x}"  # the receipt key is repo+base+head, so each seeded receipt needs its own head
    r = verdict_receipt(code, head=head, head_sha=head, **extra) if code else receipt(BASE, head)
    h.service.store.put("acme/widgets", number, store.make_envelope(r, "live", started=1.0, finished=2.0))
    return r


class VerdictCodeTests(unittest.TestCase):
    def test_a_known_code_is_surfaced_in_meta_and_the_legacy_verdict_is_unchanged(self):
        for code in CODES:
            meta = store.make_envelope(verdict_receipt(code), "live", started=1.0, finished=2.0)["meta"]
            self.assertEqual(meta["verdict_code"], code)
            self.assertEqual(meta["verdict"], "proven" if code == "VALIDATED" else "not_proven")

    def test_a_receipt_that_only_carries_base_sha_and_head_sha_can_still_be_stored(self):
        h = Harness(self)
        r = verdict_receipt("VALIDATED")
        del r["base"], r["head"]
        h.service.store.put("acme/widgets", 31, store.make_envelope(r, "live", started=1.0, finished=2.0))
        self.assertEqual(h.get_json("/api/receipt/acme/widgets/31")[1]["meta"]["verdict_code"], "VALIDATED")

    def test_old_receipts_and_unknown_codes_have_no_verdict_code(self):
        for r in (receipt(BASE, HEAD), verdict_receipt("FLAKY", verdict="PROBABLY_FINE"), verdict_receipt("FLAKY", verdict=7), {"proven": True, "verdict": "gate_open"}):
            self.assertIsNone(store.make_envelope(r, "live", started=1.0, finished=2.0)["meta"]["verdict_code"])

    def test_the_harness_reason_explains_a_verdict_that_is_not_validated(self):
        for code in CODES[1:]:
            self.assertEqual(store.explain(verdict_receipt(code)).rstrip("."), REASONS[code].rstrip("."))
        self.assertIsNone(store.explain(verdict_receipt("VALIDATED")))

    def test_old_receipts_still_explain_themselves_the_old_way(self):
        self.assertEqual(store.explain(receipt(BASE, HEAD, proven=False, head_rc=1)), store.explain(dict(receipt(BASE, HEAD, proven=False, head_rc=1))))
        self.assertIsNone(store.explain(receipt(BASE, HEAD)))


class ServedTests(unittest.TestCase):
    def test_the_verdict_module_is_served_and_loaded_before_the_scripts_that_use_it(self):
        h = Harness(self)
        status, headers, body = h.request("GET", "/static/verdict.js")
        self.assertEqual(status, 200)
        self.assertIn("LatchVerdict", body.decode())
        for page, script in (("/", "app.js"), ("/eval", "eval.js")):
            html = h.request("GET", page)[2].decode()
            self.assertIn('<script src="/static/verdict.js"></script>', html, page)
            self.assertLess(html.index("/static/verdict.js"), html.index("/static/" + script), page)

    def test_every_draft_receipt_round_trips_unchanged_and_lists_its_verdict(self):
        h = Harness(self)
        for number, code in enumerate(CODES, start=1):
            sent = seed(h, number, code)
            got = h.get_json(f"/api/receipt/acme/widgets/{number}")[1]
            self.assertEqual(got["receipt"], sent)
            self.assertEqual(got["meta"]["verdict_code"], code)
        items = {i["number"]: i for i in h.get_json("/api/recent")[1]["items"] if i["repo"] == "acme/widgets"}
        self.assertEqual({n: items[n]["verdict_code"] for n in items}, dict(enumerate(CODES, start=1)))
        self.assertEqual(items[1]["verdict"], "proven")
        self.assertEqual({items[n]["verdict"] for n in range(2, 6)}, {"not_proven"})

    def test_an_old_receipt_lists_no_verdict_code_and_the_recorded_click_still_does_not(self):
        h = Harness(self)
        seed(h, 20)
        items = h.get_json("/api/recent")[1]["items"]
        self.assertTrue(items)
        self.assertTrue(all(i["verdict_code"] is None for i in items))

    def test_the_mutation_and_verdict_step_events_are_relayed_like_any_other(self):
        def run(url, path, command, on_step=None, runner=None, on_step_event=None):
            on_step("fetching")
            on_step_event({"step": "mutation", "status": "started", "ts": "2026-10-30T04:00:00.000Z", "detail": None})
            on_step_event({"step": "mutation", "status": "done", "ts": "2026-10-30T04:00:09.000Z", "detail": {"killed": 5, "total": 8}})
            on_step_event({"step": "verdict", "status": "done", "ts": "2026-10-30T04:00:10.000Z", "detail": {"verdict": "MUTATION_SURVIVED"}})
            return verdict_receipt("MUTATION_SURVIVED", base=BASE, head="7" * 40, base_sha=BASE, head_sha="7" * 40)

        h = Harness(self, run_pr=run)
        events = h.events(h.post(h.add_pr(7))[2]["job_id"])
        relayed = [e["data"] for e in events if e["event"] == "step_event"]
        self.assertEqual([(e["step"], e["status"]) for e in relayed], [("mutation", "started"), ("mutation", "done"), ("verdict", "done")])
        self.assertEqual(relayed[1]["detail"], {"killed": 5, "total": 8})
        self.assertEqual(relayed[2]["detail"], {"verdict": "MUTATION_SURVIVED"})
        result = events[-1]
        self.assertEqual(result["event"], "result")
        self.assertEqual(result["data"]["meta"]["verdict_code"], "MUTATION_SURVIVED")

    def test_the_ledger_has_rows_for_the_mutation_and_verdict_steps(self):
        js = (STATIC / "app.js").read_text()
        self.assertIn('["mutation", "Mutation check (harness)", false]', js)
        self.assertIn('["verdict", "Decide the verdict (harness)", true]', js)
        self.assertIn("mutationSection(r)", js)


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class VerdictModuleTests(unittest.TestCase):
    """Run the real static/verdict.js under node: it is the single place the verdict wording and fail-closed rules live."""

    def info(self, receipt_obj, meta=None):
        script = ("global.window = {}; require(%s); process.stdout.write(JSON.stringify(window.LatchVerdict.info(%s, %s)));"
                  % (json.dumps(str(STATIC / "verdict.js")), json.dumps(receipt_obj), json.dumps(meta or {})))
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(out.stdout)

    def test_only_validated_is_a_pass_and_every_other_verdict_carries_its_reason(self):
        for code in CODES:
            got = self.info(verdict_receipt(code))
            self.assertEqual(got["code"], code)
            self.assertEqual(got["pass"], code == "VALIDATED", code)
            self.assertTrue(got["meaning"])
            self.assertEqual(got["reason"], REASONS[code])
        labels = [self.info(verdict_receipt(c))["label"] for c in CODES]
        self.assertEqual(len(set(labels)), 5)

    def test_old_receipts_fall_back_to_proven_and_not_proven(self):
        self.assertEqual(self.info(receipt(BASE, HEAD, proven=True))["label"], "Proven")
        old = self.info(receipt(BASE, HEAD, proven=False), {"why_not_proven": "the head still fails"})
        self.assertEqual((old["label"], old["pass"], old["code"]), ("Not proven", False, None))
        self.assertIn("the head still fails", old["meaning"])

    def test_a_contradiction_or_an_unknown_verdict_never_reads_as_a_pass(self):
        self.assertFalse(self.info(verdict_receipt("VALIDATED", proven=False))["pass"])
        self.assertFalse(self.info(verdict_receipt("FLAKY", proven=True))["pass"])
        unknown = self.info(verdict_receipt("VALIDATED", verdict="PROBABLY_FINE", proven=True))
        self.assertFalse(unknown["pass"])
        self.assertEqual(unknown["label"], "Unrecognised verdict")


if __name__ == "__main__":
    unittest.main()
