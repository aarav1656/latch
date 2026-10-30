"""On-disk receipt cache for the hosted app (stdlib only).

Receipts are stored as envelopes: {"receipt": <prove.py receipt>, "meta": {...}}.
They are keyed by repo + base SHA + head SHA, with a per-PR pointer to the
newest run for permalinks. Built-in seeds (the recorded Click run) are served
when nothing newer is on disk.
"""

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

CLICK_PR_URL = "https://github.com/pallets/click/pull/3299"
CLICK_ENRICHMENT = {
    "pull_request_url": CLICK_PR_URL,
    "pull_request_title": "Fix speculative empty string check",
    "issue_url": "https://github.com/pallets/click/issues/3298",
    "issue_title": "semver.Version as default causing an error",
    "base_branch": "stable",
    "head_branch": "fix-default-eq-check",
}


def utc_iso(timestamp=None):
    moment = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(value):
    return hashlib.sha256(value.lower().encode()).hexdigest()[:40]


def receipt_key(repo_full_name, base, head):
    return _digest(f"{repo_full_name}@{base}@{head}")


def pr_key(repo_full_name, number):
    return _digest(f"{repo_full_name}#{int(number)}")


def _sentence(text):
    text = " ".join(str(text).split())
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def explain(receipt):
    """Human reason a receipt is not proven (None when it is).

    A reason recorded by the pipeline itself (receipt["why_not_proven"], used when it fails closed) wins over
    the reasons derived from the two test runs. A receipt may have no runs at all (base_result None): then
    nothing is claimed about the base commit.
    """
    if receipt.get("proven") is True:
        return None
    recorded = receipt.get("why_not_proven")
    if isinstance(recorded, str) and recorded.strip():
        return _sentence(recorded)
    base, head = receipt.get("base_result"), receipt.get("head_result")
    if base is None:
        return "The generated test was never run on the base commit, so nothing was proven."
    if head is None:
        return "The generated test was never run on the pull request head, so nothing was proven."
    if base.get("returncode") == 0:
        return "The generated test passed on the buggy base commit, so it does not reproduce the reported issue."
    if isinstance(base.get("returncode"), int) and base["returncode"] < 0:
        return "The test process was killed by the sandbox on the base commit (resource or time limit)."
    if not receipt.get("base_failure_is_expected"):
        return (
            "The generated test failed on the base commit, but not with an assertion or the issue's "
            "unexpected-operation failure (for example an import error or crash), so it is not evidence of the reported bug."
        )
    if head.get("returncode") != 0:
        return "The generated test still fails on the pull request head, so the patch does not satisfy the issue's expected behavior."
    return "The generated test did not show the issue failing on base and passing on head."


def _short_rejection(reason):
    text = str(reason or "").strip().lower()
    for needle, label in (
        ("body is empty", "empty body"),
        ("only `...` or `pass`", "placeholder body (`...` or `pass`)"),
        ("no real check", "no real assertion"),
        ("not valid python", "not valid Python"),
        ("no top-level test_", "no test function"),
        ("no test_ function", "no test function"),
    ):
        if needle in text:
            return label
    text = text[4:] if text.startswith("the ") else text
    return (text[:70] + "...") if len(text) > 70 else (text or "rejected")


def attempts_note(receipt):
    """One quiet line about rejected proof-test generations (None when the first test was fine)."""
    attempts = receipt.get("test_attempts") or receipt.get("proof_test_attempts")
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[0], dict):
        return None
    first = attempts[0]
    if first.get("valid", True):
        return None
    why = _short_rejection(first.get("rejection"))
    if len(attempts) == 1:
        return f"The generated test was rejected: {why}."
    second = attempts[1] if isinstance(attempts[1], dict) else {}
    if second.get("valid"):
        return f"First test rejected: {why}, retried."
    return f"First test rejected: {why}; the retry was rejected too ({_short_rejection(second.get('rejection'))}), so no test was run."


def retries_note(receipt):
    """One quiet line about transient model errors that were retried (None when there were none)."""
    retries = [r for r in (receipt.get("model_retries") or []) if isinstance(r, dict) and r.get("will_retry")]
    if not retries:
        return None
    reasons = []
    for item in retries:
        status = item.get("status")
        reason = f"HTTP {status}" if status else str(item.get("error") or "network error").split(":")[0][:40]
        if reason not in reasons:
            reasons.append(reason)
    times = "once" if len(retries) == 1 else f"{len(retries)} times"
    return f"The model request was retried {times} ({', '.join(reasons)})."


def make_envelope(receipt, source, started=None, finished=None, extra=None):
    meta = {
        "source": source,
        "verdict": "proven" if receipt.get("proven") is True else "not_proven",
        "why_not_proven": explain(receipt),
        "test_attempts_note": attempts_note(receipt),
        "model_retries_note": retries_note(receipt),
        "created_at": utc_iso(started),
        "finished_at": utc_iso(finished) if finished is not None else None,
        "duration_s": round(finished - started, 1) if started is not None and finished is not None else None,
    }
    if extra:
        meta.update(extra)
    return {"receipt": receipt, "meta": meta}


