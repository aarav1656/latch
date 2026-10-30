"""Tests for the hosted app. Stdlib unittest; the proof pipeline is mocked.

Run from the repo root:  python3 -m unittest latch.web.test_app -v
"""

import http.client
import json
import re
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from latch.web import app as web
from latch.web.sandbox import SandboxConfig, SandboxRunner, SandboxTimeout
from latch.web.service import ApiError, Config, classify
from latch.web.store import receipt_key

CLICK = "https://github.com/pallets/click/pull/3299"
CLICK_BASE = "04ef3a6f473deb2499721a8d11f92a7d2c0912f2"
CLICK_HEAD = "d340b0c1202284a1b9d0ca892549208527d586ce"
FAIL = "FAILED latch_issue_test.py::test_x - AssertionError\n"


def receipt(base, head, proven=True, base_rc=1, head_rc=0, expected=True):
    return {
        "repo": "acme/widgets", "base": base, "head": head, "issue": "double(2) returns 5",
        "test_command": "python3 -m pytest -q", "model": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "completion_id": "chatcmpl-test", "test": "def test_x():\n    assert 1\n", "test_name": "test_x",
        "base_result": {"returncode": base_rc, "stdout": FAIL, "stderr": ""},
        "head_result": {"returncode": head_rc, "stdout": "1 passed", "stderr": ""},
        "base_failure_type": "assertion", "base_failure_is_expected": expected, "proven": proven,
        "pull_request_url": "https://github.com/acme/widgets/pull/7", "pull_request_title": "Fix double",
        "issue_url": "https://github.com/acme/widgets/issues/6", "issue_title": "double is off by one",
    }


class FakeRunner:
    description = "fake runner"
    notes = []


class Harness:
    """A real server on an ephemeral port with a mocked pipeline."""

    def __init__(self, test, live=True, key=True, run_pr=None, resolve=None, loop_argv=None, **config):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.prs = {CLICK: ("pallets/click", 3299, CLICK_BASE, CLICK_HEAD)}
        self.pr_count = 0

        def default_resolve(url):
            if url in self.prs:
                repo, number, base, head = self.prs[url]
                return {"repo": repo, "number": number, "base": base, "head": head, "title": "t"}
            raise ValueError("The GitHub pull request or linked issue was not found")

        def default_run(url, path, command, on_step=None, runner=None):
            self.calls.append(url)
            repo, number, base, head = self.prs[url]
            for step in ("fetching", "fetching-commits", "generating-test", "model", "base-test", "head-test", "receipt"):
                on_step(step)
            return receipt(base, head)

        config.setdefault("rate_limit", 100)
        config.setdefault("submit_rate", 1000)
        self.service = web.build_service(
            self.tmp.name,
            config=Config(live=live, **config),
            run_pr=run_pr or default_run,
            resolve=resolve or default_resolve,
            key_present=lambda: key,
            runner_factory=lambda progress: FakeRunner(),
            loop_argv=loop_argv,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(self.service, trust_proxy=True))
        self.server.daemon_threads = True
        threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True).start()
        test.addCleanup(self.close)
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def add_pr(self, number, head=None, repo="acme/widgets"):
        head = head or f"{number:040x}"
        url = f"https://github.com/{repo}/pull/{number}"
        self.prs[url] = (repo, number, "b" * 40, head)
        return url

    def request(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=payload, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def post(self, url, ip=None, **extra):
        headers = {"Content-Type": "application/json"}
        if ip:
            headers["X-Forwarded-For"] = ip
        status, hdrs, data = self.request("POST", "/api/proof", {"pull_request_url": url, **extra}, headers)
        return status, hdrs, json.loads(data)

    def get_json(self, path):
        status, _, data = self.request("GET", path)
        return status, json.loads(data)

    def events(self, job_id):
        return self.events_for("proof", job_id)

    def events_for(self, kind, job_id):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("GET", f"/api/{kind}/{job_id}/events")
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/event-stream")
        out, event = [], {}
        while True:
            line = response.readline()
            if not line:
                break
            line = line.decode().rstrip("\n")
            if line.startswith("event: "):
                event["event"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[6:])
            elif line == "" and event:
                out.append(event)
                event = {}
        conn.close()
        return out

    def run_live(self, url, **kw):
        status, _, body = self.post(url, **kw)
        self.assertion = (status, body)
        return status, body


class CacheTests(unittest.TestCase):
    def test_recorded_click_receipt_is_served_instantly_without_a_live_run(self):
        h = Harness(self)
        status, _, body = h.post(CLICK)
        self.assertEqual(status, 200)
        self.assertTrue(body["cached"])
        self.assertTrue(body["receipt"]["proven"])
        self.assertEqual(body["meta"]["source"], "recorded")
        self.assertEqual(body["permalink"], "/r/pallets/click/3299")
        self.assertEqual(h.calls, [])

    def test_first_screen_embeds_the_click_receipt_with_no_fetch(self):
        h = Harness(self, live=False)
        status, headers, page = h.request("GET", "/")
        text = page.decode()
        self.assertEqual(status, 200)
        self.assertIn("Space+Grotesk", text)
        self.assertNotIn("Inter", text.replace("Interne", ""))
        boot = json.loads(text.split('id="boot" type="application/json">')[1].split("</script>")[0])
        self.assertTrue(boot["example"]["receipt"]["proven"])
        self.assertFalse(boot["config"]["live"])
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])

    def test_example_endpoint_and_permalink(self):
        h = Harness(self)
        status, body = h.get_json("/api/example")
        self.assertEqual(status, 200)
        self.assertEqual(body["receipt"]["completion_id"], "chatcmpl-99d6e5a92020c804")
        status, _, page = h.request("GET", "/r/pallets/click/3299")
        self.assertEqual(status, 200)
        self.assertIn(b"chatcmpl-99d6e5a92020c804", page)
        status, _, page = h.request("GET", "/r/pallets/click/99999")
        self.assertEqual(status, 404)
        self.assertIn(b"No saved receipt", page)

    def test_live_result_is_cached_and_repeats_are_instant(self):
        h = Harness(self)
        url = h.add_pr(7)
        status, _, queued = h.post(url)
        self.assertEqual(status, 202)
        events = h.events(queued["job_id"])
        names = [e["event"] for e in events]
        self.assertEqual(names[0], "queued")
        self.assertEqual(names[-1], "result")
        steps = [e["data"]["step"] for e in events if e["event"] == "step"]
        self.assertEqual(steps[:1], ["fetching"])
        self.assertIn("model", steps)
        self.assertEqual(steps[-3:], ["base-test", "head-test", "receipt"])
        self.assertTrue(events[-1]["data"]["receipt"]["proven"])
        self.assertEqual(events[-1]["data"]["meta"]["source"], "live")

        status, _, again = h.post(url)
        self.assertEqual((status, again["cached"]), (200, True))
        self.assertEqual(h.calls, [url])  # no second run
        status, saved = h.get_json("/r/acme/widgets/7".replace("/r/", "/api/receipt/"))
        self.assertEqual(status, 200)
        self.assertEqual(saved["receipt"]["head"], f"{7:040x}")
        status, _, page = h.request("GET", "/r/acme/widgets/7")
        self.assertEqual(status, 200)
        self.assertIn(b"chatcmpl-test", page)

    def test_job_status_json_after_completion(self):
        h = Harness(self)
        url = h.add_pr(8)
        _, _, queued = h.post(url)
        h.events(queued["job_id"])
        status, job = h.get_json(f"/api/proof/{queued['job_id']}")
        self.assertEqual((status, job["status"]), (200, "done"))
        self.assertTrue(job["receipt"]["proven"])
        status, _ = h.get_json("/api/proof/" + "0" * 32)
        self.assertEqual(status, 404)

    def test_cache_survives_restart_and_is_keyed_by_commits(self):
        h = Harness(self)
        url = h.add_pr(9)
        _, _, queued = h.post(url)
        h.events(queued["job_id"])
        stored = Path(h.tmp.name) / "receipts" / f"{receipt_key('acme/widgets', 'b' * 40, f'{9:040x}')}.json"
        self.assertTrue(stored.exists())
        # a new head sha is a different key, so it is not served from cache
        h.prs[url] = ("acme/widgets", 9, "b" * 40, "c" * 40)
        status, _, body = h.post(url)
        self.assertEqual(status, 202)
        h.events(body["job_id"])


