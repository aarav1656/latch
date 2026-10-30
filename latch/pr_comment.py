"""Render a Latch receipt (prove or loop) as one concise Markdown PR comment, and post or update it.

The comment carries a hidden marker, so a re-run edits the same comment instead of adding a new one.
Posting uses the GitHub REST API with a GITHUB_TOKEN; `dry_run=True` only returns what it would send.
"""

import json
import os
import urllib.error
import urllib.request

MARKER = "<!-- latch-receipt -->"
API = "https://api.github.com"
LIMIT = 60000  # GitHub caps a comment at 65,536 characters


def _short(sha):
    return str(sha or "")[:10]


def _cell(text):
    """One-line, table-safe text; @ is defused so model-written reasons cannot ping people."""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")


def _fence(text, lang=""):
    text = str(text or "").rstrip("\n")
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text}\n{fence}"


def _run_cell(result, kind=None):
    if not result:
        return "not run"
    if result.get("returncode") == 0:
        return "passes"
    kind = kind or result.get("failure_type")
    return f"FAILS ({kind})" if kind else "FAILS"


def _is_loop(receipt):
    return ("gate" in receipt or "verdict" in receipt) and "initial" in receipt


def _gate(receipt):
    """The loop outcome. Receipts written before named verdicts kept it in `verdict`."""
    return receipt.get("gate") or receipt.get("verdict")


def _headline(receipt):
    if _is_loop(receipt):
        verdict, iterations = _gate(receipt), receipt.get("iterations") or []
        if verdict == "gate_open" and not iterations:
            return "✅ Gate open: the submitted change is proven by a model-written test"
        if verdict == "gate_open":
            return f"✅ Gate open after {len(iterations)} repair iteration(s): the submitted change was NOT enough on its own"
        if verdict == "gave_up":
            return "❌ Gate shut: not proven"
        return "⚠️ Error: nothing proven (fails closed)"
    if receipt.get("proven"):
        return "✅ PROVEN"
    return f"❌ NOT PROVEN ({receipt['verdict']})" if receipt.get("verdict") else "❌ NOT PROVEN"


def _reason(receipt):
    if _is_loop(receipt):
        return receipt.get("reason") or ""
    if receipt.get("verdict_reason"):
        return receipt["verdict_reason"]
    if receipt.get("proven"):
        return "The generated test failed on base and passes on head, and failed again with the fix reverted."
    return receipt.get("why_not_proven") or (
        "The test did not both fail on base with an assertion and pass on head.")


def _revert_cell(check):
    if not check:
        return "not run"
    if check.get("skipped"):
        return f"not run ({check['skipped']})"
    if not check.get("ran"):
        return "could not run: gate stays shut"
    names = ", ".join(m["name"] for m in check.get("mutants", []))
    if check.get("ok"):
        return f"✅ proof test failed again on every mutant ({names})"
    return f"❌ proof test did NOT fail on a mutant ({names}); gate shut"


def _flake_cell(flaky):
    if not flaky or not flaky.get("ran"):
        return None
    if flaky.get("flaky"):
        return (f"❌ inconsistent over {flaky['runs']} runs on each side "
                f"(flake rate {flaky['flake_rate']:.0%}; base failed {flaky['base_fail_rate']:.0%}, head passed {flaky['head_pass_rate']:.0%})")
    return f"✅ stable over {flaky['runs']} runs on base and head"


def _mutation_cell(mutation):
    if not mutation:
        return None
    if mutation.get("incomplete"):
        return f"⚠️ {mutation.get('note')}"
    if not mutation.get("total") and mutation.get("ok") is False:
        return f"❌ the mutation check could not complete ({mutation.get('note')}); the gate stays shut"
    if not mutation.get("total"):
        return "no mutable lines in the change, nothing to mutate (does not block)"
    mark = "✅" if mutation.get("ok") else "❌"
    return (f"{mark} killed {mutation['killed']}/{mutation['total']} mutants of the changed lines "
            f"(kill rate {mutation['kill_rate']:.0%}, needs {mutation['threshold']:.0%})"
            + (f"; {mutation['not_run']} not run: budget" if mutation.get("not_run") else ""))


def _models_table(receipt):
    calls = receipt.get("model_calls") or []
    if not calls:
        return ""
    rows = ["| role | model | completion id | tokens in/out | ms | est. USD |", "|---|---|---|---|---|---|"]
    for c in calls:
        tokens = ("-" if c.get("prompt_tokens") is None else f"{c['prompt_tokens']}/{c['completion_tokens']}")
        cost = "-" if c.get("cost_usd") is None else f"{c['cost_usd']:.5f}"
        rows.append(f"| {c['role']} | `{_cell(c['model']).split('/')[-1]}` | `{c.get('completion_id') or '-'}` | "
                    f"{tokens} | {c.get('latency_ms', '-')} | {cost} |")
    total = receipt.get("model_cost_usd")
    foot = (f"\nEstimated model cost: ${total:.4f} at Token Factory list prices "
            f"({receipt.get('model_prices_source', '')}); cached-input discounts not applied."
            if total is not None else "\nCost unknown: the API reported no token usage.")
    return "\n".join(rows) + foot


