import base64
import hashlib
import hmac
import json
import unittest

from coordinator.tokens import TokenMinter, derive_domain_key
from domains.domain_agent import TokenError, verify_token
from tests.helpers import FakeClock
from tests.helpers import verify_token as spec_verify_token

SECRET = "unit-test-exchange-secret"
RUN = "run-0001"
HIRE = "new.hire@example.test"
APPROVAL_ID = "b" * 32
GOOD_CLAIMS = {
    "sub": HIRE,
    "act": "coordinator",
    "aud": "hr",
    "scope": ["create_record"],
    "iat": 1000,
    "exp": 1060,
    "jti": "a" * 32,
    "run_id": RUN,
    "approval_id": APPROVAL_ID,
}


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def hand_token(claims, key_hex, sign=True):
    """Build a token by hand so tests can break one property at a time."""
    body = json.dumps(claims, sort_keys=True, separators=(",", ":"))
    payload = _b64(body.encode("ascii"))
    if not sign:
        return payload + "." + _b64(b"x" * 32)
    mac = hmac.new(bytes.fromhex(key_hex), payload.encode("ascii"), hashlib.sha256)
    return payload + "." + _b64(mac.digest())


class VerifyOrderTests(unittest.TestCase):
    def setUp(self):
        self.key = derive_domain_key(SECRET, "hr")
        self.other = derive_domain_key(SECRET, "it")

    def check(self, token, now=1000, seen=()):
        return verify_token(token, "hr", self.key, now, set(seen), set())

    def code(self, token, **kwargs):
        with self.assertRaises(TokenError) as caught:
            self.check(token, **kwargs)
        return caught.exception.code

    def test_valid_token_returns_claims(self):
        claims = self.check(hand_token(GOOD_CLAIMS, self.key))
        self.assertEqual(claims, GOOD_CLAIMS)

    def test_malformed_variants(self):
        good = hand_token(GOOD_CLAIMS, self.key)
        payload = good.split(".")[0]
        bad_values = [
            None, 7, b"bytes", "", "no-dot", good + ".extra", ".", payload + ".",
            "." + good.split(".")[1], "!!!." + good.split(".")[1],
            payload + ".!!!", "a" * 5000, _b64(b"not json") + ".AAAA",
            _b64(b"[1,2]") + ".AAAA", _b64(b"\xff\xfe") + ".AAAA",
        ]
        for bad in bad_values:
            self.assertEqual(self.code(bad), "malformed_token", msg=repr(bad))

    def test_malformed_claims(self):
        broken = []
        for name in GOOD_CLAIMS:
            missing = dict(GOOD_CLAIMS)
            del missing[name]
            broken.append(missing)
        broken.append(dict(GOOD_CLAIMS, extra="x"))
        broken.append(dict(GOOD_CLAIMS, scope=[]))
        broken.append(dict(GOOD_CLAIMS, scope="create_record"))
        broken.append(dict(GOOD_CLAIMS, scope=[1]))
        broken.append(dict(GOOD_CLAIMS, exp="1060"))
        broken.append(dict(GOOD_CLAIMS, exp=True))
        broken.append(dict(GOOD_CLAIMS, jti=""))
        for claims in broken:
            token = hand_token(claims, self.key)
            self.assertEqual(self.code(token), "malformed_token", msg=repr(claims))

    def test_domain_mismatch(self):
        token = hand_token(dict(GOOD_CLAIMS, aud="it"), self.other)
        self.assertEqual(self.code(token), "domain_mismatch")

    def test_invalid_signature_variants(self):
        wrong_key = hand_token(GOOD_CLAIMS, self.other)
        self.assertEqual(self.code(wrong_key), "invalid_signature")
        unsigned = hand_token(GOOD_CLAIMS, self.key, sign=False)
        self.assertEqual(self.code(unsigned), "invalid_signature")
        good = hand_token(GOOD_CLAIMS, self.key)
        tampered = hand_token(dict(GOOD_CLAIMS, scope=["enroll_benefits"]), self.key)
        forged = tampered.split(".")[0] + "." + good.split(".")[1]
        self.assertEqual(self.code(forged), "invalid_signature")

    def test_exchange_secret_is_not_a_signing_key(self):
        token = hand_token(GOOD_CLAIMS, SECRET.encode("ascii").hex())
        self.assertEqual(self.code(token), "invalid_signature")

    def test_expiry_boundary(self):
        token = hand_token(GOOD_CLAIMS, self.key)
        self.check(token, now=1059)
        self.assertEqual(self.code(token, now=1060), "token_expired")
        self.assertEqual(self.code(token, now=5000), "token_expired")

    def test_replay(self):
        token = hand_token(GOOD_CLAIMS, self.key)
        self.assertEqual(self.code(token, seen=["a" * 32]), "token_replayed")

    def test_order_of_checks(self):
        replayed = ["a" * 32]
        both = hand_token(dict(GOOD_CLAIMS, aud="it"), self.key, sign=False)
        self.assertEqual(self.code(both), "domain_mismatch")
        expired_bad_sig = hand_token(GOOD_CLAIMS, self.other)
        self.assertEqual(
            self.code(expired_bad_sig, now=2000), "invalid_signature"
        )
        expired_replayed = hand_token(GOOD_CLAIMS, self.key)
        self.assertEqual(
            self.code(expired_replayed, now=2000, seen=replayed), "token_expired"
        )

    def test_error_carries_run_id_once_claims_parse(self):
        token = hand_token(dict(GOOD_CLAIMS, aud="it"), self.other)
        with self.assertRaises(TokenError) as caught:
            self.check(token)
        self.assertEqual(caught.exception.run_id, RUN)
        with self.assertRaises(TokenError) as caught:
            self.check("garbage")
        self.assertIsNone(caught.exception.run_id)


