"""Deterministic, pre-run check that a generated proof test really asserts on the code the diff changed.

A proof test can pass `validate_proof_test` (it has an `assert`) and still prove nothing about the fix:
`assert True`, `assert x == x`, `assert f(a) == f(a)`, or assertions only about values the test built itself.
Such a test cannot be turned red by the bug, so running it only costs time, and when it "fails on base" it fails
for an unrelated reason. This module rejects it before any test run, with no model involved:

  1. changed_symbols(): which functions, methods, classes and module-level names the base -> head diff touched in
     non-test .py files (hunk line ranges mapped to the enclosing defs with `ast`), plus, when a checkout of
     head is given, the functions that call them (a bug fix is usually in a helper, while the proof test
     calls the public API that reaches it).
  2. check_tautology(): the test must contain at least one assertion (`assert`, `pytest.raises` / `warns`, or a
     `pytest.fail` / `raise AssertionError` guarded by a condition) whose evaluated expression depends on a
     call to, or an attribute or name of, one of those symbols, directly or through a local variable assigned
     from one. Tautologies (`assert x == x`, `assert f(a) == f(a)`, constants only) never count.

When the changed symbols cannot be determined (no diff, no changed non-test Python, parse error, too broad) the
result has checked=False and ok=True: it never blocks on a guess.

The result is the receipt field `tautology`:
    {"checked": bool, "changed_symbols": [...], "asserted_symbols": [...], "ok": bool, "reason": str | None,
     "affected_symbols": [...]}          # affected_symbols: callers of the changed symbols (extra, informational)
`rejection_reason(result)` is the string to feed the stricter regeneration prompt, or None.
"""

