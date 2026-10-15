"""Unit tests for approval: sign, verify in order, consume once (no HTTP)."""

import copy
import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.approval import (
    DEFAULT_TTL_SECONDS,
    ApprovalAlreadyConsumed,
    ApprovalExpired,
    ApprovalGate,
    ApprovalClockRegressed,
    ApprovalTagInvalid,
    Approver,
    PlanChangedSinceApproval,
)
from coordinator.planner import canonical_json
from coordinator.tokens import derive_domain_key
from tests.helpers import FakeClock

SECRET = "unit-approval-secret"
TTL = 300
PLAN = {
    "subject": "new.hire@example.test",
    "steps": [
        {"domain": "hr", "action": "create_record", "params": {"n": 1},
         "classification": "supported"},
        {"domain": "it", "action": "grant_admin_access", "params": {},
         "classification": "will_not"},
    ],
}


def changed(plan, path, value):
    """Return a deep copy of plan with one field replaced."""
    result = copy.deepcopy(plan)
    node = result
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return result


class ApprovalCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.markers = Path(tmp.name) / "approvals"
        self.approver = Approver(SECRET, self.clock, ttl_seconds=TTL)
        self.gate = ApprovalGate(SECRET, self.clock, self.markers)

    def marker_files(self):
        if not self.markers.exists():
            return []
        return sorted(self.markers.iterdir())


class HappyPathTests(ApprovalCase):
    def test_approval_verifies_and_is_consumed_once(self):
        approval = self.approver.approve(PLAN)
        self.gate.verify_and_consume(approval, PLAN)
        self.assertEqual(len(self.marker_files()), 1)
        with self.assertRaises(ApprovalAlreadyConsumed):
            self.gate.verify_and_consume(approval, PLAN)

    def test_replay_after_restart_is_refused_from_disk(self):
        approval = self.approver.approve(PLAN)
        self.gate.verify_and_consume(approval, PLAN)
        restarted = ApprovalGate(SECRET, self.clock, self.markers)
        with self.assertRaises(ApprovalAlreadyConsumed):
            restarted.verify_and_consume(approval, PLAN)

    def test_each_approval_gets_a_fresh_id_so_the_same_plan_can_run_again(self):
        first = self.approver.approve(PLAN)
        second = self.approver.approve(PLAN)
        self.assertNotEqual(first["approval_id"], second["approval_id"])
        self.gate.verify_and_consume(first, PLAN)
        self.gate.verify_and_consume(second, PLAN)
        self.assertEqual(len(self.marker_files()), 2)

    def test_approval_has_exactly_the_documented_fields(self):
        approval = self.approver.approve(PLAN)
        self.assertEqual(set(approval),
                         {"approval_id", "plan_hash", "issued_at", "expires_at", "tag"})
        self.assertEqual(approval["issued_at"], 1000)
        self.assertEqual(approval["expires_at"], 1000 + TTL)

    def test_approve_refuses_non_positive_ttl(self):
        with self.assertRaises(ValueError):
            Approver(SECRET, self.clock, ttl_seconds=0)

    def test_default_ttl_is_five_minutes(self):
        self.assertEqual(DEFAULT_TTL_SECONDS, 300)


