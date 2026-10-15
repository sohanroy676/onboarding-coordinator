import tempfile
import threading
import unittest
from pathlib import Path

from coordinator.tokens import TokenMinter, derive_domain_key
from tests.helpers import FakeClock, verify_token

SECRET = "unit-test-exchange-secret"
SCOPE_IT = ["create_account", "assign_laptop"]


class DeriveKeyTests(unittest.TestCase):
    def test_deterministic_and_hex(self):
        first = derive_domain_key(SECRET, "hr")
        self.assertEqual(first, derive_domain_key(SECRET, "hr"))
        self.assertEqual(len(first), 64)
        bytes.fromhex(first)

    def test_distinct_per_domain_and_per_secret(self):
        hr = derive_domain_key(SECRET, "hr")
        self.assertNotEqual(hr, derive_domain_key(SECRET, "it"))
        self.assertNotEqual(hr, derive_domain_key("another-secret", "hr"))
        self.assertNotEqual(hr, SECRET)

    def test_bad_domain_names_rejected(self):
        for bad in ("", "HR", "h r", "hr|it", "../hr", "h\u00e9", "a" * 33, None, 7):
            with self.assertRaises(ValueError, msg=repr(bad)):
                derive_domain_key(SECRET, bad)

    def test_bad_secret_rejected(self):
        for bad in ("", None, b"bytes"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                derive_domain_key(bad, "hr")


class MintTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.minter = TokenMinter(SECRET, self.clock, ttl_seconds=60)

    def test_claims_are_one_domain_and_exact_scope(self):
        token = self.minter.mint("alice", "it", SCOPE_IT, "run-1")
        claims = verify_token(token, derive_domain_key(SECRET, "it"), 1000)
        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["act"], "coordinator")
        self.assertEqual(claims["aud"], "it")
        self.assertEqual(claims["scope"], sorted(SCOPE_IT))
        self.assertEqual(claims["iat"], 1000)
        self.assertEqual(claims["exp"], 1060)
        self.assertEqual(claims["run_id"], "run-1")

    def test_other_domain_key_rejects_token(self):
        token = self.minter.mint("alice", "it", SCOPE_IT, "run-1")
        with self.assertRaises(ValueError) as caught:
            verify_token(token, derive_domain_key(SECRET, "hr"), 1000)
        self.assertEqual(str(caught.exception), "invalid_signature")

    def test_tampered_payload_or_signature_detected(self):
        token = self.minter.mint("alice", "it", SCOPE_IT, "run-1")
        key = derive_domain_key(SECRET, "it")
        payload, signature = token.split(".")
        flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
        with self.assertRaises(ValueError):
            verify_token(flipped + "." + signature, key, 1000)
        flipped_sig = ("A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaises(ValueError):
            verify_token(payload + "." + flipped_sig, key, 1000)
        with self.assertRaises(ValueError):
            verify_token("nodot", key, 1000)

    def test_expiry_follows_injected_clock(self):
        token = self.minter.mint("alice", "hr", ["create_record"], "run-1")
        key = derive_domain_key(SECRET, "hr")
        verify_token(token, key, 1059)
        with self.assertRaises(ValueError) as caught:
            verify_token(token, key, 1060)
        self.assertEqual(str(caught.exception), "token_expired")

    def test_jti_unique(self):
        ids = set()
        for _ in range(50):
            token = self.minter.mint("alice", "hr", ["create_record"], "run-1")
            claims = verify_token(token, derive_domain_key(SECRET, "hr"), 1000)
            ids.add(claims["jti"])
        self.assertEqual(len(ids), 50)

    def test_scope_is_deduplicated_and_sorted(self):
        token = self.minter.mint("alice", "it", ["b", "a", "b"], "run-1")
        claims = verify_token(token, derive_domain_key(SECRET, "it"), 1000)
        self.assertEqual(claims["scope"], ["a", "b"])

    def test_secrets_not_in_token(self):
        token = self.minter.mint("alice", "it", SCOPE_IT, "run-1")
        self.assertNotIn(SECRET, token)
        self.assertNotIn(derive_domain_key(SECRET, "it"), token)

    def test_invalid_inputs_rejected_and_not_counted(self):
        bad_calls = [
            ("", "it", ["a"], "r"),
            ("alice", "IT", ["a"], "r"),
            ("alice", "it", [], "r"),
            ("alice", "it", "create_account", "r"),
            ("alice", "it", ["a", ""], "r"),
            ("alice", "it", [1], "r"),
            ("alice", "it", ["a"], ""),
        ]
        for args in bad_calls:
            with self.assertRaises(ValueError, msg=repr(args)):
                self.minter.mint(*args)
        self.assertEqual(self.minter.exchange_count, 0)

    def test_bad_constructor_args(self):
        with self.assertRaises(ValueError):
            TokenMinter("", self.clock)
        with self.assertRaises(ValueError):
            TokenMinter(SECRET, self.clock, ttl_seconds=0)


class ExchangeCounterTests(unittest.TestCase):
    def test_counts_one_per_mint(self):
        minter = TokenMinter(SECRET, FakeClock())
        self.assertEqual(minter.exchange_count, 0)
        for domain in ("hr", "it", "facilities"):
            minter.mint("alice", domain, ["x"], "run-1")
        self.assertEqual(minter.exchange_count, 3)

    def test_counter_is_thread_safe(self):
        minter = TokenMinter(SECRET, FakeClock())

        def work():
            for _ in range(100):
                minter.mint("alice", "hr", ["x"], "run-1")

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(minter.exchange_count, 800)


if __name__ == "__main__":
    unittest.main()


class PersistentCounterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_count_survives_a_new_minter_on_the_same_file(self):
        path = self.folder / "exchanges.log"
        first = TokenMinter(SECRET, FakeClock(), count_path=path)
        for domain in ("hr", "it"):
            first.mint("alice", domain, ["x"], "run-1")
        restarted = TokenMinter(SECRET, FakeClock(), count_path=path)
        self.assertEqual(restarted.exchange_count, 2)
        restarted.mint("alice", "facilities", ["x"], "run-2")
        self.assertEqual(restarted.exchange_count, 3)

    def test_each_mint_adds_exactly_one_line(self):
        path = self.folder / "exchanges.log"
        minter = TokenMinter(SECRET, FakeClock(), count_path=path)
        for domain in ("hr", "it", "facilities"):
            minter.mint("alice", domain, ["x"], "run-1")
        lines = path.read_text(encoding="ascii").splitlines()
        self.assertEqual(lines, ["1", "2", "3"])

    def test_failed_write_mints_no_token_and_does_not_count(self):
        blocker = self.folder / "blocker"
        blocker.write_text("a regular file, not a folder\n", encoding="ascii")
        minter = TokenMinter(SECRET, FakeClock(), count_path=blocker / "exchanges.log")
        self.assertEqual(minter.exchange_count, 0)
        with self.assertRaises(OSError):
            minter.mint("alice", "hr", ["x"], "run-1")
        self.assertEqual(minter.exchange_count, 0)

    def test_without_a_path_nothing_is_written(self):
        minter = TokenMinter(SECRET, FakeClock())
        minter.mint("alice", "hr", ["x"], "run-1")
        self.assertEqual(list(self.folder.iterdir()), [])