class LimitTests(unittest.TestCase):
    def test_per_ip_rate_limit_blocks_the_next_live_run_but_not_cached_ones(self):
        h = Harness(self, rate_limit=1)
        first, second = h.add_pr(1), h.add_pr(2)
        status, _, body = h.post(first, ip="9.9.9.9")
        self.assertEqual(status, 202)
        h.events(body["job_id"])
        status, headers, body = h.post(second, ip="9.9.9.9")
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["code"], "rate_limited")
        self.assertIn("Retry-After", headers)
        status, _, cached = h.post(first, ip="9.9.9.9")
        self.assertEqual((status, cached["cached"]), (200, True))
        status, _, other = h.post(second, ip="8.8.8.8")  # different visitor
        self.assertEqual(status, 202)
        h.events(other["job_id"])

    def test_daily_cap_falls_back_to_cached_receipts_with_a_message(self):
        h = Harness(self, daily_cap=1)
        first, second = h.add_pr(1), h.add_pr(2)
        _, _, body = h.post(first)
        h.events(body["job_id"])
        status, _, body = h.post(second)
        self.assertEqual(status, 503)
        self.assertIn("daily limit", body["error"]["message"])
        status, _, cached = h.post(first)
        self.assertEqual(status, 200)
        status, _, forced = h.post(first, live=True)  # forcing a rerun is also capped, but cached receipt returned with the reason
        self.assertEqual(status, 200)
        self.assertIn("daily limit", forced["note"])
        _, cfg = h.get_json("/api/config")
        self.assertFalse(cfg["live"])

    def test_live_switch_off_keeps_cached_receipts_usable(self):
        h = Harness(self, live=False)
        status, _, body = h.post(CLICK)
        self.assertEqual((status, body["cached"]), (200, True))
        status, _, body = h.post(CLICK, live=True)
        self.assertEqual(status, 200)
        self.assertIn("LATCH_LIVE=0", body["note"])
        status, _, body = h.post(h.add_pr(3))
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "live_disabled")

    def test_missing_key_disables_live_runs(self):
        h = Harness(self, key=False)
        status, _, body = h.post(h.add_pr(3))
        self.assertEqual((status, body["error"]["code"]), (503, "live_disabled"))

    def test_queue_limit_returns_503_with_a_reason(self):
        gate = threading.Event()

        def slow(url, path, command, on_step=None, runner=None):
            on_step("fetching")
            gate.wait(10)
            return receipt("b" * 40, "a" * 40)

        h = Harness(self, run_pr=slow, queue_max=1)
        self.addCleanup(gate.set)
        statuses = []
        for number in (1, 2, 3):
            statuses.append(h.post(h.add_pr(number, head=f"{number}" * 40))[0])
            if number == 1:
                deadline = time.time() + 5
                while h.service.running is None and time.time() < deadline:
                    time.sleep(0.01)
        self.assertEqual(statuses, [202, 202, 503])
        _, _, body = h.post(h.add_pr(4, head="4" * 40))
        self.assertEqual(body["error"]["code"], "queue_full")
        gate.set()

    def test_identical_in_flight_request_is_deduplicated(self):
        gate = threading.Event()

        def slow(url, path, command, on_step=None, runner=None):
            gate.wait(10)
            return receipt("b" * 40, "a" * 40)

        h = Harness(self, run_pr=slow)
        self.addCleanup(gate.set)
        url = h.add_pr(5)
        _, _, first = h.post(url)
        _, _, second = h.post(url)
        self.assertEqual(first["job_id"], second["job_id"])
        gate.set()


