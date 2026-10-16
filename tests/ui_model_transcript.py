"""Run the web UI with the real model planner and save the HTTP exchange.

Run from the project root: python -m tests.ui_model_transcript

This is a recorder, not a unit test (its name does not match test*.py). It starts the
three real domains on the demo ports 8101 to 8103 and the UI on 127.0.0.1:8110, then
makes one plan with planner "model": the UI reads the key from the git-ignored .env
(ADR-0011) and calls Groq once. The reply varies from run to run, so the trace is a
single run, not reproducible byte for byte. The key is never in a request or a
response; the recorder stops with an error if "gsk_" or the key name shows up in the
saved text. The per-start CSRF token is replaced with <csrf-token>.
"""

import sys
import threading
from pathlib import Path

import provision
from app.onboarding import DOMAINS
from app.server import UiServer, UiState
from tests.ui_transcript import REDACTED, SUBJECT, UI_PORT, Recorder

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / "traces" / "v3-1-ui-model-transcript.txt"
REQUEST_TEXT = "New engineer. Needs an HR record, a laptop, an IT account and a badge."
ADMIN_TEXT = "New engineer needs a laptop and admin access on their machine."
HEADER = (
    "# Single live run against Groq through the web UI. Not reproducible byte for byte.",
    "# The API key is not in this file; the browser never receives it.",
)


def run_steps(rec):
    rec.note("UI on 127.0.0.1:%d, domains on 8101 (hr), 8102 (it), 8103 (facilities)"
             % UI_PORT)
    rec.exchange("the page loads with the CSRF token for this start", "GET", "/", 200)
    for name in DOMAINS:
        rec.exchange("start %s" % name, "POST", "/api/domains/%s/start" % name, 200, {})
    rec.exchange("an unknown planner is refused", "POST", "/api/plans", 400,
                 {"subject": SUBJECT, "planner": "grok", "requests": ["hr:create_record"]})
    rec.exchange("requests cannot be combined with the model planner", "POST",
                 "/api/plans", 400,
                 {"subject": SUBJECT, "planner": "model",
                  "requests": ["hr:create_record"], "request_text": REQUEST_TEXT})
    rec.exchange("empty request text is refused before any model call", "POST",
                 "/api/plans", 400,
                 {"subject": SUBJECT, "planner": "model", "request_text": " "})
    plan = rec.exchange("make the plan with the model planner (one Groq call)", "POST",
                        "/api/plans", 200,
                        {"subject": SUBJECT, "planner": "model",
                         "request_text": REQUEST_TEXT})
    if plan is None or "plan_hash" not in plan:
        return
    run = rec.exchange("approve and run the plan, with the hash the user saw", "POST",
                       "/api/plans/%s/approve" % plan["plan_hash"], 200, {})
    if run is not None and "run_id" in run:
        rec.exchange("per-domain rebuild of the run", "GET",
                     "/api/runs/%s" % run["run_id"], 200)
    admin = rec.exchange("make a plan from a request for admin access (one Groq call)",
                         "POST", "/api/plans", 200,
                         {"subject": SUBJECT, "planner": "model",
                          "request_text": ADMIN_TEXT})
    if admin is None or "plan_hash" not in admin:
        return
    rec.exchange("approve and run it: the domain refuses what it will not do", "POST",
                 "/api/plans/%s/approve" % admin["plan_hash"], 200, {})


def main():
    provisioner = provision.Provisioner()
    ui = UiState(provisioner)
    server = UiServer(UI_PORT, ui)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rec = Recorder(UI_PORT, ui.csrf_token)
    try:
        run_steps(rec)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        provisioner.stop()
        rec.note("all domains stopped")
    lines = [line.replace(ui.csrf_token, REDACTED) for line in rec.lines]
    text = "\n".join(list(HEADER) + [""] + lines) + "\n"
    if "gsk_" in text or "GROQ_API_KEY" in text:
        sys.stdout.write("FAILED: the key or its name appears in the transcript; not saved\n")
        return 1
    TRACE.parent.mkdir(exist_ok=True)
    TRACE.write_text(text, encoding="ascii")
    sys.stdout.write(text)
    for failure in rec.failures:
        sys.stdout.write("FAILED: " + failure + "\n")
    return 1 if rec.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