def render_comment(receipt, run_url=None):
    """Markdown for one receipt. Pure function: no network, no files."""
    loop = _is_loop(receipt)
    if loop:
        initial = receipt.get("initial") or {}
        base_cell = _run_cell(initial.get("base_proof"))
        head_cell = _run_cell(initial.get("head_proof"))
        name = (receipt.get("proof_test") or {}).get("name")
        source = (receipt.get("proof_test") or {}).get("source")
        test_id = (receipt.get("proof_test") or {}).get("completion_id")
        base, head = receipt.get("base"), receipt.get("head")
        suite = initial.get("head_suite")
    else:
        base_cell = _run_cell(receipt.get("base_result"), receipt.get("base_failure_type"))
        head_cell = _run_cell(receipt.get("head_result"))
        name, source, test_id = receipt.get("test_name"), receipt.get("test"), receipt.get("completion_id")
        base, head = receipt.get("base"), receipt.get("head")
        suite = None
    lines = [MARKER, f"### Latch: {_headline(receipt)}", ""]
    reason = _reason(receipt)
    if reason:
        lines += [f"> {_cell(reason)[:400]}", ""]
    if receipt.get("case_note"):
        lines += [f"*{_cell(receipt['case_note'])}*", ""]
    lines += ["| | |", "|---|---|",
              f"| Proof test | {'`' + name + '`' if name else 'none produced'} |",
              f"| Base `{_short(base)}` | {base_cell} |",
              f"| Head `{_short(head)}` | {head_cell}{'; repo suite ' + _run_cell(suite) if suite else ''} |"]
    if loop and receipt.get("iterations"):
        last = receipt["iterations"][-1]
        lines.append(f"| Repair | {len(receipt['iterations'])} iteration(s), last: {last.get('verdict')} |")
    if receipt.get("verdict"):
        lines.append(f"| Verdict | `{receipt['verdict']}` |")
    lines += [f"| Revert check | {_revert_cell(receipt.get('revert_check'))} |"]
    for label, cell in (("Mutation check", _mutation_cell(receipt.get("mutation"))), ("Flake check", _flake_cell(receipt.get("flaky")))):
        if cell:
            lines.append(f"| {label} | {cell} |")
    triage = receipt.get("triage")
    if isinstance(triage, dict) and triage.get("verdict"):
        lines.append(f"| Triage (Lightning) | {triage['verdict']}{' (advisory)' if triage.get('advisory') else ''} |")
    lines.append(f"| Proof test written by | `{(receipt.get('test_model') or receipt.get('model') or '').split('/')[-1]}`"
                 f"{', completion `' + test_id + '`' if test_id else ''} |")
    lines.append("")
    table = _models_table(receipt)
    if table:
        lines += ["<details><summary>Model calls</summary>", "", table, "", "</details>", ""]
    if source:
        lines += ["<details><summary>Proof test</summary>", "", _fence(source, "python"), "", "</details>", ""]
    if loop:
        for it in receipt.get("iterations") or []:
            if it.get("verdict") == "gate_open" and it.get("diff"):
                lines += [f"<details><summary>Patch that opened the gate (iteration {it['iteration']}, "
                          f"`{it.get('completion_id')}`)</summary>", "", _fence(it["diff"], "diff"), "", "</details>", ""]
    footer = ("Verdict set by the harness (the proof test must fail on base, pass on head, be stable on reruns, fail with the fix "
              "reverted and kill most mutants of the changed lines), not by the model.")
    if run_url:
        footer += f" [Run]({run_url})."
    lines.append(f"<sub>{footer}</sub>")
    body = "\n".join(lines) + "\n"
    if len(body) > LIMIT:
        body = body[:LIMIT - 200].rstrip() + "\n\n*(comment truncated)*\n"
    return body


def _http(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "latch-pr-comment",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        return error.code, None


def post_or_update_comment(repo, pr_number, body, token=None, dry_run=False, http=None, api=API):
    """Create the Latch comment on a PR, or edit the one carrying MARKER. Returns {action, url, ...}.

    dry_run: no request is made; returns {"action": "dry-run", "would": [...]} describing the calls.
    http(method, url, token, payload) -> (status, json) is injectable for tests.
    """
    if MARKER not in body:
        raise ValueError("comment body lacks the Latch marker")
    base = f"{api}/repos/{repo}/issues"
    if dry_run:
        return {"action": "dry-run", "would": [
            f"GET {base}/{pr_number}/comments (find the comment containing {MARKER})",
            f"POST {base}/{pr_number}/comments  or  PATCH {base}/comments/<id> if one exists"]}
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    http = http or _http
    existing, page = None, 1
    while existing is None:
        status, comments = http("GET", f"{base}/{pr_number}/comments?per_page=100&page={page}", token, None)
        if status != 200 or not isinstance(comments, list):
            raise RuntimeError(f"could not list PR comments: HTTP {status}")
        for comment in comments:
            if MARKER in (comment.get("body") or ""):
                existing = comment
                break
        if len(comments) < 100:
            break
        page += 1
    if existing:
        status, result = http("PATCH", f"{base}/comments/{existing['id']}", token, {"body": body})
        action, verb = "updated", "update"
    else:
        status, result = http("POST", f"{base}/{pr_number}/comments", token, {"body": body})
        action, verb = "created", "create"
    if status not in (200, 201):
        raise RuntimeError(f"could not {verb} the comment: HTTP {status}")
    return {"action": action, "url": (result or {}).get("html_url"), "id": (result or {}).get("id")}