class Store:
    def __init__(self, root, seed_receipt_path=None):
        self.root = Path(root)
        (self.root / "receipts").mkdir(parents=True, exist_ok=True)
        (self.root / "pr").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.seeds = {}
        self.seed_prs = {}
        if seed_receipt_path:
            self._load_click_seed(Path(seed_receipt_path))

    # -- seeds ---------------------------------------------------------
    def _load_click_seed(self, path):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            return
        receipt.update({k: v for k, v in CLICK_ENRICHMENT.items() if k not in receipt})
        envelope = make_envelope(
            receipt,
            "recorded",
            extra={
                "created_at": utc_iso(mtime),
                "recorded_run": "latch/runs/click-3298.json",
                "note": "Recorded run of the same pipeline. Press Run live to reproduce it.",
                "enriched_fields": sorted(CLICK_ENRICHMENT),
                "repo": "pallets/click",
                "number": 3299,
            },
        )
        self.seeds[receipt_key("pallets/click", receipt["base"], receipt["head"])] = envelope
        self.seed_prs[pr_key("pallets/click", 3299)] = envelope

    @property
    def example(self):
        return next(iter(self.seed_prs.values()), None)

    # -- disk ------------------------------------------------------------
    def _read(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, path, payload):
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, repo_full_name, base, head):
        key = receipt_key(repo_full_name, base, head)
        found = self._read(self.root / "receipts" / f"{key}.json")
        return found or self.seeds.get(key)

    def get_pr(self, repo_full_name, number):
        key = pr_key(repo_full_name, number)
        pointer = self._read(self.root / "pr" / f"{key}.json")
        if pointer:
            found = self._read(self.root / "receipts" / f"{pointer['key']}.json")
            if found:
                return found
        return self.seed_prs.get(key)

    def pr_for_issue(self, repo_full_name, number):
        """PR number whose cached receipt closes this issue number (None when unknown).

        Lets /r/<owner>/<repo>/<issue> send people to the receipt of the pull request that fixes it, so a page
        never says "no receipt" above a receipt.
        """
        suffix = f"/{repo_full_name}/issues/{int(number)}".lower()
        candidates = list(self.seed_prs.values())
        try:
            candidates += [e for e in (self._read(f) for f in sorted((self.root / "receipts").glob("*.json"))) if e]
        except OSError:
            pass
        for envelope in candidates:
            issue_url = str((envelope.get("receipt") or {}).get("issue_url") or "").lower().rstrip("/")
            meta = envelope.get("meta") or {}
            if issue_url.endswith(suffix) and str(meta.get("repo", "")).lower() == repo_full_name.lower() and meta.get("number"):
                return int(meta["number"])
        return None

    def list_recent(self, limit=12):
        """Newest cached receipts, one per pull request. Real envelopes only: nothing is invented.

        Envelopes on disk and the built-in recorded seed qualify; any without meta.repo and meta.number are skipped.
        """
        newest = {}
        candidates = list(self.seed_prs.values())
        try:
            candidates += [e for e in (self._read(f) for f in (self.root / "receipts").glob("*.json")) if e]
        except OSError:
            pass
        for envelope in candidates:
            meta = envelope.get("meta") if isinstance(envelope, dict) else None
            receipt = envelope.get("receipt") if isinstance(envelope, dict) else None
            if not isinstance(meta, dict) or not isinstance(receipt, dict):
                continue
            repo, number = meta.get("repo"), meta.get("number")
            if not repo or not isinstance(number, int):
                continue
            key = (str(repo).lower(), number)
            if key not in newest or str(meta.get("created_at") or "") > str(newest[key][0].get("created_at") or ""):
                newest[key] = (meta, receipt)
        items = []
        for (_, number), (meta, receipt) in newest.items():
            repo = meta["repo"]
            items.append({
                "repo": repo,
                "number": number,
                "verdict": meta.get("verdict") or ("proven" if receipt.get("proven") is True else "not_proven"),
                "title": receipt.get("pull_request_title") or f"Pull request #{number}",
                "created_at": meta.get("created_at"),
                "permalink": f"/r/{repo}/{number}",
                "source": meta.get("source"),
            })
        items.sort(key=lambda item: (str(item["created_at"] or ""), item["repo"], item["number"]), reverse=True)
        return items[: max(int(limit), 0)]

    def put(self, repo_full_name, number, envelope):
        receipt = envelope["receipt"]
        key = receipt_key(repo_full_name, receipt["base"], receipt["head"])
        envelope["meta"].update({"repo": repo_full_name, "number": int(number)})
        with self.lock:
            self._write(self.root / "receipts" / f"{key}.json", envelope)
            self._write(self.root / "pr" / f"{pr_key(repo_full_name, number)}.json", {"key": key, "updated": utc_iso()})
        return key
