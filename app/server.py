"""Local web UI for the onboarding flow (v2.0.0, ADR-0010).

A thin layer over app/onboarding.py: the same plan, approval and run as the
console (ADR-0009). The server runs in the coordinator process, so the exchange
and approval secrets stay in the Provisioner in memory. The browser receives no
secret and no key.

Run from the project root: python -m app.server [--port 8110]

Every request must carry the Host header for this port (127.0.0.1 or localhost).
Every POST also needs the per-start CSRF token, a matching Origin and a JSON
body of at most 16 KB. Static files come from a fixed table, so no path from the
browser is ever used as a file path.
"""

import argparse
import dataclasses
import json
import re
import secrets
import socketserver
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import provision
from app.onboarding import (DEFAULT_REQUEST_TEXTS, DOMAINS, InputError,
                            execute_plan, parse_request, validate_subject)
from coordinator.planner import build_plan, plan_hash, warnings
from coordinator.registry import Registry, RegistryError
from coordinator.run import new_run_id, post_execute
from ledger.reconstruct import LIMITS, reconstruct
from provision import ProvisionError

HOST = "127.0.0.1"
DEFAULT_PORT = 8110
MAX_BODY_BYTES = 16 * 1024
PENDING_TTL_SECONDS = 300
STATIC_DIR = Path(__file__).resolve().parent / "static"
CSRF_PLACEHOLDER = b"{{CSRF_TOKEN}}"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
DOMAIN_ROUTE = re.compile(r"/api/domains/(%s)/(start|stop)" % "|".join(DOMAINS))
APPROVE_ROUTE = re.compile(r"/api/plans/([0-9a-f]{64})/approve")
RUN_ROUTE = re.compile(r"/api/runs/([0-9a-f]{16})")


