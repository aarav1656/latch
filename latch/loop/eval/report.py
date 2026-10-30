"""Markdown report from an eval summary (schema 2): a Slopgate-style comparison table, per-case rows, and the baselines.

Pure: `render(summary) -> str`. A dry-run summary (`mode == "dry-run"`) gets a banner on top and a label on every number:
it is stubbed model output exercising the harness and never a result.
"""
from . import compare

NOT_RUN = "not run"


def _cell(v, fmt="{}"):
    return "n/a" if v is None else fmt.format(v)


def _pct(r):
    return NOT_RUN if not r or not r.get("n") else f"{r['k']}/{r['n']} ({r['rate'] * 100:.0f}%)"


def _flaky(f):
    if not isinstance(f, dict) or not f.get("ran"):
        return "n/a"
    return "FLAKY" if f.get("flaky") else f"stable ({f.get('flake_rate')})"


def _yn(v):
    return "n/a" if v is None else ("yes" if v else "no")


def _mutation(m):
    return "n/a" if not m else "{}/{}".format(m["killed"], m["total"])


def render(summary):
    mode = summary.get("mode", "live")
    out = ["# Latch eval report", ""]
    if mode != "live":
        out += ["> **DRY RUN: FIXTURE DATA, NOT A RESULT.** Every number below comes from stubbed model output built in code so the "
                "harness, summary math and report can be exercised. No model was called and nothing was spent.", ""]
    if summary.get("dev_only"):
        out += [f"> **DEV-ONLY RUN** (provider: {summary.get('provider') or 'unknown'}). {summary.get('note') or 'Not Nebius Token Factory numbers.'}", ""]
    out += [f"Generated {summary.get('generated_at')}. Schema {summary.get('schema_version')}. Latch `{summary.get('latch_git_sha') or 'unknown'}`.", ""]
    bench = summary.get("benchmark") or {}
    cmp_ = summary.get("slopgate_comparison") or {}
    latch = cmp_.get("latch") or {}
    out += ["## Comparison with Slopgate", "", f"Slopgate's column is quoted from its own repo ({compare.SLOPGATE['repo_url']}; results file "
            f"{compare.SLOPGATE['results_url']}, run {compare.SLOPGATE['run_date']}); Latch did not re-run it.", "",
            "| | Slopgate (its own numbers) | Latch (this eval) |", "|---|---|---|"]
    if latch:
        out += [f"| {label} | {a} | {b} |" for label, a, b in compare.table_rows(latch, mode)]
    out += ["", cmp_.get("caveat") or compare.DIFFERENT_TASKS, ""]

    out += ["## Named verdicts", "", "| Verdict | Runs |", "|---|---|"]
    out += [f"| {v} | {n} |" for v, n in (summary.get("verdicts") or {}).items()]
    fl = summary.get("flaky") or {}
    out += ["", f"Flaky check: {fl.get('n_cases_checked', 0)} runs checked, {fl.get('n_flaky', 0)} flaky, median flake rate "
            f"{_cell(fl.get('median_flake_rate'))}.", ""]

    mut = bench.get("mutation") or {}
    wall = bench.get("wall_s") or {}
    wrong = bench.get("wrong_patch_rejection") or {}
    out += ["## Totals", "", "| Measure | Value |", "|---|---|",
            f"| Runs (errors, not run) | {bench.get('runs', 0)} ({bench.get('errors', 0)}, {bench.get('not_run', 0)}) |",
            f"| Real fixes VALIDATED | {_pct(bench.get('real_validated'))} |",
            f"| Proof test fails on base (real fixes) | {_pct(bench.get('real_fail_on_base'))} |",
            f"| Fail-to-pass (fails on base and passes on head) | {_pct(bench.get('real_fail_to_pass'))} |",
            f"| Wrong patches rejected (FIX_FAILS_TEST) | {_pct(wrong)} |",
            f"| ... without the contested cases | {_pct(wrong.get('without_contested'))} |",
            f"| No-fix runs where the gate opened | {_pct(bench.get('nofix_gate_open'))} |",
            f"| Gate-accepted but oracle rejects | {(bench.get('gate_accepted_but_oracle_fails') or {}).get('n', NOT_RUN)} |",
            f"| Mutation kill rate (pooled) | {_cell(mut.get('pooled_kill_rate'))} ({mut.get('mutants_killed', 0)}/{mut.get('mutants_total', 0)} mutants) |",
            f"| Tokens (prompt / completion) | {_cell(bench.get('prompt_tokens'))} / {_cell(bench.get('completion_tokens'))} |",
            f"| Cost | {_cell(bench.get('cost_usd'), '${}')} |",
            f"| Wall time (total / median per run) | {_cell(wall.get('total'), '{} s')} / {_cell(wall.get('median'), '{} s')} |", ""]

    oracle = summary.get("oracle_baseline")
    if oracle:
        t = oracle["totals"]
        out += ["## Oracle baseline (no model)", "",
                f"Upstream tests on base, real and wrong, no LLM, $0: fails on base {_pct(t['oracle_fails_on_base'])}, passes on real fix "
                f"{_pct(t['oracle_passes_on_real_fix'])}, rejects wrong patch {_pct(t['oracle_rejects_wrong_patch'])}. The answer key the "
                "model never sees; kept cases were selected for this property.", ""]

    out += ["## Baselines from the literature", "", "| Baseline | Metric | Value | Benchmark | Source |", "|---|---|---|---|---|"]
    for b in summary.get("baselines") or []:
        out.append(f"| {b['name']} | {b['metric']} | {b['value'] * 100:.1f}% | {b['benchmark']} | {b['source_url']} |")
    out += ["", summary.get("caveat", ""), ""]

    out += ["## Per case", "", "| Case | Variant | Verdict | Fail on base | Pass on head | Mutation | Flaky | Tokens in/out | Cost | Wall s | Outcome |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary.get("cases") or []:
        if r.get("status") != "ran":
            out.append(f"| {r['case']} | {r['variant']} | {NOT_RUN} | | | | | | | | {r.get('status')} |")
            continue
        out.append(f"| {r['case']} | {r['variant']} | {r.get('verdict') or 'n/a'} | {_yn(r.get('fail_on_base'))} | {_yn(r.get('pass_on_head'))} | "
                   f"{_mutation(r.get('mutation'))} | {_flaky(r.get('flaky'))} | "
                   f"{_cell(r.get('prompt_tokens'))}/{_cell(r.get('completion_tokens'))} | {_cell(r.get('cost_usd'), '${}')} | "
                   f"{_cell(r.get('wall_s'))} | {r.get('outcome')} |")
    dropped = summary.get("dropped_cases") or []
    if dropped:
        out += ["", "## Dropped before any run", ""] + [f"- `{d['id']}`: {d.get('reason')}" for d in dropped]
    return "\n".join(out) + "\n"
