"""Latch loop eval: does the gate open on real fixes and stay shut on known-wrong patches?

    python3 -m latch.loop.eval.run_eval validate [--only ID ...]   check every case's ground truth (no model calls)
    python3 -m latch.loop.eval.run_eval run [--only ID ...] [--jobs 3] [--out latch/runs/eval-DATE.json]

Ground truth ("oracle") for each case is the upstream fix commit's own test files:
  - they must FAIL on the base, PASS on the real fix, and FAIL on the constructed wrong patch;
  - the repo's own suite must be green on the base and on the wrong patch (so only the proof test can catch it).
A case that does not satisfy this is dropped by `validate` (and reported), never fudged.

Per case, Latch (latch.loop.run_loop with Lightning triage, Ultra for the proof test and fixes) runs twice:
  real  : base = fix^, head = the real upstream commit
  wrong : base = fix^, head = base + the constructed wrong patch (source files only)
False accept = the gate is open at iteration 0 on the wrong patch (no loop needed). Repair = the gate was shut,
the loop patched, and the gate opened; the repaired code is then checked against the oracle (the model never sees it).

Clones, wrong-patch repos and caches live under $LATCH_EVAL_ROOT (default /mnt/data/nvdia/loop);
the venv (pytest, hypothesis, ... but none of the projects) lives at $LATCH_EVAL_VENV (default ~/.cache/latch-eval/venv).
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from latch.loop.core import LoopError, run_loop  # noqa: E402
from latch.loop.eval.cases import CASES, DROPPED  # noqa: E402

ROOT = Path(os.environ.get("LATCH_EVAL_ROOT", "/mnt/data/nvdia/loop"))
VENV = Path(os.environ.get("LATCH_EVAL_VENV", "~/.cache/latch-eval/venv")).expanduser()
PY = str(VENV / "bin" / "python")
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=latch-eval", "-c", "user.email=eval@latch.invalid"]


def sh(args, cwd=None, **kw):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)


def clone_dir(case):
    return ROOT / "repos" / case["clone"]


def test_command(case):
    extra = case["test_files"] if case.get("swe") else case.get("extra", [])
    return " ".join([shlex.quote(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra])


def swe_head(case):
    """Dangling commit in the clone = base + the instance's gold source patch (the working tree is never touched)."""
    clone = clone_dir(case)
    cache = ROOT / "swe_heads" / f"{case['id']}.sha"
    if cache.exists() and sh(["git", "cat-file", "-e", cache.read_text().strip()], cwd=clone).returncode == 0:
        return cache.read_text().strip()
    with tempfile.TemporaryDirectory() as t:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(t) / "index"), "GIT_AUTHOR_NAME": "latch-eval",
               "GIT_AUTHOR_EMAIL": "eval@latch.invalid", "GIT_COMMITTER_NAME": "latch-eval",
               "GIT_COMMITTER_EMAIL": "eval@latch.invalid"}
        run = lambda *a, **kw: subprocess.run(["git", *a], cwd=clone, env=env, capture_output=True, text=True, **kw)
        for step in (run("read-tree", case["base"]), run("apply", "--cached", "-", input=case["patch"])):
            if step.returncode:
                raise RuntimeError(f"{case['id']}: cannot build the gold head: {step.stderr}")
        tree = run("write-tree").stdout.strip()
        sha = run("commit-tree", tree, "-p", case["base"], "-m", f"{case['id']} gold patch").stdout.strip()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(sha)
    return sha


def base_sha(case):
    if case.get("swe"):
        return case["base"]
    r = sh(["git", "rev-parse", f"{case['fix']}^"], cwd=clone_dir(case))
    if r.returncode:
        raise RuntimeError(f"cannot resolve base of {case['id']}: {r.stderr.strip()}")
    return r.stdout.strip()


def archive(repo, ref, dst):
    data = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", ref], stdout=subprocess.PIPE, check=True).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(dst)], input=data, check=True)


