"""Latch web: paste a GitHub PR URL, get the issue-anchored proof receipt.

Stdlib-only HTTP server. Run from the repo root:  python3 -m latch.web.app
"""

import json
import mimetypes
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .sandbox import SandboxConfig, drop_dumpable
from .service import ApiError, Config, Service
from .store import Store, make_envelope

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent.parent
STATIC_DIR = WEB_DIR / "static"
EXAMPLE_RECEIPT = REPO_ROOT / "latch" / "runs" / "click-3298.json"
MAX_BODY = 4096
SEGMENT = r"[A-Za-z0-9_.-]{1,100}"
RECEIPT_PATH = re.compile(rf"^/(?:r|api/receipt)/({SEGMENT})/({SEGMENT})/(\d{{1,9}})/?$")
PROOF_PATH = re.compile(r"^/api/(?:proof|loop)/([0-9a-f]{32})(/events)?$")
CSP = (
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def boot_json(payload):
    text = json.dumps(payload, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


EVAL_PENDING = "Eval pending: latch/runs/eval-summary.json has not been committed yet."


def eval_root():
    return Path(os.environ.get("LATCH_EVAL_ROOT") or REPO_ROOT)


def _load_object(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def eval_payload():
    """The eval page's data: the committed summary plus the featured wrong-fix receipt, or an honest 'pending'."""
    root = eval_root()
    summary = _load_object(root / "latch" / "runs" / "eval-summary.json")
    if summary is None:
        return {"available": False, "reason": EVAL_PENDING}
    featured = None
    ref = summary.get("featured_wrong_fix_receipt")
    if isinstance(ref, str) and ref and "\x00" not in ref:
        allowed = (root / "latch" / "runs" / "eval").resolve()
        try:
            target = (root / ref).resolve()
        except (OSError, RuntimeError, ValueError):
            target = None
        if target is not None and allowed in target.parents and target.is_file():
            loaded = _load_object(target)
            if loaded is not None:
                if isinstance(loaded.get("receipt"), dict) and isinstance(loaded.get("meta"), dict):
                    featured = loaded
                else:
                    featured = make_envelope(loaded, "recorded", extra={"recorded_run": ref})
    return {"available": True, "summary": summary, "featured": featured}


def build_service(data_dir=None, **kwargs):
    data_dir = Path(data_dir or os.environ.get("LATCH_DATA") or WEB_DIR / ".data")
    store = Store(data_dir, seed_receipt_path=EXAMPLE_RECEIPT)
    return Service(store, data_dir, **kwargs)


def make_handler(service, trust_proxy=True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LatchWeb"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        # -- plumbing -------------------------------------------------------
        def log_message(self, fmt, *args):
            line = re.sub(r"\?\S*", "", fmt % args)  # never log query strings
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), line))

        def client_ip(self):
            if trust_proxy:
                # the last entry is the one appended by the nearest proxy (not client-forgeable)
                parts = [p.strip() for p in self.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
                if parts:
                    return parts[-1]
            return self.client_address[0]

        def _headers(self, status, content_type, length=None, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def send_json(self, status, payload, extra=None):
            body = json.dumps(payload).encode()
            self._headers(status, "application/json; charset=utf-8", len(body), {"Cache-Control": "no-store", **(extra or {})})
            self.wfile.write(body)

        def send_error_json(self, error):
            extra = {"Retry-After": str(error.extra["retry_after"])} if "retry_after" in error.extra else None
            self.send_json(error.status, error.payload(), extra)

        def send_bytes(self, status, content_type, body, cache="no-cache"):
            self._headers(status, content_type, len(body), {"Cache-Control": cache})
            self.wfile.write(body)

        def _redirect(self, location):
            self._headers(302, "text/plain; charset=utf-8", 0, {"Location": location, "Cache-Control": "no-store"})

        # -- pages --------------------------------------------------------
        def page(self, initial=None, status=200, notice=None):
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            boot = {
                "example": service.store.example, "config": service.public_config(), "initial": initial,
                "notice": notice, "recent": service.store.list_recent(),
            }
            html = html.replace("__LATCH_BOOT__", boot_json(boot))
            self.send_bytes(status, "text/html; charset=utf-8", html.encode())

        def html_page(self, name):
            target = STATIC_DIR / name
            if not target.is_file():
                return self.send_json(404, {"error": {"code": "not_found", "message": "Not found"}})
            self.send_bytes(200, "text/html; charset=utf-8", target.read_bytes())

        def static_file(self, name):
            target = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file() or target.name == "index.html":
                return self.send_json(404, {"error": {"code": "not_found", "message": "Not found"}})
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self.send_bytes(200, ctype, target.read_bytes(), cache="public, max-age=300")

        # -- routing ----------------------------------------------------------
        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path in ("/", "/index.html"):
                    return self.page()
                if path in ("/eval", "/eval/"):
                    return self.html_page("eval.html")
                if path in ("/ship", "/ship/"):
                    return self.html_page("ship.html")
                if path == "/api/recent":
                    return self.send_json(200, {"items": service.store.list_recent()})
                if path == "/api/eval":
                    return self.send_json(200, eval_payload())
                if path == "/healthz":
                    return self.send_json(200, {"ok": True, "live": service.live_state()["enabled"]})
                if path == "/api/config":
                    return self.send_json(200, service.public_config())
                if path == "/api/example":
                    example = service.store.example
                    if not example:
                        return self.send_json(404, {"error": {"code": "no_example", "message": "No example receipt is installed."}})
                    return self.send_json(200, example)
                if path == "/api/loop/example":
                    example = service.loop_example()
                    if not example:
                        return self.send_json(404, {"error": {"code": "no_example", "message": "No recorded fix loop run is installed."}})
                    return self.send_json(200, example)
                if path.startswith("/static/"):
                    return self.static_file(path[len("/static/"):])
                match = RECEIPT_PATH.match(path)
                if match:
                    repo, number = f"{match.group(1)}/{match.group(2)}", int(match.group(3))
                    envelope = service.store.get_pr(repo, number)
                    if path.startswith("/api/receipt/"):
                        if not envelope:
                            return self.send_json(404, {"error": {"code": "no_receipt", "message": "No saved receipt for this pull request."}})
                        return self.send_json(200, envelope)
                    if not envelope:
                        pr_number = service.store.pr_for_issue(repo, number)
                        if pr_number and pr_number != number:
                            return self._redirect(f"/r/{repo}/{pr_number}")
                        return self.page(None, 404, f"No saved receipt for {repo}#{number} yet. Paste its URL above to run one.")
                    return self.page(envelope)
                match = PROOF_PATH.match(path)
                if match:
                    job = service.get_job(match.group(1))
                    if not job:
                        return self.send_json(404, {"error": {"code": "unknown_job", "message": "Unknown or expired job."}})
                    if match.group(2):
                        return self.stream(job)
                    return self.send_json(200, service.job_json(job))
                return self.send_json(404, {"error": {"code": "not_found", "message": "Not found"}})
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/api/proof", "/api/loop"):
                return self.send_json(404, {"error": {"code": "not_found", "message": "Not found"}})
            try:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    raise ApiError("bad_request", 413, "Request body too large.")
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError
                except ValueError:
                    raise ApiError("bad_request", 400, "Send JSON like {\"pull_request_url\": \"https://github.com/owner/repo/pull/1\"}.")
                if path == "/api/loop":
                    result = service.submit_loop(self.client_ip())
                    return self.send_json(202, result)
                result = service.submit(payload.get("pull_request_url"), self.client_ip(), force=bool(payload.get("live")))
                self.send_json(200 if result.get("cached") else 202, result)
            except ApiError as error:
                self.send_error_json(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:  # fail closed, never leak a traceback
                sys.stderr.write(f"unhandled: {error!r}\n")
                self.send_json(500, {"error": {"code": "internal_error", "message": "Unexpected server error."}})

        # -- SSE ----------------------------------------------------------------
        def stream(self, job):
            self._headers(200, "text/event-stream; charset=utf-8", None, {"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "close"})
            try:
                last = int(self.headers.get("Last-Event-ID") or 0)
            except ValueError:
                last = 0
            try:
                self.wfile.write(b"retry: 3000\n\n")
                while True:
                    with job.cond:
                        if last >= len(job.events) and not job.terminal:
                            job.cond.wait(timeout=5)
                        pending = job.events[last:]
                        done = job.terminal
                    for event in pending:
                        last = event["id"]
                        data = json.dumps(event["data"])
                        self.wfile.write(f"id: {event['id']}\nevent: {event['event']}\ndata: {data}\n\n".encode())
                    if not pending and not done:
                        if job.status == "queued":
                            self.wfile.write(f"event: queue\ndata: {{\"position\": {service.position(job)}}}\n\n".encode())
                        else:
                            self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    if done and last >= len(job.events):
                        return
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return

    return Handler


def main():
    dumpable_dropped = drop_dumpable()
    port = int(os.environ.get("PORT", "8080"))
    service = build_service()
    trust_proxy = os.environ.get("LATCH_TRUST_PROXY", "1") != "0"
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service, trust_proxy))
    server.daemon_threads = True
    live = service.live_state()
    print(
        f"latch-web listening on 0.0.0.0:{port} data={service.store.root} live={live['enabled']}"
        f"{'' if live['enabled'] else ' (' + live['reason'] + ')'} daily_cap={service.config.daily_cap} "
        f"rate={service.config.rate_limit}/{service.config.rate_window}s non_dumpable={dumpable_dropped}",
        flush=True,
    )
    isolation = service.sandbox_status()
    print(f"sandbox: {isolation['description']}", flush=True)
    if isolation["warning"]:
        sys.stderr.write(f"WARNING: {isolation['warning']}\n")
        sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
