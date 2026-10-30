"""Eval manifest: everything a reader needs to re-run the benchmark and know it is the same one.

`latch/loop/eval/manifest.json` pins the model ids, each prompt template (path, constant, sha256), the dataset (SWE-bench Lite instance
ids and the Hugging Face dataset revision), the repo SHAs of every case and the Latch git SHA it was written at.

    python3 -m latch.loop.eval.manifest --write    regenerate latch/loop/eval/manifest.json (needs the clones for repo SHAs)
    python3 -m latch.loop.eval.manifest --check    exit 1 if the prompts, models or case list no longer match the file
"""
import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = Path(__file__).with_name("manifest.json")
SWE_DATASET = "princeton-nlp/SWE-bench_Lite"
SCHEMA_VERSION = 1

# (role, module, constant, path relative to the repo root)
PROMPTS = [
    ("proof_test_writer", "latch.loop.core", "TEST_SYSTEM", "latch/loop/core.py"),
    ("fixer", "latch.loop.core", "FIX_SYSTEM", "latch/loop/core.py"),
    ("triage", "latch.prove", "TRIAGE_SYSTEM", "latch/prove.py"),
    ("repo_map", "latch.repomap", "REPO_MAP_SYSTEM", "latch/repomap.py"),
    ("lightning_system", "latch.run", "LIGHTNING_SYSTEM", "latch/run.py"),
]


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_pins():
    import importlib

    out = []
    for role, module, const, path in PROMPTS:
        text = getattr(importlib.import_module(module), const)
        out.append({"role": role, "constant": const, "path": path, "sha256": sha256(text), "chars": len(text)})
    return out


def model_pins():
    from ...run import LIGHTNING, MODEL

    return {"proof_test_and_fix": MODEL, "triage_and_repo_map": LIGHTNING, "endpoint": "Nebius Token Factory (OpenAI-compatible)"}


def case_pins(cases, resolve=None):
    """Per-case repo SHAs. `resolve(case) -> (base, head)` is injectable; the default needs the eval clones and returns None if absent."""
    if resolve is None:
        def resolve(case):
            try:
                from . import run_eval
                return run_eval.base_sha(case), (case["fix"] if not case.get("swe") else None)
            except Exception:
                return None, None
    out = []
    for c in cases:
        base, head = resolve(c)
        pin = {"id": c["id"], "repo": c["repo"], "suite": "swebench_lite" if c.get("swe") else "upstream",
               "base_sha": c.get("base") if c.get("swe") else base, "fix_sha": head if not c.get("swe") else None}
        if c.get("swe"):
            pin.update(instance_id=c["instance_id"], gold_patch_sha256=sha256(c["patch"]), test_patch_sha256=sha256(c["test_patch"]))
        else:
            pin["fix_sha"] = c["fix"]
        out.append(pin)
    return out


def dataset_pin(cases, fetch=True):
    ids = sorted(c["instance_id"] for c in cases if c.get("swe"))
    revision, note = None, None
    if fetch:
        try:
            req = urllib.request.Request(f"https://huggingface.co/api/datasets/{SWE_DATASET}", headers={"User-Agent": "latch-eval"})
            revision = json.load(urllib.request.urlopen(req, timeout=20)).get("sha")
        except Exception as error:
            note = f"dataset revision not fetched: {type(error).__name__}"
    return {"name": SWE_DATASET, "url": f"https://huggingface.co/datasets/{SWE_DATASET}", "revision": revision, "revision_note": note,
            "instance_ids": ids, "n_instances": len(ids)}


def latch_git(root=REPO_ROOT):
    def git(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "latch", ":!latch/loop/eval/manifest.json"))}


def build(cases, dropped=(), fetch=True, resolve=None):
    return {"schema_version": SCHEMA_VERSION, "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latch": latch_git(), "models": model_pins(), "prompts": prompt_pins(), "dataset": dataset_pin(cases, fetch),
            "cases": case_pins(cases, resolve), "dropped": [d["id"] for d in dropped]}


def check(manifest, cases, dropped=()):
    """-> list of mismatches between the file and the code (empty when they agree). Ignores the git SHA and the dataset revision."""
    problems = []
    if manifest.get("models") != model_pins():
        problems.append("model ids differ from latch.run")
    have = {p["role"]: p for p in manifest.get("prompts", [])}
    for p in prompt_pins():
        if have.get(p["role"], {}).get("sha256") != p["sha256"]:
            problems.append(f"prompt {p['role']} ({p['constant']} in {p['path']}) changed since the manifest was written")
    if [c["id"] for c in manifest.get("cases", [])] != [c["id"] for c in cases]:
        problems.append("case list differs from latch/loop/eval/cases.py")
    if sorted(manifest.get("dataset", {}).get("instance_ids", [])) != sorted(c["instance_id"] for c in cases if c.get("swe")):
        problems.append("SWE-bench Lite instance ids differ")
    if manifest.get("dropped") != [d["id"] for d in dropped]:
        problems.append("dropped-case list differs")
    return problems


def load(path=MANIFEST_PATH):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def main(argv=None):
    from .cases import CASES, DROPPED

    ap = argparse.ArgumentParser(prog="latch eval manifest")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate manifest.json (fetches the dataset revision; reads the eval clones)")
    mode.add_argument("--check", action="store_true", help="exit 1 if the prompts, models or cases no longer match manifest.json")
    ap.add_argument("--path", default=str(MANIFEST_PATH))
    args = ap.parse_args(argv)
    if args.write:
        m = build(CASES, DROPPED)
        Path(args.path).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.path}", file=sys.stderr)
        return 0
    m = load(args.path)
    if m is None:
        print(f"no manifest at {args.path}; run with --write", file=sys.stderr)
        return 1
    if args.check:
        problems = check(m, CASES, DROPPED)
        for p in problems:
            print("MISMATCH:", p, file=sys.stderr)
        print("manifest ok" if not problems else f"{len(problems)} mismatch(es)", file=sys.stderr)
        return 1 if problems else 0
    print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