def oracle_files(case):
    """The fix commit's own test files (python files under a test path)."""
    out = sh(["git", "show", "--name-only", "--format=", case["fix"]], cwd=clone_dir(case)).stdout.split()
    return [f for f in out if f.endswith(".py") and re.search(r"(^|/)(tests?|test_[^/]*|[^/]*_test\.py)(/|$)", f)]


def issue_text(case):
    if case.get("swe"):
        return case["problem_statement"].strip()
    cache = ROOT / "issues" / f"{case['clone']}-{case['issue']}.json"
    if cache.exists():
        data = json.loads(cache.read_text())["issue"]
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(f"https://api.github.com/repos/{case['repo']}/issues/{case['issue']}",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "latch-eval"})
        data = json.load(urllib.request.urlopen(req, timeout=30))
        cache.write_text(json.dumps({"repo": case["repo"], "issue": data}, indent=1))
    return f"{data['title']}\n\n{data.get('body') or ''}".strip()


def links(case):
    r = case["repo"]
    if case.get("swe"):
        return {"swe_bench_instance": f"https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite ({case['instance_id']})",
                "pr": f"https://github.com/{r}/pull/{case['pr']}"}
    out = {"issue": f"https://github.com/{r}/issues/{case['issue']}",
           "fix_commit": f"https://github.com/{r}/commit/{case['fix']}"}
    if case.get("pr"):
        out["pr"] = f"https://github.com/{r}/pull/{case['pr']}"
    return out


def pytest_run(directory, command, args=()):
    """Run pytest in `directory` with the same minimal env the harness uses."""
    d = Path(directory)
    home = d / ".latch-eval-home"
    home.mkdir(exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    env.update(HOME=str(home), PYTHONPATH=os.pathsep.join([str(d), str(d / "src")]), PYTHONDONTWRITEBYTECODE="1")
    t = time.time()
    r = subprocess.run([*shlex.split(command), *args], cwd=d, env=env, capture_output=True, text=True, timeout=600)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return {"returncode": r.returncode, "seconds": round(time.time() - t, 1), "summary": tail[-200:]}


def apply_wrong(case, directory):
    w = case["wrong"]
    path = Path(directory) / w["file"]
    text = path.read_text(encoding="utf-8")
    for old, new in w["edits"]:
        if text.count(old) != 1:
            raise RuntimeError(f"{case['id']}: wrong-patch edit matches {text.count(old)} times in {w['file']}: {old[:60]!r}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def wrong_repo(case):
    """A tiny git repo: commit 1 = base snapshot, commit 2 = base + the constructed wrong patch."""
    repo = ROOT / "wrong" / case["id"]
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    base = base_sha(case)
    archive(clone_dir(case), base, repo)
    for junk in repo.rglob("._*"):
        junk.unlink()
    sh(GIT + ["init", "-q"], cwd=repo)
    sh(GIT + ["add", "-A"], cwd=repo)
    r = sh(GIT + ["commit", "-q", "-m", "base"], cwd=repo)
    if r.returncode:
        raise RuntimeError(f"wrong_repo commit failed: {r.stderr}")
    b = sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    apply_wrong(case, repo)
    sh(GIT + ["add", "-A"], cwd=repo)
    r = sh(GIT + ["commit", "-q", "-m", "wrong patch"], cwd=repo)
    if r.returncode:
        raise RuntimeError(f"wrong_repo commit failed: {r.stderr}")
    return repo, b, sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()


def swe_oracle(case, directory):
    """Copy `directory`, apply the instance's test_patch, run its FAIL_TO_PASS tests (selected with -k)."""
    with tempfile.TemporaryDirectory(prefix="latch-oracle-") as t:
        dst = Path(t) / "code"
        shutil.copytree(directory, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".latch-*", ".pytest_cache"))
        r = subprocess.run(["git", "apply", "-"], cwd=dst, input=case["test_patch"], capture_output=True, text=True)
        if r.returncode:
            return {"oracle_pass": False, "oracle_summary": f"test_patch does not apply: {r.stderr.strip()[:150]}",
                    "oracle_files": case["test_files"]}
        names = " or ".join(n.split("::")[-1] for n in case["f2p"])
        res = pytest_run(dst, test_command(case), ["-k", names])
    return {"oracle_pass": res["returncode"] == 0, "oracle_summary": res["summary"], "oracle_files": case["test_files"],
            "oracle_tests": case["f2p"]}


def oracle_check(case, directory):
    """Copy `directory`, drop the fix commit's test files over it, run only those files."""
    if case.get("swe"):
        return swe_oracle(case, directory)
    files = oracle_files(case)
    with tempfile.TemporaryDirectory(prefix="latch-oracle-") as t:
        dst = Path(t) / "code"
        shutil.copytree(directory, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".latch-*", ".pytest_cache"))
        for f in files:
            data = subprocess.run(["git", "-C", str(clone_dir(case)), "show", f"{case['fix']}:{f}"],
                                  stdout=subprocess.PIPE, check=True).stdout
            (dst / f).parent.mkdir(parents=True, exist_ok=True)
            (dst / f).write_bytes(data)
        r = pytest_run(dst, test_command(case), files)
    return {"oracle_pass": r["returncode"] == 0, "oracle_summary": r["summary"], "oracle_files": files}


