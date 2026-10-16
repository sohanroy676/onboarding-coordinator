"""The web UI (app/server.py): security checks, the flow over HTTP, and a live run.

The HTTP tests bind port 0, use an injected clock and a fake provisioner, and
never sleep. The live class starts the real domains on ephemeral ports.
"""

import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

import provision
from app.onboarding import DEFAULT_REQUEST_TEXTS, DOMAINS
from app.server import (HOST, MAX_BODY_BYTES, PENDING_TTL_SECONDS, STATIC_DIR,
                        STATIC_ROUTES, UiServer, UiState)
from app.model_planner import ModelPlannerError
from provision import ProvisionError
from tests.helpers import FakeClock
from tests.test_unit_app_onboarding import PORTS, FakePost, fake_fetch

TOKEN = "csrf-fixture"
EPHEMERAL = {"hr": 0, "it": 0, "facilities": 0}
SUBJECT = "new.hire@example.test"
RUN_ID = re.compile(r"[0-9a-f]{16}")
PLAN_HASH = re.compile(r"[0-9a-f]{64}")
TRAVERSAL_PATHS = (
    "/static/../server.py",
    "/static/..%2Fserver.py",
    "/static/%2e%2e/server.py",
    "/static/..%5cserver.py",
    "/static/..\\server.py",
    "/static//etc/passwd",
    "/static/server.py",
    "/static/app.css/..",
    "/static/%00app.css",
)


class FakeProvisioner:
    """Stands in for provision.Provisioner: records which domains are up."""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.ports = dict(PORTS)
        self.exchange_secret = "unit-exchange-secret"
        self.approval_secret = "unit-approval-secret"
        self.up = set()
        self.health_error = None

    def running(self, name):
        return name in self.up

    def start_domain(self, name):
        if name in self.up:
            raise ProvisionError("%s is already running" % name)
        self.up.add(name)

    def check_domain_health(self, name):
        if self.health_error:
            raise self.health_error

    def stop_domain(self, name):
        self.up.discard(name)

    def stop(self):
        self.up.clear()


def serve(ui):
    """Start the UI on port 0 in a thread; return the server and its thread."""
    server = UiServer(0, ui)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class FakeModel:
    """A model client that returns a fixed reply or raises; counts the calls."""

    model = "ui-fake"

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def propose(self, system_prompt, user_text):
        self.calls.append((system_prompt, user_text))
        if self.error:
            raise self.error
        return self.reply


def proposal(*pairs):
    return json.dumps({"requests": [{"domain": d, "action": a} for d, a in pairs]})


def refusing_factory():
    raise AssertionError("the model client must not be built in this mode")


class HttpClient:
    """Raw HTTP so the tests can send a bad Host, Origin or length on purpose."""

    def __init__(self, port, token):
        self.port = port
        self.host = "%s:%d" % (HOST, port)
        self.origin = "http://" + self.host
        self.token = token
        self.bodies = []

    def headers(self, method, body=b"", override=None):
        headers = {"Host": self.host}
        if method == "POST":
            headers.update({
                "Origin": self.origin,
                "X-CSRF-Token": self.token,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            })
        headers.update(override or {})
        return {name: value for name, value in headers.items() if value is not None}

    def send(self, method, path, headers, body=b""):
        conn = http.client.HTTPConnection(HOST, self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers.items():
                conn.putheader(name, value)
            conn.endheaders()
            if body:
                conn.send(body)
            response = conn.getresponse()
            data = response.read()
            self.bodies.append(data)
            return response.status, dict(response.getheaders()), data
        finally:
            conn.close()

    def call(self, method, path, payload=None, override=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        status, headers, data = self.send(method, path,
                                          self.headers(method, body, override), body)
        if headers.get("Content-Type", "").startswith("application/json"):
            return status, json.loads(data.decode("utf-8"))
        return status, data


class UiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.provisioner = FakeProvisioner(tmp.name)
        self.clock = FakeClock()
        self.post = FakePost()
        self.model = FakeModel(
            reply=proposal(("hr", "create_record"), ("it", "assign_laptop")))
        self.ui = UiState(self.provisioner, clock=self.clock, post=self.post,
                          fetch=fake_fetch, csrf_token=TOKEN,
                          client_factory=lambda: self.model)
        self.server, thread = serve(self.ui)
        self.addCleanup(self.stop_server, thread)
        self.http = HttpClient(self.server.server_address[1], TOKEN)

    def stop_server(self, thread):
        self.server.shutdown()
        self.server.server_close()
        thread.join()

    def start_all(self):
        for name in DOMAINS:
            status, _body = self.http.call("POST", "/api/domains/%s/start" % name, {})
            self.assertEqual(status, 200)

    def make_plan(self, requests=None):
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT,
            "requests": requests or list(DEFAULT_REQUEST_TEXTS),
        })
        self.assertEqual(status, 200, body)
        return body


