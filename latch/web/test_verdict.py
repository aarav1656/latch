"""Tests for the verdict, mutation and rerun displays against latch/verdict.py (the pinned schema).

The fixtures run the real `latch.verdict.verdict_fields`, so a schema change in the harness shows up here as a
failing test rather than as a UI that quietly shows nothing. Run from the repo root:
    python3 -m unittest latch.web.test_verdict -v
"""

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from latch import strengthen as strengthening
from latch import tautology as taut
from latch import verdict as harness
from latch.web import store
from latch.web.service import Config
from latch.web.test_app import Harness, receipt

STATIC = Path(__file__).parent / "static"
BASE, HEAD = "b" * 40, "9" * 40
CODES = harness.VERDICTS  # precedence order: INVALID_TEST, FLAKY, NO_REGRESSION_FOUND, FIX_FAILS_TEST, MUTATION_SURVIVED, VALIDATED

# The one-line meanings are fixed copy, agreed with the user. They must not drift.
MEANINGS = {
    "VALIDATED": "The test fails on the old code, passes on the fix, and catches the fix being undone.",
    "FIX_FAILS_TEST": "The test is good, but this change still fails it. The bug isn't fixed.",
    "NO_REGRESSION_FOUND": "The test already passes on the old code, so it can't show the bug.",
    "MUTATION_SURVIVED": "The test still passes when the fix is broken on purpose, so it isn't really checking the fix.",
    "FLAKY": "The test gave different results on reruns, so it can't be trusted.",
    "INVALID_TEST": "The test is empty, never checks the changed code, or crashed instead of asserting.",
}

FAIL = {"returncode": 1, "stdout": "____ test_x ____\nE   AssertionError: double(2) == 5\nFAILED latch_issue_test.py::test_x", "stderr": ""}
PASS = {"returncode": 0, "stdout": "1 passed in 0.03s", "stderr": ""}
ERR = {"returncode": 2, "stdout": "ERROR collecting latch_issue_test.py\nImportError: cannot import name 'price_totl' from 'widgets.price'", "stderr": ""}

DIFF = "--- a/widgets/price.py\n+++ b/widgets/price.py\n@@ -14,1 +14,1 @@\n-    return round(total + 0.005, 2)\n+    return round(total, 2)\n"
OPERATORS = ("compare_op", "constant_replace", "arith_op", "negate_condition")
WHATS = ("flipped >= to >", "changed 0.005 to 0.0", "swapped + for -", "negated the guard on line 17")


def mutant(i, killed, file="widgets/price.py", line=None):
    return {"id": f"m{i}", "operator": OPERATORS[i % 4], "file": file, "line": line or 14 + i, "what": WHATS[i % 4], "diff": DIFF,
            "killed": killed, "output_excerpt": "FAILED latch_issue_test.py::test_x - AssertionError" if killed else "1 passed in 0.03s"}


def mutation(flags, **over):
    """The mutation dict as latch/verdict.py documents it: threshold 0.6, ok when kill_rate meets it."""
    mutants = [mutant(i + 1, k) for i, k in enumerate(flags)]
    killed = sum(1 for k in flags if k)
    rate = round(killed / len(flags), 3) if flags else None
    m = {"mutants": mutants, "killed": killed, "total": len(flags), "kill_rate": rate, "threshold": harness.MUTATION_THRESHOLD,
         "ok": rate is None or rate >= harness.MUTATION_THRESHOLD,
         "note": f"{killed} of {len(flags)} mutants of the changed lines were killed" if flags else "no mutable lines in the change"}
    m.update(over)
    return m


STABLE = harness.flake_summary([False] * 5, [True] * 5)
FLAKY_RUN = harness.flake_summary([False, False, True, False, False], [True, True, False, True, True])
SURVIVING = mutation([True, False, True, False, False, True, False, False])  # 3 of 8 is below the 0.6 threshold

CHANGED = {"determined": True, "symbols": ["price_total", "round_half"], "affected": ["checkout"]}
# The harness's own results, so the fixture has exactly the shape a receipt carries.
TAUT_OK = taut.check_tautology("def test_x():\n    from widgets.price import price_total\n    assert price_total(2.675) == 2.68\n", CHANGED)
TAUT_REJECTED = taut.check_tautology("def test_x():\n    assert 1 == 1\n", CHANGED)
TAUT_UNCHECKED = {"checked": False, "changed_symbols": [], "asserted_symbols": [], "ok": True,
                  "reason": "not checked: no proof test reached the tautology check"}

EVIDENCE = {
    "VALIDATED": dict(base=FAIL, head=PASS, flaky=STABLE, mutation=mutation([True] * 8)),
    "MUTATION_SURVIVED": dict(base=FAIL, head=PASS, flaky=STABLE, mutation=SURVIVING),
    "FIX_FAILS_TEST": dict(base=FAIL, head=FAIL, flaky=STABLE),
    "NO_REGRESSION_FOUND": dict(base=PASS, head=PASS, flaky=STABLE),
    "FLAKY": dict(base=FAIL, head=PASS, flaky=FLAKY_RUN),
    "INVALID_TEST": dict(base=ERR, head=PASS),
}


