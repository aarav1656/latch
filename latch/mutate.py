"""AST-guided mutation check, aimed only at the lines the change touched.

Given the head revision of a change, generate a few small mutants of exactly the lines that differ from base
(comparison boundary flips, negated conditions, off-by-one constants, a `None` return, `and`/`or` swaps) and run the
frozen proof test against each. A mutant is killed when the proof test fails. A proof test that fixed-bug-detects but
lets most plausible mutants of the fix survive does not pin the fix down.

Mutants are spliced into the source text at AST node positions (so formatting and comments survive), compiled to make
sure they are valid Python, and run in throw-away copies of the head tree. The user's repo is never touched.
No dependencies beyond the standard library.
"""

import ast
import difflib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

THRESHOLD = 0.6          # kill_rate needed to pass
MAX_MUTANTS = 5
RUN_TIMEOUT = 60         # seconds per mutant run (a timeout counts as killed: the mutant hangs or is far too slow)
TIME_BUDGET = 240        # seconds for all mutant runs together; mutants not reached are recorded as not_run (never survived)
RUNNER_TIME_BUDGET = 600  # the same, when a custom runner (the hosted sandbox) does its own setup for every mutant
MIN_RAN = 2              # fewer mutants than this actually ran because of the budget: the check is incomplete, not a verdict
BUDGET_ENV = "LATCH_MUTATION_BUDGET"
OPERATORS = ("compare_boundary", "negate_condition", "bool_swap", "const_off_by_one", "return_none")
IGNORE = shutil.ignore_patterns(".latch-home", ".latch-suite-home", ".pytest_cache", "__pycache__", ".git", ".latch-venv")

_CMP = {  # AST op -> (regex over the bytes between the operands, replacement, operator family)
    ast.Lt: (rb"(?<![<>=!])<(?![<=])", b"<=", "compare_boundary"),
    ast.LtE: (rb"<=", b"<", "compare_boundary"),
    ast.Gt: (rb"(?<![<>=!\-])>(?![>=])", b">=", "compare_boundary"),
    ast.GtE: (rb">=", b">", "compare_boundary"),
    ast.Eq: (rb"==", b"!=", "compare_boundary"),
    ast.NotEq: (rb"!=", b"==", "compare_boundary"),
    ast.Is: (rb"\bis\b(?!\s+not\b)", b"is not", "negate_condition"),
    ast.IsNot: (rb"\bis\s+not\b", b"is", "negate_condition"),
    ast.In: (rb"(?<!not )\bin\b", b"not in", "negate_condition"),
    ast.NotIn: (rb"\bnot\s+in\b", b"in", "negate_condition"),
}


def changed_lines(old_text, new_text):
    """1-based line numbers in `new_text` that were inserted or replaced relative to `old_text`."""
    old, new = old_text.splitlines(), new_text.splitlines()
    lines = set()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            lines.update(range(j1 + 1, j2 + 1))
    return lines


def _starts(data):
    starts, pos = [0], 0
    for line in data.split(b"\n")[:-1]:
        pos += len(line) + 1
        starts.append(pos)
    return starts


def candidates(source, lines):
    """Possible single-edit mutants of `source` restricted to nodes that start on one of `lines`.

    Returns [{"operator", "line", "start", "end", "replacement" (bytes), "what"}], offsets into source.encode().
    """
    data = source.encode("utf-8")
    tree = ast.parse(source)
    starts = _starts(data)

    def at(lineno, col):
        return starts[lineno - 1] + col

    def span(node):
        return at(node.lineno, node.col_offset), at(node.end_lineno, node.end_col_offset)

    found = []

    def add(operator, node, start, end, replacement, what):
        found.append({"operator": operator, "line": node.lineno, "start": start, "end": end,
                      "replacement": replacement, "what": what})

    for node in ast.walk(tree):
        if getattr(node, "lineno", None) not in lines:
            continue
        if isinstance(node, ast.Compare):
            op = type(node.ops[0])
            if op in _CMP:
                pattern, replacement, family = _CMP[op]
                left_end = span(node.left)[1]
                right_start = span(node.comparators[0])[0]
                match = re.search(pattern, data[left_end:right_start])
                if match:
                    add(family, node, left_end + match.start(), left_end + match.end(), replacement,
                        f"`{match.group().decode()}` -> `{replacement.decode()}`")
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            start, end = span(node.test)
            add("negate_condition", node, start, end, b"not (" + data[start:end] + b")", "negated the condition")
        elif isinstance(node, ast.BoolOp) and len(node.values) >= 2:
            left_end = span(node.values[0])[1]
            right_start = span(node.values[1])[0]
            word, other = (b"and", b"or") if isinstance(node.op, ast.And) else (b"or", b"and")
            match = re.search(rb"\b" + word + rb"\b", data[left_end:right_start])
            if match:
                add("bool_swap", node, left_end + match.start(), left_end + match.end(), other,
                    f"`{word.decode()}` -> `{other.decode()}`")
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            start, end = span(node)
            if re.fullmatch(rb"\d+", data[start:end]):
                add("const_off_by_one", node, start, end, str(node.value + 1).encode(),
                    f"constant {node.value} -> {node.value + 1}")
        elif isinstance(node, ast.Return) and node.value is not None \
                and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            start, end = span(node.value)
            add("return_none", node, start, end, b"None", "return None instead of the computed value")
    return found


