import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from coordinator.tokens import TokenMinter, derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from ledger.ledger import read_entries, verify_file
from tests.helpers import FakeClock

SECRET = "unit-test-exchange-secret"
RUN = "run-0001"
APPROVAL_ID = "c" * 32
HIRE = "new.hire@example.test"


def call(port, method, path, body=None, raw=None):
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=data, method=method
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("ascii"))
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("ascii"))


class DomainServerCase(unittest.TestCase):
    spec = it_agent.SPEC

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.clock = FakeClock(1000.0)
        self.minter = TokenMinter(SECRET, self.clock, ttl_seconds=60)
        self.start_server()

    def start_server(self):
        key = derive_domain_key(SECRET, self.spec.name)
        self.agent = DomainAgent(self.spec, key, self.state_dir, self.clock)
        self.server = make_server(self.agent, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        self.addCleanup(self.stop_server, self.server, self.thread)

    @staticmethod
    def stop_server(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(5)

    def restart(self):
        self.stop_server(self.server, self.thread)
        self.start_server()

    def token(self, scope, domain=None, run=RUN, approval=APPROVAL_ID):
        return self.minter.mint(HIRE, domain or self.spec.name, scope, run, approval)

    def execute(self, token, names):
        actions = [{"name": name} for name in names]
        return call(self.port, "POST", "/execute", {"token": token, "actions": actions})

    def ledger(self):
        return read_entries(self.agent.ledger_path)


class CapabilitiesTests(unittest.TestCase):
    def test_each_domain_declares_itself(self):
        for module in (hr_agent, it_agent, facilities_agent):
            with tempfile.TemporaryDirectory() as tmp:
                key = derive_domain_key(SECRET, module.NAME)
                agent = DomainAgent(module.SPEC, key, tmp, FakeClock())
                server = make_server(agent, port=0)
                thread = threading.Thread(target=server.serve_forever)
                thread.daemon = True
                thread.start()
                try:
                    status, body = call(
                        server.server_address[1], "GET", "/capabilities"
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(5)
                self.assertEqual(status, 200)
                self.assertEqual(body["domain"], module.NAME)
                self.assertEqual(body["capabilities"], sorted(module.CAPABILITIES))
                self.assertEqual(body["will_not"], sorted(module.WILL_NOT))


class ExecuteTests(DomainServerCase):
    def test_happy_path_writes_one_line_per_action(self):
        token = self.token(["create_account", "assign_laptop"])
        status, body = self.execute(token, ["create_account", "assign_laptop"])
        self.assertEqual(status, 200)
        self.assertEqual(body["run_id"], RUN)
        outcomes = [(r["action"], r["outcome"]) for r in body["results"]]
        self.assertEqual(
            outcomes,
            [("create_account", "executed"), ("assign_laptop", "executed")],
        )
        lines = self.ledger()
        self.assertEqual([e["event"] for e in lines], ["action_executed"] * 2)
        self.assertTrue(all(e["run_id"] == RUN for e in lines))
        self.assertEqual(verify_file(self.agent.ledger_path), (True, None))

    def test_will_not_is_refused_and_others_still_run(self):
        scope = ["create_account", "grant_admin_access", "assign_laptop"]
        names = ["create_account", "grant_admin_access", "assign_laptop"]
        status, body = self.execute(self.token(scope), names)
        self.assertEqual(status, 200)
        got = [(r["action"], r["outcome"], r.get("reason")) for r in body["results"]]
        self.assertEqual(
            got,
            [
                ("create_account", "executed", None),
                ("grant_admin_access", "refused", "will_not"),
                ("assign_laptop", "executed", None),
            ],
        )
        events = [e["event"] for e in self.ledger()]
        self.assertEqual(
            events, ["action_executed", "action_refused", "action_executed"]
        )

    def test_out_of_scope_wins_over_will_not(self):
        token = self.token(["create_account"])
        status, body = self.execute(token, ["grant_admin_access"])
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["reason"], "out_of_scope")

    def test_unsupported_action(self):
        token = self.token(["format_disk"])
        _status, body = self.execute(token, ["format_disk"])
        self.assertEqual(body["results"][0]["outcome"], "refused")
        self.assertEqual(body["results"][0]["reason"], "unsupported_action")

    def test_refusal_is_written_before_nothing_runs(self):
        calls = []

        def spy(subject, params):
            calls.append(subject)
            return {}

        handlers = {"create_account": spy, "assign_laptop": spy}
        spec = it_agent.SPEC.__class__(
            name="it",
            capabilities=it_agent.CAPABILITIES,
            will_not=it_agent.WILL_NOT,
            handlers=handlers,
            port_env="OC_PORT_IT",
            default_port=8102,
        )
        key = derive_domain_key(SECRET, "it")
        agent = DomainAgent(spec, key, self.state_dir / "spy", self.clock)
        status, _ = agent.execute(
            {"token": self.token(["grant_admin_access"]),
             "actions": [{"name": "grant_admin_access"}]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(calls, [])

    def test_handler_fault_is_reported_not_fatal(self):
        def boom(subject, params):
            raise RuntimeError("simulated fault")

        spec = it_agent.SPEC.__class__(
            name="it",
            capabilities=("create_account",),
            will_not=(),
            handlers={"create_account": boom},
            port_env="OC_PORT_IT",
            default_port=8102,
        )
        key = derive_domain_key(SECRET, "it")
        agent = DomainAgent(spec, key, self.state_dir / "boom", self.clock)
        status, body = agent.execute(
            {"token": self.token(["create_account"]),
             "actions": [{"name": "create_account"}]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["outcome"], "failed")
        events = [e["event"] for e in read_entries(agent.ledger_path)]
        self.assertEqual(events, ["action_executed", "action_failed"])


class TokenRejectionTests(DomainServerCase):
    def test_wrong_domain_token(self):
        token = self.token(["create_record"], domain="hr")
        status, body = self.execute(token, ["create_record"])
        self.assertEqual((status, body), (403, {"error": "domain_mismatch"}))

    def test_missing_token_is_malformed(self):
        status, body = call(
            self.port, "POST", "/execute", {"actions": [{"name": "create_account"}]}
        )
        self.assertEqual((status, body), (400, {"error": "malformed_token"}))

    def test_expired_token(self):
        token = self.token(["create_account"])
        self.clock.advance(60)
        status, body = self.execute(token, ["create_account"])
        self.assertEqual((status, body), (401, {"error": "token_expired"}))
        self.assertEqual(self.ledger()[-1]["event"], "token_rejected")
        self.assertEqual(self.ledger()[-1]["run_id"], RUN)

    def test_replay_is_refused_and_nothing_runs_twice(self):
        token = self.token(["create_account"])
        self.assertEqual(self.execute(token, ["create_account"])[0], 200)
        status, body = self.execute(token, ["create_account"])
        self.assertEqual((status, body), (401, {"error": "token_replayed"}))
        events = [e["event"] for e in self.ledger()]
        self.assertEqual(events, ["action_executed", "token_rejected"])

    def test_replay_is_refused_after_restart(self):
        token = self.token(["create_account"])
        self.assertEqual(self.execute(token, ["create_account"])[0], 200)
        self.restart()
        status, body = self.execute(token, ["create_account"])
        self.assertEqual((status, body), (401, {"error": "token_replayed"}))
        self.assertEqual(verify_file(self.agent.ledger_path), (True, None))

    def test_token_with_all_actions_refused_is_still_consumed(self):
        token = self.token(["grant_admin_access"])
        self.assertEqual(self.execute(token, ["grant_admin_access"])[0], 200)
        status, body = self.execute(token, ["grant_admin_access"])
        self.assertEqual(body, {"error": "token_replayed"})

    def test_bad_action_shape_does_not_consume_token(self):
        token = self.token(["create_account"])
        for bad in (None, [], "x", [1], [{"name": 3}], [{"name": "a", "params": 1}]):
            status, body = call(
                self.port, "POST", "/execute", {"token": token, "actions": bad}
            )
            self.assertEqual((status, body), (400, {"error": "bad_request"}))
        self.assertEqual(self.execute(token, ["create_account"])[0], 200)

    def test_concurrent_submissions_of_one_token_run_once(self):
        token = self.token(["create_account"])
        statuses = []
        guard = threading.Lock()

        def submit():
            status, _ = self.execute(token, ["create_account"])
            with guard:
                statuses.append(status)

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(sorted(statuses), [200] + [401] * 7)
        executed = [e for e in self.ledger() if e["event"] == "action_executed"]
        self.assertEqual(len(executed), 1)
        self.assertEqual(verify_file(self.agent.ledger_path), (True, None))


class HttpEdgeTests(DomainServerCase):
    def test_non_json_and_non_object_bodies(self):
        for raw in (b"not json", b"\xff\xfe", b"[1]", b"7", b"null", b""):
            status, body = call(self.port, "POST", "/execute", raw=raw)
            self.assertEqual((status, body), (400, {"error": "bad_request"}), raw)

    def test_oversized_body_is_refused(self):
        raw = b"{" + b" " * (70 * 1024) + b"}"
        status, body = call(self.port, "POST", "/execute", raw=raw)
        self.assertEqual((status, body), (400, {"error": "bad_request"}))

    def test_unknown_path_and_wrong_method(self):
        self.assertEqual(call(self.port, "GET", "/nope")[0], 404)
        self.assertEqual(call(self.port, "POST", "/nope", body={})[0], 404)
        self.assertEqual(call(self.port, "GET", "/execute")[0], 405)
        self.assertEqual(call(self.port, "POST", "/capabilities", body={})[0], 405)


if __name__ == "__main__":
    unittest.main()


class ApprovalReuseTests(DomainServerCase):
    def test_second_run_with_the_same_approval_is_refused(self):
        status, _ = self.execute(self.token(["create_account"]), ["create_account"])
        self.assertEqual(status, 200)
        token = self.token(["create_account"], run="run-0002")
        status, body = self.execute(token, ["create_account"])
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "approval_replayed")

    def test_reuse_is_refused_after_a_restart(self):
        self.execute(self.token(["create_account"]), ["create_account"])
        self.restart()
        token = self.token(["create_account"], run="run-0002")
        status, body = self.execute(token, ["create_account"])
        self.assertEqual((status, body["error"]), (401, "approval_replayed"))

    def test_a_new_approval_is_accepted_for_the_same_domain(self):
        self.execute(self.token(["create_account"]), ["create_account"])
        token = self.token(["create_account"], run="run-0002", approval="d" * 32)
        status, _ = self.execute(token, ["create_account"])
        self.assertEqual(status, 200)

    def test_refused_reuse_executes_nothing_and_records_the_refusal(self):
        self.execute(self.token(["create_account"]), ["create_account"])
        token = self.token(["create_account"], run="run-0002")
        self.execute(token, ["create_account"])
        entries = self.ledger()
        events = [entry["event"] for entry in entries]
        self.assertEqual(events.count("action_executed"), 1)
        self.assertEqual(entries[-1]["event"], "token_rejected")
        self.assertEqual(entries[-1]["data"]["reason"], "approval_replayed")