def verdict_receipt(code, base_sha=BASE, head_sha=HEAD, **extra):
    """A receipt carrying the pinned contract, built by the harness's own verdict_fields for the evidence behind `code`."""
    evidence = copy.deepcopy(dict(EVIDENCE[code], test_name="test_x", suite_ok=True))
    fields = harness.verdict_fields(evidence, base_sha, head_sha)
    assert fields["verdict"] == code, (code, fields["verdict"])
    base, head = evidence["base"], evidence["head"]
    r = receipt(base_sha, head_sha, proven=fields["proven"], base_rc=base["returncode"], head_rc=head["returncode"])
    r["base_result"], r["head_result"] = dict(base), dict(head)
    r.update(fields)
    r["tautology"] = copy.deepcopy(TAUT_OK)
    if code == "INVALID_TEST":
        r["base_failure_is_expected"] = False
    r.update(extra)
    return r


def tautology_receipt(base_sha=BASE, head_sha=HEAD, tautology=None):
    """What prove.py writes when the proof test is rejected before any run: no test, no results, INVALID_TEST."""
    tautology = copy.deepcopy(tautology or TAUT_REJECTED)
    fields = harness.verdict_fields({"tautology": tautology}, base_sha, head_sha)
    assert fields["verdict"] == "INVALID_TEST" and fields["verdict_reason"].startswith("tautology check: ")
    r = receipt(base_sha, head_sha, proven=False)
    r.update(fields)
    r.update({"test": None, "test_name": None, "base_result": None, "head_result": None, "base_failure_is_expected": False,
              "rejected_test_reason": tautology["reason"], "why_not_proven": tautology["reason"], "head": head_sha})
    return r


def seed(h, number, code=None, **extra):
    """Store a receipt with the given verdict (or an old one without any) under acme/widgets#number."""
    head = f"{number:040x}"  # the receipt key is repo+base+head, so each seeded receipt needs its own head
    r = verdict_receipt(code, head_sha=head, **extra) if code else receipt(BASE, head)
    if code:
        r["head"] = head
    h.service.store.put("acme/widgets", number, store.make_envelope(r, "live", started=1.0, finished=2.0))
    return r


class ContractTests(unittest.TestCase):
    def test_every_field_the_harness_promises_is_in_the_fixture_receipts(self):
        for code in CODES:
            r = verdict_receipt(code)
            self.assertTrue(set(harness.RECEIPT_FIELDS) <= set(r), code)
            self.assertEqual(r["proven"], code == "VALIDATED")

    def test_the_web_module_knows_the_six_verdicts_in_the_harness_order_with_the_agreed_wording(self):
        out = subprocess.run([NODE, "-e", "global.window={};require(%s);process.stdout.write(JSON.stringify(window.LatchVerdict.VERDICTS))" % json.dumps(str(STATIC / "verdict.js"))],
                             capture_output=True, text=True, timeout=30, check=True) if NODE else None
        if out is None:
            self.skipTest("node is not installed")
        got = json.loads(out.stdout)
        self.assertEqual(list(got), list(CODES))
        for code in CODES:
            self.assertEqual(got[code]["meaning"], MEANINGS[code], code)
            self.assertEqual(got[code]["pass"], code == "VALIDATED", code)
        self.assertEqual(len({v["label"] for v in got.values()}), 6)

    def test_store_and_web_agree_on_the_codes(self):
        self.assertEqual(tuple(store.VERDICT_CODES), tuple(CODES))


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
        for code in CODES:
            r = verdict_receipt(code)
            if code == "VALIDATED":
                self.assertIsNone(store.explain(r))
            else:
                self.assertEqual(store.explain(r), store._sentence(r["verdict_reason"]))

    def test_old_receipts_still_explain_themselves_the_old_way(self):
        self.assertEqual(store.explain(receipt(BASE, HEAD, proven=False, head_rc=1)), store.explain(dict(receipt(BASE, HEAD, proven=False, head_rc=1))))
        self.assertIsNone(store.explain(receipt(BASE, HEAD)))