def validate_swe(case):
    d = {"id": case["id"]}
    with tempfile.TemporaryDirectory(prefix="latch-val-") as t:
        t = Path(t)
        base, head = t / "base", t / "head"
        for p in (base, head):
            p.mkdir()
        archive(clone_dir(case), case["base"], base)
        archive(clone_dir(case), swe_head(case), head)
        cmd = test_command(case)
        d["suite_base"] = pytest_run(base, cmd)
        d["suite_gold"] = pytest_run(head, cmd)
        d["oracle_base"] = oracle_check(case, base)
        d["oracle_head"] = oracle_check(case, head)
    d["checks"] = {
        "base suite green": d["suite_base"]["returncode"] == 0,
        "gold-patch suite green": d["suite_gold"]["returncode"] == 0,
        "oracle fails on base": not d["oracle_base"]["oracle_pass"],
        "oracle passes on gold patch": d["oracle_head"]["oracle_pass"],
    }
    d["ok"] = all(d["checks"].values())
    return d["ok"], d


def validate_case(case):
    """Ground truth for one case. Returns (ok, details)."""
    if case.get("swe"):
        return validate_swe(case)
    d = {"id": case["id"]}
    with tempfile.TemporaryDirectory(prefix="latch-val-") as t:
        t = Path(t)
        base, head, wrong = t / "base", t / "head", t / "wrong"
        for p in (base, head, wrong):
            p.mkdir()
        archive(clone_dir(case), base_sha(case), base)
        archive(clone_dir(case), case["fix"], head)
        shutil.copytree(base, wrong, dirs_exist_ok=True)
        apply_wrong(case, wrong)
        cmd = test_command(case)
        d["suite_base"] = pytest_run(base, cmd)
        d["suite_wrong"] = pytest_run(wrong, cmd)
        d["oracle_base"] = oracle_check(case, base)
        d["oracle_head"] = oracle_check(case, head)
        d["oracle_wrong"] = oracle_check(case, wrong)
    checks = {
        "base suite green": d["suite_base"]["returncode"] == 0,
        "wrong patch suite green": d["suite_wrong"]["returncode"] == 0,
        "oracle fails on base": not d["oracle_base"]["oracle_pass"],
        "oracle passes on real fix": d["oracle_head"]["oracle_pass"],
        "oracle fails on wrong patch": not d["oracle_wrong"]["oracle_pass"],
    }
    d["checks"] = checks
    d["ok"] = all(checks.values())
    return d["ok"], d


