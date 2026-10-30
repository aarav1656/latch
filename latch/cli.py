"""`latch`: one console entry point for prove, the fix loop and the PR comment.

    latch prove   --repo R --base B --head H --issue TEXT [--receipt F] [--pr-comment F|-]
    latch loop    --repo R --base B --head H --issue TEXT [--receipt F] [--pr-comment F|-] [--human|--jsonl]
    latch demo    [--human|--jsonl] [--pace 1]
    latch comment RECEIPT [--post --repo OWNER/REPO --pr N]     (default: print the comment, post nothing)
    latch eval    run [--dry-run] | summarize | report | oracle | manifest     (the Slopgate-comparable benchmark; --dry-run spends nothing)

Every model-calling command takes --provider nebius|openrouter (or set LATCH_PROVIDER); the default is nebius.
openrouter is DEV ONLY (free tier, rate limited, not Token Factory numbers): its receipts say provider=openrouter and
default to latch/runs/dev/, and `latch eval run` then writes only under latch/runs/dev/, never latch/runs/eval-summary.json.

Exit status: prove 0 proven / 1 not proven / 2 error; loop 0 gate_open / 1 gave_up / 2 error; 64 bad arguments.
Nothing is posted anywhere unless `latch comment --post` is given explicitly, with GITHUB_TOKEN set.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import provider as providers
from .pr_comment import post_or_update_comment, render_comment


def _emit_comment(markdown, dest):
    if dest == "-":
        print(markdown)
    else:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(markdown, encoding="utf-8")


def _prove(argv):
    p = argparse.ArgumentParser(prog="latch prove", description="Prove a change against its issue with a model-written test")
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    issue = p.add_mutually_exclusive_group(required=True)
    issue.add_argument("--issue")
    issue.add_argument("--issue-file")
    p.add_argument("--test-command", default="python3 -m pytest -q")
    p.add_argument("--receipt", default=None, help="default latch/runs/latest-proof.json (latch/runs/dev/latest-proof-openrouter.json on openrouter)")
    p.add_argument("--no-revert", action="store_true", help="skip the revert check (not recommended)")
    p.add_argument("--no-mutation", action="store_true", help="skip the AST mutation check of the changed lines (not recommended)")
    p.add_argument("--no-strengthen", action="store_true", help="do not give the test writer the one survivor-driven retry after a failed mutation check")
    p.add_argument("--no-triage", action="store_true")
    p.add_argument("--flake-runs", type=int, default=5, metavar="N",
                   help="rerun the proof test N times on base and head to catch flakiness (default 5, max 10; 1 = off)")
    p.add_argument("--pr-comment", metavar="PATH", help="write the receipt as a Markdown PR comment ('-' = stdout)")
    args = p.parse_args(argv)
    if args.receipt is None:
        default = "latch/runs/latest-proof.json"
        args.receipt = str(providers.dev_path(default)) if providers.is_dev() else default
    from .prove import prove
    try:
        text = args.issue if args.issue is not None else Path(args.issue_file).read_text(encoding="utf-8")
        result = prove(args.repo, args.base, args.head, text, args.test_command, args.receipt,
                       revert=not args.no_revert, triage=not args.no_triage, flake_runs=args.flake_runs,
                       mutation=not args.no_mutation, strengthen=not args.no_strengthen)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Latch proof failed: {error}", file=sys.stderr)
        return 2
    if args.pr_comment:
        _emit_comment(render_comment(result), args.pr_comment)
    print(json.dumps({"proven": result["proven"], "receipt": args.receipt, "completion_id": result["completion_id"]}),
          file=sys.stderr if args.pr_comment == "-" else sys.stdout)
    return 0 if result["proven"] else 1


def _comment(argv):
    p = argparse.ArgumentParser(prog="latch comment", description="Render a receipt as a PR comment; optionally post it")
    p.add_argument("receipt", help="receipt JSON from `latch prove` or `latch loop`")
    p.add_argument("--post", action="store_true", help="really post or update the PR comment (needs GITHUB_TOKEN)")
    p.add_argument("--dry-run", action="store_true", help="print the comment and the API calls, send nothing (the default)")
    p.add_argument("--repo", help="OWNER/REPO (with --post)")
    p.add_argument("--pr", type=int, help="pull request number (with --post)")
    p.add_argument("--run-url", help="link to the CI run, shown in the footer")
    args = p.parse_args(argv)
    try:
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"cannot read receipt: {error}", file=sys.stderr)
        return 64
    markdown = render_comment(receipt, run_url=args.run_url)
    if not args.post or args.dry_run:
        print(markdown)
        if args.repo and args.pr:
            for line in post_or_update_comment(args.repo, args.pr, markdown, dry_run=True)["would"]:
                print(f"dry-run: {line}", file=sys.stderr)
        return 0
    if not (args.repo and args.pr):
        print("--post needs --repo OWNER/REPO and --pr N", file=sys.stderr)
        return 64
    try:
        result = post_or_update_comment(args.repo, args.pr, markdown)
    except (RuntimeError, OSError) as error:
        print(f"could not post the comment: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 64
    cmd, rest = argv[0], argv[1:]
    try:
        rest = providers.take_flag(rest)
    except ValueError as error:
        print(f"latch: {error}", file=sys.stderr)
        return 64
    if cmd == "prove":
        return _prove(rest)
    if cmd == "comment":
        return _comment(rest)
    if cmd in ("loop", "demo"):
        from .loop.cli import main as loop_main
        return loop_main([{"loop": "run"}.get(cmd, cmd), *rest])
    if cmd == "eval":
        from .loop.eval.cli import main as eval_main
        return eval_main(rest)
    print(f"unknown command: {cmd} (prove | loop | demo | comment | eval)", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