class FailClosedTests(unittest.TestCase):
    def assert_resolve_error(self, message, code, status):
        def resolve(url):
            raise ValueError(message)

        h = Harness(self, resolve=resolve)
        got, _, body = h.post("https://github.com/acme/widgets/pull/1")
        self.assertEqual((got, body["error"]["code"]), (status, code))
        self.assertTrue(body["error"]["message"])

    def test_bad_urls_are_rejected(self):
        h = Harness(self)
        for bad in ("", "not a url", "https://example.com/a/b/pull/1", "https://github.com/a/b/issues/1", "http://github.com/a/b/pull/1"):
            status, _, body = h.post(bad)
            self.assertEqual((status, body["error"]["code"]), (400, "bad_url"), bad)
        status, _, body = h.post(None)
        self.assertEqual(status, 400)

    def test_resolution_failures_have_human_reasons(self):
        self.assert_resolve_error("The GitHub pull request or linked issue was not found", "not_found", 404)
        self.assert_resolve_error("This pull request does not close an issue in its repository", "no_closing_issue", 422)
        self.assert_resolve_error("The pull request closes more than one issue; Latch needs one issue as its oracle", "multiple_issues", 422)
        self.assert_resolve_error("The pull request closes an issue in another repository", "cross_repo_issue", 422)
        self.assert_resolve_error("GitHub rate limit or access policy blocked this request", "github_rate_limited", 503)

    def run_failure(self, error):
        def failing(url, path, command, on_step=None, runner=None):
            on_step("fetching")
            raise error

        h = Harness(self, run_pr=failing)
        _, _, queued = h.post(h.add_pr(1))
        events = h.events(queued["job_id"])
        self.assertEqual(events[-1]["event"], "error")
        status, job = h.get_json(f"/api/proof/{queued['job_id']}")
        self.assertEqual(job["status"], "error")
        # nothing is cached for failures
        status, _, again = h.post(h.add_pr(1))
        self.assertEqual(status, 202)
        return events[-1]["data"]

    def test_run_failures_are_reported_not_cached(self):
        cases = [
            (ValueError("the selected revisions have no changed Python files"), "no_python_changes"),
            (ValueError("Python diff exceeds the 40,000 character model input limit"), "diff_too_large"),
            (ValueError("The linked issue is too long for one proof run"), "issue_too_long"),
            (RuntimeError("Nebius model request failed: HTTP 429"), "model_error"),
            (RuntimeError("NEBIUS_API_KEY is not configured"), "live_disabled"),
            (ValueError("no function in text"), "model_bad_output"),
            (SandboxTimeout("test", 120), "timeout"),
            (RuntimeError("something odd"), "internal_error"),
        ]
        for error, code in cases:
            with self.subTest(code=code):
                self.assertEqual(self.run_failure(error)["code"], code)

    def test_not_proven_receipts_explain_why(self):
        for kwargs, fragment in (
            (dict(proven=False, base_rc=0, head_rc=0), "passed on the buggy base"),
            (dict(proven=False, base_rc=1, head_rc=1), "still fails on the pull request head"),
            (dict(proven=False, base_rc=2, head_rc=0, expected=False), "not with an assertion"),
            (dict(proven=False, base_rc=-15, head_rc=-15, expected=False), "killed by the sandbox"),
        ):
            def run(url, path, command, on_step=None, runner=None, kwargs=kwargs):
                return receipt("b" * 40, "a" * 40, **kwargs)

            h = Harness(self, run_pr=run)
            _, _, queued = h.post(h.add_pr(1))
            result = h.events(queued["job_id"])[-1]
            self.assertEqual(result["event"], "result")
            meta = result["data"]["meta"]
            self.assertEqual(meta["verdict"], "not_proven")
            self.assertIn(fragment, meta["why_not_proven"])

    def test_bad_requests(self):
        h = Harness(self)
        status, _, _ = h.request("POST", "/api/proof", raw=b"{nope", headers={"Content-Length": "5"})
        self.assertEqual(status, 400)
        status, _, _ = h.request("POST", "/api/proof", raw=b"x" * 5000, headers={"Content-Length": "5000"})
        self.assertEqual(status, 413)
        self.assertEqual(h.request("POST", "/api/nope", raw=b"{}")[0], 404)
        self.assertEqual(h.request("GET", "/static/../app.py")[0], 404)
        self.assertEqual(h.request("GET", "/static/%2e%2e/app.py")[0], 404)
        self.assertEqual(h.request("GET", "/r/..%2f../etc/1")[0], 404)

    def test_health_and_static_assets(self):
        h = Harness(self)
        self.assertEqual(h.get_json("/healthz")[1]["ok"], True)
        status, headers, css = h.request("GET", "/static/app.css")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/css"))
        self.assertNotIn(b"Inter", css.replace(b"Interface", b""))
        status, _, tokens = h.request("GET", "/static/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn(b"--accent", tokens)
        self.assertNotIn(b"gradient", css + tokens)
        self.assertNotIn(b"backdrop-filter", css + tokens)

    def test_boot_json_cannot_break_out_of_its_script_tag(self):
        text = web.boot_json({"x": "</script><script>alert(1)</script>"})
        self.assertNotIn("<", text)
        self.assertEqual(json.loads(text)["x"], "</script><script>alert(1)</script>")

    def test_classify_passes_api_errors_through(self):
        error = ApiError("x", 418, "tea")
        self.assertIs(classify(error), error)


class SandboxTests(unittest.TestCase):
    def runner(self, **options):
        options.setdefault("install", "none")
        options.setdefault("net_isolation", "off")
        options.setdefault("test_timeout", 5)
        return SandboxRunner(SandboxConfig(**options))

    def run_snippet(self, snippet, **options):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)
            (snapshot / "latch_issue_test.py").write_text("")
            return self.runner(**options)(snapshot, ["python3", "-c", snippet])

    def test_child_environment_has_no_secrets(self):
        env = {"NEBIUS_API_KEY": "sk-secret", "GITHUB_TOKEN": "ghp-secret", "AWS_SECRET_ACCESS_KEY": "x"}
        with mock.patch.dict(os.environ, env):
            result = self.run_snippet("import os; print(sorted(os.environ)); print(os.environ['HOME'])")
        self.assertEqual(result["returncode"], 0, result)
        for name in env:
            self.assertNotIn(name, result["stdout"])
        self.assertNotIn("sk-secret", result["stdout"] + result["stderr"])
        self.assertIn(".latch-home", result["stdout"])

    def test_hard_timeout_kills_the_process_group(self):
        marker = tempfile.mktemp()
        snippet = (
            "import os,subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
            f"open({marker!r},'w').write(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        started = time.time()
        with self.assertRaises(SandboxTimeout) as caught:
            self.run_snippet(snippet, test_timeout=1)
        self.assertLess(time.time() - started, 8)
        self.assertEqual(caught.exception.phase, "test")
        time.sleep(0.2)
        pid = int(Path(marker).read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        os.unlink(marker)

    def test_pr_conftest_and_pytest_config_cannot_change_the_outcome(self):
        try:
            import pytest  # noqa: F401
        except ImportError:
            self.skipTest("pytest not installed")
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)
            (snapshot / "latch_issue_test.py").write_text("def test_it():\n    assert 1 + 1 == 2\n")
            (snapshot / "conftest.py").write_text("raise RuntimeError('hostile conftest')\n")
            (snapshot / "pytest.ini").write_text("[pytest]\naddopts = --collect-only\n")
            result = self.runner(test_timeout=60)(snapshot, ["python3", "-m", "pytest", "-q"])
        self.assertEqual(result["returncode"], 0, result)
        self.assertIn("1 passed", result["stdout"])

    def test_sandbox_env_sets_wide_columns_and_status_warns_without_netns(self):
        runner = self.runner()
        with tempfile.TemporaryDirectory() as temp:
            env = runner._env(Path(temp), Path(temp))
        self.assertEqual(env["COLUMNS"], "200")
        from latch.web import service as service_module

        with mock.patch.object(service_module, "net_namespace_available", return_value=False):
            holder = mock.Mock(sandbox_config=SandboxConfig(net_isolation="auto"))
            status = service_module.Service.sandbox_status(holder)
            self.assertFalse(status["network_isolated"])
            self.assertIn("unavailable", status["warning"])
            holder = mock.Mock(sandbox_config=SandboxConfig(net_isolation="off"))
            self.assertIsNone(service_module.Service.sandbox_status(holder)["warning"])

    def test_public_error_detail_hides_server_paths(self):
        from latch.web.service import redact

        text = redact("fatal: could not read /tmp/latch-pr-ab12/repo/.git/config and /Users/me/x.py")
        self.assertNotIn("latch-pr-ab12", text)
        self.assertNotIn("/Users", text)
        self.assertIn("<path>", text)

    def test_file_size_limit_is_enforced(self):
        result = self.run_snippet(
            "open('big.bin','wb').write(b'x'*(5*1024*1024))", test_fsize_mb=1
        )
        self.assertNotEqual(result["returncode"], 0)

    def test_output_is_truncated_to_the_tail(self):
        result = self.run_snippet("print('a'*50000); print('END')")
        self.assertLessEqual(len(result["stdout"]), 12000)
        self.assertTrue(result["stdout"].strip().endswith("END"))

    def test_child_cannot_read_server_environ_when_non_dumpable(self):
        # prctl(PR_SET_DUMPABLE, 0) is what app.main() applies to the server process
        from latch.web.sandbox import drop_dumpable

        if not Path("/proc/self/environ").exists():
            self.skipTest("no /proc")
        self.assertTrue(drop_dumpable())
        snippet = f"import sys\ntry:\n open('/proc/{os.getpid()}/environ').read(); print('READABLE')\nexcept OSError: print('DENIED')"
        result = self.run_snippet(snippet)
        self.assertIn(result["stdout"].strip(), ("DENIED", "READABLE"))
        if os.geteuid() != 0:
            self.assertEqual(result["stdout"].strip(), "DENIED")


LOOP_STUB = r"""
import json, sys, time
mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
def emit(**e):
    e.setdefault("ts", "2026-10-29T10:00:00Z"); e.setdefault("run_id", "r1")
    print(json.dumps(e), flush=True)
emit(type="started", issue="x", max_iterations=1)
emit(type="gate_shut", reason="proof test fails on the agent's fix", base_red=True, head_suite_green=True, head_proof_green=False, pytest_output="F")
if mode == "hang":
    time.sleep(60)
if mode == "crash":
    emit(type="error", reason="Nebius API returned 500"); sys.exit(2)
if mode == "credits":
    emit(type="error", reason="Nebius test-generation request failed: HTTP 402"); sys.exit(2)
if mode == "retry":
    emit(type="model_retry", attempt=1, attempts=3, status=None, error="RemoteDisconnected: closed", will_retry=True, delay=1.0)
if mode == "silent":
    sys.exit(3)
emit(type="iteration_result", iteration=1, verdict="gate_open", diff="--- a\n+++ b", pytest_output=".")
emit(type="gate_open", reason="ok", receipt={"verdict": "gate_open"})
"""


def loop_stub(mode="ok"):
    return [sys.executable, "-c", LOOP_STUB, mode]


class LoopTests(unittest.TestCase):
    def test_recorded_example_is_served_without_live_access(self):
        h = Harness(self, live=False, loop_argv=None)
        status, body = h.get_json("/api/loop/example")
        self.assertEqual(status, 200)
        types = [e["type"] for e in body["events"]]
        self.assertEqual(types[0], "started")
        self.assertEqual(types[-1], "gate_open")
        self.assertIn("gate_shut", types)
        self.assertIn("patch_applied", types)
        self.assertFalse(h.get_json("/api/config")[1]["loop"]["live"])

    def test_live_loop_streams_events_over_sse_and_counts_against_the_cap(self):
        h = Harness(self, loop_argv=loop_stub("ok"), daily_cap=5)
        self.assertTrue(h.get_json("/api/config")[1]["loop"]["live"])
        status, _, data = h.request("POST", "/api/loop", {})
        body = json.loads(data)
        self.assertEqual(status, 202)
        events = h.events_for("loop", body["job_id"])
        names = [e["event"] for e in events]
        self.assertIn("loop", names)
        self.assertEqual(names[-1], "done")
        loop_types = [e["data"]["type"] for e in events if e["event"] == "loop"]
        self.assertEqual(loop_types, ["started", "gate_shut", "iteration_result", "gate_open"])
        self.assertEqual(h.get_json("/api/config")[1]["daily_remaining"], 4)
        status, job = h.get_json(f"/api/loop/{body['job_id']}")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["verdict"], "gate_open")
        self.assertEqual(len(job["events"]), 4)

    def test_live_loop_is_refused_when_live_is_off(self):
        h = Harness(self, live=False, loop_argv=loop_stub())
        status, _, data = h.request("POST", "/api/loop", {})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(data)["error"]["code"], "live_disabled")

    def test_live_loop_shares_the_per_ip_rate_limit(self):
        h = Harness(self, loop_argv=loop_stub(), rate_limit=1)
        ip = {"X-Forwarded-For": "9.9.9.9"}
        status, _, data = h.request("POST", "/api/loop", {}, ip)
        self.assertEqual(status, 202)
        h.events_for("loop", json.loads(data)["job_id"])
        status, _, data = h.request("POST", "/api/loop", {}, ip)
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(data)["error"]["code"], "rate_limited")

    def test_loop_error_event_fails_closed_with_a_reason(self):
        h = Harness(self, loop_argv=loop_stub("crash"))
        _, _, data = h.request("POST", "/api/loop", {})
        events = h.events_for("loop", json.loads(data)["job_id"])
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["data"]["code"], "model_error")

    def test_loop_without_a_verdict_is_an_error(self):
        h = Harness(self, loop_argv=loop_stub("silent"))
        _, _, data = h.request("POST", "/api/loop", {})
        events = h.events_for("loop", json.loads(data)["job_id"])
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["data"]["code"], "loop_failed")

    def test_loop_timeout_kills_the_process_group(self):
        h = Harness(self, loop_argv=loop_stub("hang"), loop_timeout=1)
        _, _, data = h.request("POST", "/api/loop", {})
        events = h.events_for("loop", json.loads(data)["job_id"])
        self.assertEqual(events[-1]["data"]["code"], "timeout")

    def test_loop_unavailable_without_the_package(self):
        h = Harness(self, loop_argv=None)
        self.assertFalse(h.get_json("/api/config")[1]["loop"]["available"])
        status, _, data = h.request("POST", "/api/loop", {})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(data)["error"]["code"], "loop_unavailable")

    def test_loop_environment_carries_only_the_model_key(self):
        from latch.web.service import loop_env

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"NEBIUS_API_KEY": "k", "GITHUB_TOKEN": "g", "AWS_SECRET": "s"}
        ):
            env = loop_env(tmp)
        self.assertEqual(env["NEBIUS_API_KEY"], "k")
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("AWS_SECRET", env)
        self.assertTrue(env["HOME"].startswith(tmp))