class ServedTests(unittest.TestCase):
    def test_the_verdict_module_is_served_and_loaded_before_the_scripts_that_use_it(self):
        h = Harness(self)
        status, headers, body = h.request("GET", "/static/verdict.js")
        self.assertEqual(status, 200)
        self.assertIn("LatchVerdict", body.decode())
        for page, script in (("/", "app.js"), ("/", "loop.js"), ("/eval", "eval.js")):
            html = h.request("GET", page)[2].decode()
            self.assertIn('<script src="/static/verdict.js"></script>', html, page)
            self.assertLess(html.index("/static/verdict.js"), html.index("/static/" + script), page)

    def test_every_receipt_round_trips_unchanged_and_lists_its_verdict(self):
        h = Harness(self)
        for number, code in enumerate(CODES, start=1):
            sent = seed(h, number, code)
            got = h.get_json(f"/api/receipt/acme/widgets/{number}")[1]
            self.assertEqual(got["receipt"], sent)
            self.assertEqual(got["meta"]["verdict_code"], code)
        items = {i["number"]: i for i in h.get_json("/api/recent")[1]["items"] if i["repo"] == "acme/widgets"}
        self.assertEqual({n: items[n]["verdict_code"] for n in items}, dict(enumerate(CODES, start=1)))
        self.assertEqual({n: items[n]["verdict"] for n in items}, {n: ("proven" if c == "VALIDATED" else "not_proven") for n, c in enumerate(CODES, start=1)})

    def test_a_wrong_fix_lands_on_fix_fails_test_with_the_head_tail_in_verdict_logs(self):
        h = Harness(self)
        seed(h, 4, "FIX_FAILS_TEST")
        got = h.get_json("/api/receipt/acme/widgets/4")[1]
        self.assertEqual(got["meta"]["verdict_code"], "FIX_FAILS_TEST")
        self.assertIn("AssertionError", got["receipt"]["verdict_logs"]["head"])
        self.assertEqual(got["receipt"]["head_result"]["returncode"], 1)

    def test_an_old_receipt_lists_no_verdict_code_and_the_recorded_click_still_does_not(self):
        h = Harness(self)
        seed(h, 20)
        items = h.get_json("/api/recent")[1]["items"]
        self.assertTrue(items)
        self.assertTrue(all(i["verdict_code"] is None for i in items))

    def test_the_mutation_and_verdict_step_events_are_relayed_like_any_other(self):
        def run(url, path, command, on_step=None, runner=None, on_step_event=None):
            on_step("fetching")
            on_step_event({"step": "mutation_check", "status": "started", "ts": "2026-10-30T04:00:00.000Z", "detail": None})
            on_step_event({"step": "mutation_check", "status": "done", "ts": "2026-10-30T04:00:09.000Z", "detail": {"killed": 3, "total": 8, "kill_rate": 0.375}})
            on_step_event({"step": "verdict", "status": "done", "ts": "2026-10-30T04:00:10.000Z",
                           "detail": {"verdict": "MUTATION_SURVIVED", "reason": "mutation kill rate 38% is below the 60% threshold"}})
            return verdict_receipt("MUTATION_SURVIVED", head_sha="7" * 40, head="7" * 40)

        h = Harness(self, run_pr=run)
        events = h.events(h.post(h.add_pr(7))[2]["job_id"])
        relayed = [e["data"] for e in events if e["event"] == "step_event"]
        self.assertEqual([(e["step"], e["status"]) for e in relayed], [("mutation_check", "started"), ("mutation_check", "done"), ("verdict", "done")])
        self.assertEqual(relayed[1]["detail"], {"killed": 3, "total": 8, "kill_rate": 0.375})
        self.assertEqual(relayed[2]["detail"]["verdict"], "MUTATION_SURVIVED")
        self.assertIn("threshold", relayed[2]["detail"]["reason"])
        result = events[-1]
        self.assertEqual(result["event"], "result")
        self.assertEqual(result["data"]["meta"]["verdict_code"], "MUTATION_SURVIVED")

    def test_a_proof_test_rejected_by_the_tautology_check_is_invalid_test_and_round_trips(self):
        h = Harness(self)
        sent = tautology_receipt(head_sha=f"{50:040x}")
        h.service.store.put("acme/widgets", 50, store.make_envelope(sent, "live", started=1.0, finished=2.0))
        got = h.get_json("/api/receipt/acme/widgets/50")[1]
        self.assertEqual(got["receipt"], sent)
        self.assertEqual(got["meta"]["verdict_code"], "INVALID_TEST")
        self.assertEqual(got["meta"]["verdict"], "not_proven")
        self.assertFalse(got["receipt"]["tautology"]["ok"])
        self.assertTrue(got["receipt"]["verdict_reason"].startswith("tautology check: "))
        self.assertIn("tautology check", store.explain(got["receipt"]).lower())

    def test_every_harness_receipt_carries_the_tautology_fields_the_page_reads(self):
        for result in (TAUT_OK, TAUT_REJECTED):
            for key in ("checked", "changed_symbols", "asserted_symbols", "ok", "reason", "affected_symbols", "mode"):
                self.assertIn(key, result)
        # prove.py's "nothing reached the check" placeholder is smaller: the page must cope without the extras.
        for key in ("checked", "changed_symbols", "asserted_symbols", "ok", "reason"):
            self.assertIn(key, TAUT_UNCHECKED)
        self.assertTrue(TAUT_OK["ok"] and TAUT_OK["asserted_symbols"])
        self.assertFalse(TAUT_REJECTED["ok"])
        self.assertEqual(TAUT_OK["mode"], "changed")

    def test_the_receipt_page_script_renders_the_tautology_row(self):
        js = (STATIC / "app.js").read_text()
        for needle in ("tautologySection(r)", "Tautology check", "Changed symbols", "Asserted symbols", "changed_symbols", "asserted_symbols", "affected_symbols", "data-tautology", "t.reason"):
            self.assertIn(needle, js, needle)
        self.assertLess(js.index("tautologySection(r));"), js.index("flakySection(r));"))

    def test_the_receipt_page_script_renders_every_section_the_contract_has(self):
        js = (STATIC / "app.js").read_text()
        self.assertIn('["mutation_check", "Mutation check (harness)", false]', js)
        self.assertIn('["flake_check", "Rerun the test, expect the same result (harness)", false]', js)
        self.assertIn('["verdict", "Decide the verdict (harness)", true]', js)
        for needle in ("flakySection(r)", "mutationSection(r)", "Rerun check", "Mutation check", "verdict_logs", "base_fail_rate", "head_pass_rate", "flake_rate", "kill_rate", "threshold", "mu.what"):
            self.assertIn(needle, js, needle)