import ast
import difflib
import os
import re
import subprocess
import textwrap
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_SCAN_FILES = 3000
CALLER_DEPTH = 3
CALLER_CAP = 400
_SKIP_DIRS = {".git", ".latch-venv", ".latch-home", ".latch-suite-home", "__pycache__", "node_modules", "venv",
              ".venv", "site-packages", ".tox", ".eggs", "build", "dist"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def is_dunder(name):
    return name.startswith("__") and name.endswith("__")


# ---------------------------------------------------------------- changed symbols

def parse_hunks(diff_text):
    """Hunks of a `git diff -U0` for one file as [((base_lo, base_hi), (head_lo, head_hi))], inclusive, empty = hi < lo."""
    hunks = []
    for m in _HUNK.finditer(diff_text):
        b_start, b_count = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
        h_start, h_count = int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1
        hunks.append(((b_start, b_start + b_count - 1), (h_start, h_start + h_count - 1)))
    return hunks


def hunks_from_sources(base_src, head_src):
    """Same shape as parse_hunks, computed with difflib (no git needed)."""
    a, b = base_src.splitlines(), head_src.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append(((i1 + 1, i2), (j1 + 1, j2)))
    return out


def _extent(node):
    start = node.lineno
    for decorator in getattr(node, "decorator_list", ()):
        start = min(start, decorator.lineno)
    return start, getattr(node, "end_lineno", None) or node.lineno


def _overlaps(extent, ranges):
    start, end = extent
    return any(lo <= end and hi >= start for lo, hi in ranges if hi >= lo)


def _target_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for element in target.elts for n in _target_names(element)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _child_blocks(node):
    for field in ("body", "orelse", "finalbody"):
        block = getattr(node, field, None)
        if isinstance(block, list):
            yield block
    for handler in getattr(node, "handlers", ()):
        yield handler.body
    for case in getattr(node, "cases", ()):
        yield case.body


def _collect(body, ranges, scope, out):
    """Names of the defs / classes / module- or class-level assignments whose extent overlaps a changed range."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _overlaps(_extent(node), ranges):
                out.add(node.name)
                _collect(node.body, ranges, "class" if isinstance(node, ast.ClassDef) else "function", out)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if scope != "function" and _overlaps(_extent(node), ranges):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    out.update(_target_names(target))
        else:
            for block in _child_blocks(node):
                _collect(block, ranges, scope, out)


def symbols_from_sources(base_src, head_src, hunks=None):
    """Symbols changed between two versions of one file. Raises ValueError if either version does not parse."""
    try:
        base_tree = ast.parse(base_src) if base_src.strip() else ast.Module(body=[], type_ignores=[])
        head_tree = ast.parse(head_src) if head_src.strip() else ast.Module(body=[], type_ignores=[])
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"cannot parse the changed file: {error}") from None
    if hunks is None:
        hunks = hunks_from_sources(base_src, head_src)
    out = set()
    _collect(head_tree.body, [h for _, h in hunks], "module", out)
    _collect(base_tree.body, [b for b, _ in hunks], "module", out)  # removed or edited lines: the base-side def
    return out


def _is_test_path(rel):
    from .revert import is_test_path

    return is_test_path(rel)


def _git_text(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=60)
    if done.returncode:
        raise ValueError(done.stderr.decode("utf-8", "replace").strip() or "git failed")
    return done.stdout.decode("utf-8", "replace")


def _undetermined(reason):
    return {"determined": False, "symbols": [], "affected": [], "files": [], "reason": reason}


def _def_references(tree):
    """[(def_name, referenced_names)] for every function and class in a module."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            refs = set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    refs.add(inner.id)
                elif isinstance(inner, ast.Attribute):
                    refs.add(inner.attr)
            found.append((node.name, refs))
    return found


def callers_of(head_root, symbols, depth=CALLER_DEPTH, cap=CALLER_CAP):
    """Names of non-test functions/classes in a checkout that (transitively, `depth` levels) reference `symbols`.

    Returns (names, overflow). Matching is by simple name, so it errs toward more callers, never fewer.
    """
    root = Path(head_root)
    defs = []
    scanned = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = Path(current) / name
            rel = str(path.relative_to(root))
            if _is_test_path(rel):
                continue
            scanned += 1
            if scanned > MAX_SCAN_FILES:
                return set(), True
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                defs.extend(_def_references(ast.parse(path.read_text(encoding="utf-8", errors="replace"))))
            except (OSError, SyntaxError, ValueError):
                continue
    seen = set(symbols)
    frontier = {s for s in symbols if not is_dunder(s)}
    affected = set()
    for _ in range(depth):
        found = {name for name, refs in defs if name not in seen and refs & frontier}
        if not found:
            break
        affected |= found
        seen |= found
        if len(affected) > cap:
            return affected, True
        frontier = {s for s in found if not is_dunder(s)}
    return affected, False


def changed_symbols(repo, base, head, head_root=None):
    """Symbols the base -> head diff touched in non-test .py files.

    Returns {determined, symbols, affected, files, reason}. determined=False (with a reason) when there is no
    changed non-test Python, a changed file does not parse, or no symbol could be named: callers must not block then.
    """
    from .revert import changed_files

    try:
        changes = changed_files(repo, base, head)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _undetermined(f"could not list the changed files: {error}")
    sources = [(status, path) for status, path in changes if path.endswith(".py") and not _is_test_path(path)]
    if not sources:
        return _undetermined("the diff changes no non-test Python files, so there are no changed symbols to assert on")
    symbols, files = set(), []
    for status, path in sources:
        try:
            base_src = "" if status == "A" else _git_text(repo, "show", f"{base}:{path}")
            head_src = "" if status == "D" else _git_text(repo, "show", f"{head}:{path}")
            if len(base_src) > MAX_FILE_BYTES or len(head_src) > MAX_FILE_BYTES:
                return _undetermined(f"{path} is too large to analyze")
            if status in ("A", "D"):
                hunks = [((1, max(1, len(base_src.splitlines()))), (1, max(1, len(head_src.splitlines()))))]
            else:
                try:
                    hunks = parse_hunks(_git_text(repo, "diff", "-U0", "--no-ext-diff", "--no-renames",
                                                  base, head, "--", path))
                except ValueError:
                    hunks = None
            symbols |= symbols_from_sources(base_src, head_src, hunks)
            files.append(path)
        except ValueError as error:
            return _undetermined(f"{path}: {error}")
    if not symbols:
        return _undetermined("the changed lines are not inside any named function, class or module-level assignment")
    affected, overflow = set(), False
    if head_root is not None:
        affected, overflow = callers_of(head_root, symbols)
        if overflow:
            return _undetermined("the changed code is referenced from too much of the repository to name what a test must reach")
        affected -= symbols
    return {"determined": True, "symbols": sorted(symbols), "affected": sorted(affected), "files": files, "reason": None}


# ---------------------------------------------------------------- the test side

def _is_constant_expr(node):
    """True when an expression has no names, attributes or calls: it evaluates to the same value in any code."""
    return not any(isinstance(n, (ast.Name, ast.Attribute, ast.Call, ast.Await, ast.NamedExpr, ast.Lambda))
                   for n in ast.walk(node))


_SELF_COMPARE = (ast.Eq, ast.Is, ast.LtE, ast.GtE)


def _src(node):
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse covers parsed nodes
        return "<expression>"


def tautology_of(node):
    """Why an assert expression can never fail on any code, or None. Purely syntactic."""
    if _is_constant_expr(node):
        return f"`{_src(node)}` has no value that depends on the code under test (constants only)"
    if isinstance(node, ast.BoolOp):
        parts = [tautology_of(v) for v in node.values]
        if isinstance(node.op, ast.Or):
            return next((p for p in parts if p), None)
        return parts[0] if parts and all(parts) else None
    if isinstance(node, ast.Compare):
        sides = [node.left, *node.comparators]
        reasons = []
        for index, op in enumerate(node.ops):
            left, right = sides[index], sides[index + 1]
            if isinstance(op, _SELF_COMPARE) and ast.dump(left) == ast.dump(right):
                reasons.append(f"`{_src(left)}` is compared with itself")
            else:
                return None
        return "; ".join(reasons) if reasons else None
    return None


def _flatten_and(node):
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return [leaf for v in node.values for leaf in _flatten_and(v)]
    return [node]


def _is_pytest_call(node, names):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in names and isinstance(func.value, ast.Name) and func.value.id == "pytest"
    return isinstance(func, ast.Name) and func.id in names


class _TestAnalysis:
    def __init__(self, function, targets, repo_modules=()):
        self.function, self.targets = function, set(targets)
        self.repo_modules = set(repo_modules)  # top-level packages/modules of the repo (repo mode only)
        self.local_targets = set()  # local names bound by importing from the repo (repo mode only)
        self.alias = {}  # local name -> imported original name
        self.vars = {}  # local variable -> changed symbols it depends on
        self.asserted = set()
        self.tautologies = []

    # -- symbol dependence of an expression
    def syms(self, node):
        found = set()
        if node is None:
            return found
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                original = self.alias.get(n.id, n.id)
                if original in self.targets or n.id in self.local_targets:
                    found.add(original)
                found |= self.vars.get(n.id, set())
            elif isinstance(n, ast.Attribute):
                if n.attr in self.targets:
                    found.add(n.attr)
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("getattr", "hasattr") \
                    and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value in self.targets:
                found.add(n.args[1].value)
        return found

    def _bind(self, target, syms):
        changed = False
        for name in self._base_names(target):
            before = self.vars.get(name, set())
            if not syms <= before:
                self.vars[name] = before | syms
                changed = True
        return changed

    @staticmethod
    def _base_names(target):
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            return [n for e in target.elts for n in _TestAnalysis._base_names(e)]
        if isinstance(target, ast.Starred):
            return _TestAnalysis._base_names(target.value)
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            return _TestAnalysis._base_names(target.value)
        return []

    def prepare(self, tree):
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                from_repo = n.level == 0 and (n.module or "").split(".")[0] in self.repo_modules
                for a in n.names:
                    if a.asname:
                        self.alias[a.asname] = a.name
                    if from_repo:
                        self.local_targets.add(a.asname or a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:  # `import pkg.mod as m`: m is the module; attributes are matched by name
                        self.alias[a.asname] = a.name.split(".")[-1]
                    if a.name.split(".")[0] in self.repo_modules:
                        self.local_targets.add(a.asname or a.name.split(".")[0])
        for _ in range(6):
            changed = False
            for n in ast.walk(self.function):
                if isinstance(n, ast.Assign):
                    s = self.syms(n.value)
                    for t in n.targets:
                        changed |= self._bind(t, s)
                elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value is not None:
                    changed |= self._bind(n.target, self.syms(n.value))
                elif isinstance(n, ast.NamedExpr):
                    changed |= self._bind(n.target, self.syms(n.value))
                elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                    changed |= self._bind(n.target, self.syms(n.iter))
                elif isinstance(n, (ast.With, ast.AsyncWith)):
                    body = self._block_syms(n.body)
                    for item in n.items:
                        if item.optional_vars is not None:
                            s = self.syms(item.context_expr)
                            if _is_pytest_call(item.context_expr, {"raises", "warns"}):
                                s |= body
                            changed |= self._bind(item.optional_vars, s)
                elif isinstance(n, ast.Try):
                    body = self._block_syms(n.body)
                    for handler in n.handlers:
                        if handler.name:
                            changed |= self._bind(ast.Name(id=handler.name, ctx=ast.Store()), body)
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not self.function:
                    changed |= self._bind(ast.Name(id=n.name, ctx=ast.Store()), self._block_syms(n.body))
                elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) \
                        and isinstance(n.value.func, ast.Attribute):
                    s = self.syms(n.value)  # v.bump() / lst.append(f(x)) mutate their receiver: it now depends on them
                    if s:
                        changed |= self._bind(n.value.func.value, s)
            if not changed:
                break

    def _block_syms(self, body):
        s = set()
        for stmt in body:
            s |= self.syms(stmt)
        return s

    # -- find the qualifying assertions
    def scan(self, stmts, guard):
        for stmt in stmts:
            self.visit(stmt, guard)

    def visit(self, node, guard):
        if isinstance(node, ast.Assert):
            self._assertion(node.test)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if _is_pytest_call(item.context_expr, {"raises", "warns"}):
                    self.asserted |= self.syms(item.context_expr) | self._block_syms(node.body)
            self.scan(node.body, guard)
        elif isinstance(node, ast.If):
            inner = guard | self.syms(node.test)
            self.scan(node.body, inner)
            self.scan(node.orelse, inner)
        elif isinstance(node, ast.While):
            inner = guard | self.syms(node.test)
            self.scan(node.body, inner)
            self.scan(node.orelse, inner)
        elif isinstance(node, ast.Try):
            self.scan(node.body, guard)
            inner = guard | self._block_syms(node.body)
            for handler in node.handlers:
                self.scan(handler.body, inner)
            self.scan(node.orelse, inner)
            self.scan(node.finalbody, inner)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.scan(node.body, guard)
            self.scan(node.orelse, guard)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.scan(node.body, guard)
        elif isinstance(node, ast.Raise):
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "AssertionError":
                self.asserted |= guard
        else:
            for call in ast.walk(node):
                if _is_pytest_call(call, {"fail"}):
                    self.asserted |= guard  # a conditional pytest.fail is an assertion on its guard
                elif _is_pytest_call(call, {"raises", "warns"}) and not isinstance(node, (ast.With, ast.AsyncWith)):
                    for arg in [*call.args[1:], *[k.value for k in call.keywords]]:
                        self.asserted |= self.syms(arg)

    def _assertion(self, test):
        for leaf in _flatten_and(test):
            reason = tautology_of(leaf)
            if reason:
                self.tautologies.append(reason)
                continue
            self.asserted |= self.syms(leaf)


def _first_test_function(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            return node
    return None


def _result(checked, changed, asserted, ok, reason, affected=()):
    return {"checked": checked, "changed_symbols": sorted(changed), "asserted_symbols": sorted(asserted),
            "ok": ok, "reason": reason, "affected_symbols": sorted(affected)}


def repo_modules(root):
    """Top-level importable module/package names of a checkout (root and root/src), without tests and docs."""
    names = set()
    for base in (Path(root), Path(root) / "src"):
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith((".", "_")) and entry.name != "__init__.py":
                continue
            if entry.is_dir() and entry.name not in _SKIP_DIRS | {"tests", "test", "docs", "doc", "examples", "scripts"} \
                    and ((entry / "__init__.py").exists() or any(entry.glob("*.py"))):
                names.add(entry.name)
            elif entry.is_file() and entry.suffix == ".py" and not entry.name.startswith(("test_", "setup", "conftest")):
                names.add(entry.stem)
    return names


def check_tautology(test_source, changed, repo_modules=None):
    """Apply the check to a proof test. `changed` is the dict from changed_symbols() (or None when unknown).

    repo_modules=None is the strict mode used for proving a fix: an assertion must depend on a changed symbol (or a
    caller of one). Passing the checkout's module names selects the lenient "repo" mode used by the fix loop, whose
    diff is a candidate patch that may miss the buggy code: an assertion may depend on anything imported from the
    repository, so only tautologies, constants and values the test built itself are rejected.
    """
    if not changed or not changed.get("determined"):
        reason = (changed or {}).get("reason") or "the changed symbols could not be determined"
        return _result(False, (), (), True, f"not checked: {reason}")
    symbols, affected = set(changed["symbols"]), set(changed.get("affected", ()))
    try:
        tree = ast.parse(textwrap.dedent(test_source))
    except (SyntaxError, ValueError):
        return _result(False, symbols, (), True, "not checked: the test is not valid Python", affected)
    function = _first_test_function(tree)
    if function is None:
        return _result(False, symbols, (), True, "not checked: no top-level test_ function", affected)
    analysis = _TestAnalysis(function, symbols | affected, repo_modules or ())
    analysis.prepare(tree)
    analysis.scan(function.body, set())
    mode = "repo" if repo_modules is not None else "changed"
    if analysis.asserted:
        return {**_result(True, symbols, analysis.asserted, True, None, affected), "mode": mode}
    shown = ", ".join(f"`{s}`" for s in sorted(symbols)[:8]) + (" ..." if len(symbols) > 8 else "")
    if mode == "repo":
        reason = ("the test never asserts on code from the repository: no assert, pytest.raises or pytest.fail "
                  "depends on anything imported from it")
    else:
        reason = (f"the test never asserts on code this change touched ({shown}): no assert, pytest.raises or "
                  "pytest.fail depends on a call to or attribute of those symbols")
    if analysis.tautologies:
        reason += "; tautological checks found: " + "; ".join(analysis.tautologies[:3])
    return {**_result(True, symbols, (), False, reason, affected), "mode": mode}


def safe_changed_symbols(repo, base, head, head_root=None):
    """changed_symbols that never raises: an analysis bug must never block a proof (it becomes undetermined)."""
    try:
        return changed_symbols(repo, base, head, head_root)
    except Exception as error:
        return _undetermined(f"{type(error).__name__}: {error}")


def check_proof_test(test_source, repo, base, head, head_root=None, mode="changed"):
    """changed_symbols + check_tautology, never raising. mode "changed" (prove) or "repo" (loop, needs head_root)."""
    changed = safe_changed_symbols(repo, base, head, head_root)
    modules = repo_modules(head_root) if mode == "repo" and head_root is not None else None
    return check_tautology(test_source, changed, modules)


def rejection_reason(result):
    """The reason to reject the proof test (INVALID_TEST) or None when it may run."""
    if result and result.get("checked") and not result.get("ok"):
        return result.get("reason") or "the test does not assert on the changed code"
    return None
