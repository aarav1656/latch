import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__:
    from .prove import prove
else:
    from prove import prove


GITHUB_API = "https://api.github.com"
GITHUB_HOST = "github.com"
_PR_PATH = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9]\d*)/?$")
_CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+"
    r"(?:(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+))?#(?P<number>\d+)\b",
    re.IGNORECASE,
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def parse_pull_request_url(value):
    parsed = urllib.parse.urlsplit(value.strip())
    match = _PR_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != GITHUB_HOST
        or parsed.query
        or parsed.fragment
        or not match
    ):
        raise ValueError("Enter a public GitHub pull request URL")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def linked_issue(body, base_repo):
    references = _CLOSING.findall(body or "")
    if not references:
        raise ValueError("This pull request does not close an issue in its repository")
    issues = set()
    for owner, repo, number in references:
        linked_repo = f"{owner}/{repo}" if owner else base_repo
        if linked_repo.casefold() != base_repo.casefold():
            raise ValueError("The pull request closes an issue in another repository")
        issues.add(int(number))
    if len(issues) != 1:
        raise ValueError("The pull request closes more than one issue; Latch needs one issue as its oracle")
    return issues.pop()


def github_get(path):
    request = urllib.request.Request(
        GITHUB_API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Latch-issue-proof",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ValueError("GitHub returned an oversized response")
            return json.loads(payload)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError("The GitHub pull request or linked issue was not found") from error
        if error.code == 403:
            raise RuntimeError("GitHub rate limit or access policy blocked this request") from error
        raise RuntimeError(f"GitHub API returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach the GitHub API: {error.reason}") from error


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GIT_TERMINAL_PROMPT": "0"},
    )


def run_pull_request(url, receipt, test_command, on_step=None):
    owner, name, number = parse_pull_request_url(url)
    if on_step:
        on_step("fetching")
    pull = github_get(f"/repos/{owner}/{name}/pulls/{number}")
    base_repo = pull["base"]["repo"]["full_name"]
    head_repo = pull["head"]["repo"]
    if not head_repo or not _REPO.fullmatch(head_repo["full_name"]):
        raise ValueError("The pull request head repository is unavailable")
    issue_number = linked_issue(pull.get("body"), base_repo)
    base_sha = pull["base"]["sha"]
    head_sha = pull["head"]["sha"]
    if not _SHA.fullmatch(base_sha) or not _SHA.fullmatch(head_sha):
        raise ValueError("GitHub returned an invalid commit hash")
    base_owner, base_name = base_repo.split("/", 1)
    issue = github_get(f"/repos/{base_owner}/{base_name}/issues/{issue_number}")
    issue_report = f"{issue['title']}\n\n{issue.get('body') or ''}".strip()
    if len(issue_report) > 20_000:
        raise ValueError("The linked issue is too long for one proof run")

    if on_step:
        on_step("fetching-commits")
    with tempfile.TemporaryDirectory(prefix="latch-pr-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=15)
        base_remote = f"https://{GITHUB_HOST}/{base_repo}.git"
        head_remote = f"https://{GITHUB_HOST}/{head_repo['full_name']}.git"
        git(repo, "remote", "add", "origin", base_remote)
        git(repo, "fetch", "--depth=1", "--no-tags", "origin", base_sha)
        git(repo, "fetch", "--depth=1", "--no-tags", head_remote, head_sha)
        for sha in (base_sha, head_sha):
            git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        if on_step:
            on_step("generating-test")

        def proof_step(step):
            if on_step:
                on_step(step)

        result = prove(
            repo,
            base_sha,
            head_sha,
            issue_report,
            test_command,
            receipt,
            on_step=proof_step,
            isolate_tests=True,
        )

    result.update(
        {
            "pull_request_url": url,
            "pull_request_title": pull["title"],
            "issue_url": issue["html_url"],
            "issue_title": issue["title"],
            "base_branch": pull["base"]["ref"],
            "head_branch": pull["head"]["ref"],
        }
    )
    Path(receipt).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