def apply_candidate(source, candidate):
    data = source.encode("utf-8")
    return (data[:candidate["start"]] + candidate["replacement"] + data[candidate["end"]:]).decode("utf-8")


def generate_mutants(files, max_mutants=MAX_MUTANTS):
    """files: {path: (source, changed_line_numbers)}. Returns up to `max_mutants` mutants, varied across operators.

    Each mutant is {id, operator, file, line, what, diff, source}; its source is valid Python and differs from the original.
    """
    pools = {name: [] for name in OPERATORS}
    for path in sorted(files):
        source, lines = files[path]
        try:
            cands = candidates(source, lines)
        except (SyntaxError, ValueError):
            continue
        for cand in sorted(cands, key=lambda c: (c["line"], c["start"])):
            mutated = apply_candidate(source, cand)
            if mutated == source:
                continue
            try:
                ast.parse(mutated)
            except (SyntaxError, ValueError):
                continue
            diff = "".join(difflib.unified_diff(source.splitlines(True), mutated.splitlines(True),
                                               f"a/{path}", f"b/{path}", n=1))
            pools[cand["operator"]].append({"operator": cand["operator"], "file": path, "line": cand["line"],
                                            "what": cand["what"], "diff": diff, "source": mutated})
    picked = []
    while len(picked) < max_mutants and any(pools.values()):
        for name in OPERATORS:
            if pools[name] and len(picked) < max_mutants:
                picked.append(pools[name].pop(0))
    for number, mutant in enumerate(picked, 1):
        mutant["id"] = f"m{number}"
    return picked


def time_budget_for(custom_runner=False):
    """Seconds allowed for all mutant runs: LATCH_MUTATION_BUDGET if set to a positive number, else 600 with a custom
    runner (each mutant pays its own setup there) and 240 otherwise."""
    try:
        value = float(os.environ.get(BUDGET_ENV, ""))
        if value > 0:
            return value
    except ValueError:
        pass
    return RUNNER_TIME_BUDGET if custom_runner else TIME_BUDGET


