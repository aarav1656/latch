"""Repo map: Nemotron Lightning picks the files and symbols an issue is about; the harness checks them.

The harness builds a symbol index of the base snapshot (python files: classes, functions, methods with line
numbers and signatures) with `ast`. Lightning reads the issue plus a size-capped index and names the relevant
files and symbols. The harness drops anything that is not in the index (no invented paths or names) and always
adds the files the submitted diff touches. The resulting compact map is given to Ultra's test-writing prompt, so
the proof test imports real names. If the Lightning call fails the run goes on without a map and says so.
"""

import ast
import re
from pathlib import Path

INDEX_LIMIT = 9000     # characters of index shown to Lightning
MAP_LIMIT = 3500       # characters of map given to Ultra
MAX_FILES = 8

REPO_MAP_SYSTEM = (
    "You map a Python repository for a bug report. You are given the report and an index of the code (file, then "
    "its classes, functions and methods). Choose the files and symbols a developer must look at to reproduce and "
    "fix the report. Reply with no prose: one line per file, exactly `path/to/file.py: symbol, symbol, ...` using "
    "only names that appear in the index. At most 8 lines."
)


def _is_test(rel):
    parts = Path(rel).parts
    name = parts[-1]
    return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            or any(p in ("tests", "test", "docs", "doc", "examples", "benchmarks") for p in parts[:-1]))


def _signature(node):
    args = node.args
    names = [a.arg for a in getattr(args, "posonlyargs", [])] + [a.arg for a in args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return f"({', '.join(names)})"


def file_symbols(source):
    """[(qualified name, kind, line, signature, first docstring line)] for the top level of one module."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out = []

    def doc(node):
        text = ast.get_docstring(node) or ""
        return text.strip().splitlines()[0][:80] if text.strip() else ""

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, "def", node.lineno, _signature(node), doc(node)))
        elif isinstance(node, ast.ClassDef):
            out.append((node.name, "class", node.lineno, "", doc(node)))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{node.name}.{item.name}", "def", item.lineno, _signature(item), doc(item)))
    return out


def symbol_index(root, limit_files=4000):
    """{relative path: [symbols]} for the non-test python files under root (skips hidden and vendored dirs)."""
    root = Path(root)
    index = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if (_is_test(rel) or rel.startswith(".") or "/." in rel or "site-packages" in rel
                or "node_modules" in rel or len(index) >= limit_files):
            continue
        try:
            if path.stat().st_size > 400_000:
                continue
            symbols = file_symbols(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if symbols:
            index[rel] = symbols
    return index


def _words(text):
    return set(w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))


def _rank(index, issue, changed):
    issue_words = _words(issue)

    def score(item):
        rel, symbols = item
        if rel in changed:
            return (-1000, rel)
        names = _words(rel.replace("/", " ").replace(".", " ")) | _words(" ".join(s[0].replace(".", " ") for s in symbols))
        return (-len(names & issue_words), rel)

    return sorted(index.items(), key=score)


def index_text(index, issue, changed, limit=INDEX_LIMIT):
    """Compact index for the prompt, most relevant files first, cut at `limit` characters."""
    lines, used = [], 0
    for rel, symbols in _rank(index, issue, changed):
        names = ", ".join(s[0] for s in symbols[:40])
        line = f"{rel}: {names}"
        if used + len(line) + 1 > limit:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def parse_selection(text):
    """{path: [symbols]} from `path: sym, sym` lines. Tolerates bullets, backticks and <think> blocks."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    chosen = {}
    for line in text.splitlines():
        m = re.match(r"^[\s>*\-\d.)]*`?([\w./\-]+\.py)`?\s*:\s*(.*)$", line)
        if m:
            names = [n.strip(" `*") for n in re.split(r"[,;]", m.group(2)) if n.strip(" `*")]
            chosen.setdefault(m.group(1), []).extend(names)
    return chosen


def validate_selection(chosen, index, changed):
    """Keep only paths and symbols that exist in the index; always add the changed files.

    Returns (files, dropped): files is [{path, symbols: [qualified names], changed: bool}].
    """
    files, dropped = [], []
    order = list(chosen) + [c for c in changed if c in index and c not in chosen]
    for rel in order:
        if rel not in index:
            dropped.append(rel)
            continue
        known = {s[0]: s for s in index[rel]}
        wanted = chosen.get(rel, [])
        keep = []
        for name in wanted:
            hit = name if name in known else next((q for q in known if q.split(".")[-1] == name), None)
            if hit and hit not in keep:
                keep.append(hit)
            elif not hit:
                dropped.append(f"{rel}:{name}")
        if not keep:  # a file with no (valid) symbols named: list its top-level definitions
            keep = [s[0] for s in index[rel] if "." not in s[0]][:12]
        files.append({"path": rel, "symbols": keep, "changed": rel in changed})
        if len(files) >= MAX_FILES:
            break
    return files, dropped


def render_map(files, index, limit=MAP_LIMIT):
    """The compact text Ultra gets: path, then `kind name(sig) line  - doc` per selected symbol."""
    lines = []
    for item in files:
        lines.append(f"{item['path']}" + ("  (touched by the submitted diff)" if item["changed"] else ""))
        known = {s[0]: s for s in index[item["path"]]}
        for name in item["symbols"]:
            _, kind, line, sig, doc = known[name]
            lines.append(f"  {kind} {name}{sig}  L{line}" + (f"  - {doc}" if doc else ""))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n...[map truncated]"


def build_repo_map(ask, key, root, issue, changed=(), model=None):
    """Run the repo-map step. `ask` is a call_model-compatible function for the repo_map role.

    Returns {status, files, dropped, text, completion_id, model, reply}. status is "ok", or "unavailable" when the
    model call failed (then `text` is empty and the caller continues without a map).
    """
    from .run import LIGHTNING

    model = model or LIGHTNING
    changed = [c for c in changed if c.endswith(".py")]
    index = symbol_index(root)
    result = {"status": "unavailable", "model": model, "completion_id": None, "files": [], "dropped": [],
              "text": "", "files_indexed": len(index), "reply": None}
    if not index:
        result["detail"] = "no python source files to index"
        return result
    user = (f"Bug report:\n{issue[:4000]}\n\nFiles the submitted change touches: {', '.join(changed) or 'none'}\n\n"
            f"Code index:\n{index_text(index, issue, set(changed))}")
    status, content, completion_id = ask(key, user, model=model, system=REPO_MAP_SYSTEM, max_tokens=1024, prose=True)
    result["completion_id"] = completion_id
    if status != 200 or not content:
        result["detail"] = f"HTTP {status}"
        return result
    chosen = parse_selection(content)
    files, dropped = validate_selection(chosen, index, set(changed))
    result.update(status="ok", files=files, dropped=dropped, reply=content[:1500], text=render_map(files, index))
    return result