CREDITS = "Live runs are paused: model credits exhausted. Showing saved receipts."


def run_raising(error):
    def run(url, path, command, on_step=None, runner=None):
        raise error
    return run


class ReceiptNoteTests(unittest.TestCase):
    def test_recorded_reason_wins_and_is_a_sentence(self):
        from latch.web.store import explain

        r = receipt("b" * 40, "a" * 40, proven=False, base_rc=0, head_rc=0)
        r["why_not_proven"] = "the generated test was rejected twice: the test body is empty"
        self.assertEqual(explain(r), "The generated test was rejected twice: the test body is empty.")

    def test_proven_receipts_have_no_reason_even_with_a_stale_one(self):
        from latch.web.store import explain

        r = receipt("b" * 40, "a" * 40)
        r["why_not_proven"] = "stale"
        self.assertIsNone(explain(r))

    def test_fail_closed_receipt_without_runs_never_claims_the_base_failed(self):
        from latch.web.store import explain

        r = receipt("b" * 40, "a" * 40, proven=False)
        r.update(base_result=None, head_result=None, test=None)
        text = explain(r)
        self.assertIn("never run on the base commit", text)
        self.assertNotIn("failed on the base", text)
        r["head_result"] = {"returncode": 0, "stdout": "", "stderr": ""}
        r["base_result"] = {"returncode": 1, "stdout": "", "stderr": ""}
        r["head_result"] = None
        self.assertIn("never run on the pull request head", explain(r))

    def test_test_attempts_note(self):
        from latch.web.store import attempts_note

        bad = {"attempt": 1, "valid": False, "rejection": "the test body is empty", "source": "def test_x(): ..."}
        good = {"attempt": 2, "valid": True, "rejection": None}
        self.assertEqual(attempts_note({"test_attempts": [bad, good]}), "First test rejected: empty body, retried.")
        self.assertIsNone(attempts_note({"test_attempts": [good]}))
        self.assertIsNone(attempts_note({}))
        both = attempts_note({"test_attempts": [bad, {**bad, "attempt": 2, "rejection": "the test has no real check"}]})
        self.assertIn("retry was rejected too (no real assertion)", both)
        self.assertEqual(attempts_note({"proof_test_attempts": [bad, good]}), "First test rejected: empty body, retried.")

    def test_model_retries_note(self):
        from latch.web.store import retries_note

        one = {"attempt": 1, "attempts": 3, "status": None, "error": "RemoteDisconnected: closed", "will_retry": True, "delay": 1.0}
        two = {"attempt": 2, "attempts": 3, "status": 503, "error": None, "will_retry": True, "delay": 2.0}
        last = {"attempt": 3, "attempts": 3, "status": 503, "error": None, "will_retry": False, "delay": 0}
        self.assertEqual(retries_note({"model_retries": [one]}), "The model request was retried once (RemoteDisconnected).")
        self.assertEqual(retries_note({"model_retries": [one, two, last]}), "The model request was retried 2 times (RemoteDisconnected, HTTP 503).")
        self.assertIsNone(retries_note({"model_retries": [last]}))
        self.assertIsNone(retries_note({}))

    def test_envelope_meta_carries_the_notes_and_the_recorded_reason(self):
        def run(url, path, command, on_step=None, runner=None):
            r = receipt("b" * 40, "a" * 40, proven=False)
            r.update(base_result=None, head_result=None, test=None,
                     why_not_proven="the generated test was rejected twice: the test body is empty",
                     test_attempts=[{"attempt": 1, "valid": False, "rejection": "the test body is empty", "source": "x"},
                                    {"attempt": 2, "valid": False, "rejection": "the test body is empty", "source": "y"}],
                     model_retries=[{"attempt": 1, "attempts": 3, "status": 502, "error": None, "will_retry": True, "delay": 1}])
            return r

        h = Harness(self, run_pr=run)
        _, _, queued = h.post(h.add_pr(1))
        meta = h.events(queued["job_id"])[-1]["data"]["meta"]
        self.assertEqual(meta["verdict"], "not_proven")
        self.assertTrue(meta["why_not_proven"].startswith("The generated test was rejected twice"))
        self.assertIn("First test rejected: empty body", meta["test_attempts_note"])
        self.assertIn("retried once (HTTP 502)", meta["model_retries_note"])

    def test_clean_receipts_have_no_notes(self):
        from latch.web.store import make_envelope

        meta = make_envelope(receipt("b" * 40, "a" * 40), "live")["meta"]
        self.assertIsNone(meta["test_attempts_note"])
        self.assertIsNone(meta["model_retries_note"])


