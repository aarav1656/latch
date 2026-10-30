import unittest

from latch import verdict as v

FAIL = {"returncode": 1, "stdout": "____ test_x ____\nE   AssertionError: no\n", "stderr": ""}
PASS = {"returncode": 0, "stdout": "1 passed", "stderr": ""}
ERR = {"returncode": 2, "stdout": "ERROR collecting latch_issue_test.py\nImportError", "stderr": ""}
STABLE = v.flake_summary([False] * 5, [True] * 5)


def ev(**kw):
    base = {"base": FAIL, "head": PASS, "test_name": "test_x", "flaky": STABLE, "suite_ok": True,
            "revert": {"ran": True, "ok": True, "summary": "ok"}, "mutation": {"ok": True, "killed": 3, "total": 4, "kill_rate": 0.75, "threshold": 0.6}}
    base.update(kw)
    return base


class DecideTests(unittest.TestCase):
    def test_validated(self):
        verdict, reason = v.decide_verdict(ev())
        self.assertEqual(verdict, v.VALIDATED)
        self.assertIn("3/4 mutants", reason)

    def test_five_requested_names_exist(self):
        self.assertEqual({v.VALIDATED, v.NO_REGRESSION_FOUND, v.INVALID_TEST, v.MUTATION_SURVIVED, v.FLAKY} - set(v.VERDICTS), set())

    def test_precedence_in_order(self):
        every = ev(rejected="vacuous", base=PASS, flaky=v.flake_summary([True, False], [True, True]),
                   revert={"ran": True, "ok": False, "summary": "survived"})
        self.assertEqual(v.decide_verdict(every)[0], v.INVALID_TEST)               # 1 beats everything
        every.pop("rejected")
        self.assertEqual(v.decide_verdict(every)[0], v.FLAKY)                      # 2 beats no-regression
        every["flaky"] = STABLE
        self.assertEqual(v.decide_verdict(every)[0], v.NO_REGRESSION_FOUND)        # 3 beats mutation
        every["base"] = FAIL
        self.assertEqual(v.decide_verdict(every)[0], v.MUTATION_SURVIVED)          # 5
        every["revert"] = {"ran": True, "ok": True}
        self.assertEqual(v.decide_verdict(every)[0], v.VALIDATED)

    def test_invalid_variants(self):
        for kw in ({"rejected": "x"}, {"base": ERR}, {"head": ERR}, {"base": None}, {"tautology": {"checked": True, "ok": False, "reason": "tautology"}},
                   {"triage_blocked": "triage said no"}):
            self.assertEqual(v.decide_verdict(ev(**kw))[0], v.INVALID_TEST, kw)

    def test_flaky_beats_no_regression(self):
        self.assertEqual(v.decide_verdict(ev(base=PASS, flaky=v.flake_summary([True, False, True], [True] * 3)))[0], v.FLAKY)

    def test_patch_that_fails_the_test_or_suite(self):
        self.assertEqual(v.decide_verdict(ev(head=FAIL))[0], v.FIX_FAILS_TEST)
        self.assertEqual(v.decide_verdict(ev(suite_ok=False))[0], v.FIX_FAILS_TEST)

    def test_mutation_gate(self):
        low = {"ok": False, "killed": 1, "total": 4, "kill_rate": 0.25, "threshold": 0.6}
        verdict, reason = v.decide_verdict(ev(mutation=low))
        self.assertEqual(verdict, v.MUTATION_SURVIVED)
        self.assertIn("25%", reason)
        self.assertEqual(v.decide_verdict(ev(mutation={"ok": False, "kill_rate": None, "total": 0, "note": "could not run"}))[0], v.MUTATION_SURVIVED)
        none_to_mutate = v.decide_verdict(ev(mutation={"ok": True, "killed": 0, "total": 0, "kill_rate": None}))
        self.assertEqual(none_to_mutate[0], v.VALIDATED)
        self.assertIn("no mutable lines", none_to_mutate[1])

    def test_an_incomplete_mutation_check_validates_but_says_it_is_not_mutation_backed(self):
        inc = {"ok": True, "incomplete": True, "killed": 0, "total": 1, "kill_rate": 0.0, "not_run": 4,
               "note": "mutation check incomplete: budget (1 of 5 mutants ran, 4 not run within 240s)"}
        verdict, reason = v.decide_verdict(ev(mutation=inc))
        self.assertEqual(verdict, v.VALIDATED)
        self.assertIn("mutation check incomplete: budget", reason)
        none_ran = v.decide_verdict(ev(mutation={**inc, "total": 0, "kill_rate": None, "not_run": 5}))
        self.assertEqual(none_ran[0], v.VALIDATED)
        self.assertIn("mutation check incomplete: budget", none_ran[1])
        self.assertNotIn("no mutable lines", none_ran[1])
        partial = v.decide_verdict(ev(mutation={"ok": True, "killed": 3, "total": 3, "kill_rate": 1.0, "not_run": 2}))
        self.assertIn("killed 3/3 mutants", partial[1])
        self.assertIn("2 more mutants were not run: budget", partial[1])

    def test_revert_skipped_does_not_block_but_is_noted(self):
        verdict, reason = v.decide_verdict(ev(revert={"ran": False, "skipped": "revert check disabled"}))
        self.assertEqual(verdict, v.VALIDATED)
        self.assertIn("disabled", reason)


class FlakeSummaryTests(unittest.TestCase):
    def test_rates(self):
        s = v.flake_summary([False] * 5, [True] * 5)
        self.assertEqual((s["flaky"], s["base_fail_rate"], s["head_pass_rate"], s["flake_rate"], s["runs"]), (False, 1.0, 1.0, 0.0, 5))
        s = v.flake_summary([False, False, False, True, False], [True] * 5)
        self.assertTrue(s["flaky"])
        self.assertEqual((s["base_fail_rate"], s["flake_rate"]), (0.8, 0.1))


class FieldsTests(unittest.TestCase):
    def test_proven_is_derived_and_fields_present(self):
        f = v.verdict_fields(ev(), "b" * 40, "h" * 40)
        self.assertTrue(f["proven"])
        self.assertEqual((f["base_sha"], f["head_sha"]), ("b" * 40, "h" * 40))
        for name in v.RECEIPT_FIELDS:
            self.assertIn(name, f)
        bad = v.verdict_fields(ev(head=FAIL))
        self.assertFalse(bad["proven"])
        self.assertIn("AssertionError", bad["verdict_logs"]["head"])

    def test_survivors_listed(self):
        m = {"ok": False, "killed": 0, "total": 1, "kill_rate": 0.0, "threshold": 0.6,
             "mutants": [{"id": "m1", "operator": "bool_swap", "file": "a.py", "line": 3, "killed": False, "output_excerpt": "1 passed"}]}
        f = v.verdict_fields(ev(mutation=m))
        self.assertEqual(f["verdict"], v.MUTATION_SURVIVED)
        self.assertEqual(f["verdict_logs"]["survivors"][0]["id"], "m1")


if __name__ == "__main__":
    unittest.main()
