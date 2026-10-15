"""Gate G4: honest refusal, over real domain servers on port 0 and an injected clock.

The coordinator runs an approved plan against three real domain servers. The
domains, not the coordinator, refuse the will_not action, and their own
ledgers prove it. The grant_admin_access run must come out as partial with
six executed and one refused, counted from the run.

Children started by provision.py use the real clock, so this gate runs the
domains in process with the injected clock (as G3 does). demo.py covers the
real processes.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan, warnings
from coordinator.registry import Registry
from coordinator.run import post_execute, run_plan
from coordinator.tokens import TokenMinter, derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from ledger.ledger import read_entries
from tests.helpers import FakeClock

EXCHANGE_SECRET = "g4-exchange-secret"
APPROVAL_SECRET = "g4-approval-secret"
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
GRANT_ADMIN_REQUEST = ("it", "grant_admin_access", {"login": "nh"})


def start_thread(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


class CountingPost:
    """Calls the real POST /execute and counts calls per port."""

    def __init__(self):
        self.counts = {}

    def __call__(self, port, body, timeout):
        self.counts[port] = self.counts.get(port, 0) + 1
        return post_execute(port, body, timeout)


class G4Setup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.agents = {}
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
            self.agents[name] = agent
            self.servers[name] = (server, thread)
            self.ports[name] = server.server_address[1]
        self.registry = Registry(self.ports, self.clock, ttl_seconds=TTL)
        self.registry.refresh_all()
        markers = tempfile.TemporaryDirectory()
        self.addCleanup(markers.cleanup)
        self.gate = ApprovalGate(APPROVAL_SECRET, self.clock, Path(markers.name))
        self.approver = Approver(APPROVAL_SECRET, self.clock)
        self.minter = TokenMinter(EXCHANGE_SECRET, self.clock)

    def plan(self, requests):
        return build_plan(self.registry, SUBJECT, requests)

    def dispatch(self, plan, approval=None, post=None, run_id=None):
        approval = approval or self.approver.approve(plan)
        return run_plan(plan, approval, gate=self.gate, minter=self.minter,
                        ports=self.ports, subject=SUBJECT, run_id=run_id,
                        post=post or CountingPost())

    def ledger(self, domain, run_id):
        """Return the entries one domain wrote for one run, from its own file."""
        path = self.agents[domain].ledger_path
        if not path.exists():
            return []
        return [entry for entry in read_entries(path) if entry["run_id"] == run_id]


class CleanRun(G4Setup):
    def test_clean_run_executes_six_and_refuses_none(self):
        report = self.dispatch(self.plan(CLEAN_REQUESTS), run_id="g4-clean")
        self.assertEqual(report.status, "success")
        self.assertEqual(report.count("executed"), 6)
        self.assertEqual(report.count("refused"), 0)
        self.assertEqual(report.exchange_count, 3)


class GrantAdminAccessRun(G4Setup):
    def test_grant_admin_access_run_is_partial_six_executed_one_refused(self):
        plan = self.plan(CLEAN_REQUESTS + [GRANT_ADMIN_REQUEST])
        report = self.dispatch(plan, run_id="g4-grant")
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.count("executed"), 6)
        self.assertEqual(report.count("refused"), 1)
        refused = [row for row in report.rows if row.outcome == "refused"]
        self.assertEqual((refused[0].domain, refused[0].action), ("it", "grant_admin_access"))
        self.assertEqual((refused[0].classification, refused[0].reason),
                         ("will_not", "will_not"))

    def test_refused_step_stays_in_the_plan_with_a_warning(self):
        plan = self.plan(CLEAN_REQUESTS + [GRANT_ADMIN_REQUEST])
        self.dispatch(plan, run_id="g4-kept")
        held = [step for step in plan["steps"] if step["action"] == "grant_admin_access"]
        self.assertEqual(len(held), 1)
        self.assertEqual(len(warnings(plan)), 1)

    def test_it_ledger_records_the_refusal_and_no_execution(self):
        plan = self.plan(CLEAN_REQUESTS + [GRANT_ADMIN_REQUEST])
        report = self.dispatch(plan, run_id="g4-ledger")
        entries = self.ledger("it", report.run_id)
        refused = [e for e in entries if e["event"] == "action_refused"
                   and e["data"]["action"] == "grant_admin_access"]
        executed = [e for e in entries if e["event"] == "action_executed"
                    and e["data"]["action"] == "grant_admin_access"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["data"]["reason"], "will_not")
        self.assertEqual(executed, [])


class DomainDown(G4Setup):
    def test_unreachable_domain_is_not_executed_and_later_domains_still_run(self):
        plan = self.plan(CLEAN_REQUESTS)
        stop_server(*self.servers["hr"])
        post = CountingPost()
        report = self.dispatch(plan, post=post, run_id="g4-down")
        hr_rows = [row for row in report.rows if row.domain == "hr"]
        self.assertEqual({row.reason for row in hr_rows}, {"domain_unreachable"})
        self.assertEqual(report.count("executed"), 4)
        self.assertEqual(report.count("not_executed"), 2)
        self.assertEqual(report.status, "partial")
        self.assertEqual(post.counts[self.ports["hr"]], 1)
        self.assertEqual(post.counts[self.ports["it"]], 1)


class RefusedApprovals(G4Setup):
    def test_replayed_approval_aborts_and_leaves_domain_ledgers_untouched(self):
        plan = self.plan(CLEAN_REQUESTS)
        approval = self.approver.approve(plan)
        first = self.dispatch(plan, approval=approval, run_id="g4-first")
        before = {name: len(self.ledger(name, first.run_id)) for name in MODULES}
        second = self.dispatch(plan, approval=approval, run_id="g4-replay")
        self.assertEqual(first.status, "success")
        self.assertEqual(second.status, "aborted")
        self.assertEqual(second.abort_code, "approval_already_consumed")
        self.assertEqual(second.exchange_count, 3)
        for name in MODULES:
            self.assertEqual(self.ledger(name, second.run_id), [])
            self.assertEqual(len(self.ledger(name, first.run_id)), before[name])

    def test_changed_plan_aborts_before_any_token_is_minted(self):
        approved = self.plan(CLEAN_REQUESTS)
        approval = self.approver.approve(approved)
        changed = self.plan(CLEAN_REQUESTS + [GRANT_ADMIN_REQUEST])
        report = self.dispatch(changed, approval=approval, run_id="g4-changed")
        self.assertEqual(report.status, "aborted")
        self.assertEqual(report.abort_code, "plan_changed_since_approval")
        self.assertEqual(report.exchange_count, 0)