class IssueNumberTests(unittest.TestCase):
    def test_issue_number_redirects_to_the_pr_receipt_never_a_contradicting_banner(self):
        h = Harness(self, live=False)
        status, headers, _ = h.request("GET", "/r/pallets/click/3298")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/r/pallets/click/3299")
        self.assertEqual(h.request("GET", "/api/receipt/pallets/click/3298")[0], 404)  # the API stays literal
        status, _, page = h.request("GET", "/r/pallets/click/3299")
        self.assertEqual(status, 200)
        self.assertNotIn("No saved receipt", page.decode())

    def test_unknown_numbers_still_404_with_the_banner(self):
        h = Harness(self, live=False)
        status, _, page = h.request("GET", "/r/pallets/click/1")
        self.assertEqual(status, 404)
        self.assertIn("No saved receipt for pallets/click#1", page.decode())
        self.assertEqual(h.request("GET", "/r/pallets/other/3298")[0], 404)


class CreditsExhaustedAtStartTests(unittest.TestCase):
    def test_deployed_app_with_no_credits_degrades_cleanly_from_the_first_request(self):
        h = Harness(self, credits_exhausted=True)
        _, cfg = h.get_json("/api/config")
        self.assertFalse(cfg["live"])
        self.assertEqual(cfg["live_reason"], CREDITS)
        self.assertFalse(cfg["loop"]["live"])
        _, _, page = h.request("GET", "/")
        boot = json.loads(page.decode().split('id="boot" type="application/json">')[1].split("</script>")[0])
        self.assertFalse(boot["config"]["live"])
        self.assertTrue(boot["example"]["receipt"]["proven"])
        self.assertEqual(boot["example"]["meta"]["source"], "recorded")
        status, example = h.get_json("/api/loop/example")
        self.assertEqual(status, 200)
        self.assertTrue(example["events"])
        status, _, body = h.post(CLICK)
        self.assertEqual((status, body["cached"], body["meta"]["source"]), (200, True, "recorded"))
        status, _, body = h.post(h.add_pr(2))
        self.assertEqual((status, body["error"]["code"]), (503, "live_disabled"))
        self.assertEqual(body["error"]["message"], CREDITS)