class HostCheckTests(UiCase):
    def test_localhost_host_is_accepted(self):
        status, _ = self.http.call("GET", "/api/status",
                                   override={"Host": "localhost:%d" % self.http.port})
        self.assertEqual(status, 200)

    def test_other_host_name_is_refused(self):
        status, body = self.http.call("GET", "/api/status",
                                      override={"Host": "evil.test:%d" % self.http.port})
        self.assertEqual((status, body["error"]), (403, "bad_host"))

    def test_dns_rebinding_style_host_is_refused(self):
        status, body = self.http.call(
            "GET", "/api/status",
            override={"Host": "127.0.0.1.evil.test:%d" % self.http.port})
        self.assertEqual((status, body["error"]), (403, "bad_host"))

    def test_host_with_another_port_is_refused(self):
        status, body = self.http.call("GET", "/api/status",
                                      override={"Host": "127.0.0.1:8110"})
        self.assertEqual((status, body["error"]), (403, "bad_host"))

    def test_missing_host_is_refused(self):
        status, body = self.http.call("GET", "/api/status", override={"Host": None})
        self.assertEqual((status, body["error"]), (403, "bad_host"))

    def test_bad_host_is_refused_on_a_post_even_with_a_good_token(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Host": "evil.test:%d" % self.http.port})
        self.assertEqual((status, body["error"]), (403, "bad_host"))
        self.assertFalse(self.provisioner.running("hr"))


class OriginAndCsrfTests(UiCase):
    def assert_refused_and_nothing_started(self, status, body, code):
        self.assertEqual((status, body["error"]), (403, code))
        self.assertEqual(self.provisioner.up, set())

    def test_missing_csrf_token_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"X-CSRF-Token": None})
        self.assert_refused_and_nothing_started(status, body, "bad_csrf")

    def test_wrong_csrf_token_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"X-CSRF-Token": "guessed-token"})
        self.assert_refused_and_nothing_started(status, body, "bad_csrf")

    def test_csrf_token_with_non_ascii_is_refused_not_crashed(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"X-CSRF-Token": "tokén"})
        self.assert_refused_and_nothing_started(status, body, "bad_csrf")

    def test_csrf_is_required_on_every_post(self):
        for path in ("/api/plans", "/api/plans/%s/approve" % ("0" * 64),
                     "/api/domains/it/stop"):
            status, body = self.http.call("POST", path, {},
                                          override={"X-CSRF-Token": None})
            self.assertEqual((status, body["error"]), (403, "bad_csrf"), path)

    def test_refusal_of_a_post_with_a_body_is_always_readable(self):
        # The server must read the refused body, or a Windows close can reset
        # the connection before the client reads the 403.
        for attempt in range(40):
            status, body = self.http.call("POST", "/api/plans",
                                          {"subject": "x" * 4000},
                                          override={"X-CSRF-Token": None})
            self.assertEqual((status, body["error"]), (403, "bad_csrf"), attempt)

    def test_foreign_origin_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Origin": "http://evil.test"})
        self.assert_refused_and_nothing_started(status, body, "bad_origin")

    def test_null_origin_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Origin": "null"})
        self.assert_refused_and_nothing_started(status, body, "bad_origin")

    def test_missing_origin_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Origin": None})
        self.assert_refused_and_nothing_started(status, body, "bad_origin")

    def test_localhost_origin_is_accepted(self):
        override = {"Origin": "http://localhost:%d" % self.http.port}
        status, _ = self.http.call("POST", "/api/domains/hr/start", {}, override)
        self.assertEqual(status, 200)
        self.assertTrue(self.provisioner.running("hr"))

    def test_page_carries_the_token_and_no_placeholder(self):
        status, page = self.http.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(TOKEN.encode("ascii"), page)
        self.assertNotIn(b"{{CSRF_TOKEN}}", page)

    def test_page_and_static_responses_carry_the_security_headers(self):
        status, headers, _data = self.http.send("GET", "/", self.http.headers("GET"))
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")


