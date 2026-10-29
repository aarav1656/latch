import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from run import FIXTURE, SOURCE_NAME, SUITE_NAME, execute, render_screen
from screen.page import PAGE_HTML

ROOT = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT = 4173

STATUS = {"phase": "idle", "step": None, "state": None}
LOCK = threading.Lock()


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
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            with LOCK:
                self.send_json(dict(STATUS))
            return
        if path == "/api/fixture":
            self.send_json(fixture_payload())
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
        if self.path.split("?", 1)[0] != "/api/run":
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