class CreditsTests(unittest.TestCase):
    def clocked(self, **kw):
        now = [1_000_000.0]
        h = Harness(self, **kw)
        h.service.clock = lambda: now[0]
        return h, now

    def test_402_maps_to_a_clear_fail_closed_reason(self):
        for text in ("Nebius model request failed: HTTP 402", "Nebius test-generation request failed: HTTP 402",
                     "credit_balance_exhausted", "model credits exhausted"):
            with self.subTest(text=text):
                problem = classify(RuntimeError(text))
                self.assertEqual((problem.code, problem.status), ("credits_exhausted", 503))
                self.assertEqual(problem.payload()["error"]["message"], CREDITS)
        self.assertEqual(classify(RuntimeError("Nebius model request failed: HTTP 429")).code, "model_error")

    def test_a_402_pauses_live_mode_and_judges_get_cached_receipts(self):
        h, now = self.clocked(run_pr=run_raising(RuntimeError("Nebius model request failed: HTTP 402")))
        _, _, queued = h.post(h.add_pr(1))
        last = h.events(queued["job_id"])[-1]
        self.assertEqual(last["event"], "error")
        self.assertEqual(last["data"]["code"], "credits_exhausted")
        self.assertEqual(last["data"]["message"], CREDITS)
        _, cfg = h.get_json("/api/config")
        self.assertFalse(cfg["live"])
        self.assertEqual(cfg["live_reason"], CREDITS)
        self.assertGreater(cfg["live_paused_s"], 590)
        self.assertFalse(h.get_json("/api/config")[1]["loop"]["live"])
        # the cached Click receipt is still served, with the reason as the note, and no job is queued
        status, _, body = h.post(CLICK, live=True)
        self.assertEqual(status, 200)
        self.assertTrue(body["cached"])
        self.assertEqual(body["note"], CREDITS)
        # an uncached PR is refused fast with the same reason
        status, _, body = h.post(h.add_pr(2))
        self.assertEqual((status, body["error"]["code"]), (503, "live_disabled"))
        self.assertEqual(body["error"]["message"], CREDITS)
        self.assertEqual(h.get_json("/healthz")[1]["live"], False)

    def test_live_mode_comes_back_after_the_pause(self):
        h, now = self.clocked(run_pr=run_raising(RuntimeError("Nebius model request failed: HTTP 402")), credit_pause_s=600)
        h.events(h.post(h.add_pr(1))[2]["job_id"])
        self.assertFalse(h.get_json("/api/config")[1]["live"])
        now[0] += 599
        self.assertFalse(h.get_json("/api/config")[1]["live"])
        now[0] += 2
        cfg = h.get_json("/api/config")[1]
        self.assertTrue(cfg["live"])
        self.assertEqual(cfg["live_paused_s"], 0)

    def test_other_model_errors_do_not_pause_live_mode(self):
        h, now = self.clocked(run_pr=run_raising(RuntimeError("Nebius model request failed: HTTP 503")))
        self.assertEqual(h.events(h.post(h.add_pr(1))[2]["job_id"])[-1]["data"]["code"], "model_error")
        self.assertTrue(h.get_json("/api/config")[1]["live"])

    def test_queued_jobs_fail_fast_once_paused(self):
        gate, calls = threading.Event(), []

        def run(url, path, command, on_step=None, runner=None):
            calls.append(url)
            gate.wait(10)
            raise RuntimeError("Nebius model request failed: HTTP 402")

        h, now = self.clocked(run_pr=run)
        first = h.post(h.add_pr(1))[2]["job_id"]
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        second = h.post(h.add_pr(2))[2]["job_id"]
        gate.set()
        self.assertEqual(h.events(first)[-1]["data"]["code"], "credits_exhausted")
        self.assertEqual(h.events(second)[-1]["data"]["code"], "credits_exhausted")
        self.assertEqual(len(calls), 1)

    def test_loop_402_maps_to_credits_and_pauses(self):
        h = Harness(self, loop_argv=loop_stub("credits"))
        _, _, data = h.request("POST", "/api/loop", {})
        events = h.events_for("loop", json.loads(data)["job_id"])
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["data"]["code"], "credits_exhausted")
        self.assertEqual(events[-1]["data"]["message"], CREDITS)
        self.assertFalse(h.get_json("/api/config")[1]["live"])
        status, _, data = h.request("POST", "/api/loop", {})
        self.assertEqual((status, json.loads(data)["error"]["message"]), (503, CREDITS))

    def test_loop_model_retry_events_pass_through(self):
        h = Harness(self, loop_argv=loop_stub("retry"))
        _, _, data = h.request("POST", "/api/loop", {})
        events = h.events_for("loop", json.loads(data)["job_id"])
        types = [e["data"]["type"] for e in events if e["event"] == "loop"]
        self.assertIn("model_retry", types)
        self.assertEqual(events[-1]["event"], "done")


