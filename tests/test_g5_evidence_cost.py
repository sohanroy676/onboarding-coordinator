"""Gate G5: evidence and cost, over real domain servers on port 0 and an injected clock.

All three domains share one state folder, laid out as the demo lays it out
(state/<domain>/ledger.jsonl). One run ID must rebuild from those ledgers as
hr 2, it 2, facilities 2. The coordination multiple comes from the real
exchange counter over five clean runs: 15 exchanges, 5 runs, 3.0.
"""

import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan
from coordinator.registry import Registry
from coordinator.run import coordination_multiple, post_execute, run_plan
from coordinator.tokens import TokenMinter, derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from ledger.reconstruct import LIMITS, main, reconstruct
from tests.helpers import FakeClock

EXCHANGE_SECRET = "g5-exchange-secret"
APPROVAL_SECRET = "g5-approval-secret"
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
FIVE_RUNS = 5


def start_thread(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


class G5Setup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state = Path(state.name)
        self.agents = {}
        self.ports = {}
        for name, module in MODULES.items():
            key = derive_domain_key(EXCHANGE_SECRET, name)
            agent = DomainAgent(module.SPEC, key, self.state, self.clock)
            server = make_server(agent, port=0)
            thread = start_thread(server)
            self.addCleanup(stop_server, server, thread)
            self.agents[name] = agent
            self.ports[name] = server.server_address[1]
        self.registry = Registry(self.ports, self.clock, ttl_seconds=TTL)
        self.registry.refresh_all()
        markers = tempfile.TemporaryDirectory()
        self.addCleanup(markers.cleanup)
        self.gate = ApprovalGate(APPROVAL_SECRET, self.clock, Path(markers.name))
        self.approver = Approver(APPROVAL_SECRET, self.clock)

    def dispatch(self, requests, minter, run_id):
        plan = build_plan(self.registry, SUBJECT, requests)
        approval = self.approver.approve(plan)
        return run_plan(plan, approval, gate=self.gate, minter=minter,
                        ports=self.ports, subject=SUBJECT, run_id=run_id,
                        post=post_execute)

    def rebuild(self, run_id):
        return reconstruct(run_id, self.state)

    def counts(self, rebuild):
        """Return {domain: executed+refused+failed} for one rebuild."""
        return {d.domain: sum(d.outcomes.values()) for d in rebuild.domains}


class OneRunRebuilds(G5Setup):
    def test_clean_run_rebuilds_hr_2_it_2_facilities_2(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        report = self.dispatch(CLEAN_REQUESTS, minter, "g5-clean")
        self.assertEqual(report.status, "success")
        rebuild = self.rebuild(report.run_id)
        self.assertTrue(rebuild.chain_ok)
        self.assertEqual(self.counts(rebuild), {"hr": 2, "it": 2, "facilities": 2})
        self.assertEqual(sum(d.outcomes["executed"] for d in rebuild.domains), 6)

    def test_grant_run_shows_the_refusal_in_it(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        report = self.dispatch(CLEAN_REQUESTS + [GRANT_ADMIN_REQUEST], minter, "g5-grant")
        rebuild = self.rebuild(report.run_id)
        it = rebuild.domains[1]
        self.assertEqual(it.domain, "it")
        self.assertEqual(it.outcomes["refused"], 1)
        self.assertEqual(it.outcomes["executed"], 2)

    def test_aborted_replay_leaves_no_ledger_line(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        plan = build_plan(self.registry, SUBJECT, CLEAN_REQUESTS)
        approval = self.approver.approve(plan)
        run_plan(plan, approval, gate=self.gate, minter=minter, ports=self.ports,
                 subject=SUBJECT, run_id="g5-first", post=post_execute)
        replay = run_plan(plan, approval, gate=self.gate, minter=minter, ports=self.ports,
                          subject=SUBJECT, run_id="g5-replay", post=post_execute)
        self.assertEqual(replay.status, "aborted")
        rebuild = self.rebuild("g5-replay")
        self.assertEqual(sum(self.counts(rebuild).values()), 0)
        self.assertEqual(sum(d.rejected for d in rebuild.domains), 0)

    def test_rejected_token_is_counted_apart_from_actions(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        token = minter.mint(SUBJECT, "hr", ["create_record"], "g5-wrong-domain")
        status, _raw = post_execute(
            self.ports["it"],
            {"token": token, "actions": [{"name": "create_record", "params": {}}]},
            timeout=5)
        self.assertNotEqual(status, 200)
        rebuild = self.rebuild("g5-wrong-domain")
        it = rebuild.domains[1]
        self.assertEqual(it.rejected, 1)
        self.assertEqual(sum(it.outcomes.values()), 0)

    def test_broken_domain_chain_is_reported_and_exit_code_is_one(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        report = self.dispatch(CLEAN_REQUESTS, minter, "g5-tamper")
        path = self.state / "hr" / "ledger.jsonl"
        path.write_text(path.read_text(encoding="ascii").replace(
            '"action_executed"', '"action_refused"', 1), encoding="ascii")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([report.run_id, "--state-dir", str(self.state)])
        self.assertEqual(code, 1)
        self.assertIn("BROKEN", out.getvalue())
        self.assertIn("not verified", out.getvalue())


class FiveRunsCoordinationMultiple(G5Setup):
    def test_five_clean_runs_give_three_exchanges_each_from_the_real_counter(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        counts = []
        run_ids = []
        for number in range(FIVE_RUNS):
            run_id = "g5-five-%d" % number
            report = self.dispatch(CLEAN_REQUESTS, minter, run_id)
            self.assertEqual(report.status, "success")
            counts.append(report.exchange_count)
            run_ids.append(run_id)
        self.assertEqual(counts, [3, 6, 9, 12, 15])
        self.assertEqual(minter.exchange_count, 15)
        self.assertEqual(coordination_multiple(minter.exchange_count, FIVE_RUNS), 3.0)
        for run_id in run_ids:
            self.assertEqual(self.counts(self.rebuild(run_id)),
                             {"hr": 2, "it": 2, "facilities": 2})

    def test_limits_are_printed_for_the_rebuilt_run(self):
        minter = TokenMinter(EXCHANGE_SECRET, self.clock)
        report = self.dispatch(CLEAN_REQUESTS, minter, "g5-limits")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([report.run_id, "--state-dir", str(self.state)])
        for limit in LIMITS:
            self.assertIn(limit, out.getvalue())
