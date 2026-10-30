"""Harness-run mutation check: once the gate looks open, undo the fix and confirm the proof test goes red again.

A proof test that stays green after the fix is reverted is not testing the fix (it may be flaky, may depend on
something other than the changed code, or may have been satisfied by a changed test file). So after the gate
opens the harness
  1. reverts every non-test file the submitted change touched back to the base revision (all hunks, files
     the change added are removed, files it deleted are restored) and re-runs the frozen proof test, which must
     FAIL again with an assertion or the expected unexpected-operation failure; and
  2. when the fix loop rewrote files, restores those files to the submitted (known wrong) revision and re-runs
     the proof test, which must FAIL again; this shows the loop's edit, not luck, flipped the result.
If a mutant does not fail, the gate stays shut.
"""

import shutil
import subprocess
from pathlib import Path

from .prove import expected_base_failure

def is_test_path(rel):
    parts = Path(rel).parts
    name = parts[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or any(part in ("tests", "test") for part in parts[:-1])
    )


IGNORE = shutil.ignore_patterns(".latch-home", ".latch-suite-home", ".pytest_cache", "__pycache__", ".git")


def changed_files(repo, base, head):
    """[(status, path)] between two commits, statuses A/M/D (renames reported as D + A)."""
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-status", "--no-renames", "-z", base, head],
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "could not list changed files")
    parts = [p for p in out.stdout.split("\0") if p]
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def _copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def make_mutant(tree, restore_from, paths, target):
    """Copy `tree` to `target`, then set each of `paths` to its content in `restore_from` (or delete it there).

    Returns the list of paths that actually changed.
    """
    tree, restore_from, target = Path(tree), Path(restore_from), Path(target)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(tree, target, ignore=IGNORE, symlinks=True)
    touched = []
    for rel in paths:
        old, new = restore_from / rel, target / rel
        if old.is_file():
            if not new.is_file() or old.read_bytes() != new.read_bytes():
                _copy(old, new)
                touched.append(rel)
        elif new.exists():
            new.unlink()
            touched.append(rel)
    return touched


def _judge(name, result, test_name, files, extra=None):
    kind = expected_base_failure(result, test_name) if result["returncode"] != 0 else None
    entry = {"name": name, "files": files, "returncode": result["returncode"], "failure_type": kind,
             "failed_as_expected": result["returncode"] != 0 and kind is not None,
             "output": (result["stdout"] + result["stderr"])[-1500:]}
    entry.update(extra or {})
    return entry


def revert_check(run, test_name, test_source, test_file, head_tree, base_tree, source_changes, target_root,
                 is_test, loop_files=None, submitted_tree=None):
    """Run the mutation check and return a receipt dict.

    run(directory) -> {returncode, stdout, stderr}: runs the frozen proof test in a directory.
    head_tree: the tree that passed the gate (head, or the loop's final work dir).
    base_tree: the base revision's tree. source_changes: [(status, path)] of submitted base -> head change.
    loop_files / submitted_tree: when the loop rewrote files, those paths and the submitted (wrong) revision.
    Never raises on an infra failure of a mutant run: it records {ran: False, error} and ok False (fail closed).
    """
    target_root = Path(target_root)
    non_test = [p for _, p in source_changes if not is_test(p)]
    # files the fix loop rewrote are part of the fix too: the first mutant sets them back to base as well
    non_test += [p for p in (loop_files or []) if p not in non_test and not is_test(p)]
    tests_kept = [p for _, p in source_changes if is_test(p)]
    mutants = []
    try:
        if non_test:
            mutant = target_root / "revert-fix"
            touched = make_mutant(head_tree, base_tree, non_test, mutant)
            (mutant / test_file).write_text(test_source, encoding="utf-8")
            mutants.append(_judge("revert_fix_to_base", run(mutant), test_name, touched,
                                  {"identical_to_base": not tests_kept,
                                   "note": "all non-test files the change touched were set back to base"
                                           + ("" if tests_kept else "; the mutant equals the base revision")}))
        if loop_files and submitted_tree is not None:
            mutant = target_root / "restore-submitted"
            touched = make_mutant(head_tree, submitted_tree, loop_files, mutant)
            (mutant / test_file).write_text(test_source, encoding="utf-8")
            mutants.append(_judge("restore_submitted_patch", run(mutant), test_name, touched,
                                  {"note": "files the fix loop rewrote were set back to the submitted (wrong) patch"}))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return {"ran": False, "ok": False, "mutants": mutants, "error": f"{type(error).__name__}: {error}",
                "summary": "the revert check could not run, so the gate stays shut"}
    if not mutants:
        return {"ran": False, "ok": False, "mutants": [], "tests_kept": tests_kept,
                "summary": "the change touches no non-test file, so there is nothing to revert; the gate stays shut"}
    ok = all(m["failed_as_expected"] for m in mutants)
    bad = [m["name"] for m in mutants if not m["failed_as_expected"]]
    return {"ran": True, "ok": ok, "mutants": mutants, "tests_kept": tests_kept,
            "summary": ("the proof test went red again on every mutant (fix reverted)" if ok else
                        f"the proof test did NOT fail on the mutant(s) {', '.join(bad)}; it does not depend on the fix")}