def run_one(case, variant, max_iterations, out_dir):
    cid = f"{case['id']}.{variant}"
    events = []
    started = time.time()
    if variant == "nofix":
        repo, base, head = clone_dir(case), base_sha(case), base_sha(case)
    elif variant == "real":
        repo, base, head = clone_dir(case), base_sha(case), (swe_head(case) if case.get("swe") else case["fix"])
    else:
        repo, base, head = wrong_repo(case)
    labels = {"real": "real (upstream fix)", "wrong": "constructed wrong patch", "nofix": "no fix: Nemotron writes the patch"}
    row = {"case": case["id"], "variant": variant, "label": labels[variant],
           "expected_gate": "open" if variant == "real" else ("shut" if variant == "wrong" else "open only if the fix is right")}
    ref = case["fix"][:10] if case.get("fix") else case["instance_id"]
    receipt_path = Path(out_dir) / f"{cid}.json"
    try:
        receipt = run_loop(
            repo, base, head, issue_text(case), test_command=test_command(case),
            max_iterations=max_iterations, receipt_path=receipt_path, on_event=events.append,
            source_label=f"{case['repo']}@{ref}{'' if variant == 'real' else (' + constructed wrong patch' if variant == 'wrong' else ' (no fix)')}",
            inspect_final=lambda directory: oracle_check(case, directory), run_id=cid.replace("-", "")[:40])
    except LoopError as error:
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        row.update(outcome="error", reason=str(error), verdict="error")
    except Exception as error:  # an eval harness bug must show up as an error row, not vanish
        receipt = {}
        row.update(outcome="error", reason=f"{type(error).__name__}: {error}", verdict="error")
    else:
        row["verdict"] = receipt["verdict"]
        row["reason"] = receipt["reason"]
    row["wall_seconds"] = round(time.time() - started, 1)
    initial = receipt.get("initial") or {}
    its = receipt.get("iterations") or []
    row.update(
        base_red=initial.get("base_red"),
        head_suite_green=initial.get("head_suite_green"),
        gate_open_at_iteration_0=initial.get("gate_open"),
        iterations_used=len(its),
        inspection=receipt.get("inspection"),
        completion_ids={
            "proof_test": (receipt.get("proof_test") or {}).get("completion_id"),
            "triage": (receipt.get("triage") or {}).get("completion_id"),
            "fix": [i.get("completion_id") for i in its],
        },
        triage_verdict=(receipt.get("triage") or {}).get("verdict"),
        proof_test_name=(receipt.get("proof_test") or {}).get("name"),
        receipt=str(receipt_path),
    )
    if "outcome" not in row:
        opened = receipt["verdict"] == "gate_open"
        oracle_ok = (receipt.get("inspection") or {}).get("oracle_pass")
        if variant == "real":
            row["outcome"] = "proven" if opened else ("gave_up" if True else "")
        elif variant == "nofix":
            row["outcome"] = ("nemotron_fix_correct" if oracle_ok else "green_but_wrong") if opened else "gave_up"
        else:
            if opened and not its:
                row["outcome"] = "false_accept"
            elif opened:
                row["outcome"] = "repaired" if oracle_ok else "repaired_but_oracle_fails"
            else:
                row["outcome"] = "shut_gave_up"
    return row


def summarize(rows, dropped):
    real = [r for r in rows if r["variant"] == "real"]
    wrong = [r for r in rows if r["variant"] == "wrong"]
    nofix = [r for r in rows if r["variant"] == "nofix"]
    n = len({r["case"] for r in rows})
    count = lambda rs, o: sum(1 for r in rs if r["outcome"] == o)
    return {
        "cases_run": n,
        "dropped_cases": dropped,
        "real_proven": count(real, "proven"),
        "real_total": len(real),
        "real_gave_up": count(real, "gave_up"),
        "real_error": count(real, "error"),
        "wrong_total": len(wrong),
        "wrong_false_accept": count(wrong, "false_accept"),
        "wrong_shut_gave_up": count(wrong, "shut_gave_up"),
        "wrong_repaired_oracle_pass": count(wrong, "repaired"),
        "wrong_repaired_but_oracle_fails": count(wrong, "repaired_but_oracle_fails"),
        "wrong_error": count(wrong, "error"),
        "nofix_total": len(nofix),
        "nofix_fix_correct": count(nofix, "nemotron_fix_correct"),
        "nofix_green_but_wrong": count(nofix, "green_but_wrong"),
        "nofix_gave_up": count(nofix, "gave_up"),
        "nofix_error": count(nofix, "error"),
        "total_wall_seconds_sum": round(sum(r["wall_seconds"] for r in rows), 1),
        "gave_up_reasons": {f"{r['case']}.{r['variant']}": r["reason"] for r in rows if r["outcome"] in ("gave_up", "shut_gave_up")},
        "error_reasons": {f"{r['case']}.{r['variant']}": r["reason"] for r in rows if r["outcome"] == "error"},
    }