class BodyLimitTests(UiCase):
    def test_wrong_content_type_is_refused(self):
        body = b"subject=x"
        status, _headers, data = self.http.send(
            "POST", "/api/plans",
            self.http.headers("POST", body, {"Content-Type": "text/plain"}), body)
        self.assertEqual(status, 415)
        self.assertEqual(json.loads(data)["error"], "not_json")

    def test_body_over_the_limit_is_refused_before_it_is_read(self):
        status, headers, data = self.http.send(
            "POST", "/api/plans",
            self.http.headers("POST", b"", {"Content-Length": str(MAX_BODY_BYTES + 1)}))
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(data)["error"], "too_large")

    def test_body_exactly_at_the_limit_is_read(self):
        padding = "x" * (MAX_BODY_BYTES - 40)
        body = json.dumps({"subject": padding}).encode("utf-8")
        self.assertLessEqual(len(body), MAX_BODY_BYTES)
        status, headers, data = self.http.send(
            "POST", "/api/plans", self.http.headers("POST", body), body)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data)["error"], "bad_input")

    def test_invalid_json_is_refused(self):
        body = b"{not json"
        status, _h, data = self.http.send(
            "POST", "/api/plans", self.http.headers("POST", body), body)
        self.assertEqual((status, json.loads(data)["error"]), (400, "bad_json"))

    def test_non_utf8_body_is_refused(self):
        body = b'{"subject": "\xff"}'
        status, _h, data = self.http.send(
            "POST", "/api/plans", self.http.headers("POST", body), body)
        self.assertEqual((status, json.loads(data)["error"]), (400, "bad_json"))

    def test_json_that_is_not_an_object_is_refused(self):
        body = b"[1, 2]"
        status, _h, data = self.http.send(
            "POST", "/api/plans", self.http.headers("POST", body), body)
        self.assertEqual((status, json.loads(data)["error"]), (400, "bad_json"))

    def test_missing_content_length_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Content-Length": None})
        self.assertEqual((status, body["error"]), (411, "length_required"))

    def test_non_numeric_content_length_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {},
                                      override={"Content-Length": "-5"})
        self.assertEqual((status, body["error"]), (400, "bad_length"))


class StaticFileTests(UiCase):
    def test_traversal_and_unknown_static_paths_are_not_found(self):
        for path in TRAVERSAL_PATHS:
            status, body = self.http.call("GET", path)
            self.assertEqual((status, body["error"]), (404, "not_found"), path)

    def test_allowlisted_files_are_served_with_their_types(self):
        for path, (name, content_type) in STATIC_ROUTES.items():
            status, headers, data = self.http.send(
                "GET", path, self.http.headers("GET"))
            self.assertEqual(status, 200, path)
            self.assertEqual(headers["Content-Type"], content_type)
            self.assertEqual(data, (STATIC_DIR / name).read_bytes().replace(
                b"{{CSRF_TOKEN}}", TOKEN.encode("ascii")))

    def test_static_files_are_ascii_and_load_nothing_remote(self):
        for name in ("index.html", "app.css", "app.js"):
            text = (STATIC_DIR / name).read_bytes().decode("ascii")
            self.assertNotIn("http://", text, name)
            self.assertNotIn("https://", text, name)

    def test_index_has_exactly_one_csrf_placeholder(self):
        text = (STATIC_DIR / "index.html").read_bytes()
        self.assertEqual(text.count(b"{{CSRF_TOKEN}}"), 1)


