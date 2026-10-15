import dataclasses
import json
import unittest

from coordinator.registry import (
    DEFAULT_TTL_SECONDS,
    MAX_BODY_BYTES,
    Declaration,
    DeclarationInvalid,
    DeclarationMissing,
    DeclarationStale,
    DomainUnavailable,
    Registry,
    _parse_declaration,
)
from tests.helpers import FakeClock

GOOD = {
    "domain": "hr",
    "capabilities": ["create_record", "enroll_benefits"],
    "will_not": ["change_payroll"],
}
PORTS = {"hr": 9001, "it": 9002}


def encode(obj):
    return json.dumps(obj).encode("utf-8")


def variant(**changes):
    data = dict(GOOD)
    data.update(changes)
    return encode(data)


class FakeFetch:
    """Stands in for the HTTP GET; the test sets the next answer."""

    def __init__(self, status=200, body=None, error=None):
        self.status = status
        self.body = encode(GOOD) if body is None else body
        self.error = error
        self.calls = []

    def __call__(self, port, timeout):
        self.calls.append(port)
        if self.error is not None:
            raise self.error
        return self.status, self.body


class ParseTests(unittest.TestCase):
    def test_accepts_good_body_and_sorts_lists(self):
        body = variant(capabilities=["enroll_benefits", "create_record"])
        declaration = _parse_declaration("hr", body, 1000.0)
        self.assertEqual(declaration.domain, "hr")
        self.assertEqual(declaration.capabilities,
                         ("create_record", "enroll_benefits"))
        self.assertEqual(declaration.will_not, ("change_payroll",))
        self.assertEqual(declaration.received_at, 1000.0)

    def test_rejects_bad_bodies(self):
        cases = {
            "non-utf8": b"\xff\xfe\x00",
            "not json": b"{not json",
            "json list": encode(["hr"]),
            "json string": encode("hr"),
            "missing capabilities": encode(
                {"domain": "hr", "will_not": []}),
            "missing will_not": encode(
                {"domain": "hr", "capabilities": []}),
            "missing domain": encode(
                {"capabilities": [], "will_not": []}),
            "extra key": variant(timestamp=5),
            "capabilities not a list": variant(capabilities="create_record"),
            "will_not not a list": variant(will_not="change_payroll"),
            "non-string item": variant(capabilities=[1]),
            "boolean item": variant(capabilities=[True]),
            "null item": variant(capabilities=[None]),
            "empty item": variant(capabilities=[""]),
            "duplicate item": variant(capabilities=["a", "a"]),
            "overlap": variant(capabilities=["change_payroll"]),
            "wrong domain": variant(domain="it"),
            "oversize": b" " * (MAX_BODY_BYTES + 1),
        }
        for label, body in cases.items():
            with self.subTest(label):
                with self.assertRaises(DeclarationInvalid):
                    _parse_declaration("hr", body, 1000.0)

    def test_declaration_is_frozen(self):
        declaration = _parse_declaration("hr", encode(GOOD), 1000.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            declaration.received_at = 5.0


class ConstructorTests(unittest.TestCase):
    def test_rejects_bad_ports(self):
        for port in (0, 70000, True, "9001"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    Registry({"hr": port}, FakeClock())

    def test_rejects_non_positive_ttl(self):
        for ttl in (0, -1):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ValueError):
                    Registry(PORTS, FakeClock(), ttl_seconds=ttl)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.fetch = FakeFetch()
        self.registry = Registry(PORTS, self.clock, fetch=self.fetch)

    def test_refresh_stores_and_stamps_receipt_time(self):
        declaration = self.registry.refresh("hr")
        self.assertIsInstance(declaration, Declaration)
        self.assertEqual(declaration.received_at, 1000.0)
        self.assertEqual(self.fetch.calls, [9001])
        self.assertEqual(self.registry.declaration("hr"), declaration)

    def test_connection_error_is_unavailable(self):
        self.fetch.error = ConnectionRefusedError("refused")
        with self.assertRaises(DomainUnavailable):
            self.registry.refresh("hr")

    def test_timeout_is_unavailable(self):
        self.fetch.error = TimeoutError("slow")
        with self.assertRaises(DomainUnavailable):
            self.registry.refresh("hr")

    def test_non_200_status_is_unavailable(self):
        for status in (404, 405, 500):
            with self.subTest(status=status):
                self.fetch.status = status
                with self.assertRaises(DomainUnavailable):
                    self.registry.refresh("hr")

    def test_unknown_domain_is_keyerror(self):
        with self.assertRaises(KeyError):
            self.registry.refresh("payroll")
        with self.assertRaises(KeyError):
            self.registry.supports("payroll", "create_record")
        with self.assertRaises(KeyError):
            self.registry.declaration("payroll")
        with self.assertRaises(KeyError):
            self.registry.will_not("payroll")
        with self.assertRaises(KeyError):
            self.registry.classify("payroll", "create_record")

    def test_undiscovered_domain_is_missing_not_keyerror(self):
        with self.assertRaises(DeclarationMissing) as ctx:
            self.registry.supports("hr", "create_record")
        self.assertNotIsInstance(ctx.exception, KeyError)

    def test_failed_refresh_keeps_last_good_declaration(self):
        good = self.registry.refresh("hr")
        self.clock.advance(5)
        self.fetch.error = ConnectionRefusedError("down")
        with self.assertRaises(DomainUnavailable):
            self.registry.refresh("hr")
        self.assertEqual(self.registry.declaration("hr"), good)

    def test_malformed_refresh_keeps_last_good_declaration(self):
        good = self.registry.refresh("hr")
        self.clock.advance(5)
        self.fetch.body = b"not json"
        with self.assertRaises(DeclarationInvalid):
            self.registry.refresh("hr")
        self.assertEqual(self.registry.declaration("hr"), good)

    def test_refresh_all_stops_at_first_failure(self):
        self.fetch.error = ConnectionRefusedError("down")
        with self.assertRaises(DomainUnavailable) as ctx:
            self.registry.refresh_all()
        self.assertIn("hr", str(ctx.exception))
        self.assertEqual(self.fetch.calls, [9001])

    def test_classify_distinguishes_three_outcomes(self):
        self.registry.refresh("hr")
        self.assertEqual(self.registry.classify("hr", "create_record"),
                         "supported")
        self.assertEqual(self.registry.classify("hr", "change_payroll"),
                         "will_not")
        self.assertEqual(self.registry.classify("hr", "launch_rocket"),
                         "unsupported")

    def test_will_not_is_reported_not_filtered(self):
        self.registry.refresh("hr")
        self.assertEqual(self.registry.will_not("hr"), ("change_payroll",))
        self.assertFalse(self.registry.supports("hr", "change_payroll"))

    def test_supports_is_false_for_undeclared_action(self):
        self.registry.refresh("hr")
        self.assertFalse(self.registry.supports("hr", "launch_rocket"))


class StalenessTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.fetch = FakeFetch()
        self.registry = Registry(PORTS, self.clock, ttl_seconds=60,
                                 fetch=self.fetch)
        self.registry.refresh("hr")

    def test_exact_ttl_age_is_still_fresh(self):
        self.clock.advance(60)
        self.assertTrue(self.registry.supports("hr", "create_record"))

    def test_older_than_ttl_is_refused_everywhere(self):
        self.clock.advance(60.5)
        with self.assertRaises(DeclarationStale):
            self.registry.supports("hr", "create_record")
        with self.assertRaises(DeclarationStale):
            self.registry.declaration("hr")
        with self.assertRaises(DeclarationStale):
            self.registry.classify("hr", "create_record")
        with self.assertRaises(DeclarationStale):
            self.registry.will_not("hr")

    def test_refresh_makes_stale_domain_usable_again(self):
        self.clock.advance(61)
        with self.assertRaises(DeclarationStale):
            self.registry.supports("hr", "create_record")
        fresh = self.registry.refresh("hr")
        self.assertEqual(fresh.received_at, 1061.0)
        self.assertTrue(self.registry.supports("hr", "create_record"))

    def test_default_ttl_is_sixty_seconds(self):
        self.assertEqual(DEFAULT_TTL_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