def selected(only):
    cases = [c for c in CASES if not only or c["id"] in only]
    if only and len(cases) != len(set(only)):
        raise SystemExit(f"unknown case id in {only}")
    return cases


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m latch.loop.eval.run_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--only", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*")
    r.add_argument("--jobs", type=int, default=3)
    r.add_argument("--max-iterations", type=int, default=3)
    r.add_argument("--out", default=None)
    r.add_argument("--skip-validate", action="store_true")
    args = ap.parse_args(argv)
    cases = selected(args.only)

    valid, dropped, vdetails = [], [], {}
    for case in cases:
        if args.cmd == "run" and args.skip_validate:
            valid.append(case)
            continue
        ok, d = validate_case(case)
        vdetails[case["id"]] = d
        print(f"[validate] {case['id']}: {'OK' if ok else 'DROP'} {json.dumps(d['checks'])}", file=sys.stderr, flush=True)
        (valid if ok else dropped).append(case if ok else {"id": case["id"], "reason": [k for k, x in d["checks"].items() if not x]})
    if args.cmd == "validate":
        print(json.dumps(vdetails, indent=2))
        return 0 if not dropped else 1

    date = datetime.date.today().isoformat()
    out = Path(args.out or REPO_ROOT / "latch" / "runs" / f"eval-{date}.json")
    rec_dir = ROOT / "receipts" / date
    rec_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(c, v) for c in valid for v in (("real", "nofix") if c.get("swe") else ("real", "wrong"))]
    rows, t0 = [], time.time()
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(run_one, c, v, args.max_iterations, rec_dir): (c, v) for c, v in jobs}
        for f in cf.as_completed(futs):
            row = f.result()
            rows.append(row)
            print(f"[run] {row['case']}.{row['variant']}: {row['outcome']} ({row['wall_seconds']}s) {str(row.get('reason'))[:100]}",
                  file=sys.stderr, flush=True)
    order = {c["id"]: i for i, c in enumerate(CASES)}
    rows.sort(key=lambda r: (order[r["case"]], r["variant"] != "real"))
    case_meta = [{
        "id": c["id"], "repo": c["repo"], "title": c["title"], "base": base_sha(c),
        "fix": swe_head(c) if c.get("swe") else c["fix"],
        "source": "SWE-bench Lite instance " + c["instance_id"] if c.get("swe") else "upstream commit",
        "links": links(c), "real_fix_label": "real (SWE-bench gold patch)" if c.get("swe") else "real (upstream commit)",
        **({"oracle_tests": c["f2p"], "oracle_files": c["test_files"]} if c.get("swe") else {
            "wrong_patch_label": "constructed", "wrong_patch_summary": c["wrong"]["summary"],
            "wrong_patch_file": c["wrong"]["file"], "wrong_patch_edits": c["wrong"]["edits"],
            "oracle_files": oracle_files(c)}),
        "test_command": test_command(c).replace(str(VENV), "$VENV"),
        "validation": vdetails.get(c["id"]),
    } for c in valid]
    doc = {
        "date": date, "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "max_iterations": args.max_iterations, "jobs": args.jobs,
        "models": {"proof_test": "nvidia/Nemotron-3-Ultra-550b-a55b", "fix": "nvidia/Nemotron-3-Ultra-550b-a55b",
                   "triage": "nvidia/Nemotron-3_5-Lightning"},
        "elapsed_seconds": round(time.time() - t0, 1),
        "summary": summarize(rows, dropped + [dict(d, source="dropped before the run (record only)") for d in DROPPED]), "cases": case_meta, "runs": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc["summary"], indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
