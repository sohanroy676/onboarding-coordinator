"""Unit tests for coordinator/run.py: status rules, response checks, no retries.

No HTTP here. A fake poster stands in for POST /execute, a fake registry
stands in for the capability registry, and the approval gate and minter are
real, on an injected clock and a temporary marker folder.
"""

import json
import tempfile
import unittest
from pathlib import Path

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan
from coordinator.run import (
    ABORTED,
    FAILED,
    PARTIAL,
    SUCCESS,
    DomainCallFailed,
    parse_results,
    run_plan,
)
from coordinator.tokens import TokenMinter
from tests.helpers import FakeClock

EXCHANGE_SECRET = "unit-run-exchange-secret"
APPROVAL_SECRET = "unit-run-approval-secret"
SUBJECT = "new.hire@example.test"
PORTS = {"hr": 9001, "it": 9002, "facilities": 9003}
CLASSES = {
    ("hr", "create_record"): "supported",
    ("hr", "change_payroll"): "will_not",
    ("it", "create_account"): "supported",
    ("it", "grant_admin_access"): "will_not",
    ("facilities", "issue_badge"): "supported",
}


class FakeRegistry:
    def classify(self, domain, action):
        return CLASSES.get((domain, action), "unsupported")


def requests_all_domains():
    return [
        ("facilities", "issue_badge", {"floor": 3}),
        ("it", "create_account", {"login": "nh"}),
        ("hr", "create_record", {"employee": "nh"}),
        ("it", "grant_admin_access", {"login": "nh"}),
    ]


def body_for(actions, outcomes):
    results = []
    for action, (outcome, reason) in zip(actions, outcomes):
        entry = {"action": action["name"], "outcome": outcome}
        if outcome == "refused":
            entry["reason"] = reason
        results.append(entry)
    return json.dumps({"domain": "x", "run_id": "r", "results": results}).encode()