class DomainControlTests(UiCase):
    def test_start_then_status_then_stop(self):
        status, body = self.http.call("POST", "/api/domains/hr/start", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["domains"]["hr"]["running"])
        status, body = self.http.call("POST", "/api/domains/hr/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(body["domains"]["hr"]["running"])

    def test_starting_a_running_domain_is_refused(self):
        self.http.call("POST", "/api/domains/hr/start", {})
        status, body = self.http.call("POST", "/api/domains/hr/start", {})
        self.assertEqual((status, body["error"]), (409, "already_running"))

    def test_stopping_a_stopped_domain_is_refused(self):
        status, body = self.http.call("POST", "/api/domains/it/stop", {})
        self.assertEqual((status, body["error"]), (409, "not_running"))

    def test_unknown_domain_name_is_not_found(self):
        status, body = self.http.call("POST", "/api/domains/payroll/start", {})
        self.assertEqual((status, body["error"]), (404, "not_found"))

    def test_failed_health_check_stops_the_domain_again(self):
        self.provisioner.health_error = ProvisionError("hr failed health check")
        status, body = self.http.call("POST", "/api/domains/hr/start", {})
        self.assertEqual((status, body["error"]), (503, "domain_not_started"))
        self.assertFalse(self.provisioner.running("hr"))

    def test_status_lists_all_domains_and_the_default_requests(self):
        status, body = self.http.call("GET", "/api/status")
        self.assertEqual(set(body["domains"]), set(DOMAINS))
        self.assertEqual(body["default_requests"], list(DEFAULT_REQUEST_TEXTS))


class PlanTests(UiCase):
    def test_plan_is_refused_while_a_domain_is_down(self):
        self.provisioner.up = {"hr", "it"}
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "requests": list(DEFAULT_REQUEST_TEXTS)})
        self.assertEqual((status, body["error"]), (409, "domains_down"))
        self.assertIn("facilities", body["message"])

    def test_bad_subjects_are_refused(self):
        self.start_all()
        for subject in ("", "no-at-sign", "two@at@signs", "has space@x.test",
                        "x" * 300 + "@a.test", None, 7):
            status, body = self.http.call("POST", "/api/plans", {
                "subject": subject, "requests": ["hr:create_record"]})
            self.assertEqual((status, body["error"]), (400, "bad_input"), subject)

    def test_bad_request_text_is_refused(self):
        self.start_all()
        for requests in (["payroll:create"], ["hr-create"], ["hr:Drop"], [7], "hr:x"):
            status, body = self.http.call("POST", "/api/plans", {
                "subject": SUBJECT, "requests": requests})
            self.assertEqual((status, body["error"]), (400, "bad_input"), requests)

    def test_unsupported_action_is_refused_at_planning(self):
        self.start_all()
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "requests": ["it:drop_database"]})
        self.assertEqual((status, body["error"]), (400, "plan_refused"))

    def test_plan_shows_warnings_and_its_hash(self):
        self.start_all()
        plan = self.make_plan(["hr:create_record", "it:grant_admin_access"])
        self.assertRegex(plan["plan_hash"], PLAN_HASH)
        self.assertEqual(plan["plan"]["subject"], SUBJECT)
        self.assertTrue(plan["warnings"])
        self.assertIn("grant_admin_access", " ".join(plan["warnings"]))

    def test_plan_is_not_run_until_approved(self):
        self.start_all()
        self.make_plan()
        self.assertEqual(self.post.calls, [])


