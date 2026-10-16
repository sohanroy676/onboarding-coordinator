"""Gate G6: perimeters, over the real project tree and in-process domains.

Static checks read every project file: no credential literal, no forbidden
import, no write outside the allowlist, no domain key reachable from
coordinator/. Each static check has a planted control, so a scanner that
finds nothing is shown to be able to find something. Runtime checks run one
onboarding over domain servers on port 0 with an injected clock and assert
that a run changes only its approval marker and the domain ledgers, that
reconstruct writes nothing, and that both coordinator secrets are refused
as tokens.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan
from coordinator.registry import Registry
from coordinator.run import post_execute, run_plan
from coordinator.tokens import TokenMinter, derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from ledger.ledger import read_entries
from ledger.reconstruct import reconstruct
from tests.helpers import FakeClock
from tests.perimeter_scan import (
    ALLOWED_WRITES,
    ROOT,
    changed_paths,
    scan_coordinator_env,
    scan_imports,
    scan_model_env_use,
    scan_secrets,
    scan_writes,
    snapshot,
)

EXCHANGE_SECRET = "g6-exchange-secret"
APPROVAL_SECRET = "g6-approval-secret"
SUBJECT = "new.hire@example.test"
TTL = 60
MODULES = {"hr": hr_agent, "it": it_agent, "facilities": facilities_agent}
CLEAN_REQUESTS = [
    ("hr", "create_record", {"employee": "nh"}),
    ("hr", "enroll_benefits", {"employee": "nh"}),
    ("it", "create_account", {"login": "nh"}),
    ("it", "assign_laptop", {"login": "nh"}),
    ("facilities", "issue_badge", {"floor": 3}),
    ("facilities", "assign_desk", {"floor": 3}),
]
PLANTED_KEY_LINE = "OC_DOMAIN_KEY=" + "ab" * 32
PLANTED_TOKEN_LINE = 'token = "' + "Q" * 30 + '"'


def start_thread(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


class StaticCredentialScan(unittest.TestCase):
    def test_project_tree_has_no_credential_literal(self):
        self.assertEqual(scan_secrets(ROOT), [])

    def test_planted_credentials_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "notes.md"
            planted.write_text(PLANTED_KEY_LINE + "\n" + PLANTED_TOKEN_LINE + "\n",
                               encoding="ascii")
            findings = scan_secrets(Path(tmp))
        self.assertEqual({f.line for f in findings}, {1, 2})

    def test_coordinator_has_no_domain_key_or_env_read(self):
        self.assertEqual(scan_coordinator_env(ROOT), [])


class ModelKeyPerimeter(unittest.TestCase):
    """ADR-0011: the model key stays in .env and in app/ and onboard.py."""

    def test_no_key_shaped_value_outside_the_exempt_env_file(self):
        self.assertEqual([f for f in scan_secrets(ROOT) if f.rule == "xai api key"], [])

    def test_only_the_app_layer_names_the_key_or_imports_the_planner(self):
        self.assertEqual(scan_model_env_use(ROOT), [])

    def test_planted_key_and_planted_reader_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "coordinator").mkdir()
            (root / "coordinator" / "bad.py").write_text(
                'KEY = "XAI_API_KEY"\n', encoding="ascii")
            (root / "notes.txt").write_text("xai-" + "B" * 30 + "\n", encoding="ascii")
            (root / ".env").write_text("XAI_API_KEY=xai-" + "B" * 30 + "\n",
                                       encoding="ascii")
            self.assertEqual([f.path for f in scan_secrets(root)], ["notes.txt"])
            self.assertEqual([f.path for f in scan_model_env_use(root)],
                             ["coordinator/bad.py"])


class StaticImportScan(unittest.TestCase):
    def test_project_imports_respect_the_boundaries(self):
        self.assertEqual(scan_imports(ROOT), [])

    def test_planted_cross_import_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("domains", "coordinator", "ledger"):
                (root / folder).mkdir()
            (root / "coordinator" / "bad.py").write_text(
                "from domains import hr_agent\n", encoding="ascii")
            (root / "domains" / "bad.py").write_text(
                "import hmac\n", encoding="ascii")
            findings = scan_imports(root)
        rules = sorted(f.rule for f in findings)
        self.assertEqual(len(rules), 2)
        self.assertIn("import domains from coordinator", rules)


class StaticWriteScan(unittest.TestCase):
    def test_write_sites_match_the_allowlist_exactly(self):
        self.assertEqual(scan_writes(ROOT), ALLOWED_WRITES)

    def test_planted_write_outside_the_allowlist_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("domains", "coordinator", "ledger"):
                (root / folder).mkdir()
            (root / "coordinator" / "bad.py").write_text(
                'def leak(path):\n    open(path, "w").write("x")\n', encoding="ascii")
            found = scan_writes(root)
        self.assertEqual(found[("coordinator/bad.py", "open:w")], 1)


class DomainSetup(unittest.TestCase):
    """Three domain servers on port 0, one injected clock, one approval gate."""

    def setUp(self):
        self.clock = FakeClock(1000.0)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state = Path(state.name)
        self.ports = {}
        for name, module in MODULES.items():
            key = derive_domain_key(EXCHANGE_SECRET, name)
            agent = DomainAgent(module.SPEC, key, self.state, self.clock)
            server = make_server(agent, port=0)
            thread = start_thread(server)
            self.addCleanup(stop_server, server, thread)
            self.ports[name] = server.server_address[1]
        self.registry = Registry(self.ports, self.clock, ttl_seconds=TTL)
        self.registry.refresh_all()
        self.gate = ApprovalGate(APPROVAL_SECRET, self.clock, self.state / "approvals")
        self.approver = Approver(APPROVAL_SECRET, self.clock)


class CoordinatorSecretsRefused(DomainSetup):
    """Both coordinator secrets, presented as bearer tokens, are refused."""

    def test_both_secrets_are_refused_by_every_domain(self):
        for secret in (EXCHANGE_SECRET, APPROVAL_SECRET):
            for name, port in self.ports.items():
                body = {"token": secret, "actions": [{"name": "x", "params": {}}]}
                status, _raw = post_execute(port, body, timeout=5)
                self.assertNotEqual(status, 200, "%s accepted %s" % (name, secret))
        for name in MODULES:
            entries = read_entries(self.state / name / "ledger.jsonl")
            rejected = [e for e in entries if e["event"] == "token_rejected"]
            self.assertEqual(len(rejected), 2, name)


class RuntimeWrites(DomainSetup):
    def setUp(self):
        super().setUp()
        self.minter = TokenMinter(EXCHANGE_SECRET, self.clock,
                                  count_path=self.state / "exchanges.log")

    def test_one_run_changes_only_its_marker_ledgers_and_exchange_count(self):
        plan = build_plan(self.registry, SUBJECT, CLEAN_REQUESTS)
        approval = self.approver.approve(plan)
        before = snapshot(self.state)
        report = run_plan(plan, approval, gate=self.gate, minter=self.minter,
                          ports=self.ports, subject=SUBJECT, run_id="g6-writes",
                          post=post_execute)
        self.assertEqual(report.status, "success")
        expected = {
            "approvals/%s.consumed" % approval["approval_id"],
            "hr/ledger.jsonl",
            "it/ledger.jsonl",
            "facilities/ledger.jsonl",
            "exchanges.log",
        }
        self.assertEqual(changed_paths(before, snapshot(self.state)), expected)

    def test_aborted_replay_writes_nothing(self):
        plan = build_plan(self.registry, SUBJECT, CLEAN_REQUESTS)
        approval = self.approver.approve(plan)
        run_plan(plan, approval, gate=self.gate, minter=self.minter, ports=self.ports,
                 subject=SUBJECT, run_id="g6-first", post=post_execute)
        before = snapshot(self.state)
        replay = run_plan(plan, approval, gate=self.gate, minter=self.minter,
                          ports=self.ports, subject=SUBJECT, run_id="g6-replay",
                          post=post_execute)
        self.assertEqual(replay.status, "aborted")
        self.assertEqual(changed_paths(before, snapshot(self.state)), set())

    def test_reconstruct_is_read_only(self):
        plan = build_plan(self.registry, SUBJECT, CLEAN_REQUESTS)
        approval = self.approver.approve(plan)
        report = run_plan(plan, approval, gate=self.gate, minter=self.minter,
                          ports=self.ports, subject=SUBJECT, run_id="g6-read",
                          post=post_execute)
        before = snapshot(self.state)
        reconstruct(report.run_id, self.state)
        self.assertEqual(changed_paths(before, snapshot(self.state)), set())


if __name__ == "__main__":
    unittest.main()