class MinterAgreementTests(unittest.TestCase):
    """The real verifier, the spec checker and the minter must agree."""

    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.minter = TokenMinter(SECRET, self.clock, ttl_seconds=60)

    def test_minted_tokens_verify_for_every_domain(self):
        for domain in ("hr", "it", "facilities"):
            key = derive_domain_key(SECRET, domain)
            token = self.minter.mint(HIRE, domain, ["b", "a", "a"], RUN, APPROVAL_ID)
            real = verify_token(token, domain, key, self.clock(), set(), set())
            spec = spec_verify_token(token, key, self.clock())
            self.assertEqual(real, spec)
            self.assertEqual(real["aud"], domain)
            self.assertEqual(real["scope"], ["a", "b"])
            self.assertEqual(real["sub"], HIRE)
            self.assertEqual(real["act"], "coordinator")
            self.assertEqual(real["run_id"], RUN)

    def test_minted_token_for_one_domain_fails_at_another(self):
        token = self.minter.mint(HIRE, "hr", ["create_record"], RUN, APPROVAL_ID)
        key_it = derive_domain_key(SECRET, "it")
        with self.assertRaises(TokenError) as caught:
            verify_token(token, "it", key_it, self.clock(), set(), set())
        self.assertEqual(caught.exception.code, "domain_mismatch")

    def test_expiry_agrees_with_spec_checker(self):
        key = derive_domain_key(SECRET, "hr")
        token = self.minter.mint(HIRE, "hr", ["create_record"], RUN, APPROVAL_ID)
        for now in (1000, 1059, 1060, 1061):
            try:
                spec_verify_token(token, key, now)
                spec_ok = True
            except ValueError:
                spec_ok = False
            try:
                verify_token(token, "hr", key, now, set(), set())
                real_ok = True
            except TokenError:
                real_ok = False
            self.assertEqual(spec_ok, real_ok, msg="now=%d" % now)

    def test_each_minted_token_has_a_fresh_jti(self):
        seen = set()
        for _ in range(20):
            token = self.minter.mint(HIRE, "hr", ["create_record"], RUN, APPROVAL_ID)
            key = derive_domain_key(SECRET, "hr")
            claims = verify_token(token, "hr", key, self.clock(), seen, set())
            self.assertNotIn(claims["jti"], seen)
            seen.add(claims["jti"])


if __name__ == "__main__":
    unittest.main()


class ApprovalReplayVerifyTests(unittest.TestCase):
    def setUp(self):
        self.key = derive_domain_key(SECRET, "hr")

    def test_approval_seen_before_is_refused_as_replayed(self):
        token = hand_token(GOOD_CLAIMS, self.key)
        with self.assertRaises(TokenError) as caught:
            verify_token(token, "hr", self.key, 1000, set(), {APPROVAL_ID})
        self.assertEqual(caught.exception.code, "approval_replayed")

    def test_signature_is_checked_before_the_approval_check(self):
        other = derive_domain_key(SECRET, "it")
        token = hand_token(GOOD_CLAIMS, other)
        with self.assertRaises(TokenError) as caught:
            verify_token(token, "hr", self.key, 1000, set(), {APPROVAL_ID})
        self.assertEqual(caught.exception.code, "invalid_signature")

    def test_token_without_an_approval_id_is_malformed(self):
        claims = dict(GOOD_CLAIMS)
        del claims["approval_id"]
        token = hand_token(claims, self.key)
        with self.assertRaises(TokenError) as caught:
            verify_token(token, "hr", self.key, 1000, set(), set())
        self.assertEqual(caught.exception.code, "malformed_token")
