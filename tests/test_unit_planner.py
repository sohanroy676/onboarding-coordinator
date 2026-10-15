"""Unit tests for plan building and advisory warnings (no HTTP, injected clock)."""

import json
import unittest

from coordinator.planner import build_plan, plan_hash, warnings
from coordinator.registry import DeclarationStale, Registry
from tests.helpers import FakeClock

TTL = 60
PORTS = {"hr": 1, "it": 2, "facilities": 3}
DECLARATIONS = {
    1: {"domain": "hr", "capabilities": ["create_record", "enroll_benefits"],
        "will_not": ["change_payroll"]},
    2: {"domain": "it", "capabilities": ["create_account", "assign_laptop"],
        "will_not": ["grant_admin_access"]},
    3: {"domain": "facilities", "capabilities": ["issue_badge"],
        "will_not": ["disable_alarm"]},
}
SUBJECT = "new.hire@example.test"


def make_registry(clock):
    def fetch(port, timeout):
        return 200, json.dumps(DECLARATIONS[port]).encode("utf-8")

    registry = Registry(PORTS, clock, ttl_seconds=TTL, fetch=fetch)
    registry.refresh_all()
    return registry


def requests_all():
    return [
        ("facilities", "issue_badge", {"floor": 3}),
        ("it", "create_account", {"login": "nh"}),
        ("hr", "create_record", {"employee": "nh"}),
        ("it", "grant_admin_access", {"login": "nh"}),
    ]


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.registry = make_registry(self.clock)

    def test_steps_are_ordered_hr_it_facilities_whatever_the_request_order(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        domains = [step["domain"] for step in plan["steps"]]
        self.assertEqual(domains, ["hr", "it", "it", "facilities"])

    def test_within_one_domain_request_order_is_kept(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        it_actions = [s["action"] for s in plan["steps"] if s["domain"] == "it"]
        self.assertEqual(it_actions, ["create_account", "grant_admin_access"])

    def test_plan_names_the_subject_and_has_no_timestamp(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        self.assertEqual(plan["subject"], SUBJECT)
        self.assertEqual(set(plan), {"subject", "steps"})

    def test_will_not_action_stays_in_plan_marked_will_not(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        refused = [s for s in plan["steps"] if s["action"] == "grant_admin_access"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["classification"], "will_not")

    def test_supported_action_is_marked_supported(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        supported = [s for s in plan["steps"] if s["action"] == "create_account"]
        self.assertEqual(supported[0]["classification"], "supported")

    def test_undeclared_action_is_refused_not_planned(self):
        requests = [("it", "launch_rocket", {})]
        with self.assertRaises(ValueError):
            build_plan(self.registry, SUBJECT, requests)

    def test_unknown_domain_raises_keyerror(self):
        with self.assertRaises(KeyError):
            build_plan(self.registry, SUBJECT, [("payroll", "create_record", {})])

    def test_stale_declaration_is_refused_at_planning(self):
        self.clock.advance(TTL + 1)
        with self.assertRaises(DeclarationStale):
            build_plan(self.registry, SUBJECT, requests_all())

    def test_empty_subject_or_empty_requests_are_refused(self):
        with self.assertRaises(ValueError):
            build_plan(self.registry, "", requests_all())
        with self.assertRaises(ValueError):
            build_plan(self.registry, SUBJECT, [])

    def test_params_must_be_an_object(self):
        with self.assertRaises(ValueError):
            build_plan(self.registry, SUBJECT, [("hr", "create_record", "nh")])

    def test_same_requests_give_same_hash_regardless_of_param_key_order(self):
        first = build_plan(self.registry, SUBJECT,
                           [("hr", "create_record", {"a": 1, "b": 2})])
        second = build_plan(self.registry, SUBJECT,
                            [("hr", "create_record", {"b": 2, "a": 1})])
        self.assertEqual(plan_hash(first), plan_hash(second))

    def test_hash_changes_when_any_step_field_changes(self):
        base = build_plan(self.registry, SUBJECT, requests_all())
        changed = [
            build_plan(self.registry, "other.hire@example.test", requests_all()),
            build_plan(self.registry, SUBJECT, [
                ("facilities", "issue_badge", {"floor": 4}),
                ("it", "create_account", {"login": "nh"}),
                ("hr", "create_record", {"employee": "nh"}),
                ("it", "grant_admin_access", {"login": "nh"}),
            ]),
            build_plan(self.registry, SUBJECT, [
                ("facilities", "issue_badge", {"floor": 3}),
                ("it", "create_account", {"login": "nh"}),
                ("hr", "enroll_benefits", {"employee": "nh"}),
                ("it", "grant_admin_access", {"login": "nh"}),
            ]),
        ]
        for other in changed:
            with self.subTest(hash=plan_hash(other)):
                self.assertNotEqual(plan_hash(base), plan_hash(other))


class WarningTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.registry = make_registry(self.clock)

    def test_will_not_step_gets_one_advisory_warning(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        found = warnings(plan)
        self.assertEqual(len(found), 1)
        self.assertIn("grant_admin_access", found[0])
        self.assertIn("it", found[0])

    def test_no_warnings_for_a_plan_without_will_not_steps(self):
        plan = build_plan(self.registry, SUBJECT, [("hr", "create_record", {})])
        self.assertEqual(warnings(plan), [])

    def test_warnings_do_not_change_the_plan_or_its_hash(self):
        plan = build_plan(self.registry, SUBJECT, requests_all())
        before = plan_hash(plan)
        warnings(plan)
        self.assertEqual(plan_hash(plan), before)
        self.assertEqual(set(plan), {"subject", "steps"})


if __name__ == "__main__":
    unittest.main()
