import json
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
if __package__:
    from .github_pr import parse_pull_request_url, run_pull_request
    from .run import FIXTURE, SOURCE_NAME, SUITE_NAME, execute, render_screen
    from .screen.page import PAGE_HTML
else:
    sys.path.insert(0, os.path.dirname(ROOT))
    from latch.github_pr import parse_pull_request_url, run_pull_request
    from latch.run import FIXTURE, SOURCE_NAME, SUITE_NAME, execute, render_screen
    from latch.screen.page import PAGE_HTML

HOST = "127.0.0.1"
PORT = int(os.environ.get("LATCH_PORT", "4173"))
PROOF_RECEIPT = os.path.join(ROOT, "runs", "latest-proof.json")

STATUS = {"phase": "idle", "step": None, "state": None}
LOCK = threading.Lock()
PR_JOBS = {}
PR_LOCK = threading.Lock()


def fixture_payload():
    def read(name):
        with open(os.path.join(FIXTURE, name), encoding="utf-8") as handle:
            return handle.read()

    return {"billing": read(SOURCE_NAME), "tests": read(SUITE_NAME)}


def run_job():
    state = {
        "weak_green": None,
        "mutant_still_green": None,
        "kill_failed": False,
        "restored_passed": False,
        "model": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "lightning_model": "nvidia/Nemotron-3_5-Lightning",
        "assertion": None,
        "lightning": None,
        "http_status": None,
        "reason": "running",
    }

    def on_step(name):
        with LOCK:
            STATUS["step"] = name
            STATUS["state"] = dict(state)

    try:
        code = execute(state, on_step=on_step)
    except TimeoutError:
        state["reason"] = "timeout"
        code = 6
    runs = os.path.join(ROOT, "runs")
    os.makedirs(runs, exist_ok=True)
    with open(os.path.join(runs, "latest.json"), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    render_screen(state)
    with LOCK:
        STATUS["phase"] = "done"
        STATUS["code"] = code
        STATUS["state"] = state
        STATUS["step"] = state.get("step")


def start_pr_job(job_id, pull_url):
    def set_step(step):
        with PR_LOCK:
            job = PR_JOBS[job_id]
            job["step"] = step

    def work():
        try:
            result = run_pull_request(
                pull_url,
                PROOF_RECEIPT,
                "python3 -m pytest -q",
                on_step=set_step,
            )
            with PR_LOCK:
                PR_JOBS[job_id]["phase"] = "done"
                PR_JOBS[job_id]["proven"] = result["proven"]
        except Exception as error:
            with PR_LOCK:
                PR_JOBS[job_id]["phase"] = "failed"
                PR_JOBS[job_id]["reason"] = str(error)[:500]

    with PR_LOCK:
        if any(job["phase"] == "running" for job in PR_JOBS.values()):
            return False
        PR_JOBS[job_id] = {
            "phase": "running",
            "step": "queued",
            "pull_request_url": pull_url,
            "proven": None,
            "reason": None,
        }
    threading.Thread(target=work, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if path == "/api/status":
            with LOCK:
                self.send_json(dict(STATUS))
            return
        if path == "/api/fixture":
            self.send_json(fixture_payload())
            return
        if path == "/api/pr-proof/latest":
            if not os.path.exists(PROOF_RECEIPT):
                self.send_json({"receipt": None})
                return
            with open(PROOF_RECEIPT, encoding="utf-8") as handle:
                self.send_json({"receipt": json.load(handle)})
            return
        if path == "/api/pr-proof/status":
            job_id = parse_qs(url.query).get("id", [""])[0]
            if not re.fullmatch(r"[a-f0-9]{32}", job_id):
                self.send_json({"error": "invalid job id"}, 400)
                return
            with PR_LOCK:
                job = PR_JOBS.get(job_id)
                if not job:
                    self.send_json({"error": "proof job not found"}, 404)
                    return
                self.send_json({"id": job_id, **job})
            return
        if path not in ("/", "/app.html"):
            self.send_error(404)
            return
        body = PAGE_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/pr-proof":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise ValueError("request body must be under 4 KB")
                payload = json.loads(self.rfile.read(length))
                pull_url = payload.get("pull_request_url", "")
                parse_pull_request_url(pull_url)
            except (ValueError, json.JSONDecodeError, AttributeError) as error:
                self.send_json({"ok": False, "reason": str(error)}, 400)
                return
            job_id = uuid.uuid4().hex
            if not start_pr_job(job_id, pull_url):
                self.send_json({"ok": False, "reason": "A proof is already running"}, 409)
                return
            self.send_json({"ok": True, "id": job_id}, 202)
            return
        if path != "/api/run":
            self.send_error(404)
            return
        with LOCK:
            if STATUS["phase"] == "running":
                self.send_json({"ok": False, "reason": "already running"}, 409)
                return
            STATUS["phase"] = "running"
            STATUS["step"] = "suite"
            STATUS["code"] = None
            STATUS["state"] = {"reason": "running", "kill_failed": False, "restored_passed": False}
        threading.Thread(target=run_job, daemon=True).start()
        self.send_json({"ok": True})


def hydrate():
    path = os.path.join(ROOT, "runs", "latest.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if not (state.get("kill_failed") and state.get("restored_passed")):
        return
    STATUS["phase"] = "done"
    STATUS["code"] = 0
    STATUS["step"] = "done"
    STATUS["state"] = state


def main():
    hydrate()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