class TamperTests(ApprovalCase):
    def assert_plan_refused_and_no_marker(self, approval, plan):
        with self.assertRaises(PlanChangedSinceApproval) as caught:
            self.gate.verify_and_consume(approval, plan)
        self.assertEqual(caught.exception.code, "plan_changed_since_approval")
        self.assertEqual(self.marker_files(), [])

    def test_any_changed_plan_field_is_refused(self):
        approval = self.approver.approve(PLAN)
        tampered = [
            changed(PLAN, ["subject"], "other.hire@example.test"),
            changed(PLAN, ["steps", 0, "action"], "enroll_benefits"),
            changed(PLAN, ["steps", 0, "params", "n"], 2),
            changed(PLAN, ["steps", 1, "classification"], "supported"),
            changed(PLAN, ["steps", 0, "domain"], "it"),
            {"subject": PLAN["subject"], "steps": PLAN["steps"][:1]},
        ]
        for plan in tampered:
            with self.subTest(plan=canonical_json(plan)):
                self.assert_plan_refused_and_no_marker(approval, plan)

    def test_failed_plan_check_leaves_the_approval_usable(self):
        approval = self.approver.approve(PLAN)
        self.assert_plan_refused_and_no_marker(
            approval, changed(PLAN, ["steps", 0, "params", "n"], 9))
        self.gate.verify_and_consume(approval, PLAN)
        self.assertEqual(len(self.marker_files()), 1)

    def test_changed_approval_fields_are_refused_as_bad_tag(self):
        approval = self.approver.approve(PLAN)
        bad_fields = [
            ("approval_id", "0" * 32),
            ("plan_hash", "0" * 64),
            ("expires_at", approval["expires_at"] + 1000),
            ("issued_at", approval["issued_at"] - 1),
            ("tag", "A" * len(approval["tag"])),
        ]
        for field, value in bad_fields:
            with self.subTest(field=field):
                forged = dict(approval)
                forged[field] = value
                with self.assertRaises(ApprovalTagInvalid) as caught:
                    self.gate.verify_and_consume(forged, PLAN)
                self.assertEqual(caught.exception.code, "invalid_approval_tag")
        self.assertEqual(self.marker_files(), [])

    def test_malformed_approvals_are_refused(self):
        approval = self.approver.approve(PLAN)
        malformed = [
            None,
            "approval",
            {},
            {k: v for k, v in approval.items() if k != "tag"},
            dict(approval, extra="x"),
            dict(approval, approval_id="../../escape"),
            dict(approval, approval_id=7),
            dict(approval, expires_at="soon"),
            dict(approval, tag="é" * 64),
        ]
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(ApprovalTagInvalid):
                    self.gate.verify_and_consume(value, PLAN)
        self.assertEqual(self.marker_files(), [])

    def test_approval_signed_with_another_secret_is_refused(self):
        other_secrets = [
            "some-other-secret",
            derive_domain_key(SECRET, "hr"),
        ]
        for secret in other_secrets:
            with self.subTest(secret=secret[:8]):
                forged = Approver(secret, self.clock, ttl_seconds=TTL).approve(PLAN)
                with self.assertRaises(ApprovalTagInvalid):
                    self.gate.verify_and_consume(forged, PLAN)
        self.assertEqual(self.marker_files(), [])

    def test_gate_refuses_an_empty_secret(self):
        with self.assertRaises(ValueError):
            ApprovalGate("", self.clock, self.markers)


class ClockTests(ApprovalCase):
    def test_approval_used_at_its_issue_time_is_valid(self):
        approval = self.approver.approve(PLAN)
        self.gate.verify_and_consume(approval, PLAN)

    def test_clock_set_back_before_issue_is_refused_and_writes_no_marker(self):
        approval = self.approver.approve(PLAN)
        self.clock.advance(-1)
        with self.assertRaises(ApprovalClockRegressed) as caught:
            self.gate.verify_and_consume(approval, PLAN)
        self.assertEqual(caught.exception.code, "approval_clock_regressed")
        self.assertEqual(self.marker_files(), [])

    def test_clock_rewound_after_issue_is_a_stated_limit_not_detected(self):
        # Limit (ADR-0004): a rewind to a time still after issued_at extends
        # the approval's life; only a rewind before issued_at is caught.
        approval = self.approver.approve(PLAN)
        self.clock.advance(TTL - 10)
        self.clock.advance(-(TTL - 20))
        self.gate.verify_and_consume(approval, PLAN)


class ExpiryTests(ApprovalCase):
    def test_one_second_before_expiry_is_valid(self):
        approval = self.approver.approve(PLAN)
        self.clock.advance(TTL - 1)
        self.gate.verify_and_consume(approval, PLAN)

    def test_exactly_at_expiry_is_expired(self):
        approval = self.approver.approve(PLAN)
        self.clock.advance(TTL)
        with self.assertRaises(ApprovalExpired) as caught:
            self.gate.verify_and_consume(approval, PLAN)
        self.assertEqual(caught.exception.code, "approval_expired")
        self.assertEqual(self.marker_files(), [])

    def test_expired_approval_with_extended_expiry_is_bad_tag_not_valid(self):
        approval = self.approver.approve(PLAN)
        self.clock.advance(TTL + 500)
        extended = dict(approval, expires_at=approval["expires_at"] + 10_000)
        with self.assertRaises(ApprovalTagInvalid):
            self.gate.verify_and_consume(extended, PLAN)
        self.assertEqual(self.marker_files(), [])


class RaceTests(ApprovalCase):
    ROUNDS = 20
    CONTENDERS = 8

    def test_exactly_one_of_many_concurrent_consumes_wins(self):
        for round_number in range(self.ROUNDS):
            with self.subTest(round=round_number):
                approval = self.approver.approve(PLAN)
                barrier = threading.Barrier(self.CONTENDERS)
                outcomes = []
                outcome_lock = threading.Lock()

                def contend():
                    barrier.wait()
                    try:
                        self.gate.verify_and_consume(approval, PLAN)
                        result = "won"
                    except ApprovalAlreadyConsumed:
                        result = "consumed"
                    with outcome_lock:
                        outcomes.append(result)

                threads = [threading.Thread(target=contend)
                           for _ in range(self.CONTENDERS)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10)
                self.assertEqual(outcomes.count("won"), 1)
                self.assertEqual(outcomes.count("consumed"), self.CONTENDERS - 1)
        self.assertEqual(len(self.marker_files()), self.ROUNDS)


if __name__ == "__main__":
    unittest.main()
