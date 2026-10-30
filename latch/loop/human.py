"""Human-readable timeline of a loop run (the film mode): gate shut -> triage -> patch -> gate open.

Consumes the same events the JSONL stream carries, so what you watch is what the receipt records.
"""

import subprocess
import sys
import time

COLORS = {"red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
          "dim": "2", "bold": "1"}


def submitted_diff(repo, base, head, max_lines=14):
    """Short unified diff of the submitted change (tests left out) for display ('' if git cannot produce it)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "diff", "--no-ext-diff", "--unified=1", base, head, "--",
                              ".", ":(exclude)test_*.py", ":(exclude)*_test.py", ":(exclude)tests", ":(exclude)test"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = [l for l in out.splitlines() if not l.startswith(("diff --git", "index "))]
    return "\n".join(lines[:max_lines] + (["..."] if len(lines) > max_lines else []))


def headline(issue):
    for line in str(issue).splitlines():
        if line.strip():
            return line.strip()
    return ""


class Timeline:
    """Callable event sink: prints one readable line (or a few) per event."""

    def __init__(self, out=None, color=None, pace=0.0, show_issue=None, diff_text=None):
        self.out = out or sys.stdout
        self.color = self.out.isatty() if color is None else color
        self.pace = pace
        self.t0 = time.monotonic()
        self.show_issue = show_issue
        self.diff_text = diff_text
        self.calls = []
        self.open_steps = {}

    def c(self, name, text):
        return f"\x1b[{COLORS[name]}m{text}\x1b[0m" if self.color else text

    def say(self, text="", pause=0.0):
        print(text, file=self.out, flush=True)
        if self.pace and pause:
            time.sleep(self.pace * pause)

    def stamp(self):
        return self.c("dim", f"[{time.monotonic() - self.t0:5.1f}s]")

    def line(self, text, pause=0.0, indent=0):
        self.say(f"{self.stamp()} {' ' * indent}{text}", pause)

    def block(self, text, color=None, indent=9, limit=14):
        rows = str(text).rstrip("\n").splitlines()
        for row in rows[:limit]:
            shade = color or ("green" if row.startswith("+") and not row.startswith("+++") else
                              "red" if row.startswith("-") and not row.startswith("---") else None)
            self.say(" " * indent + (self.c(shade, row) if shade else row))
        if len(rows) > limit:
            self.say(" " * indent + self.c("dim", f"... {len(rows) - limit} more line(s)"))

    def __call__(self, e):
        t = e["type"]
        if t == "started":
            self.say(self.c("bold", "LATCH") + "  the gate, not the model, decides open or shut")
            if e.get("case_note"):
                self.say(self.c("yellow", e["case_note"]))
            self.say(self.c("bold", "Issue: ") + (self.show_issue or headline(e.get("issue", ""))), 1)
            if self.diff_text:
                self.say(self.c("bold", "Submitted change:"))
                self.block(self.diff_text, indent=2)
            self.say("", 1)
            self.t0 = time.monotonic()
        elif t == "step":
            self.step(e)
        elif t == "model_call":
            self.calls.append(e)
            tokens = "" if e.get("prompt_tokens") is None else f"  {e['prompt_tokens']}+{e['completion_tokens']} tok"
            cost = "" if e.get("cost_usd") is None else f"  ~${e['cost_usd']:.5f}"
            self.line(self.c("dim", f"{e['role']:<11} {str(e['model']).split('/')[-1]}  {e.get('completion_id') or '-'}"
                                    f"{tokens}  {e.get('latency_ms', 0) / 1000:.1f}s{cost}"), indent=2)
        elif t == "model_retry":
            self.line(self.c("yellow", f"model retry {e.get('attempt')}/{e.get('attempts')}: {e.get('error') or e.get('status')}"), indent=2)
        elif t == "proof_test":
            self.line(self.c("bold", f"Proof test frozen: {e['name']}") + self.c("dim", "  (written once, never edited)"))
            self.block(e["test"].replace("import pytest\n\n", "", 1), color="cyan", limit=9)
            self.say("", 0.5)
        elif t == "gate_shut":
            self.line(self.c("red", "GATE SHUT") + f"  {e.get('reason', '')}", 1.5)
        elif t == "gate_check":
            self.line(self.c("green", "gate check") + "  proof test red on base, green on the submitted change", 0.5)
        elif t == "triage":
            verdict = e.get("verdict")
            self.line(self.c("magenta", "Lightning triage: ") + self.c("green" if verdict == "reproduced" else "red", str(verdict))
                      + self.c("dim", f"  {str(e.get('reason') or '')[:110]}"), 1)
        elif t == "iteration_started":
            self.line(self.c("blue", f"Ultra writes a patch (iteration {e['iteration']})"))
        elif t == "patch_applied":
            self.line("patch applied to " + ", ".join(e.get("changed_files", [])), 0.3)
            self.block(e.get("diff", ""), limit=16)
            self.say("", 0.7)
        elif t == "iteration_result":
            ok = e.get("verdict") == "gate_open"
            tail = [l for l in str(e.get("pytest_output") or "").splitlines() if l.strip()]
            word = "proof test passes and repo suite green" if ok else str(e.get("detail") or (tail[-1] if tail else "proof test still red"))[:120]
            self.line((self.c("green", "pass: ") if ok else self.c("red", "still shut: ")) + word, 0.5)
        elif t in ("gate_open", "gave_up", "error"):
            self.finish(e)

    def step(self, e):
        name, status, detail = e["step"], e["status"], e.get("detail")
        label = {"fetch": "fetch revisions", "repo_map": "Lightning repo map", "test_writer": "Ultra writes the proof test",
                 "base_run": "run proof test on base", "head_run": "run proof test + suite on submitted change",
                 "triage": "Lightning triage", "fix": "fix", "revert_check": "revert check", "mutation_check": "mutation check", "flake_check": "flake check",
                 "verdict": "verdict"}.get(name, name)
        if name in ("triage", "fix", "verdict"):
            return  # these have richer events of their own
        if status == "started":
            if name in ("repo_map", "test_writer", "revert_check", "flake_check", "mutation_check"):
                self.line(self.c("bold", label) + self.c("dim", " ..."))
            return
        if name == "repo_map":
            files = (detail or {}).get("files") or []
            self.line((self.c("green", "ok  ") + f"{len(files)} file(s): {', '.join(files[:4])}") if status == "done"
                      else self.c("yellow", f"unavailable ({(detail or {}).get('detail')}); continuing without a map"), indent=2)
        elif name == "base_run":
            red = (detail or {}).get("red")
            self.line(f"base:  proof test " + (self.c("green", "FAILS with an assertion") + " (red on the bug)" if red
                                                else self.c("red", "does not fail with an assertion")), 0.6)
        elif name == "head_run":
            ok = (detail or {}).get("gate_open")
            self.line("head:  " + (self.c("green", "proof test passes, suite green") if ok
                                   else self.c("red", "proof test fails on the submitted change")), 0.6)
        elif name == "flake_check":
            d = detail or {}
            self.line((self.c("green", "ok  ") + f"stable over {d.get('runs')} runs on base and head" if status == "done"
                       else self.c("red", "FLAKY  ") + f"inconsistent results over {d.get('runs')} runs (flake rate {d.get('flake_rate', 0):.0%})"),
                      0.5, indent=2)
        elif name == "mutation_check":
            d = detail or {}
            rate = d.get("kill_rate")
            self.line((self.c("green", "ok  ") if status == "done" else self.c("red", "FAILED  "))
                      + ("no mutants ran (nothing to mutate, or the time budget ran out); see the receipt note" if not d.get("total") and status == "done"
                         else f"killed {d.get('killed', 0)}/{d.get('total', 0)} mutants of the changed lines"
                              + (f" (kill rate {rate:.0%})" if rate is not None else " (the check could not complete)")), 0.8, indent=2)
        elif name == "revert_check":
            summary = detail if isinstance(detail, str) else ""
            self.line((self.c("green", "ok  ") if status == "done" else self.c("red", "FAILED  ")) + summary, 0.8, indent=2)

    def finish(self, e):
        t = e["type"]
        self.say("", 0.3)
        if t == "gate_open":
            receipt = e.get("receipt") or {}
            n = len(receipt.get("iterations") or [])
            self.line(self.c("green", self.c("bold", "GATE OPEN")) + "  "
                      + ("the submitted change already passed" if not n else f"after {n} iteration(s)")
                      + "; the proof test also fails with the fix reverted")
        else:
            self.line(self.c("red", self.c("bold", "GATE SHUT" if t == "gave_up" else "ERROR")) + f"  {e.get('reason', '')}")
        receipt = e.get("receipt") or {}
        if receipt.get("verdict"):
            self.line(self.c("bold", "VERDICT ") + self.c("green" if receipt.get("proven") else "red", receipt["verdict"])
                      + self.c("dim", f"  {str(receipt.get('verdict_reason') or '')[:140]}"))
            flaky, mutation = receipt.get("flaky") or {}, receipt.get("mutation") or {}
            if flaky.get("ran"):
                self.line(f"flake check: {flaky['runs']} runs on base and head, flake rate {flaky['flake_rate']:.0%}", indent=2)
            if mutation.get("ran") is False and mutation.get("ok") is False:
                self.line(f"mutation check: could not complete ({mutation.get('note')})", indent=2)
            elif mutation.get("incomplete"):
                self.line(f"mutation check: {mutation.get('note')}", indent=2)
            elif mutation.get("total"):
                self.line(f"mutation check: killed {mutation['killed']}/{mutation['total']} (kill rate {mutation['kill_rate']:.0%}, needs {mutation['threshold']:.0%})", indent=2)
        calls = receipt.get("model_calls") or self.calls
        if calls:
            cost = receipt.get("model_cost_usd")
            self.say(self.c("dim", f"  {len(calls)} model calls ({', '.join(sorted({c['role'] for c in calls}))}); "
                                   + (f"estimated ${cost:.4f} at Token Factory list prices" if cost is not None else "cost unknown")))
        if e.get("receipt_path"):
            self.say(self.c("dim", f"  receipt: {e['receipt_path']}"))