class EvalFixtureTests(unittest.TestCase):
    """/api/eval hands the summary through unchanged, so the new per-case and top-level fields reach eval.js intact."""

    def test_cases_carry_verdict_reason_and_flaky_and_the_summary_carries_the_flaky_totals(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runs = Path(tmp.name) / "latch" / "runs"
        (runs / "eval").mkdir(parents=True)
        wrong = verdict_receipt("FIX_FAILS_TEST")
        (runs / "eval" / "wrong.json").write_text(json.dumps(wrong))
        summary = {
            "featured_wrong_fix_receipt": "latch/runs/eval/wrong.json",
            "flaky": {"n_cases_checked": 3, "n_flaky": 1, "median_flake_rate": 0.0},
            "cases": [
                {"case": "wrong-1", "variant": "wrong_fix", "status": "ran", "verdict": "FIX_FAILS_TEST", "verdict_reason": "the proof test fails on the change under test too", "flaky": STABLE},
                {"case": "real-1", "variant": "real_fix", "status": "ran", "verdict": "VALIDATED", "verdict_reason": "red on base with an assertion, green on head", "flaky": STABLE},
                {"case": "real-2", "variant": "real_fix", "status": "ran", "verdict": "FLAKY", "verdict_reason": "inconsistent", "flaky": FLAKY_RUN},
                {"case": "real-3", "variant": "real_fix", "status": "not run"},
            ],
        }
        (runs / "eval-summary.json").write_text(json.dumps(summary))
        with mock.patch.dict(os.environ, {"LATCH_EVAL_ROOT": tmp.name}):
            body = Harness(self).get_json("/api/eval")[1]
        self.assertEqual(body["summary"], summary)
        self.assertEqual(body["featured"]["meta"]["verdict_code"], "FIX_FAILS_TEST")
        self.assertEqual(body["featured"]["meta"]["verdict"], "not_proven")

    def test_the_eval_script_renders_the_verdict_breakdown_the_flaky_summary_and_per_case_cells(self):
        js = (STATIC / "eval.js").read_text()
        for needle in ("breakdown(cases)", "n_cases_checked", "n_flaky", "median_flake_rate", "verdict_reason", "caseFlaky", "caseVerdict", "Median mutation kill rate"):
            self.assertIn(needle, js, needle)


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class VerdictModuleTests(unittest.TestCase):
    """Run the real static/verdict.js under node: it is the single place the verdict wording and fail-closed rules live."""

    def call(self, expr):
        script = "global.window = {}; require(%s); process.stdout.write(JSON.stringify(%s));" % (json.dumps(str(STATIC / "verdict.js")), expr)
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(out.stdout)

    def info(self, receipt_obj, meta=None):
        return self.call("window.LatchVerdict.info(%s, %s)" % (json.dumps(receipt_obj), json.dumps(meta or {})))

    def test_only_validated_is_a_pass_and_every_other_verdict_carries_its_reason(self):
        for code in CODES:
            got = self.info(verdict_receipt(code))
            self.assertEqual(got["code"], code)
            self.assertEqual(got["pass"], code == "VALIDATED", code)
            self.assertEqual(got["meaning"], MEANINGS[code])
            self.assertEqual(got["reason"], store._sentence(verdict_receipt(code)["verdict_reason"]))
        self.assertEqual(len({self.info(verdict_receipt(c))["label"] for c in CODES}), 6)

    def test_old_receipts_fall_back_to_proven_and_not_proven(self):
        self.assertEqual(self.info(receipt(BASE, HEAD, proven=True))["label"], "Proven")
        old = self.info(receipt(BASE, HEAD, proven=False), {"why_not_proven": "the head still fails"})
        self.assertEqual((old["label"], old["pass"], old["code"]), ("Not proven", False, None))
        self.assertIn("the head still fails", old["meaning"])

    def test_a_contradiction_or_an_unknown_verdict_never_reads_as_a_pass(self):
        self.assertFalse(self.info(verdict_receipt("VALIDATED", proven=False))["pass"])
        for code in CODES[:-1]:
            self.assertFalse(self.info(verdict_receipt(code, proven=True))["pass"], code)
        unknown = self.info(verdict_receipt("VALIDATED", verdict="PROBABLY_FINE", proven=True))
        self.assertFalse(unknown["pass"])
        self.assertEqual(unknown["label"], "Unrecognised verdict")

    def test_the_breakdown_counts_every_verdict_from_the_cases_and_keeps_unlabelled_cases_out_of_the_passes(self):
        cases = [{"verdict": "VALIDATED"}, {"verdict": "VALIDATED"}, {"verdict": "FIX_FAILS_TEST"}, {"verdict": "FLAKY"},
                 {"verdict": "NOPE"}, {"status": "not run"}, None]
        got = self.call("window.LatchVerdict.breakdown(%s)" % json.dumps(cases))
        self.assertEqual(got["counts"], {"INVALID_TEST": 0, "FLAKY": 1, "NO_REGRESSION_FOUND": 0, "FIX_FAILS_TEST": 1, "MUTATION_SURVIVED": 0, "VALIDATED": 2})
        self.assertEqual((got["none"], got["total"]), (3, 7))
        self.assertEqual(list(got["counts"]), list(CODES))
        self.assertEqual(self.call("window.LatchVerdict.breakdown(undefined)")["total"], 0)


class StepNamesAndMutantStateTests(unittest.TestCase):
    """The harness step names (fix, flake_check, mutation_check) and the mutant states it can report."""

    @classmethod
    def setUpClass(cls):
        cls.app = (STATIC / "app.js").read_text()
        cls.loop = (STATIC / "loop.js").read_text()

    def test_the_ledger_lists_the_harness_steps_in_pipeline_order(self):
        order = ["fetch", "repo_map", "test_writer", "base_run", "head_run", "triage", "fix", "flake_check", "revert_check", "mutation_check", "verdict"]
        at = [self.app.index('["%s",' % name) for name in order]
        self.assertEqual(at, sorted(at), "the ledger rows are out of pipeline order")
        self.assertIn('["flake_check", "Rerun the test, expect the same result (harness)", false]', self.app)
        self.assertIn('["fix", "Fix the change (agent loop)", false]', self.app)

    def test_the_old_mutation_step_name_is_mapped_to_mutation_check(self):
        self.assertIn('"mutation": "mutation_check"', self.app)
        self.assertIn("STEP_ALIAS", self.app)

    def test_the_flake_check_detail_fields_are_read_when_shown(self):
        for field in ("flake_rate", "base_fail_rate", "head_pass_rate"):
            self.assertIn(field, self.app)

    def test_timed_out_and_errored_mutants_are_not_labelled_survived(self):
        self.assertIn("function mutantState", self.app)
        for needle in ('"timed out"', '"error"', "timed_out", "mu.error"):
            self.assertIn(needle, self.app)
        self.assertIn("data-state", self.app.replace("setAttribute(\"data-state\"", "data-state"))

    def test_a_mutation_check_that_did_not_run_fails_closed(self):
        self.assertIn("mu.ran === false", self.app)
        self.assertIn('"not-run"', self.app)
        self.assertIn("This is not a pass.", self.app)
        self.assertIn("a check that did not run has no mutants worth listing", self.app)

    def test_the_gate_and_the_named_verdict_are_read_separately_for_loop_receipts(self):
        for needle in ("function gateHolds", "function finalVerdict", "No verdict: infrastructure error", "Gate open, not validated"):
            self.assertIn(needle, self.loop)

    def test_a_final_event_with_a_new_receipt_shows_only_the_receipts_verdict(self):
        self.assertIn('Object.prototype.hasOwnProperty.call(ev.receipt, "gate")', self.loop)
        self.assertIn("a final event shows its receipt's verdict instead", self.loop)

    def test_the_recorded_loop_demo_with_the_old_receipt_shape_still_loads(self):
        h = Harness(self)
        status, body = h.get_json("/api/loop/example")
        if status == 404:
            self.skipTest("no recorded loop run is installed")
        self.assertEqual(status, 200)
        events = body["events"]
        self.assertTrue(events and events[-1].get("receipt"))
        self.assertNotIn("gate", events[-1]["receipt"], "the recorded demo predates the gate field")


CAUTION = "Mutation check incomplete: this verdict is not mutation-backed."
INCOMPLETE_NOTE = "mutation check incomplete: budget exhausted after 2 of 5 mutants, the verdict is not mutation-backed"


def not_run_mutant(i):
    """What mutate.py leaves for a mutant the budget never reached: in the list, not killed, no error."""
    m = mutant(i, False)
    for key in ("diff", "output_excerpt"):
        m.pop(key)
    m.update(not_run=True)
    return m


def incomplete_mutation(ran=2, total=5):
    mutants = [mutant(i + 1, True) for i in range(ran)] + [not_run_mutant(i + 1) for i in range(ran, total)]
    return {"ran": True, "mutants": mutants, "killed": ran, "total": ran, "kill_rate": 1.0 if ran else None, "threshold": harness.MUTATION_THRESHOLD,
            "ok": True, "not_run": total - ran, "incomplete": True, "note": INCOMPLETE_NOTE}


class IncompleteMutationTests(unittest.TestCase):
    """A budget-limited mutation check: unreached mutants are 'not run', and the verdict says it is not mutation-backed."""

    @classmethod
    def setUpClass(cls):
        cls.app = (STATIC / "app.js").read_text()
        cls.css = (STATIC / "app.css").read_text()

    def test_the_harness_still_validates_when_the_check_is_incomplete(self):
        for ran in (0, 2):
            evidence = copy.deepcopy(dict(EVIDENCE["VALIDATED"], test_name="test_x", suite_ok=True))
            evidence["mutation"] = incomplete_mutation(ran)
            fields = harness.verdict_fields(evidence, BASE, HEAD)
            self.assertEqual(fields["verdict"], "VALIDATED")
            self.assertIn("not mutation-backed", fields["verdict_reason"])

    def test_not_run_mutants_get_their_own_neutral_state_and_never_read_as_killed_or_survived(self):
        state = self.app[self.app.index("function mutantState"):]
        state = state[:state.index("\n  }\n")]
        self.assertIn("not run (budget)", state)
        self.assertLess(state.index("not_run === true"), state.index('"survived"'))
        self.assertLess(state.index("not_run === true"), state.index('"killed"'))
        for needle in ("neutralPill", "is-notrun", "const killed = mu.killed === true && !notRun"):
            self.assertIn(needle, self.app)
        for rule in (".pill.neutral", ".mutant.is-notrun"):
            self.assertIn(rule, self.css)
        neutral = self.css[self.css.index(".pill.neutral"):]
        neutral = neutral[:neutral.index("}")]
        self.assertNotIn("--pass", neutral)
        self.assertNotIn("--fail", neutral)

    def test_the_score_counts_mutants_that_ran_and_the_ones_that_did_not(self):
        for needle in ("not_run", "mutation-notrun", " not run", "killed of the mutants that ran", "reached"):
            self.assertIn(needle, self.app)
        self.assertIn("survived = reached.filter", self.app.replace("const survived = reached.filter", "survived = reached.filter"))

    def test_an_incomplete_check_carries_the_caution_in_the_verdict_and_in_the_mutation_section(self):
        self.assertIn('const CAUTION = "%s"' % CAUTION, self.app)
        for needle in ("isIncomplete(r)", "verdict-caution", "mutation-caution", '"incomplete"'):
            self.assertIn(needle, self.app)
        self.assertIn(".caution", self.css)
        hero = self.app[self.app.index("verdict-reason"):]
        self.assertLess(hero.index("verdict-caution"), hero.index("is-pass") if "is-pass" in hero else len(hero))

    def test_no_mutable_lines_and_an_incomplete_run_read_differently_in_the_ledger_and_the_section(self):
        self.assertIn("function mutationStepNote", self.app)
        self.assertIn("no mutable lines, so no mutants were generated", self.app)
        self.assertIn("not run (budget). Not mutation-backed.", self.app)
        self.assertIn("No mutable lines: no mutants were generated", self.app)
        # the step event is {0,0,null} for both, so the saved receipt decides; it runs before the ledger is finished
        result = self.app[self.app.index("function onResult"):]
        self.assertLess(result.index("mutationStepNote(data.receipt)"), result.index("finishSteps()"))

    def test_an_incomplete_receipt_is_stored_and_served_unchanged(self):
        h = Harness(self)
        sent = seed(h, 1, "VALIDATED", mutation=incomplete_mutation(2), verdict_reason=INCOMPLETE_NOTE)
        got = h.get_json("/api/receipt/acme/widgets/1")[1]
        self.assertEqual(got["receipt"], sent)
        self.assertEqual(got["meta"]["verdict_code"], "VALIDATED")
        mu = got["receipt"]["mutation"]
        self.assertTrue(mu["incomplete"])
        self.assertEqual(mu["not_run"], 3)
        self.assertEqual([m for m in mu["mutants"] if m.get("not_run")], mu["mutants"][2:])
        for m in mu["mutants"][2:]:
            self.assertIs(m["killed"], False)
            self.assertNotIn("error", m)


# ---- survivor-driven strengthening (latch/strengthen.py, latch/loop/core.py, latch/prove.py) ----

def strengthened_mutation(outcome):
    """The mutation dict the engine leaves in the receipt, built with the engine's own record helpers.

    adopted / still_surviving: the NEW test's mutation result carries `strengthened`.
    kept_original: the ORIGINAL result carries it (the stronger test never reached the mutation check)."""
    first = mutation([True, False, False, True, False])  # 2 of 5 killed: below the 0.6 bar, three survivors
    record = strengthening.new_record(first, strengthening.survivors(first), "test_x")
    if outcome == "kept_original":
        first["strengthened"] = strengthening.finish(record, outcome, "the stronger test does not fail on the base revision with an assertion")
        return first
    after = mutation([True] * 5) if outcome == "adopted" else mutation([True, False, True, False, False])
    after["strengthened"] = strengthening.finish(
        record, outcome, None if outcome == "adopted" else "the stronger test still killed too few mutants", after, "chatcmpl-stronger")
    return after


def strengthened_receipt(outcome, **extra):
    """A receipt whose verdict_fields were decided by the real harness for that mutation result."""
    code = "VALIDATED" if outcome == "adopted" else "MUTATION_SURVIVED"
    m = strengthened_mutation(outcome)
    evidence = copy.deepcopy(dict(EVIDENCE[code], test_name="test_x", suite_ok=True))
    evidence["mutation"] = m
    fields = harness.verdict_fields(evidence, BASE, HEAD)
    assert fields["verdict"] == code, (code, fields["verdict"])
    r = verdict_receipt(code, mutation=m, verdict_reason=fields["verdict_reason"], verdict_logs=fields["verdict_logs"])
    r.update(extra)
    return r


LONG_ERROR = "ValueError: could not convert string to float: " + "'" + "x" * 90 + "'"


def invalid_test_receipt():
    """INVALID_TEST whose reason now names the error that ended the proof test (an unbroken 160-character excerpt)."""
    base = {"returncode": 1, "stdout": "____ test_x ____\nE   " + LONG_ERROR + "\n1 failed", "stderr": ""}
    evidence = {"base": base, "head": PASS, "test_name": "test_x", "suite_ok": True}
    fields = harness.verdict_fields(copy.deepcopy(evidence), BASE, HEAD)
    assert fields["verdict"] == "INVALID_TEST", fields["verdict"]
    r = verdict_receipt("INVALID_TEST", verdict_reason=fields["verdict_reason"])
    r["base_result"] = base
    return r


def run_node(source):
    out = subprocess.run([NODE, "-e", "global.window={};require(%s);const L=window.LatchVerdict;process.stdout.write(JSON.stringify(%s))"
                          % (json.dumps(str(STATIC / "verdict.js")), source)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


class StrengthenedTests(unittest.TestCase):
    """mutation.strengthened and the `strengthen` step: shown plainly, the first attempt kept visible, the verdict never softened."""

    @classmethod
    def setUpClass(cls):
        cls.app = (STATIC / "app.js").read_text()
        cls.css = (STATIC / "app.css").read_text()
        cls.loop = (STATIC / "loop.js").read_text()

    def test_the_fixtures_have_the_exact_keys_the_engine_writes(self):
        adopted = strengthened_mutation("adopted")["strengthened"]
        self.assertEqual(set(adopted), {"attempted", "survivors_before", "killed_before", "total_before", "kill_rate_before", "threshold",
                                        "test_before", "outcome", "completion_id", "killed_after", "total_after", "kill_rate_after"})
        self.assertEqual((adopted["killed_before"], adopted["total_before"], adopted["kill_rate_before"]), (2, 5, 0.4))
        self.assertEqual(len(adopted["survivors_before"]), 3)
        self.assertEqual(set(adopted["survivors_before"][0]), set(strengthening.RECORD_KEYS))
        kept = strengthened_mutation("kept_original")["strengthened"]
        self.assertNotIn("killed_after", kept)
        self.assertTrue(kept["reason"])
        self.assertEqual(strengthening.not_attempted("strengthening is off"), {"attempted": False, "reason": "strengthening is off"})

    def test_the_harness_names_the_strengthening_round_in_the_reason_only_when_the_stronger_test_was_judged(self):
        self.assertIn("after one strengthening round (it was 2/5 before)", strengthened_receipt("adopted")["verdict_reason"])
        self.assertIn("after one strengthening round", strengthened_receipt("still_surviving")["verdict_reason"])
        self.assertNotIn("strengthening", strengthened_receipt("kept_original")["verdict_reason"])
        for outcome in ("still_surviving", "kept_original"):
            self.assertEqual(strengthened_receipt(outcome)["verdict"], "MUTATION_SURVIVED")
            self.assertFalse(strengthened_receipt(outcome)["proven"])
        self.assertEqual(strengthened_receipt("adopted")["verdict"], "VALIDATED")

    def test_the_plain_line_reads_the_engine_record_for_every_outcome(self):
        if not NODE:
            self.skipTest("node is not installed")
        got = {o: run_node("L.strengthened(%s,{cleared:%s})" % (json.dumps(strengthened_mutation(o)["strengthened"]),
                                                               "true" if o == "adopted" else "false")) for o in ("adopted", "still_surviving", "kept_original")}
        self.assertEqual(got["adopted"]["state"], "adopted")
        self.assertEqual(got["adopted"]["text"], "First test let 3 mutants survive (kill rate 40%); Latch wrote a stronger test, which now kills 5/5 (100%).")
        self.assertEqual(got["still_surviving"]["state"], "still_surviving")
        self.assertIn("it still let 3 mutants survive (kill rate 40%)", got["still_surviving"]["text"])
        self.assertTrue(got["still_surviving"]["text"].endswith("so the Mutation survived verdict stands."))
        self.assertEqual(got["kept_original"]["state"], "kept_original")
        self.assertIn("it did not clear the gate (the stronger test does not fail on the base revision with an assertion)", got["kept_original"]["text"])
        self.assertTrue(got["kept_original"]["text"].endswith("The original test and its Mutation survived verdict stand."))
        self.assertNotIn("now kills", got["kept_original"]["text"])

    def test_the_line_never_claims_more_than_the_receipt_says(self):
        if not NODE:
            self.skipTest("node is not installed")
        adopted = json.dumps(strengthened_mutation("adopted")["strengthened"])
        # adopted, yet the receipt's own mutation result did not clear the bar: that result wins
        self.assertEqual(run_node("L.strengthened(%s,{cleared:false})" % adopted)["state"], "still_surviving")
        # an outcome this page does not know, or none at all, says only that the verdict stands
        for rec in ({"attempted": True, "survivors_before": [], "kill_rate_before": 0.4, "outcome": "somethingnew"}, {"attempted": True}):
            got = run_node("L.strengthened(%s)" % json.dumps(rec))
            self.assertEqual(got["state"], "unknown")
            self.assertIn("verdict stands as written", got["text"])
            self.assertNotIn("now kills", got["text"])
        self.assertEqual(run_node("L.strengthened({attempted:false,reason:'strengthening is off'})")["text"],
                         "Latch did not write a stronger test: strengthening is off.")
        # live (step event) form, one survivor
        self.assertEqual(run_node("L.strengthened({live:true,survivors_before:1,kill_rate_before:0.5})")["text"],
                         "First test let 1 mutant survive (kill rate 50%); Latch is writing a stronger test.")

    def test_absent_or_hostile_values_never_throw(self):
        if not NODE:
            self.skipTest("node is not installed")
        self.assertEqual(run_node("[L.strengthened(null),L.strengthened(undefined),L.strengthened('x'),L.strengthened([]),L.strengthened(7)]"),
                         [None] * 5)
        hostile = {"attempted": True, "outcome": {"a": 1}, "survivors_before": "many", "kill_rate_before": "0.4", "killed_after": "5", "reason": ["x"]}
        self.assertEqual(run_node("L.strengthened(%s)" % json.dumps(hostile))["state"], "unknown")

    def test_a_receipt_with_strengthening_is_stored_and_served_unchanged(self):
        h = Harness(self)
        for number, outcome in ((81, "adopted"), (82, "still_surviving"), (83, "kept_original")):
            sent = seed(h, number, "VALIDATED" if outcome == "adopted" else "MUTATION_SURVIVED", mutation=strengthened_mutation(outcome))
            got = h.get_json(f"/api/receipt/acme/widgets/{number}")[1]
            self.assertEqual(got["receipt"]["mutation"], sent["mutation"])
            self.assertEqual(got["receipt"]["mutation"]["strengthened"]["outcome"], outcome)

    def test_the_receipt_view_renders_the_block_with_the_first_attempt_kept_and_marked(self):
        block = self.app[self.app.index("function strengthenedBlock"):]
        block = block[:block.index("function mutationSection")]
        for needle in ("LatchVerdict.strengthened", "data-strengthened", "Strengthened test", "First test", "(superseded)", "Stronger test",
                       "not adopted; the original test is the one judged", "the first test missed", "survivors_before"):
            self.assertIn(needle, block)
        # the originals are shown as survivors even though the record has no `killed` key; text only, never HTML
        self.assertIn("killed: false", block)
        self.assertNotIn("innerHTML", block)
        self.assertIn("const stronger = strengthenedBlock(mu)", self.app)

    def test_the_ledger_groups_the_repeated_gate_steps_after_strengthen_and_marks_the_first_attempt_superseded(self):
        for needle in ('const REPEATS = ["base_run", "head_run", "flake_check", "revert_check", "mutation_check"]', "round2",
                       '"superseded"', '"discarded"', "Strengthened test", "in-round", "LAST occurrence"):
            self.assertIn(needle, self.app)
        apply = self.app[self.app.index("function applyEvent"):]
        apply = apply[:apply.index("function applyLegacy")]
        self.assertIn('d.step === "strengthen"', apply)
        self.assertIn("unknown step name never breaks the ledger", apply)
        self.assertLess(apply.index('d.step === "strengthen"'), apply.index("if (!s) return"))
        # a round that never reached the mutation check (kept_original) does not demote the first attempt
        self.assertIn('round2.outcome !== "kept_original"', self.app)
        # the verdict row is decided last and its reason is never truncated
        draw = self.app[self.app.index("function drawSteps"):self.app.index("function applyEvent")]
        self.assertLess(draw.index("round2"), draw.index('LEDGER.find((x) => x[0] === "verdict")'))
        self.assertIn("verdict reasons show in full", draw)
        # the saved receipt note goes to the current mutation_check row
        result = self.app[self.app.index("function onResult"):]
        self.assertIn("round2.steps.mutation_check", result[:result.index("finishSteps()")])
        for rule in ('.steps li.round', 'li[data-mark="superseded"]', ".strengthened", '.strengthened[data-strengthened="kept_original"]'):
            self.assertIn(rule, self.css)

    def test_the_loop_timeline_shows_the_strengthen_step_and_hides_every_other_step_event(self):
        step = self.loop[self.loop.index('case "step"'):self.loop.index('case "proof_test"')]
        self.assertIn('ev.step !== "strengthen"', step)
        self.assertIn("return null", step)
        self.assertIn("Stronger proof test written and frozen", self.loop)
        self.assertIn("strengthened-line", self.loop)

    def test_invalid_test_reasons_name_the_error_and_display_in_full_without_overflow(self):
        r = invalid_test_receipt()
        self.assertIn("(" + LONG_ERROR[:100], r["verdict_reason"])
        self.assertGreater(len(r["verdict_reason"]), 200)
        for selector in (".verdict-reason", ".case-reason", ".steps .sub"):
            rule = self.css[self.css.index(selector):] if selector in self.css else (STATIC / "eval.css").read_text()[(STATIC / "eval.css").read_text().index(selector):]
            self.assertIn("overflow-wrap: anywhere", rule[:rule.index("}")], selector)
        self.assertIn("overflow-wrap: anywhere", (STATIC / "loop.css").read_text()[(STATIC / "loop.css").read_text().index(".tl-meta"):][:260])
        h = Harness(self)
        sent = seed(h, 84, "INVALID_TEST", verdict_reason=r["verdict_reason"])
        self.assertEqual(h.get_json("/api/receipt/acme/widgets/84")[1]["receipt"]["verdict_reason"], sent["verdict_reason"])


class TimeoutAndEnvReuseTests(unittest.TestCase):
    def test_the_loop_timeout_covers_reruns_and_mutants_and_can_be_overridden(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LATCH_LOOP_TIMEOUT", None)
            self.assertGreaterEqual(Config().loop_timeout, 900)
        with mock.patch.dict(os.environ, {"LATCH_LOOP_TIMEOUT": "123"}):
            self.assertEqual(Config().loop_timeout, 123)

    def test_a_prepared_environment_is_reused_by_the_next_run_in_the_same_snapshot(self):
        from latch.web.sandbox import SandboxConfig, SandboxRunner
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)
            python = snapshot / ".latch-venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("")
            runner = SandboxRunner(SandboxConfig(install="auto", net_isolation="off"))
            with mock.patch.object(SandboxRunner, "_run", side_effect=AssertionError("setup must not run again")):
                # not marked ready: the setup runs (and would call _run)
                with self.assertRaises(AssertionError):
                    runner._setup(snapshot, snapshot / ".latch-home", "head")
                (snapshot / ".latch-venv" / ".latch-ready").write_text("ok\n")
                self.assertEqual(runner._setup(snapshot, snapshot / ".latch-home", "head"), snapshot / ".latch-venv")


if __name__ == "__main__":
    unittest.main()