def mutation_check(run, head_tree, base_tree, files, test_source, test_file, work_root,
                   threshold=THRESHOLD, max_mutants=MAX_MUTANTS, time_budget=None, clock=time.monotonic):
    """Run the frozen proof test against mutants of the changed lines of `files`.

    run(directory) -> {returncode, stdout, stderr}: runs the proof test in a directory (it should apply its own timeout).
    head_tree / base_tree: Paths of the tree that passed the gate and of the base revision.
    files: non-test .py paths the change touched (relative). Returns the receipt dict
    {mutants, killed, total, kill_rate, threshold, ok, note, not_run, incomplete}. Mutants the time budget stopped
    before they ran are recorded with not_run: true and left out of killed/total (kill_rate = killed / mutants that ran).
    If the budget left fewer than MIN_RAN mutants run, the check is `incomplete`: it does not block, and says so.
    """
    if time_budget is None:
        time_budget = time_budget_for(False)
    head_tree, base_tree, work_root = Path(head_tree), Path(base_tree), Path(work_root)
    sources = {}
    for rel in files:
        if not rel.endswith(".py") or not (head_tree / rel).is_file():
            continue
        new = (head_tree / rel).read_text(encoding="utf-8", errors="replace")
        old_path = base_tree / rel
        old = old_path.read_text(encoding="utf-8", errors="replace") if old_path.is_file() else ""
        lines = changed_lines(old, new)
        if lines:
            sources[rel] = (new, lines)
    mutants = generate_mutants(sources, max_mutants)
    if not mutants:
        return {"mutants": [], "killed": 0, "total": 0, "kill_rate": None, "threshold": threshold, "ok": True,
                "note": "no mutable lines in the changed code (no comparison, condition, boolean operator, integer "
                        "constant or return among the changed lines), so there was nothing to mutate; this does not block"}
    started = clock()
    records = []
    for mutant in mutants:
        record = {"id": mutant["id"], "operator": mutant["operator"], "file": mutant["file"], "line": mutant["line"],
                  "what": mutant["what"], "diff": mutant["diff"], "killed": False, "output_excerpt": ""}
        if clock() - started > time_budget:
            record.update(not_run=True, output_excerpt="not run: the time budget was exhausted before this mutant")
            records.append(record)
            continue
        target = work_root / f"mutant-{mutant['id']}"
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(head_tree, target, ignore=IGNORE, symlinks=True)
            (target / mutant["file"]).write_text(mutant["source"], encoding="utf-8")
            (target / test_file).write_text(test_source, encoding="utf-8")
            result = run(target)
            record["killed"] = result["returncode"] != 0
            record["output_excerpt"] = ((result.get("stdout") or "") + (result.get("stderr") or ""))[-600:]
        except subprocess.TimeoutExpired:
            record.update(killed=True, timed_out=True, output_excerpt="the proof test timed out on this mutant (counted as killed)")
        except Exception as error:  # an infra failure is never a kill: it lowers the rate (fail closed)
            record["error"] = f"{type(error).__name__}: {error}"
        finally:
            shutil.rmtree(target, ignore_errors=True)
        records.append(record)
    ran = [r for r in records if not r.get("not_run")]
    skipped = len(records) - len(ran)
    killed = sum(1 for r in ran if r["killed"])
    rate = round(killed / len(ran), 3) if ran else None
    result = {"mutants": records, "killed": killed, "total": len(ran), "kill_rate": rate, "threshold": threshold,
              "not_run": skipped, "incomplete": False}
    if skipped and len(ran) < MIN_RAN:
        result.update(ok=True, incomplete=True,
                      note=f"mutation check incomplete: budget ({len(ran)} of {len(records)} mutants ran, {skipped} not run "
                           f"within {time_budget:g}s); this does not block, and the verdict is not mutation-backed")
        return result
    note = f"{killed}/{len(ran)} mutants of the changed lines were killed by the frozen proof test (needs {threshold:.0%})"
    if skipped:
        note += f"; {skipped} more were not run because the {time_budget:g}s budget ran out"
    result.update(ok=rate >= threshold, note=note)
    return result


def mutation_detail(result):
    """The step-event detail (the contract with latch-web): exactly {killed, total, kill_rate}."""
    return {"killed": result.get("killed", 0), "total": result.get("total", 0), "kill_rate": result.get("kill_rate")}


def run_mutation(run, head_tree, base_tree, source_changes, test_source, test_file, work_root, is_test,
                 loop_files=None, **options):
    """mutation_check over the non-test Python files the change added or modified (plus any the fix loop rewrote).

    Never raises: an infrastructure failure becomes {ran: False, ok: False, kill_rate: None}, which the verdict treats
    as MUTATION_SURVIVED (fail closed). Returns the receipt dict, with `ran` added.
    """
    files = [path for status, path in source_changes if status in ("A", "M") and path.endswith(".py") and not is_test(path)]
    files += [path for path in (loop_files or []) if path not in files and path.endswith(".py") and not is_test(path)]
    threshold = options.get("threshold", THRESHOLD)
    try:
        result = mutation_check(run, head_tree, base_tree, files, test_source, test_file, work_root, **options)
    except Exception as error:  # fail closed: a check that could not run is not a pass
        return {"ran": False, "mutants": [], "killed": 0, "total": 0, "kill_rate": None, "threshold": threshold, "ok": False,
                "note": f"{type(error).__name__}: {error}"}
    return {"ran": True, **result}