class RecentTests(unittest.TestCase):
    def test_empty_store_lists_only_the_recorded_click_seed(self):
        h = Harness(self)
        status, body = h.get_json("/api/recent")
        self.assertEqual(status, 200)
        self.assertEqual([(i["repo"], i["number"], i["source"]) for i in body["items"]], [("pallets/click", 3299, "recorded")])
        self.assertEqual(body["items"][0]["permalink"], "/r/pallets/click/3299")

    def test_lists_real_cached_receipts_newest_first_and_skips_junk(self):
        h = Harness(self)
        for number in (1, 2):
            job = h.post(h.add_pr(number))[2]["job_id"]
            self.assertEqual(h.events(job)[-1]["event"], "result")
            time.sleep(1.05)  # created_at has one second resolution
        junk = Path(h.tmp.name) / "receipts" / "junk.json"
        junk.write_text(json.dumps({"receipt": {"proven": True}, "meta": {}}))
        (Path(h.tmp.name) / "receipts" / "bad.json").write_text("not json")
        items = h.get_json("/api/recent")[1]["items"]
        self.assertEqual([i["number"] for i in items][:2], [2, 1])
        self.assertEqual(items[0]["title"], "Fix double")
        self.assertEqual(items[0]["verdict"], "proven")
        self.assertEqual(items[0]["source"], "live")
        self.assertNotIn(None, [i["repo"] for i in items])

    def test_one_item_per_pull_request_and_limit(self):
        h = Harness(self)
        for number in range(1, 5):
            h.events(h.post(h.add_pr(number))[2]["job_id"])
        self.assertEqual(len(h.service.store.list_recent(limit=3)), 3)
        self.assertEqual(len({(i["repo"], i["number"]) for i in h.service.store.list_recent()}), 5)

    def test_boot_json_carries_recent_for_the_first_screen(self):
        h = Harness(self)
        _, _, data = h.request("GET", "/")
        text = data.decode()
        start = text.index('id="boot"')
        blob = text[text.index(">", start) + 1:text.index("</script>", start)]
        boot = json.loads(blob)
        self.assertEqual([i["number"] for i in boot["recent"]], [3299])


class StepEventTests(unittest.TestCase):
    def test_step_events_are_relayed_with_a_sequence_when_the_runner_accepts_them(self):
        def run(url, path, command, on_step=None, runner=None, on_step_event=None):
            on_step("fetching")
            on_step_event({"step": "fetch", "status": "started", "ts": "2026-10-30T04:00:00.000Z", "detail": None})
            on_step_event({"step": "fetch", "status": "done", "ts": "2026-10-30T04:00:01.000Z", "detail": "ok"})
            on_step_event({"step": "repo_map", "status": "failed", "ts": "2026-10-30T04:00:02.000Z", "detail": "x"})
            return receipt("b" * 40, "7" * 40)

        h = Harness(self, run_pr=run)
        events = h.events(h.post(h.add_pr(7))[2]["job_id"])
        relayed = [e["data"] for e in events if e["event"] == "step_event"]
        self.assertEqual([(e["step"], e["status"], e["seq"]) for e in relayed],
                         [("fetch", "started", 1), ("fetch", "done", 2), ("repo_map", "failed", 3)])
        self.assertEqual(relayed[1]["detail"], "ok")
        self.assertIn("step", [e["event"] for e in events])  # legacy events are untouched
        self.assertEqual(events[-1]["event"], "result")

    def test_step_events_replay_with_last_event_id(self):
        def run(url, path, command, on_step=None, runner=None, **kwargs):
            kwargs["on_step_event"]({"step": "fetch", "status": "started", "ts": "t", "detail": None})
            kwargs["on_step_event"]({"step": "fetch", "status": "done", "ts": "t", "detail": None})
            return receipt("b" * 40, "8" * 40)

        h = Harness(self, run_pr=run)
        job = h.post(h.add_pr(8))[2]["job_id"]
        h.events(job)
        conn = http.client.HTTPConnection("127.0.0.1", h.port, timeout=15)
        conn.request("GET", f"/api/proof/{job}/events", headers={"Last-Event-ID": "1"})
        body = conn.getresponse().read().decode()
        conn.close()
        self.assertIn("event: step_event", body)
        self.assertEqual(body.count("event: step_event"), body.count('"seq"') )

    def test_runners_without_the_keyword_still_work(self):
        h = Harness(self)
        events = h.events(h.post(h.add_pr(9))[2]["job_id"])
        self.assertNotIn("step_event", [e["event"] for e in events])
        self.assertEqual(events[-1]["event"], "result")


