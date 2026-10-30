"""Flaky gate: rerun the proof test on base and head and report any inconsistency. No model calls.

`runs` counts the first run too, so a check with runs=5 does 4 extra runs on each side. A side that is not
the same on every run (pass on one, fail on another) makes the verdict FLAKY, whatever the first run said.
"""

import shutil
from pathlib import Path

from .verdict import FLAKE_RUNS, FLAKE_RUNS_MAX, flake_summary

# What a run leaves behind that could make the next run differ: bytecode caches, pytest's cache and the fake HOME.
_LEFTOVERS = ("__pycache__", ".pytest_cache", ".latch-home")


def clamp_runs(runs):
    """Number of runs per side: default 5, at most 10. 1 (or 0) switches the check off."""
    if runs is None:
        return FLAKE_RUNS
    return max(0, min(int(runs), FLAKE_RUNS_MAX))


def clean_snapshot(directory):
    """Remove caches left by the previous run so every rerun starts from the same files."""
    root = Path(directory)
    for name in _LEFTOVERS:
        for path in root.rglob(name):
            shutil.rmtree(path, ignore_errors=True)


def passed(result):
    return bool(result) and result.get("returncode") == 0


def flake_check(run_base, run_head, first_base_passed, first_head_passed, runs=FLAKE_RUNS):
    """Rerun until each side has `runs` outcomes. `run_base()` / `run_head()` return a result dict with a
    `returncode` (or raise: a rerun that cannot finish counts as a failed run). `run_head` may be None
    when only base is checked. Returns the `flaky` receipt dict (see latch.verdict.flake_summary)."""
    runs = clamp_runs(runs)
    if runs <= 1:
        return {"ran": False, "skipped": "flake check disabled", "flaky": False}

    def again(run):
        try:
            return passed(run())
        except Exception:  # timeouts and OS errors: the run did not pass
            return False

    base = [bool(first_base_passed)] + [again(run_base) for _ in range(runs - 1)]
    if run_head is None or first_head_passed is None:
        head, note = [], "head was not rerun"
    else:
        head, note = [bool(first_head_passed)] + [again(run_head) for _ in range(runs - 1)], None
    return flake_summary(base, head, note)