class UiError(Exception):
    """A request the UI refuses. status is the HTTP status, code is machine-readable."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class UiState:
    """Everything the UI does, with no HTTP in it. The tests call this directly.

    One run or domain change at a time: approve, start and stop share a lock
    that is taken without waiting, so a second request gets 409 at once.
    """

    def __init__(self, provisioner, *, clock=time.time, post=post_execute,
                 fetch=None, csrf_token=None):
        self.provisioner = provisioner
        self.clock = clock
        self.post = post
        self.fetch = fetch
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self._busy = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._reports = {}

    def status(self):
        domains = {
            name: {"running": self.provisioner.running(name),
                   "port": self.provisioner.ports.get(name)}
            for name in DOMAINS
        }
        return {"domains": domains, "default_requests": list(DEFAULT_REQUEST_TEXTS)}

    def start_domain(self, name):
        with self._busy_lock():
            if self.provisioner.running(name):
                raise UiError(409, "already_running", "%s is already running" % name)
            try:
                self.provisioner.start_domain(name)
                self.provisioner.check_domain_health(name)
            except ProvisionError as exc:
                self.provisioner.stop_domain(name)
                raise UiError(503, "domain_not_started", str(exc))
        return self.status()

    def stop_domain(self, name):
        with self._busy_lock():
            if not self.provisioner.running(name):
                raise UiError(409, "not_running", "%s is not running" % name)
            self.provisioner.stop_domain(name)
        return self.status()

    def make_plan(self, subject, request_texts):
        """Validate the input, refresh every domain, and keep the plan for approval."""
        try:
            validate_subject(subject)
            requests = [parse_request(text) for text in request_texts]
        except (InputError, TypeError, AttributeError) as exc:
            raise UiError(400, "bad_input", str(exc))
        down = [name for name in DOMAINS if not self.provisioner.running(name)]
        if down:
            raise UiError(409, "domains_down",
                          "start these domains first: " + ", ".join(down))
        registry = Registry(dict(self.provisioner.ports), self.clock, fetch=self.fetch)
        try:
            registry.refresh_all()
            plan = build_plan(registry, subject, requests)
        except RegistryError as exc:
            raise UiError(503, "domain_unavailable", str(exc))
        except (ValueError, KeyError) as exc:
            raise UiError(400, "plan_refused", str(exc))
        digest = plan_hash(plan)
        now = self.clock()
        with self._pending_lock:
            self._pending = {key: entry for key, entry in self._pending.items()
                             if entry[1] > now}
            self._pending[digest] = (plan, now + PENDING_TTL_SECONDS)
        return {"plan": plan, "plan_hash": digest, "warnings": warnings(plan),
                "expires_at": now + PENDING_TTL_SECONDS}

    def approve(self, digest):
        """Approve and run the plan the user saw, identified by its hash."""
        with self._busy_lock():
            plan = self._take_pending(digest)
            if plan_hash(plan) != digest:
                raise UiError(409, "plan_changed", "the stored plan differs from the hash")
            down = [name for name in DOMAINS if not self.provisioner.running(name)]
            if down:
                raise UiError(409, "domains_down",
                              "start these domains first: " + ", ".join(down))
            run_id = new_run_id()
            report = execute_plan(self.provisioner, plan, post=self.post,
                                  clock=self.clock, run_id=run_id)
            self._reports[run_id] = report
        return _report_view(report)

    def run_view(self, run_id):
        """The run report, if this server ran it, and the per-domain rebuild."""
        rebuild = reconstruct(run_id, self.provisioner.state_dir)
        report = self._reports.get(run_id)
        seen = any(evidence.outcomes or evidence.rejected
                   for evidence in rebuild.domains)
        if report is None and not seen:
            raise UiError(404, "unknown_run", "no run with this id")
        view = {
            "run_id": run_id,
            "report": _report_view(report) if report else None,
            "domains": [_domain_view(evidence) for evidence in rebuild.domains],
            "chain_ok": rebuild.chain_ok,
            "limits": list(LIMITS),
        }
        return view

    def _take_pending(self, digest):
        with self._pending_lock:
            entry = self._pending.pop(digest, None)
        if entry is None or entry[1] <= self.clock():
            raise UiError(404, "plan_not_pending",
                          "no pending plan with this hash; make a new plan")
        return entry[0]

    def _busy_lock(self):
        return _BusyGuard(self._busy)


class _BusyGuard:
    def __init__(self, lock):
        self._lock = lock

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            raise UiError(409, "busy", "a run or a domain change is already in progress")

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()


def _report_view(report):
    return {
        "run_id": report.run_id,
        "status": report.status,
        "abort_code": report.abort_code,
        "exchange_count": report.exchange_count,
        "rows": [dataclasses.asdict(row) for row in report.rows],
    }


def _domain_view(evidence):
    return {
        "domain": evidence.domain,
        "chain_ok": evidence.chain_ok,
        "chain_error": evidence.chain_error,
        "outcomes": dict(evidence.outcomes),
        "rejected": evidence.rejected,
    }


class UiHandler(BaseHTTPRequestHandler):
    server_version = "OnboardingUI"
    sys_version = ""

    def log_message(self, format, *args):
        """Quiet: the transcript script and the tests read the responses."""

    @property
    def ui(self):
        return self.server.ui

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        try:
            self._check_host()
            path = urlsplit(self.path).path
            if method == "GET":
                self._get(path)
            else:
                self._post(path)
        except UiError as exc:
            self._send_json(exc.status, {"error": exc.code, "message": exc.message})
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "internal",
                                  "message": "the UI hit an unexpected error"})

    def _get(self, path):
        if path in STATIC_ROUTES:
            return self._send_static(path)
        if path == "/api/status":
            return self._send_json(200, self.ui.status())
        match = RUN_ROUTE.fullmatch(path)
        if match:
            return self._send_json(200, self.ui.run_view(match.group(1)))
        raise UiError(404, "not_found", "no such page")

    def _post(self, path):
        self._check_origin()
        self._check_csrf()
        body = self._read_json()
        match = DOMAIN_ROUTE.fullmatch(path)
        if match:
            name, action = match.groups()
            if action == "start":
                return self._send_json(200, self.ui.start_domain(name))
            return self._send_json(200, self.ui.stop_domain(name))
        if path == "/api/plans":
            return self._send_json(200, self.ui.make_plan(body.get("subject"),
                                                          body.get("requests")))
        match = APPROVE_ROUTE.fullmatch(path)
        if match:
            return self._send_json(200, self.ui.approve(match.group(1)))
        raise UiError(404, "not_found", "no such action")

    def _check_host(self):
        port = self.server.server_address[1]
        allowed = {"%s:%d" % (HOST, port), "localhost:%d" % port}
        if self.headers.get("Host") not in allowed:
            raise UiError(403, "bad_host", "the Host header is not this UI")

    def _check_origin(self):
        port = self.server.server_address[1]
        allowed = {"http://%s:%d" % (HOST, port), "http://localhost:%d" % port}
        if self.headers.get("Origin") not in allowed:
            raise UiError(403, "bad_origin", "the Origin header is not this UI")

    def _check_csrf(self):
        sent = self.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(sent.encode("utf-8"),
                                      self.ui.csrf_token.encode("ascii")):
            raise UiError(403, "bad_csrf", "the CSRF token is missing or wrong")

    def _read_json(self):
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            raise UiError(415, "not_json", "the body must be application/json")
        if self.headers.get("Transfer-Encoding"):
            raise UiError(411, "length_required", "send a Content-Length header")
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise UiError(411, "length_required", "send a Content-Length header")
        if not length_text.isdigit():
            raise UiError(400, "bad_length", "Content-Length is not a number")
        length = int(length_text)
        if length > MAX_BODY_BYTES:
            raise UiError(413, "too_large", "the body is over 16 KB")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise UiError(400, "bad_json", "the body is not valid JSON")
        if not isinstance(body, dict):
            raise UiError(400, "bad_json", "the body must be a JSON object")
        return body

    def _send_static(self, path):
        name, content_type = STATIC_ROUTES[path]
        data = (STATIC_DIR / name).read_bytes()
        if name == "index.html":
            data = data.replace(CSRF_PLACEHOLDER,
                                self.ui.csrf_token.encode("ascii"))
        self._send(200, content_type, data, csp=True)

    def _send_json(self, status, obj):
        data = json.dumps(obj, sort_keys=True).encode("ascii")
        self._send(status, "application/json; charset=utf-8", data)

    def _send(self, status, content_type, data, csp=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if csp:
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)


class UiServer(ThreadingHTTPServer):
    """Binds 127.0.0.1 only, and never does a reverse DNS lookup on the address."""
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, ui):
        super().__init__((HOST, port), UiHandler)
        self.ui = ui

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = HOST
        self.server_port = self.server_address[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local onboarding web UI on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    provisioner = provision.Provisioner()
    server = UiServer(args.port, UiState(provisioner))
    port = server.server_address[1]
    print("onboarding UI on http://%s:%d/" % (HOST, port))
    print("start the domains from the page; Ctrl-C stops the UI and any running domains")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        provisioner.stop()
        print("all domains stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
