"""CLI: python3 -m latch.loop {run,demo} ...

stdout is JSONL, one event per line (flushed). A human summary goes to stderr.
Exit status: 0 gate_open, 1 gave_up, 2 error (fail closed), 64 bad arguments.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .core import (now, ALLOWED_MODELS, DEFAULT_MODEL, LoopError, prepare_demo, run_demo, run_loop)


def _common(p):
    p.add_argument("--max-iterations", type=int, default=3)
    p.add_argument("--model", default=DEFAULT_MODEL, help="fix agent: " + " | ".join(ALLOWED_MODELS))
    p.add_argument("--test-command", default="python3 -m pytest -q")
    p.add_argument("--receipt", help="write the JSON receipt here")
    p.add_argument("--events", help="also write the JSONL events here")
    p.add_argument("--proof-test", help="file with a pytest function to use instead of generating one")
    p.add_argument("--no-triage", action="store_true", help="skip the Lightning triage (not recommended)")
    p.add_argument("--run-id")


def build_parser():
    parser = argparse.ArgumentParser(prog="python3 -m latch.loop", description="Latch fix loop")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the loop on a git repo")
    run.add_argument("--repo", required=True)
    run.add_argument("--base", required=True, help="buggy revision")
    run.add_argument("--head", required=True, help="the submitted fix revision")
    issue = run.add_mutually_exclusive_group(required=True)
    issue.add_argument("--issue")
    issue.add_argument("--issue-file")
    _common(run)
    demo = sub.add_parser("demo", help="bundled constructed demo (green suite, wrong fix)")
    demo.add_argument("--prepare", action="store_true", help="only pre-warm: build the demo repo, check tooling")
    demo.add_argument("--force", action="store_true", help="with --prepare, rebuild the demo repo")
    _common(demo)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.model not in ALLOWED_MODELS:
        print(f"--model must be one of: {', '.join(ALLOWED_MODELS)}", file=sys.stderr)
        return 64

    if args.cmd == "demo" and args.prepare:
        try:
            prep = prepare_demo(force=args.force)
        except (LoopError, OSError) as error:
            print(f"prepare failed: {error}", file=sys.stderr)
            return 2
        print(json.dumps({"type": "prepared", "repo": prep["repo"], "base": prep["base"],
                          "head": prep["head"], "checks": prep["checks"]}))
        return 0 if all(prep["checks"].values()) else 2

    try:
        proof_text = Path(args.proof_test).read_text(encoding="utf-8") if args.proof_test else None
    except OSError as error:
        print(f"cannot read --proof-test: {error}", file=sys.stderr)
        return 64
    events_file = open(args.events, "w", encoding="utf-8") if args.events else None

    seen = {"error": False}

    def on_event(event):
        seen["error"] = seen["error"] or event["type"] == "error"
        line = json.dumps(event)
        print(line, flush=True)
        if events_file:
            events_file.write(line + "\n")
            events_file.flush()
        t = event["type"]
        if t in ("gate_shut", "iteration_result", "triage", "gate_open", "gave_up", "error"):
            note = event.get("verdict") or event.get("reason") or ""
            print(f"[{t}] iteration={event.get('iteration', '-')} {str(note)[:160]}", file=sys.stderr)

    kwargs = dict(
        test_command=args.test_command,
        max_iterations=args.max_iterations,
        model=args.model,
        receipt_path=args.receipt,
        on_event=on_event,
        proof_test=proof_text,
        triage=not args.no_triage,
        run_id=args.run_id,
    )
    started = time.monotonic()
    try:
        if args.cmd == "demo":
            receipt = run_demo(**kwargs)
        else:
            issue = args.issue if args.issue is not None else Path(args.issue_file).read_text(encoding="utf-8")
            receipt = run_loop(args.repo, args.base, args.head, issue, **kwargs)
    except ValueError as error:
        print(f"bad arguments: {error}", file=sys.stderr)
        return 64
    except (LoopError, OSError, subprocess.SubprocessError) as error:
        if not seen["error"]:  # failed before run_loop could emit its own error event
            on_event({"type": "error", "ts": now(), "run_id": args.run_id or "none", "reason": str(error)})
        return 2
    finally:
        if events_file:
            events_file.close()
    print(f"wall time: {time.monotonic() - started:.1f}s", file=sys.stderr)
    return 0 if receipt["verdict"] == "gate_open" else 1
