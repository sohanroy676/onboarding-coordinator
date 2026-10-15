"""Gate G2: delegation. Token attacks against all three real domains.

The domains run in this process on port 0 with an injected clock, the same
way test_g1 runs them. Valid tokens come from the real TokenMinter. Attack
tokens are forged here, so each attack breaks exactly one property.
"""

import base64
import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from coordinator.tokens import TokenMinter, derive_domain_key
from domains import facilities_agent, hr_agent, it_agent
from domains.domain_agent import DomainAgent, make_server
from ledger.ledger import read_entries, verify_file
from tests.helpers import FakeClock

SECRET = "g2-exchange-secret"
RUN = "run-g2"
HIRE = "new.hire@example.test"
TTL = 60
MODULES = {"hr": hr_agent, "it": it_agent, "facilities": facilities_agent}
NAMES = tuple(MODULES)
_MISSING = object()  # stands for a body with no token key at all


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def encode_claims(claims):
    body = json.dumps(claims, sort_keys=True, separators=(",", ":"))
    return _b64(body.encode("ascii"))


def sign(payload, key):
    mac = hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest()
    return _b64(mac)


def forge(claims, key):
    """Sign claims with raw key bytes. Used only for attack tokens."""
    payload = encode_claims(claims)
    return payload + "." + sign(payload, key)


def claims_for(domain, scope, now=1000):
    return {
        "sub": HIRE,
        "act": "coordinator",
        "aud": domain,
        "scope": sorted(scope),
        "iat": now,
        "exp": now + TTL,
        "jti": "f" * 32,
        "run_id": RUN,
    }


def call(port, body):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:%d/execute" % port, data=data, method="POST"
    )
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("ascii"))
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("ascii"))


class DelegationGateTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.minter = TokenMinter(SECRET, self.clock, ttl_seconds=TTL)
        self.state = {}
        self.servers = {}
        self.ports = {}
        self.agents = {}
        for name in NAMES:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.state[name] = Path(tmp.name)
            self.start(name)

    def start(self, name):
        key = derive_domain_key(SECRET, name)
        agent = DomainAgent(MODULES[name].SPEC, key, self.state[name], self.clock)
        server = make_server(agent, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        self.agents[name] = agent
        self.servers[name] = (server, thread)
        self.ports[name] = server.server_address[1]
        self.addCleanup(self.stop, name)

    def stop(self, name):
        if name not in self.servers:
            return
        server, thread = self.servers.pop(name)
        server.shutdown()
        server.server_close()
        thread.join(5)

    def restart(self, name):
        self.stop(name)
        self.start(name)

    def spec(self, name):
        return MODULES[name].SPEC

    def execute(self, name, token, actions):
        body = {"actions": [{"name": action} for action in actions]}
        if token is not _MISSING:
            body["token"] = token
        return call(self.ports[name], body)

    def ledger(self, name):
        return read_entries(self.agents[name].ledger_path)

    def events(self, name, event):
        return [entry for entry in self.ledger(name) if entry["event"] == event]

    def assert_nothing_executed(self, name):
        self.assertEqual(self.events(name, "action_executed"), [])

    def assert_rejected_as(self, name, code):
        self.assertEqual(self.events(name, "token_rejected")[-1]["data"]["reason"], code)


class WrongDomainTests(DelegationGateTests):
    def test_token_for_one_domain_is_refused_by_each_other_domain(self):
        for owner in NAMES:
            scope = [self.spec(owner).capabilities[0]]
            for target in NAMES:
                if target == owner:
                    continue
                token = self.minter.mint(HIRE, owner, scope, RUN)
                status, body = self.execute(target, token, scope)
                self.assertEqual((status, body), (403, {"error": "domain_mismatch"}))
                self.assert_rejected_as(target, "domain_mismatch")
                self.assert_nothing_executed(target)


class MalformedTokenTests(DelegationGateTests):
    def test_missing_or_broken_tokens_are_malformed(self):
        broken = [None, "", 7, "abc", "a.b.c", "!!.!!", ".", SECRET, "x" * 5000]
        for name in NAMES:
            action = self.spec(name).capabilities[0]
            for token in broken:
                status, body = self.execute(name, token, [action])
                self.assertEqual((status, body), (400, {"error": "malformed_token"}))
            status, body = self.execute(name, _MISSING, [action])
            self.assertEqual((status, body), (400, {"error": "malformed_token"}))
            self.assertEqual(
                len(self.events(name, "token_rejected")), len(broken) + 1
            )
            self.assert_nothing_executed(name)


class ForgedSignatureTests(DelegationGateTests):
    def test_exchange_secret_cannot_sign_a_token(self):
        for name in NAMES:
            scope = [self.spec(name).capabilities[0]]
            unlabelled = hmac.new(SECRET.encode("utf-8"), name.encode("ascii"), hashlib.sha256)
            keys = (
                SECRET.encode("utf-8"),
                unlabelled.digest(),
                bytes(32),
            )
            for key in keys:
                token = forge(claims_for(name, scope), key)
                status, body = self.execute(name, token, scope)
                self.assertEqual((status, body), (401, {"error": "invalid_signature"}))
                self.assert_rejected_as(name, "invalid_signature")
            self.assert_nothing_executed(name)

    def test_widened_scope_with_real_signature_is_refused(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            forbidden = self.spec(name).will_not[0]
            real = self.minter.mint(HIRE, name, [own], RUN)
            _payload, signature = real.split(".")
            widened = encode_claims(claims_for(name, [own, forbidden]))
            token = widened + "." + signature
            status, body = self.execute(name, token, [own])
            self.assertEqual((status, body), (401, {"error": "invalid_signature"}))
            self.assert_rejected_as(name, "invalid_signature")
            self.assert_nothing_executed(name)

    def test_edited_claims_keep_the_old_signature_and_are_refused(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            real = self.minter.mint(HIRE, name, [own], RUN)
            _payload, signature = real.split(".")
            claims = claims_for(name, [own])
            claims["sub"] = "someone.else@example.test"
            token = encode_claims(claims) + "." + signature
            status, body = self.execute(name, token, [own])
            self.assertEqual((status, body), (401, {"error": "invalid_signature"}))
            self.assert_nothing_executed(name)


class ExpiryAndReplayTests(DelegationGateTests):
    def test_token_is_valid_one_second_before_expiry(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            token = self.minter.mint(HIRE, name, [own], RUN)
            self.clock.advance(TTL - 1)
            status, _body = self.execute(name, token, [own])
            self.assertEqual(status, 200)

    def test_expired_token_is_refused_at_expiry(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            token = self.minter.mint(HIRE, name, [own], RUN)
            self.clock.advance(TTL)
            status, body = self.execute(name, token, [own])
            self.assertEqual((status, body), (401, {"error": "token_expired"}))
            self.assert_rejected_as(name, "token_expired")
            self.assert_nothing_executed(name)

    def test_replay_is_refused_before_and_after_restart(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            token = self.minter.mint(HIRE, name, [own], RUN)
            self.assertEqual(self.execute(name, token, [own])[0], 200)
            status, body = self.execute(name, token, [own])
            self.assertEqual((status, body), (401, {"error": "token_replayed"}))
            self.restart(name)
            status, body = self.execute(name, token, [own])
            self.assertEqual((status, body), (401, {"error": "token_replayed"}))
            self.assert_rejected_as(name, "token_replayed")
            self.assertEqual(len(self.events(name, "action_executed")), 1)
            self.assertEqual(verify_file(self.agents[name].ledger_path), (True, None))


class ScopeAndWillNotTests(DelegationGateTests):
    def test_will_not_action_is_refused_inside_a_valid_token(self):
        for name in NAMES:
            own = self.spec(name).capabilities[0]
            forbidden = self.spec(name).will_not[0]
            token = self.minter.mint(HIRE, name, [own, forbidden], RUN)
            status, body = self.execute(name, token, [own, forbidden])
            self.assertEqual(status, 200)
            self.assertEqual([r["outcome"] for r in body["results"]], ["executed", "refused"])
            self.assertEqual(body["results"][1]["reason"], "will_not")
            pairs = [(e["event"], e["data"]["action"]) for e in self.ledger(name)]
            self.assertEqual(
                pairs,
                [("action_executed", own), ("action_refused", forbidden)],
            )

    def test_action_outside_token_scope_is_refused(self):
        for name in NAMES:
            caps = self.spec(name).capabilities
            token = self.minter.mint(HIRE, name, [caps[0]], RUN)
            status, body = self.execute(name, token, [caps[1]])
            self.assertEqual(status, 200)
            self.assertEqual(body["results"][0]["reason"], "out_of_scope")
            pairs = [(e["event"], e["data"]["action"]) for e in self.ledger(name)]
            self.assertEqual(pairs, [("action_refused", caps[1])])


if __name__ == "__main__":
    unittest.main()
