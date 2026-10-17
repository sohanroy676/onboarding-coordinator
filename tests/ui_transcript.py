"""Run the web UI for real and save the HTTP exchange as traces/v3-2-ui-transcript.txt.

Run from the project root: python -m tests.ui_transcript

This is a recorder, not a unit test (its name does not match test*.py). It starts
the three real domains on the demo ports 8101 to 8103 and the UI on 127.0.0.1:8110,
sends every request with plain HTTP, and writes what the server returned. Each
expected status is checked, and the exit code is 1 if one is not what the code
returned. The per-start CSRF token is replaced with <csrf-token> in the saved
text, because it is a secret of this server start and is not needed to read the trace.
"""

import http.client
import json
import sys
import threading
from pathlib import Path

import provision
from app.onboarding import DEFAULT_REQUEST_TEXTS, DOMAINS
from app.server import HOST, UiServer, UiState

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / "traces" / "v3-2-ui-transcript.txt"
UI_PORT = 8110
SUBJECT = "new.hire@example.test"
REDACTED = "<csrf-token>"


class Recorder:
    def __init__(self, port, token):
        self.port = port
        self.host = "%s:%d" % (HOST, port)
        self.origin = "http://" + self.host
        self.token = token
        self.lines = []
        self.failures = []
        self.step = 0

    def exchange(self, title, method, path, expect, payload=None, override=None):
        """Send one request, record it and its response, return the parsed body."""
        self.step += 1
        body = b""
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        headers = {"Host": self.host}
        if method == "POST":
            headers.update({
                "Origin": self.origin,
                "X-CSRF-Token": self.token,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            })
        headers.update(override or {})
        headers = {name: value for name, value in headers.items() if value is not None}
        self.lines.append("=== %d. %s ===" % (self.step, title))
        self.lines.append("%s %s HTTP/1.1" % (method, path))
        for name, value in headers.items():
            self.lines.append("%s: %s" % (name, value))
        if body:
            self.lines.append("")
            self.lines.append(self._text(body))
        status, reply_headers, data = self._send(method, path, headers, body)
        self.lines.append("")
        self.lines.append("--> HTTP %d" % status)
        if reply_headers.startswith("application/json"):
            parsed = json.loads(data.decode("utf-8"))
            self.lines.append(json.dumps(parsed, indent=2, sort_keys=True))
        else:
            parsed = None
            self.lines.append("(%s, %d bytes)" % (reply_headers, len(data)))
        if status != expect:
            self.failures.append("%s: expected %d, got %d" % (title, expect, status))
            self.lines.append("!! expected HTTP %d" % expect)
        self.lines.append("")
        return parsed

    def _send(self, method, path, headers, body):
        conn = http.client.HTTPConnection(HOST, self.port, timeout=30)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers.items():
                conn.putheader(name, value)
            conn.endheaders()
            if body:
                conn.send(body)
            response = conn.getresponse()
            data = response.read()
            content_type = response.getheader("Content-Type", "")
            return response.status, content_type, data
        finally:
            conn.close()

    def _text(self, body):
        try:
            return json.dumps(json.loads(body.decode("utf-8")), indent=2, sort_keys=True)
        except ValueError:
            return body.decode("ascii", "replace")

    def note(self, text):
        self.lines.append("# " + text)
        self.lines.append("")


def run_steps(rec, ui):
    rec.note("UI on 127.0.0.1:%d, domains on 8101 (hr), 8102 (it), 8103 (facilities)"
             % UI_PORT)
    rec.exchange("bad Host header is refused", "GET", "/", 403,
                 override={"Host": "evil.test:%d" % UI_PORT})
    rec.exchange("the page loads with the CSRF token for this start", "GET", "/", 200)
    rec.exchange("status before any domain is started", "GET", "/api/status", 200)
    rec.exchange("a plan is refused while the domains are down", "POST", "/api/plans",
                 409, {"subject": SUBJECT, "requests": list(DEFAULT_REQUEST_TEXTS)})
    for name in DOMAINS:
        rec.exchange("start %s" % name, "POST", "/api/domains/%s/start" % name, 200, {})
    rec.exchange("starting a running domain is refused", "POST",
                 "/api/domains/hr/start", 409, {})
    rec.exchange("a POST without the CSRF token is refused", "POST", "/api/plans", 403,
                 {"subject": SUBJECT, "requests": ["hr:create_record"]},
                 override={"X-CSRF-Token": None})
    default_plan = rec.exchange("make the plan (six default steps)", "POST",
                                "/api/plans", 200,
                                {"subject": SUBJECT,
                                 "requests": list(DEFAULT_REQUEST_TEXTS)})
    clean = rec.exchange("approve and run the default plan, with the hash the user saw",
                         "POST", "/api/plans/%s/approve" % default_plan["plan_hash"],
                         200, {})
    rec.exchange("the same plan cannot be approved twice", "POST",
                 "/api/plans/%s/approve" % default_plan["plan_hash"], 404, {})
    warned_plan = rec.exchange("make a plan with a will_not step (warning shown)",
                               "POST", "/api/plans", 200,
                               {"subject": SUBJECT,
                                "requests": ["hr:create_record",
                                             "it:grant_admin_access"]})
    rec.exchange("approve and run the warned plan (partial, one refusal)", "POST",
                 "/api/plans/%s/approve" % warned_plan["plan_hash"], 200, {})
    rec.exchange("per-domain rebuild of the clean run", "GET",
                 "/api/runs/%s" % clean["run_id"], 200)
    rec.exchange("a traversal path is not found", "GET", "/static/../server.py", 404)
    rec.exchange("stop facilities", "POST", "/api/domains/facilities/stop", 200, {})
    rec.exchange("a stopped domain cannot be stopped again", "POST",
                 "/api/domains/facilities/stop", 409, {})


def main():
    provisioner = provision.Provisioner()
    ui = UiState(provisioner)
    server = UiServer(UI_PORT, ui)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rec = Recorder(UI_PORT, ui.csrf_token)
    try:
        run_steps(rec, ui)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        provisioner.stop()
        rec.note("all domains stopped")
    rec.lines = [line.replace(ui.csrf_token, REDACTED) for line in rec.lines]
    text = "\n".join(rec.lines) + "\n"
    TRACE.parent.mkdir(exist_ok=True)
    TRACE.write_text(text, encoding="ascii")
    sys.stdout.write(text)
    for failure in rec.failures:
        sys.stdout.write("FAILED: " + failure + "\n")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
