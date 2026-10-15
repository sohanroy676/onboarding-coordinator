import re
import tempfile
import unittest
from pathlib import Path

import provision

ROOT = Path(__file__).resolve().parent.parent
EPHEMERAL = {"hr": 0, "it": 0, "facilities": 0}


class ChildEnvTests(unittest.TestCase):
    def test_child_env_holds_only_its_own_key(self):
        prov = provision.Provisioner(state_dir="s", ports=EPHEMERAL,
                                     exchange_secret="unit-secret")
        for name, spec, _module in provision.AGENTS:
            env = prov._child_env(name, spec, 1234)
            allowed = {"SYSTEMROOT", "PATH", "OC_DOMAIN_KEY", "OC_STATE_DIR",
                       spec.port_env}
            self.assertLessEqual(set(env), allowed)
            self.assertEqual(len(env["OC_DOMAIN_KEY"]), 64)
            self.assertNotIn("unit-secret", env.values())
            self.assertNotIn("OC_EXCHANGE_SECRET", env)
            self.assertNotIn("OC_APPROVAL_SECRET", env)

    def test_keys_differ_per_domain(self):
        prov = provision.Provisioner(ports=EPHEMERAL)
        keys = {
            name: prov._child_env(name, spec, 1)["OC_DOMAIN_KEY"]
            for name, spec, _m in provision.AGENTS
        }
        self.assertEqual(len(set(keys.values())), 3)

    def test_secret_is_random_per_provisioner(self):
        first = provision.Provisioner().exchange_secret
        second = provision.Provisioner().exchange_secret
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 32)

    def test_approval_secret_is_random_and_separate_from_exchange(self):
        first = provision.Provisioner()
        second = provision.Provisioner()
        self.assertGreaterEqual(len(first.approval_secret), 32)
        self.assertNotEqual(first.approval_secret, second.approval_secret)
        self.assertNotEqual(first.approval_secret, first.exchange_secret)


class ProcessTests(unittest.TestCase):
    def test_start_health_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = provision.Provisioner(state_dir=tmp, ports=EPHEMERAL)
            ports = prov.start()
            try:
                self.assertEqual(set(ports), {"hr", "it", "facilities"})
                self.assertTrue(all(port > 0 for port in ports.values()))
                prov.check_health()
                processes = list(prov._processes.values())
            finally:
                prov.stop()
            for process in processes:
                self.assertIsNotNone(process.poll())

    def test_bad_port_fails_and_leaves_no_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = provision.Provisioner(state_dir=tmp, ports={"hr": 70000})
            with self.assertRaises(provision.ProvisionError):
                prov.start()
            self.assertEqual(prov._processes, {})

    def test_start_failure_stops_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = provision.Provisioner(state_dir=tmp, ports=EPHEMERAL)
            ports = first.start()
            try:
                clash = provision.Provisioner(
                    state_dir=tmp, ports={"hr": ports["hr"]}
                )
                with self.assertRaises(provision.ProvisionError):
                    clash.start()
                self.assertEqual(clash._processes, {})
            finally:
                first.stop()


class BoundaryTests(unittest.TestCase):
    """Static checks of the invariants that gates G1 and G2 rely on."""

    def read_sources(self, folder):
        return {
            path.name: path.read_text(encoding="ascii")
            for path in (ROOT / folder).glob("*.py")
        }

    def test_domains_do_not_import_coordinator(self):
        pattern = re.compile(r"^\s*(from|import)\s+coordinator", re.MULTILINE)
        for name, text in self.read_sources("domains").items():
            self.assertIsNone(pattern.search(text), name)

    def test_coordinator_does_not_import_domains(self):
        pattern = re.compile(r"^\s*(from|import)\s+domains", re.MULTILINE)
        for name, text in self.read_sources("coordinator").items():
            self.assertIsNone(pattern.search(text), name)

    def test_only_domain_agent_verifies_and_only_tokens_mints(self):
        for name, text in self.read_sources("domains").items():
            if name != "domain_agent.py":
                self.assertNotIn("hmac", text, name)
        for name, text in self.read_sources("coordinator").items():
            if name != "tokens.py":
                self.assertNotIn("hmac", text, name)

    def test_no_package_markers_and_file_budget(self):
        total = 0
        for folder in ("domains", "coordinator", "ledger"):
            files = [p.name for p in (ROOT / folder).glob("*.py")]
            self.assertNotIn("__init__.py", files)
            total += len(files)
        self.assertLessEqual(total, 11)


if __name__ == "__main__":
    unittest.main()