class ApprovalTests(UiCase):
    def test_approve_runs_the_plan_the_user_saw(self):
        self.start_all()
        plan = self.make_plan()
        status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "success")
        self.assertRegex(result["run_id"], RUN_ID)
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(len(self.post.calls), 3)

    def test_secrets_never_reach_the_browser(self):
        self.start_all()
        plan = self.make_plan()
        self.http.call("POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.http.call("GET", "/")
        for data in self.http.bodies:
            self.assertNotIn(b"unit-exchange-secret", data)
            self.assertNotIn(b"unit-approval-secret", data)

    def test_a_plan_can_be_approved_only_once(self):
        self.start_all()
        plan = self.make_plan()
        path = "/api/plans/%s/approve" % plan["plan_hash"]
        self.assertEqual(self.http.call("POST", path, {})[0], 200)
        status, body = self.http.call("POST", path, {})
        self.assertEqual((status, body["error"]), (404, "plan_not_pending"))
        self.assertEqual(len(self.post.calls), 3)

    def test_unknown_plan_hash_is_refused(self):
        status, body = self.http.call("POST", "/api/plans/%s/approve" % ("ab" * 32), {})
        self.assertEqual((status, body["error"]), (404, "plan_not_pending"))
        self.assertEqual(self.post.calls, [])

    def test_malformed_plan_hash_is_not_found(self):
        status, body = self.http.call("POST", "/api/plans/not-a-hash/approve", {})
        self.assertEqual((status, body["error"]), (404, "not_found"))

    def test_changed_plan_is_refused_and_nothing_is_sent(self):
        self.start_all()
        plan = self.make_plan()
        stored = self.ui._pending[plan["plan_hash"]][0]
        stored["steps"][0]["params"]["tampered"] = True
        status, body = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual((status, body["error"]), (409, "plan_changed"))
        self.assertEqual(self.post.calls, [])

    def test_pending_plan_expires_after_its_ttl(self):
        self.start_all()
        plan = self.make_plan()
        self.clock.advance(PENDING_TTL_SECONDS)
        status, body = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual((status, body["error"]), (404, "plan_not_pending"))
        self.assertEqual(self.post.calls, [])

    def test_pending_plan_is_still_valid_just_before_its_ttl(self):
        self.start_all()
        plan = self.make_plan()
        self.clock.advance(PENDING_TTL_SECONDS - 1)
        status, _ = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual(status, 200)

    def test_a_domain_stopped_after_planning_blocks_approval(self):
        self.start_all()
        plan = self.make_plan()
        self.http.call("POST", "/api/domains/it/stop", {})
        status, body = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual((status, body["error"]), (409, "domains_down"))
        self.assertEqual(self.post.calls, [])


class OneRunAtATimeTests(UiCase):
    def test_start_is_refused_while_a_run_holds_the_lock(self):
        self.ui._busy.acquire()
        try:
            status, body = self.http.call("POST", "/api/domains/hr/start", {})
        finally:
            self.ui._busy.release()
        self.assertEqual((status, body["error"]), (409, "busy"))
        self.assertFalse(self.provisioner.running("hr"))

    def test_approve_is_refused_while_a_domain_change_holds_the_lock(self):
        self.start_all()
        plan = self.make_plan()
        self.ui._busy.acquire()
        try:
            status, body = self.http.call(
                "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        finally:
            self.ui._busy.release()
        self.assertEqual((status, body["error"]), (409, "busy"))
        self.assertEqual(self.post.calls, [])


class RunViewTests(UiCase):
    def test_run_view_shows_the_report_and_each_domain(self):
        self.start_all()
        plan = self.make_plan()
        _status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        status, view = self.http.call("GET", "/api/runs/%s" % result["run_id"])
        self.assertEqual(status, 200)
        self.assertEqual([d["domain"] for d in view["domains"]], list(DOMAINS))
        self.assertEqual(view["report"]["status"], "success")
        self.assertTrue(view["chain_ok"])
        self.assertTrue(view["limits"])

    def test_unknown_run_id_is_not_found(self):
        status, body = self.http.call("GET", "/api/runs/%s" % ("0" * 16))
        self.assertEqual((status, body["error"]), (404, "unknown_run"))

    def test_malformed_run_id_is_not_found(self):
        for path in ("/api/runs/..", "/api/runs/XYZ", "/api/runs/%s/x" % ("a" * 16),
                     "/api/runs/../status"):
            status, body = self.http.call("GET", path)
            self.assertEqual((status, body["error"]), (404, "not_found"), path)


class ModelPlannerTests(UiCase):
    """The opt-in model planner through the UI (ADR-0011). Fake client, no network."""

    def model_plan(self, **extra):
        payload = {"subject": SUBJECT, "planner": "model", "request_text": "a laptop"}
        payload.update(extra)
        return self.http.call("POST", "/api/plans", payload)

    def test_model_plan_is_built_and_names_its_planner(self):
        self.start_all()
        status, body = self.model_plan()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["planner"], "model (ui-fake)")
        steps = [(s["domain"], s["action"]) for s in body["plan"]["steps"]]
        self.assertEqual(steps, [("hr", "create_record"), ("it", "assign_laptop")])
        self.assertEqual(body["plan"]["subject"], SUBJECT)
        self.assertRegex(body["plan_hash"], PLAN_HASH)
        self.assertEqual(self.post.calls, [])

    def test_only_the_text_and_action_names_go_to_the_model(self):
        self.start_all()
        self.model_plan()
        system_prompt, user_text = self.model.calls[0]
        self.assertEqual(user_text, "a laptop")
        self.assertNotIn(SUBJECT, system_prompt + user_text)

    def test_model_plan_can_be_approved_and_run(self):
        self.start_all()
        _status, plan = self.model_plan()
        status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual((status, result["status"]), (200, "success"))
        self.assertEqual(len(self.post.calls), 2)

    def test_deterministic_plan_names_its_planner_and_never_builds_a_client(self):
        self.ui.client_factory = refusing_factory
        self.start_all()
        body = self.make_plan()
        self.assertEqual(body["planner"], "deterministic")
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "planner": "deterministic",
            "requests": ["hr:create_record"]})
        self.assertEqual((status, body["planner"]), (200, "deterministic"))

    def test_bad_planner_values_are_refused(self):
        self.start_all()
        for planner in ("", "grok", "MODEL", 7, ["model"], {"a": 1}):
            status, body = self.http.call("POST", "/api/plans", {
                "subject": SUBJECT, "planner": planner,
                "requests": ["hr:create_record"]})
            self.assertEqual((status, body["error"]), (400, "bad_input"), planner)
        self.assertEqual(self.model.calls, [])

    def test_requests_and_request_text_cannot_be_combined(self):
        self.start_all()
        status, body = self.model_plan(requests=["hr:create_record"])
        self.assertEqual((status, body["error"]), (400, "bad_input"))
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "requests": ["hr:create_record"],
            "request_text": "a laptop"})
        self.assertEqual((status, body["error"]), (400, "bad_input"))
        self.assertEqual(self.model.calls, [])

    def test_bad_request_text_is_refused_before_any_model_call(self):
        self.start_all()
        for text in (None, "", "   ", 7, ["a"], "x" * 1001, "caf\u00e9", "two\nlines"):
            status, body = self.model_plan(request_text=text)
            self.assertEqual((status, body["error"]), (400, "bad_input"), text)
        status, body = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "planner": "model"})
        self.assertEqual((status, body["error"]), (400, "bad_input"))
        self.assertEqual(self.model.calls, [])

    def test_bad_subject_is_refused_before_any_model_call(self):
        self.start_all()
        status, body = self.model_plan(subject="no-at-sign")
        self.assertEqual((status, body["error"]), (400, "bad_input"))
        self.assertEqual(self.model.calls, [])

    def test_domains_down_is_refused_before_any_model_call(self):
        self.provisioner.up = {"hr", "it"}
        status, body = self.model_plan()
        self.assertEqual((status, body["error"]), (409, "domains_down"))
        self.assertEqual(self.model.calls, [])

    def test_model_failure_gives_502_and_stores_no_plan(self):
        self.start_all()
        self.model.error = ModelPlannerError(
            "model call refused: rate limit exceeded (HTTP 429)")
        status, body = self.model_plan()
        self.assertEqual((status, body["error"]), (502, "model_failed"))
        self.assertIn("rate limit", body["message"])
        self.assertEqual(self.ui._pending, {})
        self.assertEqual(self.post.calls, [])
        self.assertEqual(len(self.model.calls), 1)

    def test_missing_key_gives_502_and_stores_no_plan(self):
        def no_key():
            raise ModelPlannerError("no API key")
        self.ui.client_factory = no_key
        self.start_all()
        status, body = self.model_plan()
        self.assertEqual((status, body["error"]), (502, "model_failed"))
        self.assertEqual(self.ui._pending, {})

    def test_unusable_replies_give_502_with_no_fallback(self):
        self.start_all()
        replies = ("not json", "[]", '{"requests": []}',
                   '{"requests": [{"domain": "hr", "action": "x", "extra": 1}]}',
                   '{"requests": [{"domain": "payroll", "action": "pay"}]}',
                   '{"requests": [{"domain": "hr", "action": "Drop Table"}]}',
                   "x" * 5000)
        for reply in replies:
            self.model.reply = reply
            status, body = self.model_plan()
            self.assertEqual((status, body["error"]), (502, "model_failed"), reply[:30])
        self.assertEqual(self.ui._pending, {})
        self.assertEqual(self.post.calls, [])

    def test_unknown_action_from_the_model_is_refused_at_planning(self):
        self.start_all()
        self.model.reply = proposal(("it", "drop_database"))
        status, body = self.model_plan()
        self.assertEqual((status, body["error"]), (400, "plan_refused"))
        self.assertEqual(self.ui._pending, {})

    def test_will_not_action_from_the_model_stays_in_the_plan_with_a_warning(self):
        self.start_all()
        self.model.reply = proposal(("hr", "create_record"), ("it", "grant_admin_access"))
        status, body = self.model_plan()
        self.assertEqual(status, 200, body)
        self.assertIn("grant_admin_access", [s["action"] for s in body["plan"]["steps"]])
        self.assertIn("grant_admin_access", " ".join(body["warnings"]))

    def test_no_key_name_or_value_in_any_response_or_page(self):
        self.start_all()
        self.model.error = ModelPlannerError("HTTP 401: bad key")
        self.model_plan()
        self.model.error = None
        self.model_plan()
        self.http.call("GET", "/")
        self.http.call("GET", "/static/app.js")
        everything = b"".join(self.http.bodies)
        self.assertNotIn(b"gsk_", everything)
        self.assertNotIn(b"GROQ_API_KEY", everything)

    def test_page_has_the_planner_selector_and_note(self):
        status, _headers, data = self.http.send("GET", "/", self.http.headers("GET"))
        page = data.decode("utf-8")
        self.assertEqual(status, 200)
        for needle in ('id="planner"', 'value="model"', 'id="request-text"',
                       "leaves this machine", "Use synthetic data only"):
            self.assertIn(needle, page)
        script = self.http.call("GET", "/static/app.js")[1].decode("utf-8")
        self.assertIn("request_text", script)
        self.assertIn("made.planner", script)


