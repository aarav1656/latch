"""Offline tests for the AST mutation check: stub runners only, no model calls."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from latch import mutate
from latch.revert import is_test_path

OLD = "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    return x\n"
NEW = ("def clamp(x, lo, hi):\n    if x < lo or x > hi:\n        return lo if x < lo else hi\n"
       "    flag = x == 3 and lo == 0\n    return x + 1 if flag else x\n")


def operators(source, lines):
    return sorted({c["operator"] for c in mutate.candidates(source, lines)})


class OperatorTests(unittest.TestCase):
    def test_changed_lines_are_the_inserted_and_replaced_lines_of_the_new_text(self):
        self.assertEqual(mutate.changed_lines(OLD, NEW), {2, 3, 4, 5})
        self.assertEqual(mutate.changed_lines(NEW, NEW), set())
        self.assertEqual(mutate.changed_lines("", "a = 1\nb = 2\n"), {1, 2})

    def test_every_operator_family_is_generated_for_the_changed_lines_only(self):
        found = {c["operator"] for c in mutate.candidates(NEW, {2, 3, 4, 5})}
        self.assertEqual(found, set(mutate.OPERATORS))
        self.assertEqual(operators(NEW, {1}), [])  # the def line has nothing to mutate

    def test_boundary_flip(self):
        source = "def f(x):\n    return x < 3\n"
        cand = next(c for c in mutate.candidates(source, {2}) if c["operator"] == "compare_boundary")
        self.assertEqual(mutate.apply_candidate(source, cand), "def f(x):\n    return x <= 3\n")

    def test_negated_condition_wraps_the_test_in_not(self):
        source = "def f(x):\n    if x > 1:\n        return 2\n    return 3\n"
        cand = next(c for c in mutate.candidates(source, {2}) if c["what"] == "negated the condition")
        self.assertIn("if not (x > 1):", mutate.apply_candidate(source, cand))

    def test_and_or_swap(self):
        source = "def f(a, b):\n    return a and b\n"
        cand = next(c for c in mutate.candidates(source, {2}) if c["operator"] == "bool_swap")
        self.assertEqual(mutate.apply_candidate(source, cand), "def f(a, b):\n    return a or b\n")

    def test_int_constant_off_by_one_leaves_floats_and_strings_alone(self):
        source = "def f():\n    a = 1.5\n    b = '7'\n    return 7\n"
        cands = [c for c in mutate.candidates(source, {2, 3, 4}) if c["operator"] == "const_off_by_one"]
        self.assertEqual([c["what"] for c in cands], ["constant 7 -> 8"])

    def test_return_none_skips_a_bare_none_return(self):
        source = "def f(x):\n    if x:\n        return None\n    return x\n"
        cands = [c for c in mutate.candidates(source, {3, 4}) if c["operator"] == "return_none"]
        self.assertEqual([c["line"] for c in cands], [4])

    def test_generated_mutants_are_valid_distinct_python_capped_and_varied(self):
        mutants = mutate.generate_mutants({"clamp.py": (NEW, {2, 3, 4, 5})})
        self.assertEqual(len(mutants), 5)
        self.assertEqual(len({m["operator"] for m in mutants}), 5)  # one of each operator before any repeats
        self.assertEqual([m["id"] for m in mutants], ["m1", "m2", "m3", "m4", "m5"])
        for m in mutants:
            compile(m["source"], "clamp.py", "exec")
            self.assertNotEqual(m["source"], NEW)
            self.assertIn("@@", m["diff"])
        self.assertEqual(len(mutate.generate_mutants({"clamp.py": (NEW, {2, 3, 4, 5})}, max_mutants=3)), 3)

    def test_a_syntax_error_in_a_file_is_skipped(self):
        self.assertEqual(mutate.generate_mutants({"bad.py": ("def (:\n", {1})}), [])


class MutationCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.head, self.base, self.work = root / "head", root / "base", root / "work"
        for tree, text in ((self.head, NEW), (self.base, OLD)):
            tree.mkdir()
            (tree / "clamp.py").write_text(text)
        self.work.mkdir()
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, run, **kw):
        return mutate.mutation_check(run, self.head, self.base, ["clamp.py"], "def test_x():\n    pass\n", "latch_issue_test.py",
                                     self.work, **kw)

    def killer(self, kill):
        """A stub runner that fails (kills) the mutants whose ids are in `kill`."""
        def run(directory):
            self.calls.append(directory.name)
            self.assertTrue((directory / "latch_issue_test.py").exists())
            self.assertNotEqual((directory / "clamp.py").read_text(), NEW)  # it really is a mutant
            return {"returncode": 1 if directory.name.split("-")[1] in kill else 0, "stdout": "AssertionError", "stderr": ""}
        return run

    def test_all_killed_passes_with_a_kill_rate_of_one(self):
        out = self.check(self.killer({"m1", "m2", "m3", "m4", "m5"}))
        self.assertEqual((out["killed"], out["total"], out["kill_rate"], out["ok"]), (5, 5, 1.0, True))
        self.assertEqual(set(out["mutants"][0]), {"id", "operator", "file", "line", "what", "diff", "killed", "output_excerpt"})
        self.assertEqual(self.calls, ["mutant-m1", "mutant-m2", "mutant-m3", "mutant-m4", "mutant-m5"])

    def test_kill_rate_gate_is_sixty_percent(self):
        three = self.check(self.killer({"m1", "m2", "m3"}))
        self.assertEqual((three["kill_rate"], three["ok"]), (0.6, True))  # exactly at the threshold passes
        two = self.check(self.killer({"m1", "m2"}))
        self.assertEqual((two["kill_rate"], two["ok"]), (0.4, False))
        self.assertEqual([m["id"] for m in two["mutants"] if not m["killed"]], ["m3", "m4", "m5"])
        none = self.check(self.killer(set()))
        self.assertEqual((none["killed"], none["ok"]), (0, False))

    def test_no_mutable_lines_records_zero_and_does_not_block(self):
        (self.head / "clamp.py").write_text("def clamp(x, lo, hi):\n    x\n")
        (self.base / "clamp.py").write_text("def clamp(x, lo, hi):\n    pass\n")
        out = self.check(self.killer(set()))
        self.assertEqual((out["total"], out["killed"], out["kill_rate"], out["ok"]), (0, 0, None, True))
        self.assertIn("nothing to mutate", out["note"])
        self.assertEqual(self.calls, [])

    def test_unchanged_files_and_non_python_files_are_not_mutated(self):
        (self.base / "clamp.py").write_text(NEW)
        self.assertEqual(self.check(self.killer(set()))["total"], 0)

    def test_a_timeout_counts_as_killed(self):
        def run(directory):
            raise subprocess.TimeoutExpired("pytest", 60)
        out = self.check(run)
        self.assertEqual((out["killed"], out["ok"]), (5, True))
        self.assertTrue(all(m["timed_out"] for m in out["mutants"]))

    def test_an_infrastructure_error_is_never_a_kill(self):
        def run(directory):
            raise OSError("disk full")
        out = self.check(run)
        self.assertEqual((out["killed"], out["total"], out["ok"]), (0, 5, False))
        self.assertIn("OSError", out["mutants"][0]["error"])

    def test_the_time_budget_stops_running_mutants_and_counts_the_rest_as_survived(self):
        ticks = iter(range(0, 1000, 100))
        out = self.check(self.killer({"m1", "m2", "m3", "m4", "m5"}), time_budget=350, clock=lambda: next(ticks))
        self.assertEqual(self.calls, ["mutant-m1", "mutant-m2", "mutant-m3"])
        self.assertEqual((out["killed"], out["total"], out["ok"]), (3, 5, True))
        self.assertIn("time budget", out["mutants"][-1]["error"])

    def test_the_user_trees_are_never_modified_and_no_mutant_copy_is_left_behind(self):
        self.check(self.killer({"m1"}))
        self.assertEqual((self.head / "clamp.py").read_text(), NEW)
        self.assertEqual((self.base / "clamp.py").read_text(), OLD)
        self.assertFalse((self.head / "latch_issue_test.py").exists())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_the_head_tree_caches_and_vcs_dirs_are_not_copied(self):
        (self.head / "__pycache__").mkdir()
        (self.head / ".git").mkdir()
        (self.head / ".latch-venv").mkdir()
        seen = []

        def run(directory):
            seen.append(sorted(p.name for p in directory.iterdir()))
            return {"returncode": 1, "stdout": "", "stderr": ""}
        self.check(run, max_mutants=1)
        self.assertEqual(seen, [["clamp.py", "latch_issue_test.py"]])


class RunMutationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.head, self.base, self.work = root / "head", root / "base", root / "work"
        for tree in (self.head, self.base, self.work):
            tree.mkdir()
        (self.head / "clamp.py").write_text(NEW)
        (self.head / "test_clamp.py").write_text(NEW)
        (self.base / "clamp.py").write_text(OLD)
        self.seen = []

    def tearDown(self):
        self._tmp.cleanup()

    def go(self, changes, run=None, **kw):
        def default(directory):
            self.seen.append(directory.name)
            return {"returncode": 1, "stdout": "", "stderr": ""}
        return mutate.run_mutation(run or default, self.head, self.base, changes, "def test_x():\n    pass\n",
                                   "latch_issue_test.py", self.work, is_test_path, **kw)

    def test_only_added_or_modified_non_test_python_files_are_mutated(self):
        out = self.go([("M", "clamp.py"), ("M", "test_clamp.py"), ("D", "gone.py"), ("M", "README.md")])
        self.assertTrue(out["ran"] and out["ok"])
        self.assertEqual({m["file"] for m in out["mutants"]}, {"clamp.py"})

    def test_loop_files_are_mutated_too(self):
        (self.head / "extra.py").write_text("def g(x):\n    return x + 3\n")
        out = self.go([("M", "clamp.py")], loop_files=["extra.py"], max_mutants=30)
        self.assertIn("extra.py", {m["file"] for m in out["mutants"]})

    def test_a_check_that_cannot_run_fails_closed(self):
        def boom(directory):
            raise RuntimeError("never reached")
        out = mutate.run_mutation(boom, self.head / "missing", self.base, [("M", "clamp.py")], "t", "latch_issue_test.py",
                                  self.work, is_test_path)
        self.assertEqual((out["ran"], out["ok"], out["kill_rate"], out["total"]), (True, True, None, 0))  # missing file: nothing to mutate
        out = mutate.run_mutation(boom, self.head, self.base, [("M", "clamp.py")], "t", "latch_issue_test.py",
                                  Path("/proc/not/writable"), is_test_path, max_mutants="x")
        self.assertEqual((out["ran"], out["ok"], out["kill_rate"]), (False, False, None))

    def test_step_detail_is_exactly_killed_total_kill_rate(self):
        out = self.go([("M", "clamp.py")])
        detail = mutate.mutation_detail(out)
        self.assertEqual(set(detail), {"killed", "total", "kill_rate"})
        self.assertEqual(detail, {"killed": out["killed"], "total": out["total"], "kill_rate": 1.0})
        self.assertEqual(mutate.mutation_detail({"ok": False, "note": "x"}), {"killed": 0, "total": 0, "kill_rate": None})


if __name__ == "__main__":
    unittest.main()