class FakePost:
    """Records every call; answers by port with a status and raw body, or raises."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, port, body, timeout):
        self.calls.append((port, body))
        answer = self.answers[port]
        if isinstance(answer, BaseException):
            raise answer
        return answer(body) if callable(answer) else answer


def executed_for(body):
    """A fake domain that executes every action it is asked for."""
    def answer(request):
        return 200, body_for(request["actions"],
                             [("executed", None)] * len(request["actions"]))
    return answer


class RunSetup(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        markers = tempfile.TemporaryDirectory()
        self.addCleanup(markers.cleanup)
        self.gate = ApprovalGate(APPROVAL_SECRET, self.clock, Path(markers.name))
        self.approver = Approver(APPROVAL_SECRET, self.clock)
        self.minter = TokenMinter(EXCHANGE_SECRET, self.clock)

    def plan(self):
        return build_plan(FakeRegistry(), SUBJECT, requests_all_domains())

    def dispatch(self, post, plan=None, approval=None, ports=PORTS):
        plan = plan or self.plan()
        approval = approval or self.approver.approve(plan)
        return run_plan(plan, approval, gate=self.gate, minter=self.minter,
                        ports=ports, subject=SUBJECT, run_id="unit-run",
                        post=post)


class StatusRules(RunSetup):
    def test_every_action_executed_is_success(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        report = self.dispatch(post)
        self.assertEqual(report.status, SUCCESS)
        self.assertEqual(report.count("executed"), 4)
        self.assertEqual(report.count("refused"), 0)

    def test_some_executed_and_some_refused_is_partial(self):
        def it_refuses(request):
            outcomes = [("executed", None), ("refused", "will_not")]
            return 200, body_for(request["actions"], outcomes)
        post = FakePost({
            PORTS["hr"]: executed_for(PORTS["hr"]),
            PORTS["it"]: it_refuses,
            PORTS["facilities"]: executed_for(PORTS["facilities"]),
        })
        report = self.dispatch(post)
        self.assertEqual(report.status, PARTIAL)
        self.assertEqual(report.count("executed"), 3)
        self.assertEqual(report.count("refused"), 1)

    def test_nothing_executed_is_failed(self):
        def refuse_all(request):
            outcomes = [("refused", "out_of_scope")] * len(request["actions"])
            return 200, body_for(request["actions"], outcomes)
        post = FakePost({port: refuse_all for port in PORTS.values()})
        report = self.dispatch(post)
        self.assertEqual(report.status, FAILED)
        self.assertEqual(report.count("executed"), 0)

    def test_empty_plan_is_refused_before_anything_runs(self):
        with self.assertRaises(ValueError):
            run_plan({"subject": SUBJECT, "steps": []}, {}, gate=self.gate,
                         minter=self.minter, ports=PORTS, subject=SUBJECT)

    def test_missing_domain_port_is_refused_before_anything_runs(self):
        with self.assertRaises(ValueError):
            self.dispatch(FakePost({}), ports={"hr": 9001, "it": 9002})
        self.assertEqual(self.minter.exchange_count, 0)


class ApprovalFirst(RunSetup):
    def test_refused_approval_mints_nothing_and_calls_no_domain(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        plan = self.plan()
        approval = self.approver.approve(plan)
        approval["tag"] = "0" * 64
        report = self.dispatch(post, plan=plan, approval=approval)
        self.assertEqual(report.status, ABORTED)
        self.assertEqual(report.abort_code, "invalid_approval_tag")
        self.assertEqual(report.rows, [])
        self.assertEqual(self.minter.exchange_count, 0)
        self.assertEqual(post.calls, [])

    def test_replayed_approval_aborts_with_already_consumed(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        plan = self.plan()
        approval = self.approver.approve(plan)
        first = self.dispatch(post, plan=plan, approval=approval)
        second = self.dispatch(post, plan=plan, approval=approval)
        self.assertEqual(first.status, SUCCESS)
        self.assertEqual(second.status, ABORTED)
        self.assertEqual(second.abort_code, "approval_already_consumed")
        self.assertEqual(self.minter.exchange_count, 3)
        self.assertEqual(len(post.calls), 3)


class DispatchRules(RunSetup):
    def test_domains_are_called_once_each_in_hr_it_facilities_order(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        self.dispatch(post)
        self.assertEqual([port for port, _ in post.calls],
                         [PORTS["hr"], PORTS["it"], PORTS["facilities"]])

    def test_one_token_is_minted_per_dispatched_domain(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        report = self.dispatch(post)
        self.assertEqual(report.exchange_count, 3)

    def test_will_not_step_is_sent_to_the_domain_not_filtered(self):
        post = FakePost({port: executed_for(port) for port in PORTS.values()})
        self.dispatch(post)
        it_body = post.calls[1][1]
        self.assertEqual([a["name"] for a in it_body["actions"]],
                         ["create_account", "grant_admin_access"])

    def test_unreachable_domain_is_not_executed_and_later_domains_still_run(self):
        post = FakePost({
            PORTS["hr"]: ConnectionRefusedError("refused"),
            PORTS["it"]: executed_for(PORTS["it"]),
            PORTS["facilities"]: executed_for(PORTS["facilities"]),
        })
        report = self.dispatch(post)
        hr_rows = [row for row in report.rows if row.domain == "hr"]
        self.assertEqual({row.outcome for row in hr_rows}, {"not_executed"})
        self.assertEqual({row.reason for row in hr_rows}, {"domain_unreachable"})
        self.assertEqual(report.status, PARTIAL)
        self.assertEqual(len(post.calls), 3)

    def test_domain_error_status_is_recorded_and_not_retried(self):
        post = FakePost({
            PORTS["hr"]: (401, json.dumps({"error": "token_expired"}).encode()),
            PORTS["it"]: executed_for(PORTS["it"]),
            PORTS["facilities"]: executed_for(PORTS["facilities"]),
        })
        report = self.dispatch(post)
        hr_rows = [row for row in report.rows if row.domain == "hr"]
        self.assertEqual(hr_rows[0].reason, "domain_error:token_expired")
        self.assertEqual([port for port, _ in post.calls].count(PORTS["hr"]), 1)

    def test_a_malformed_domain_answer_is_not_trusted(self):
        post = FakePost({
            PORTS["hr"]: (200, b"not json"),
            PORTS["it"]: executed_for(PORTS["it"]),
            PORTS["facilities"]: executed_for(PORTS["facilities"]),
        })
        report = self.dispatch(post)
        hr_rows = [row for row in report.rows if row.domain == "hr"]
        self.assertEqual([row.outcome for row in hr_rows], ["not_executed"])
        self.assertEqual(hr_rows[0].reason, "bad_response")


class ParseResults(unittest.TestCase):
    ACTIONS = [{"name": "create_record", "params": {}},
               {"name": "change_payroll", "params": {}}]

    def test_well_formed_answer_gives_outcomes_in_order(self):
        raw = body_for(self.ACTIONS, [("executed", None), ("refused", "will_not")])
        self.assertEqual(parse_results(self.ACTIONS, 200, raw),
                         [("executed", None), ("refused", "will_not")])

    def test_wrong_result_count_is_refused(self):
        raw = body_for(self.ACTIONS[:1], [("executed", None)])
        with self.assertRaises(DomainCallFailed):
            parse_results(self.ACTIONS, 200, raw)

    def test_wrong_action_name_is_refused(self):
        raw = json.dumps({"results": [
            {"action": "other", "outcome": "executed"},
            {"action": "change_payroll", "outcome": "refused"}]}).encode()
        with self.assertRaises(DomainCallFailed):
            parse_results(self.ACTIONS, 200, raw)

    def test_unknown_outcome_is_refused(self):
        raw = json.dumps({"results": [
            {"action": "create_record", "outcome": "maybe"},
            {"action": "change_payroll", "outcome": "refused"}]}).encode()
        with self.assertRaises(DomainCallFailed):
            parse_results(self.ACTIONS, 200, raw)

    def test_non_object_answer_is_refused(self):
        with self.assertRaises(DomainCallFailed):
            parse_results(self.ACTIONS, 200, b"[]")

    def test_error_status_names_the_code(self):
        with self.assertRaises(DomainCallFailed) as ctx:
            parse_results(self.ACTIONS, 403, b'{"error": "domain_mismatch"}')
        self.assertEqual(ctx.exception.reason, "domain_error:domain_mismatch")

    def test_error_status_without_a_code_is_unknown(self):
        with self.assertRaises(DomainCallFailed) as ctx:
            parse_results(self.ACTIONS, 500, b"not json")
        self.assertEqual(ctx.exception.reason, "domain_error:unknown")
