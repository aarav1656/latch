"""`latch eval`: the Slopgate-comparable benchmark.

    latch eval run --dry-run [--only ID ...] [--out-dir DIR]     stubbed model output, spends nothing, writes DIR (default latch/runs/eval-dryrun/)
    latch eval run [--only ID ...] [--jobs 3] [--max-iterations 3] [--out F] [--skip-validate]     LIVE: real Nemotron calls, spends Token Factory credit
    latch eval summarize EVAL.json                                rebuild latch/runs/eval-summary.json and eval-report.md from a finished run
    latch eval diff BEFORE.json AFTER.json [--out F]              side by side: per-case verdict before -> after, and the headline numbers
    latch eval report [--summary F] [--out F]                     render the Markdown report from an eval-summary.json
    latch eval oracle [--only ID ...] [--jobs 2]                  oracle baseline (no model): upstream tests on base, real and wrong; $0
    latch eval manifest [--write|--check]                         pin models, prompts, dataset and SHAs

`run --tag NAME` writes a second run beside the first (never over it); an untagged run refuses to replace an existing eval-DATE.json.

--provider nebius|openrouter (or $LATCH_PROVIDER) picks the model provider; nebius is the default. openrouter is DEV ONLY: `run` then writes only
latch/runs/dev/eval-summary-openrouter.json (+ eval-report-openrouter.md, eval-DATE-openrouter.json, eval/), marked dev_only, and never latch/runs/eval-summary.json.

`--dry-run` (alias `--fixture`) never writes latch/runs/eval-summary.json, so a placeholder can never look like a result.
Clones and caches live under $LATCH_EVAL_ROOT (use a large disk); the venv is $LATCH_EVAL_VENV.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _selected(only):
    from .cases import CASES

    cases = [c for c in CASES if not only or c["id"] in only]
    if only and len(cases) != len(set(only)):
        raise SystemExit(f"unknown case id in {only}")
    return cases


def run_dry(only=None, out_dir=None, root=REPO_ROOT):
    """Build a summary and report from stubbed receipts. Returns (summary, summary_path, report_path). Spends nothing, calls nothing."""
    from .cases import CASES, DROPPED
    from .fixture import make_fixture
    from .report import render
    from .summary import build_summary, extras

    cases = _selected(only)
    doc, receipts = make_fixture(cases)
    ex = extras(root)
    summary = build_summary(doc, CASES, receipts.get, dropped=DROPPED, root=root, mode="dry-run", **ex)
    out_dir = Path(out_dir or Path(root) / "latch" / "runs" / "eval-dryrun")
    out_dir.mkdir(parents=True, exist_ok=True)
    s_path, r_path = out_dir / "eval-summary.json", out_dir / "eval-report.md"
    s_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    r_path.write_text(render(summary), encoding="utf-8")
    return summary, s_path, r_path


def main(argv=None):
    from latch import provider as providers
    try:
        argv = providers.take_flag(sys.argv[1:] if argv is None else argv)
    except ValueError as error:
        print(f"latch eval: {error}", file=sys.stderr)
        return 64
    ap = argparse.ArgumentParser(prog="latch eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the benchmark (live) or --dry-run it with stubbed outputs")
    r.add_argument("--dry-run", "--fixture", dest="dry_run", action="store_true", help="stubbed model output; spends nothing; not a result")
    r.add_argument("--only", nargs="*")
    r.add_argument("--jobs", type=int, default=3)
    r.add_argument("--max-iterations", type=int, default=3)
    r.add_argument("--out", default=None)
    r.add_argument("--out-dir", default=None, help="dry-run output directory")
    r.add_argument("--skip-validate", action="store_true")
    r.add_argument("--no-summary", action="store_true")
    r.add_argument("--tag", default=None, help="write a second run beside the first (eval-DATE-TAG.json, eval-summary-TAG.json, eval-report-TAG.md, eval-TAG/)")
    r.add_argument("--no-test-repair", action="store_true", help="turn the one-round test repair off")
    r.add_argument("--overwrite", action="store_true", help="allow an untagged run to replace an existing eval-DATE.json")
    r.add_argument("--test-model", default=None, help="model that writes the proof test (default Ultra); the fix model is unchanged")
    s = sub.add_parser("summarize")
    s.add_argument("eval_json")
    d = sub.add_parser("diff", help="before/after of two eval summaries (for example the first run and the --tag repair run)")
    d.add_argument("before")
    d.add_argument("after")
    d.add_argument("--out", default=None, help="write here instead of stdout")
    p = sub.add_parser("report")
    p.add_argument("--summary", default=str(REPO_ROOT / "latch" / "runs" / "eval-summary.json"))
    p.add_argument("--out", default=None, help="write here instead of stdout")
    o = sub.add_parser("oracle")
    o.add_argument("--only", nargs="*")
    o.add_argument("--jobs", type=int, default=2)
    o.add_argument("--out", default=str(REPO_ROOT / "latch" / "runs" / "eval-oracle-baseline.json"))
    sub.add_parser("manifest", add_help=False)
    args, rest = ap.parse_known_args(argv)
    if args.cmd == "manifest":
        from .manifest import main as manifest_main
        return manifest_main(rest)
    if rest:
        ap.error(f"unrecognized arguments: {' '.join(rest)}")

    if args.cmd == "run":
        if args.dry_run:
            summary, s_path, r_path = run_dry(args.only, args.out_dir)
            print(json.dumps({"mode": summary["mode"], "verdicts": summary["verdicts"], "summary": str(s_path), "report": str(r_path),
                              "note": "DRY RUN: stubbed model output, not a result; nothing was spent"}, indent=2))
            return 0
        from .run_eval import main as run_main
        argv2 = ["run", "--jobs", str(args.jobs), "--max-iterations", str(args.max_iterations)]
        if args.only:
            argv2 += ["--only", *args.only]
        for flag, val in (("--out", args.out),):
            if val:
                argv2 += [flag, val]
        if args.tag:
            argv2 += ["--tag", args.tag]
        if args.test_model:
            argv2 += ["--test-model", args.test_model]
        argv2 += [f for f, on in (("--skip-validate", args.skip_validate), ("--no-summary", args.no_summary),
                                  ("--no-test-repair", args.no_test_repair), ("--overwrite", args.overwrite)) if on]
        return run_main(argv2)
    if args.cmd == "summarize":
        from .run_eval import main as run_main
        return run_main(["summarize", args.eval_json])
    if args.cmd == "diff":
        from .rundiff import diff_summaries, render_diff
        diff = diff_summaries(json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text()),
                              Path(args.before).name, Path(args.after).name)
        text = json.dumps(diff, indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            Path(args.out).with_suffix(".md").write_text(render_diff(diff), encoding="utf-8")
            print(f"wrote {args.out} and {Path(args.out).with_suffix('.md')}", file=sys.stderr)
        else:
            print(render_diff(diff))
        return 0
    if args.cmd == "report":
        from .report import render
        summary = json.loads(Path(args.summary).read_text())
        text = render(summary)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(text)
        return 0
    if args.cmd == "oracle":
        from . import oracle
        from .cases import DROPPED
        doc = oracle.run_oracle(_selected(args.only), jobs=args.jobs, dropped=DROPPED,
                                progress=lambda row: print(f"[oracle] {row['case']}: {'ok' if row['ok'] else 'NOT ok'} ({row['wall_s']}s)", file=sys.stderr, flush=True))
        md = str(Path(args.out).with_suffix(".md"))
        oracle.write(doc, args.out, md)
        print(oracle.render(doc))
        print(f"wrote {args.out} and {md}", file=sys.stderr)
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main())
