"""Oracle baseline (no model): what the benchmark's own ground truth does on the same cases, with no LLM, $0 and no Token Factory.

For each case it runs the human-written tests that came with the real fix, with real git and real pytest:
  upstream case: the fix commit's own test files, on base, on the real fix and on the constructed wrong patch;
  SWE-bench Lite case: the instance's FAIL_TO_PASS tests (via test_patch), on base and on the gold patch.
It is the reference a model-written test is judged against, not a rival: it uses the answer key (the upstream tests the model never
sees), so it is an upper bound for a test that needs no model. Read the numbers as "can the answer key tell the real fix from the
wrong patch", not as a measured Latch result. And note the selection effect: `latch eval run` keeps only cases this check
validated (see `dropped`), so over the kept cases the oracle separates real from wrong by construction.
"""
import concurrent.futures as cf
import datetime
import json
import time
from pathlib import Path

LABEL = "oracle baseline (no model)"
SCHEMA_VERSION = 1


def _row(case, ok, d, wall):
    c = d.get("checks") or {}
    swe = bool(case.get("swe"))
    return {
        "case": case["id"], "suite": "swebench_lite" if swe else "upstream", "repo": case["repo"],
        "ok": bool(ok),
        "fails_on_base": c.get("oracle fails on base"),
        "passes_on_real_fix": c.get("oracle passes on gold patch" if swe else "oracle passes on real fix"),
        "fails_on_wrong_patch": None if swe else c.get("oracle fails on wrong patch"),
        "base_suite_green": c.get("base suite green"),
        "wall_s": round(wall, 1), "error": d.get("error"), "checks": c,
        "oracle_summary": {k: (d.get(k) or {}).get("oracle_summary") for k in ("oracle_base", "oracle_head", "oracle_wrong") if d.get(k)},
    }


def _ratio(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None}


def totals(rows):
    ok = [r for r in rows if not r.get("error")]
    up = [r for r in ok if r["suite"] == "upstream"]
    return {
        "cases": len(rows), "errors": len(rows) - len(ok),
        "oracle_fails_on_base": _ratio(sum(1 for r in ok if r["fails_on_base"]), len(ok)),
        "oracle_passes_on_real_fix": _ratio(sum(1 for r in ok if r["passes_on_real_fix"]), len(ok)),
        "oracle_rejects_wrong_patch": _ratio(sum(1 for r in up if r["fails_on_wrong_patch"]), len(up)),
        "oracle_separates_real_from_wrong": _ratio(sum(1 for r in up if r["ok"]), len(up)),
        "cost_usd": 0.0, "model_calls": 0,
        "wall_s": {"total": round(sum(r["wall_s"] for r in rows), 1), "median": round(sorted(r["wall_s"] for r in rows)[len(rows) // 2], 1) if rows else None},
    }


def run_oracle(cases, validate=None, jobs=2, dropped=(), progress=None):
    """Run the oracle over `cases` and return the baseline document. `validate(case) -> (ok, details)` is injectable for tests."""
    if validate is None:
        from .run_eval import validate_case as validate

    def one(case):
        t = time.time()
        try:
            ok, d = validate(case)
        except Exception as error:  # a broken checkout must show as an error row, never vanish
            ok, d = False, {"error": f"{type(error).__name__}: {error}"[:300]}
        row = _row(case, ok, d, time.time() - t)
        if progress:
            progress(row)
        return row

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        rows = list(pool.map(one, cases))  # preserves case order
    return {"schema_version": SCHEMA_VERSION, "label": LABEL, "kind": "oracle_baseline", "model_free": True,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "wall_s_elapsed": round(time.time() - t0, 1), "cost_usd": 0.0, "model_calls": 0,
            "dropped": [{"id": d["id"], "reason": d["reason"]} for d in dropped], "totals": totals(rows), "cases": rows}


def render(doc):
    t = doc["totals"]
    f = lambda r: "n/a" if not r["n"] else f"{r['k']}/{r['n']} ({r['rate'] * 100:.0f}%)"
    out = [f"## {doc['label']}", "",
           f"Run {doc['generated_at']}. No model, no Token Factory call: $0.00, {doc['wall_s_elapsed']} s wall. Real git and pytest.",
           "", "| Measure | Result |", "|---|---|",
           f"| Cases checked | {t['cases']} ({t['errors']} errors) |",
           f"| Oracle fails on base | {f(t['oracle_fails_on_base'])} |",
           f"| Oracle passes on the real fix | {f(t['oracle_passes_on_real_fix'])} |",
           f"| Oracle rejects the wrong patch (upstream cases) | {f(t['oracle_rejects_wrong_patch'])} |",
           f"| Oracle separates real from wrong (upstream cases) | {f(t['oracle_separates_real_from_wrong'])} |",
           "", "These tests are the upstream answer key that Latch never shows the model. The kept cases were selected for this property, so the "
           "oracle separates real from wrong by construction; the number is the reference the gate is judged against, not a Latch result.", ""]
    if doc["dropped"]:
        out += ["Cases dropped before any run (reported, not hidden):", ""] + [f"- `{d['id']}`: {d['reason']}" for d in doc["dropped"]] + [""]
    out += ["| Case | Fails on base | Passes on real | Fails on wrong | Wall s |", "|---|---|---|---|---|"]
    mark = lambda v: "n/a" if v is None else ("yes" if v else "NO")
    for r in doc["cases"]:
        out.append(f"| {r['case']} | {mark(r['fails_on_base'])} | {mark(r['passes_on_real_fix'])} | {mark(r['fails_on_wrong_patch'])} | {r['wall_s']} |")
    return "\n".join(out) + "\n"


def write(doc, json_path, md_path=None):
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if md_path:
        Path(md_path).write_text(render(doc), encoding="utf-8")
