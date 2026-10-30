"""Offline tests for the flaky gate: stub runners only, no model calls."""

import tempfile
import unittest
from pathlib import Path

from latch.flake import clamp_runs, clean_snapshot, flake_check
from latch.verdict import FLAKE_RUNS, FLAKE_RUNS_MAX


def scripted(outcomes):
    """A run function that returns the scripted pass/fail outcomes in order and counts its calls."""
    calls = []

    def run():
        calls.append(1)
        return {"returncode": 0 if outcomes[len(calls) - 1] else 1, "stdout": "", "stderr": ""}
    run.calls = calls
    return run


class FlakeCheckTests(unittest.TestCase):
    def test_stable_runs_are_not_flaky(self):
        base, head = scripted([False] * 4), scripted([True] * 4)
        out = flake_check(base, head, False, True, runs=5)
        self.assertEqual((len(base.calls), len(head.calls)), (4, 4))  # the first run on each side is already done
        self.assertFalse(out["flaky"])
        self.assertEqual((out["runs"], out["flake_rate"], out["base_fail_rate"], out["head_pass_rate"]), (5, 0.0, 1.0, 1.0))

    def test_one_odd_rerun_on_head_is_flaky(self):
        out = flake_check(scripted([False] * 4), scripted([True, True, False, True]), False, True, runs=5)
        self.assertTrue(out["flaky"])
        self.assertEqual(out["head_pass_rate"], 0.8)
        self.assertEqual(out["flake_rate"], 0.1)  # 1 disagreeing run out of 10
        self.assertEqual(out["outcomes"]["head_passed"], [True, True, True, False, True])

    def test_a_base_that_sometimes_passes_is_flaky(self):
        out = flake_check(scripted([False, True, False, False]), scripted([True] * 4), False, True, runs=5)
        self.assertTrue(out["flaky"])
        self.assertEqual(out["base_fail_rate"], 0.8)

    def test_the_first_run_counts_in_the_comparison(self):
        out = flake_check(scripted([True] * 4), scripted([True] * 4), False, True, runs=5)  # first base run failed, reruns passed
        self.assertTrue(out["flaky"])

    def test_runs_are_clamped_and_one_turns_the_check_off(self):
        self.assertEqual((clamp_runs(None), clamp_runs(99), clamp_runs(-3)), (FLAKE_RUNS, FLAKE_RUNS_MAX, 0))
        base, head = scripted([False] * 20), scripted([True] * 20)
        out = flake_check(base, head, False, True, runs=99)
        self.assertEqual((out["runs"], len(base.calls)), (FLAKE_RUNS_MAX, FLAKE_RUNS_MAX - 1))
        off = flake_check(base, head, False, True, runs=1)
        self.assertEqual((off["ran"], off["flaky"]), (False, False))

    def test_a_rerun_that_raises_counts_as_a_failed_run(self):
        def boom():
            raise TimeoutError("hung")
        out = flake_check(boom, scripted([True] * 4), True, True, runs=5)  # base passed first, then every rerun died
        self.assertTrue(out["flaky"])

    def test_base_only_check(self):
        base = scripted([True, True])
        out = flake_check(base, None, True, None, runs=3)
        self.assertFalse(out["flaky"])
        self.assertEqual(out["outcomes"]["head_passed"], [])
        self.assertIn("head was not rerun", out["note"])

    def test_clean_snapshot_removes_caches_but_keeps_the_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pkg" / "__pycache__").mkdir(parents=True)
            (root / ".latch-home").mkdir()
            (root / ".pytest_cache").mkdir()
            (root / "pkg" / "mod.py").write_text("x = 1\n")
            clean_snapshot(root)
            self.assertEqual(sorted(p.name for p in root.rglob("*")), ["mod.py", "pkg"])


if __name__ == "__main__":
    unittest.main()
