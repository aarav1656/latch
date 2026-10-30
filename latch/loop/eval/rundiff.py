"""Side-by-side of two eval summaries (the first run and a --tag rerun): per-case verdicts before -> after and the headline numbers.

Pure functions over two eval-summary documents; writes nothing by itself. Both inputs are kept exactly as they are: this is a third file.
"""


def _rows(summary):
    return {(r["case"], r["variant"]): r for r in summary.get("cases") or []}


def _count(summary, key):
    return (summary.get("verdicts") or {}).get(key, 0)


def _pair(before, after, getter):
    return {"before": getter(before), "after": getter(after)}


def _validated_real(summary):
    return sum(1 for r in summary.get("cases") or [] if r.get("variant") == "real" and r.get("verdict") == "VALIDATED")


def _real_count(summary):
    return sum(1 for r in summary.get("cases") or [] if r.get("variant") == "real" and r.get("status") == "ran")


def diff_summaries(before, after, before_name="before", after_name="after"):
    b_rows, a_rows = _rows(before), _rows(after)
    cases = []
    for key in sorted(set(b_rows) | set(a_rows)):
        b, a = b_rows.get(key) or {}, a_rows.get(key) or {}
        repair = a.get("test_repair") or {}
        cases.append({"case": key[0], "variant": key[1], "verdict_before": b.get("verdict"), "verdict_after": a.get("verdict"),
                      "outcome_before": b.get("outcome"), "outcome_after": a.get("outcome"),
                      "changed": b.get("verdict") != a.get("verdict"), "test_repair": repair.get("outcome") if repair.get("attempted") else None,
                      "receipt_before": b.get("receipt"), "receipt_after": a.get("receipt")})
    b_wrong, a_wrong = before.get("wrong_fixes") or {}, after.get("wrong_fixes") or {}
    b_cost, a_cost = (before.get("benchmark") or {}).get("cost_usd"), (after.get("benchmark") or {}).get("cost_usd")
    return {
        "before": {"file": before_name, **(before.get("run") or {}), "latch_git_sha": before.get("latch_git_sha")},
        "after": {"file": after_name, **(after.get("run") or {}), "latch_git_sha": after.get("latch_git_sha")},
        "headline": {
            "real_validated": {"before": f"{_validated_real(before)}/{_real_count(before)}", "after": f"{_validated_real(after)}/{_real_count(after)}"},
            "invalid_test": _pair(before, after, lambda s: _count(s, "INVALID_TEST")),
            "wrong_patches_failed_by_valid_test": _pair(b_wrong, a_wrong, lambda w: (w.get("caught_by_valid_test") or {}).get("caught")),
            "false_accepts": _pair(b_wrong, a_wrong, lambda w: w.get("false_accepts")),
            "cost_usd": {"before": b_cost, "after": a_cost},
            "test_repair": {"before": (before.get("test_repair") or {}).get("attempted"), "after": (after.get("test_repair") or {}).get("attempted"),
                            "ok_after": (after.get("test_repair") or {}).get("ok")},
        },
        "verdicts": {"before": before.get("verdicts"), "after": after.get("verdicts")},
        "cases": cases,
        "note": "The first run is reported unchanged. Rates over a few single runs with a non-deterministic model carry wide uncertainty; "
                "a verdict that changed between runs is not by itself an effect of the repair.",
    }


def render_diff(diff):
    h = diff["headline"]
    out = ["# Latch eval: before / after", "",
           f"Before: `{diff['before']['file']}` (Latch `{diff['before'].get('latch_git_sha')}`). After: `{diff['after']['file']}` "
           f"(tag `{diff['after'].get('tag')}`, Latch `{diff['after'].get('latch_git_sha')}`).", "",
           "| Measure | Before | After |", "|---|---|---|",
           f"| Real fixes VALIDATED | {h['real_validated']['before']} | {h['real_validated']['after']} |",
           f"| INVALID_TEST runs | {h['invalid_test']['before']} | {h['invalid_test']['after']} |",
           f"| Wrong patches failed by a valid test | {h['wrong_patches_failed_by_valid_test']['before']} | {h['wrong_patches_failed_by_valid_test']['after']} |",
           f"| False accepts | {h['false_accepts']['before']} | {h['false_accepts']['after']} |",
           f"| Cost | {h['cost_usd']['before']} | {h['cost_usd']['after']} |",
           f"| Test repairs attempted (worked) | {h['test_repair']['before']} | {h['test_repair']['after']} ({h['test_repair']['ok_after']}) |", "",
           "| Case | Variant | Before | After | Test repair |", "|---|---|---|---|---|"]
    out += [f"| {c['case']} | {c['variant']} | {c['verdict_before']} | {c['verdict_after']}{' *' if c['changed'] else ''} | {c['test_repair'] or ''} |"
            for c in diff["cases"]]
    return "\n".join(out + ["", "\\* verdict changed. " + diff["note"], ""])
