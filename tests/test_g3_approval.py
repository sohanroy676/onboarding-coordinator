"""Gate G3: plan and one approval, over real domains on port 0 and an injected clock.

The registry discovers three real domain servers over HTTP, the planner
builds one plan across them, and one approval covers the whole plan. Each
test breaks one property: staleness, unknown domain, a changed sub-plan,
expiry, replay after restart, and a race between concurrent consumes.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.approval import (
    ApprovalAlreadyConsumed,
    ApprovalExpired,
    ApprovalGate,
    Approver,
    PlanChangedSinceApproval,
)
from coordinator.planner import build_plan, warnings
from coordinator.registry import DeclarationStale, Registry
from coordinator.tokens import derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from tests.helpers import FakeClock

EXCHANGE_SECRET = "g3-exchange-secret"
APPROVAL_SECRET = "g3-approval-secret"
SUBJECT = "new.hire@example.test"
TTL = 60
APPROVAL_TTL = 300
MODULES = {"hr": hr_agent, "it": it_agent, "facilities": facilities_agent}
RACE_ROUNDS = 10
RACE_CONTENDERS = 8


def start_thread(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


def requests_across_domains():
    return [
        ("facilities", "issue_badge", {"floor": 3}),
        ("it", "create_account", {"login": "nh"}),
        ("hr", "create_record", {"employee": "nh"}),
        ("it", "grant_admin_access", {"login": "nh"}),
        ("hr", "change_payroll", {"employee": "nh"}),
    ]


class ApprovalGateSetup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.servers = {}
        self.ports = {}
        for name, module in MODULES.items():
            state = tempfile.TemporaryDirectory()
            self.addCleanup(state.cleanup)
            key = derive_domain_key(EXCHANGE_SECRET, name)
            agent = DomainAgent(module.SPEC, key, Path(state.name), self.clock)
            server = make_server(agent, port=0)
            thread = start_thread(server)
            self.addCleanup(stop_server, server, thread)
            self.servers[name] = (server, thread)
            self.ports[name] = server.server_address[1]
        self.registry = Registry(self.ports, self.clock, ttl_seconds=TTL)
        self.registry.refresh_all()
        markers = tempfile.TemporaryDirectory()
        self.addCleanup(markers.cleanup)
        self.markers = Path(markers.name) / "approvals"
        self.approver = Approver(APPROVAL_SECRET, self.clock, ttl_seconds=APPROVAL_TTL)
        self.gate = ApprovalGate(APPROVAL_SECRET, self.clock, self.markers)

    def plan(self):
        return build_plan(self.registry, SUBJECT, requests_across_domains())

    def marker_count(self):
        if not self.markers.exists():
            return 0
        return len(list(self.markers.iterdir()))


class OneApprovalTests(ApprovalGateSetup):
    def test_one_approval_covers_all_three_domains_and_is_consumed_once(self):
        plan = self.plan()
        self.assertEqual([s["domain"] for s in plan["steps"]],
                         ["hr", "hr", "it", "it", "facilities"])
        approval = self.approver.approve(plan)
        self.gate.verify_and_consume(approval, plan)
        self.assertEqual(self.marker_count(), 1)
        with self.assertRaises(ApprovalAlreadyConsumed):
            self.gate.verify_and_consume(approval, plan)

    def test_will_not_steps_are_approved_and_warned_not_dropped(self):
        plan = self.plan()
        held = [s for s in plan["steps"] if s["classification"] == "will_not"]
        self.assertEqual(sorted(s["action"] for s in held),
                         ["change_payroll", "grant_admin_access"])
        self.assertEqual(len(warnings(plan)), 2)
        self.gate.verify_and_consume(self.approver.approve(plan), plan)

    def test_forced_stale_declaration_refuses_the_plan_before_any_approval(self):
        self.clock.advance(TTL + 1)
        with self.assertRaises(DeclarationStale):
            self.plan()
        self.assertEqual(self.marker_count(), 0)

    def test_unknown_domain_raises_keyerror_at_planning(self):
        with self.assertRaises(KeyError):
            build_plan(self.registry, SUBJECT, [("payroll", "create_record", {})])


class ChangedPlanTests(ApprovalGateSetup):
    def test_changed_sub_plan_in_one_domain_is_refused(self):
        plan = self.plan()
        approval = self.approver.approve(plan)
        changed = build_plan(self.registry, SUBJECT, [
            ("facilities", "issue_badge", {"floor": 4}),
            ("it", "create_account", {"login": "nh"}),
            ("hr", "create_record", {"employee": "nh"}),
            ("it", "grant_admin_access", {"login": "nh"}),
            ("hr", "change_payroll", {"employee": "nh"}),
        ])
        with self.assertRaises(PlanChangedSinceApproval):
            self.gate.verify_and_consume(approval, changed)
        self.assertEqual(self.marker_count(), 0)
        self.gate.verify_and_consume(approval, plan)

    def test_dropping_a_will_not_step_is_a_changed_plan(self):
        plan = self.plan()
        approval = self.approver.approve(plan)
        trimmed = build_plan(self.registry, SUBJECT, [
            ("facilities", "issue_badge", {"floor": 3}),
            ("it", "create_account", {"login": "nh"}),
            ("hr", "create_record", {"employee": "nh"}),
        ])
        with self.assertRaises(PlanChangedSinceApproval):
            self.gate.verify_and_consume(approval, trimmed)
        self.assertEqual(self.marker_count(), 0)


class ExpiryAndReplayTests(ApprovalGateSetup):
    def test_expired_approval_is_refused_and_leaves_no_marker(self):
        plan = self.plan()
        approval = self.approver.approve(plan)
        self.clock.advance(APPROVAL_TTL)
        with self.assertRaises(ApprovalExpired):
            self.gate.verify_and_consume(approval, plan)
        self.assertEqual(self.marker_count(), 0)

    def test_replay_after_restart_is_refused(self):
        plan = self.plan()
        approval = self.approver.approve(plan)
        self.gate.verify_and_consume(approval, plan)
        restarted = ApprovalGate(APPROVAL_SECRET, self.clock, self.markers)
        with self.assertRaises(ApprovalAlreadyConsumed):
            restarted.verify_and_consume(approval, plan)
        self.assertEqual(self.marker_count(), 1)


class RaceTests(ApprovalGateSetup):
    def test_concurrent_consumes_of_one_approval_have_one_winner(self):
        plan = self.plan()
        for round_number in range(RACE_ROUNDS):
            with self.subTest(round=round_number):
                approval = self.approver.approve(plan)
                barrier = threading.Barrier(RACE_CONTENDERS)
                outcomes = []
                outcome_lock = threading.Lock()

                def contend():
                    barrier.wait()
                    try:
                        self.gate.verify_and_consume(approval, plan)
                        result = "won"
                    except ApprovalAlreadyConsumed:
                        result = "consumed"
                    with outcome_lock:
                        outcomes.append(result)

                threads = [threading.Thread(target=contend)
                           for _ in range(RACE_CONTENDERS)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10)
                self.assertEqual(outcomes.count("won"), 1)
                self.assertEqual(outcomes.count("consumed"), RACE_CONTENDERS - 1)
        self.assertEqual(self.marker_count(), RACE_ROUNDS)


if __name__ == "__main__":
    unittest.main()
