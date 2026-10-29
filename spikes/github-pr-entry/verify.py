import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


API = "https://api.github.com"
OWNER, REPO, PR = "pallets", "click", 3299
BASE = "04ef3a6f473deb2499721a8d11f92a7d2c0912f2"
HEAD = "d340b0c1202284a1b9d0ca892549208527d586ce"


def get(path):
    request = urllib.request.Request(
        API + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Latch-issue-proof-spike"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


status, pull = get(f"/repos/{OWNER}/{REPO}/pulls/{PR}")
assert status == 200
assert pull["base"]["sha"] == BASE and pull["head"]["sha"] == HEAD
closing = re.search(r"(?i)(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", pull.get("body") or "")
assert closing and closing.group(1) == "3298"
issue_status, issue = get(f"/repos/{OWNER}/{REPO}/issues/{closing.group(1)}")
assert issue_status == 200 and issue["title"] == "semver.Version as default causing an error"
bad_pr, _ = get(f"/repos/{OWNER}/{REPO}/pulls/0")
assert bad_pr == 404

with tempfile.TemporaryDirectory(prefix="latch-pr-fetch-") as temp:
    repo = Path(temp)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", f"https://github.com/{OWNER}/{REPO}.git"],
        check=True,
    )
    for sha in (BASE, HEAD):
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--depth=1", "origin", sha],
            check=True,
            capture_output=True,
            timeout=60,
        )
        subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"], check=True)
    bad_sha = "0" * 40
    rejected = subprocess.run(
        ["git", "-C", str(repo), "fetch", "--depth=1", "origin", bad_sha],
        capture_output=True,
        timeout=60,
    )
    assert rejected.returncode != 0

print("PASS: PR 200, issue 200, exact base/head fetched, unknown PR 404, unknown commit rejected")