class EvalTests(unittest.TestCase):
    def root(self, summary=None, featured=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runs = Path(tmp.name) / "latch" / "runs"
        (runs / "eval").mkdir(parents=True)
        if summary is not None:
            (runs / "eval-summary.json").write_text(summary if isinstance(summary, str) else json.dumps(summary))
        if featured is not None:
            (runs / "eval" / "wrong.json").write_text(json.dumps(featured))
        patcher = mock.patch.dict(os.environ, {"LATCH_EVAL_ROOT": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        return Path(tmp.name)

    def test_missing_summary_is_pending(self):
        self.root()
        body = Harness(self).get_json("/api/eval")[1]
        self.assertEqual(body["available"], False)
        self.assertIn("Eval pending", body["reason"])

    def test_invalid_or_non_object_summary_is_pending(self):
        for text in ("{not json", "[1, 2]"):
            self.root(text)
            self.assertFalse(Harness(self).get_json("/api/eval")[1]["available"])

    def test_summary_is_returned_unchanged_with_featured_envelope(self):
        wrong = receipt("b" * 40, "9" * 40, proven=False)
        summary = {"upstream": {"n": 9, "proven": 7, "proven_rate": 0.78}, "caveat": "not like for like",
                   "featured_wrong_fix_receipt": "latch/runs/eval/wrong.json"}
        self.root(summary, wrong)
        body = Harness(self).get_json("/api/eval")[1]
        self.assertTrue(body["available"])
        self.assertEqual(body["summary"], summary)
        self.assertEqual(body["featured"]["meta"]["verdict"], "not_proven")
        self.assertEqual(body["featured"]["meta"]["source"], "recorded")

    def test_featured_path_cannot_escape_the_eval_directory(self):
        root = self.root({"featured_wrong_fix_receipt": "../../../../etc/passwd"})
        h = Harness(self)
        self.assertIsNone(h.get_json("/api/eval")[1]["featured"])
        secret = root / "secret.json"
        secret.write_text(json.dumps(receipt("b" * 40, "a" * 40)))
        for ref in (str(secret), "secret.json", "latch/runs/eval/../../../secret.json", "latch/runs/eval"):
            (root / "latch" / "runs" / "eval-summary.json").write_text(json.dumps({"featured_wrong_fix_receipt": ref}))
            body = h.get_json("/api/eval")[1]
            self.assertTrue(body["available"])
            self.assertIsNone(body["featured"], ref)


class PageRouteTests(unittest.TestCase):
    PAGES = (("/", "Prove a PR"), ("/eval", "Evidence"), ("/ship", "Use in CI"))

    def test_every_page_is_served_with_csp_and_no_inline_code(self):
        h = Harness(self)
        for path, _ in self.PAGES + (("/eval", ""), ("/ship", "")):
            status, headers, body = h.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["Content-Type"].startswith("text/html"))
            self.assertIn("Content-Security-Policy", headers)
            self.assertNotIn(b"__LATCH_BOOT__", body)
            text = body.decode()
            self.assertNotIn(" style=", text, path)  # CSP has no inline styles
            self.assertNotIn("onclick=", text, path)
            for tag in re.findall(r"<script\b[^>]*>", text):
                self.assertTrue("src=" in tag or "application/json" in tag, (path, tag))

    def test_pages_share_the_same_nav_and_mark_their_own_link_current(self):
        h = Harness(self)
        for path, label in self.PAGES:
            text = h.request("GET", path)[2].decode()
            for _, other in self.PAGES:
                self.assertIn(">" + other + "</a>", text, (path, other))
            current = re.findall(r'<a href="[^"]*" aria-current="page">([^<]*)</a>', text)
            self.assertEqual(current, [label], path)

    def test_static_files_referenced_by_pages_exist(self):
        h = Harness(self)
        for path, _ in self.PAGES:
            text = h.request("GET", path)[2].decode()
            for ref in re.findall(r'(?:src|href)="(/static/[^"]+)"', text):
                self.assertEqual(h.request("GET", ref)[0], 200, (path, ref))

    def test_eval_page_has_no_invented_numbers_and_ship_page_documents_the_action(self):
        h = Harness(self)
        eval_html = h.request("GET", "/eval")[2].decode()
        self.assertNotRegex(eval_html, r"\d+(\.\d+)?%")  # every figure comes from /api/eval at runtime
        ship = h.request("GET", "/ship")[2].decode()
        for needle in ("latch prove", "latch comment", "NEBIUS_API_KEY", "kamalbuilds/latch/.github/actions/latch", "GITHUB_TOKEN"):
            self.assertIn(needle, ship)

    def test_ship_page_workflow_matches_the_shipped_example(self):
        example = (web.REPO_ROOT / "latch/loop/github/latch.yml")
        if not example.is_file():
            self.skipTest("example workflow not present")
        lines = [l.strip() for l in example.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
        import html as htmllib
        ship = htmllib.unescape(Harness(self).request("GET", "/ship")[2].decode())
        for line in lines:
            code = line.split("   #")[0].strip()
            self.assertIn(code, ship, code)


class RecordedLabelTests(unittest.TestCase):
    def test_click_receipt_is_dated_by_its_commit_not_a_file_mtime(self):
        h = Harness(self)
        status, body = h.get_json("/api/receipt/pallets/click/3299")
        self.assertEqual(status, 200)
        self.assertEqual(body["meta"]["source"], "recorded")
        self.assertEqual(body["meta"]["created_at"], "2026-10-29T08:37:03Z")
        self.assertEqual(body["receipt"]["completion_id"], "chatcmpl-99d6e5a92020c804")

    def test_front_end_labels_recorded_cached_and_live_and_never_claims_a_live_time(self):
        js = (web.STATIC_DIR / "app.js").read_text()
        for label in ("Recorded run", "Cached receipt", "Live run", "not recorded"):
            self.assertIn(label, js)
        for path in web.STATIC_DIR.glob("*"):
            if path.suffix in (".html", ".js", ".css"):
                self.assertNotIn("16.1", path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
