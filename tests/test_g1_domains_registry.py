"""Gate G1: domains and registry, over real HTTP on port 0 and an injected clock."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import provision
from coordinator.registry import (
    DeclarationInvalid,
    DeclarationMissing,
    DeclarationStale,
    DomainUnavailable,
    Registry,
)
from coordinator.tokens import derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from tests.helpers import FakeClock

SECRET = "g1-exchange-secret"
TTL = 60
MODULES = {"hr": hr_agent, "it": it_agent, "facilities": facilities_agent}
EPHEMERAL = {"hr": 0, "it": 0, "facilities": 0}


def start_thread(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


class StubServer:
    """Answers every GET with a fixed status and body; the real domains never do this."""

    def __init__(self, status, body):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(outer.body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.status = status
        self.body = body
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = start_thread(self.server)

    def close(self):
        stop_server(self.server, self.thread)


class DomainsDiscoveryTests(unittest.TestCase):
    """Three real domain servers, discovered by the registry over HTTP."""

    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.ports = {}
        self.servers = {}
        for name, module in MODULES.items():
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            key = derive_domain_key(SECRET, name)
            agent = DomainAgent(module.SPEC, key, Path(tmp.name), self.clock)
            server = make_server(agent, port=0)
            thread = start_thread(server)
            self.addCleanup(stop_server, server, thread)
            self.servers[name] = (server, thread)
            self.ports[name] = server.server_address[1]
        self.registry = Registry(self.ports, self.clock, ttl_seconds=TTL)
        self.registry.refresh_all()

    def test_three_real_domains_are_discovered(self):
        for name, module in MODULES.items():
            with self.subTest(domain=name):
                declaration = self.registry.declaration(name)
                self.assertEqual(declaration.domain, name)
                self.assertEqual(declaration.capabilities,
                                 tuple(sorted(module.CAPABILITIES)))
                self.assertEqual(declaration.will_not,
                                 tuple(sorted(module.WILL_NOT)))
                self.assertEqual(declaration.received_at, 1000.0)

    def test_declared_capabilities_are_supported(self):
        self.assertTrue(self.registry.supports("hr", "create_record"))
        self.assertTrue(self.registry.supports("it", "assign_laptop"))
        self.assertTrue(self.registry.supports("facilities", "issue_badge"))

    def test_will_not_actions_are_reported_not_dropped(self):
        self.assertEqual(self.registry.classify("hr", "change_payroll"),
                         "will_not")
        self.assertEqual(self.registry.classify("it", "grant_admin_access"),
                         "will_not")
        self.assertEqual(self.registry.classify("facilities", "disable_alarm"),
                         "will_not")
        self.assertIn("change_payroll", self.registry.will_not("hr"))
        self.assertFalse(self.registry.supports("hr", "change_payroll"))

    def test_undeclared_action_is_unsupported(self):
        self.assertEqual(self.registry.classify("it", "launch_rocket"),
                         "unsupported")

    def test_unknown_domain_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.registry.supports("payroll", "create_record")
        with self.assertRaises(KeyError):
            self.registry.declaration("payroll")
        with self.assertRaises(KeyError):
            self.registry.will_not("payroll")

    def test_forced_stale_declaration_is_refused_then_refreshed(self):
        self.clock.advance(TTL + 1)
        with self.assertRaises(DeclarationStale):
            self.registry.supports("hr", "create_record")
        with self.assertRaises(DeclarationStale):
            self.registry.declaration("hr")
        with self.assertRaises(DeclarationStale):
            self.registry.classify("hr", "create_record")
        self.registry.refresh("hr")
        self.assertTrue(self.registry.supports("hr", "create_record"))

    def test_rubric_figures_declaration_0_1s_old_with_max_0_01s_is_refused(self):
        registry = Registry(self.ports, self.clock, ttl_seconds=0.01)
        registry.refresh_all()
        self.clock.advance(0.1)
        with self.assertRaises(DeclarationStale) as raised:
            registry.supports("hr", "create_record")
        self.assertIn("0.1s old", str(raised.exception))
        self.assertIn("TTL is 0.01s", str(raised.exception))
        with self.assertRaises(KeyError):
            registry.supports("payroll", "create_record")

    def test_exact_ttl_age_is_fresh_and_one_more_second_is_stale(self):
        self.clock.advance(TTL)
        self.assertTrue(self.registry.supports("it", "assign_laptop"))
        self.clock.advance(1)
        with self.assertRaises(DeclarationStale):
            self.registry.supports("it", "assign_laptop")

    def test_unreachable_domain_is_unavailable(self):
        server, thread = self.servers["hr"]
        stop_server(server, thread)
        with self.assertRaises(DomainUnavailable):
            self.registry.refresh("hr")

    def test_failed_refresh_keeps_last_good_declaration(self):
        before = self.registry.declaration("hr")
        server, thread = self.servers["hr"]
        stop_server(server, thread)
        self.clock.advance(5)
        with self.assertRaises(DomainUnavailable):
            self.registry.refresh("hr")
        self.assertEqual(self.registry.declaration("hr"), before)

    def test_never_discovered_domain_is_missing(self):
        registry = Registry({"hr": self.ports["hr"]}, self.clock, ttl_seconds=TTL)
        with self.assertRaises(DeclarationMissing):
            registry.supports("hr", "create_record")

    def test_answering_as_another_domain_is_refused(self):
        registry = Registry({"it": self.ports["hr"]}, self.clock, ttl_seconds=TTL)
        with self.assertRaises(DeclarationInvalid):
            registry.refresh("it")


class BadAnswerTests(unittest.TestCase):
    """Responses a real domain never sends, served by stub servers on port 0."""

    def setUp(self):
        self.clock = FakeClock(1000.0)

    def probe(self, status, body):
        stub = StubServer(status, body)
        self.addCleanup(stub.close)
        registry = Registry({"it": stub.port}, self.clock, ttl_seconds=TTL)
        return registry

    def test_503_is_unavailable(self):
        registry = self.probe(503, json.dumps({"error": "down"}).encode())
        with self.assertRaises(DomainUnavailable):
            registry.refresh("it")

    def test_non_json_200_is_invalid(self):
        registry = self.probe(200, b"not json")
        with self.assertRaises(DeclarationInvalid):
            registry.refresh("it")

    def test_missing_will_not_is_invalid(self):
        body = json.dumps({"domain": "it", "capabilities": []}).encode()
        registry = self.probe(200, body)
        with self.assertRaises(DeclarationInvalid):
            registry.refresh("it")


class ProvisionerPortZeroTests(unittest.TestCase):
    """Real child processes started with port 0; the READY line reports the port."""

    def test_registry_discovers_children_started_on_port_zero(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = FakeClock(1000.0)
        with provision.Provisioner(state_dir=tmp.name, ports=EPHEMERAL,
                                   exchange_secret=SECRET) as prov:
            registry = Registry(prov.ports, clock, ttl_seconds=TTL)
            registry.refresh_all()
            self.assertTrue(registry.supports("hr", "create_record"))
            self.assertEqual(registry.classify("facilities", "disable_alarm"),
                             "will_not")


if __name__ == "__main__":
    unittest.main()