class LiveUiFlow(unittest.TestCase):
    """The whole flow on the real domains, through the UI's HTTP API."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.provisioner = provision.Provisioner(state_dir=tmp.name, ports=EPHEMERAL)
        self.addCleanup(self.provisioner.stop)
        self.ui = UiState(self.provisioner, clock=time.time, csrf_token=TOKEN)
        server, thread = serve(self.ui)
        self.addCleanup(self.stop_server, server, thread)
        self.http = HttpClient(server.server_address[1], TOKEN)

    def stop_server(self, server, thread):
        server.shutdown()
        server.server_close()
        thread.join()

    def test_plan_approve_and_rebuild_on_real_domains(self):
        for name in DOMAINS:
            status, _ = self.http.call("POST", "/api/domains/%s/start" % name, {})
            self.assertEqual(status, 200)
        status, plan = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "requests": list(DEFAULT_REQUEST_TEXTS)})
        self.assertEqual(status, 200, plan)
        status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "success")
        status, view = self.http.call("GET", "/api/runs/%s" % result["run_id"])
        self.assertEqual(status, 200)
        self.assertTrue(view["chain_ok"])
        for domain in view["domains"]:
            self.assertTrue(domain["chain_ok"])
            self.assertEqual(domain["outcomes"], {"executed": 2}, domain["domain"])
        for data in self.http.bodies:
            self.assertNotIn(self.provisioner.exchange_secret.encode("ascii"), data)
            self.assertNotIn(self.provisioner.approval_secret.encode("ascii"), data)

    def test_will_not_step_gives_partial_and_a_refusal_in_it(self):
        for name in DOMAINS:
            self.http.call("POST", "/api/domains/%s/start" % name, {})
        _status, plan = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT,
            "requests": ["hr:create_record", "it:grant_admin_access"]})
        self.assertTrue(plan["warnings"])
        _status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual(result["status"], "partial")
        refused = [row for row in result["rows"] if row["outcome"] == "refused"]
        self.assertEqual([(row["domain"], row["action"]) for row in refused],
                         [("it", "grant_admin_access")])

    def test_model_plan_on_real_domains_with_a_fake_client(self):
        model = FakeModel(reply=proposal(("hr", "create_record"),
                                         ("it", "grant_admin_access"),
                                         ("facilities", "issue_badge")))
        self.ui.client_factory = lambda: model
        for name in DOMAINS:
            self.http.call("POST", "/api/domains/%s/start" % name, {})
        status, plan = self.http.call("POST", "/api/plans", {
            "subject": SUBJECT, "planner": "model", "request_text": "admin please"})
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["planner"], "model (ui-fake)")
        _status, result = self.http.call(
            "POST", "/api/plans/%s/approve" % plan["plan_hash"], {})
        self.assertEqual(result["status"], "partial")
        refused = [(r["domain"], r["action"]) for r in result["rows"]
                   if r["outcome"] == "refused"]
        self.assertEqual(refused, [("it", "grant_admin_access")])

    def test_stopping_one_domain_leaves_the_others_running(self):
        for name in DOMAINS:
            self.http.call("POST", "/api/domains/%s/start" % name, {})
        status, body = self.http.call("POST", "/api/domains/hr/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(body["domains"]["hr"]["running"])
        self.assertTrue(body["domains"]["it"]["running"])
        self.assertTrue(body["domains"]["facilities"]["running"])


if __name__ == "__main__":
    unittest.main()
