"""Shared fixtures: an injected clock and a spec-based token checker.

verify_token re-implements the token spec only to prove tokens.py
round-trips. The real verifier lives in domains/domain_agent.py (v0.2).
"""

import base64
import hashlib
import hmac
import json


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_token(token, domain_key_hex, now):
    """Return claims, or raise ValueError with a short reason."""
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("malformed_token")
    payload, signature = parts
    expected = hmac.new(
        bytes.fromhex(domain_key_hex), payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, _unb64(signature)):
        raise ValueError("invalid_signature")
    claims = json.loads(_unb64(payload))
    if now >= claims["exp"]:
        raise ValueError("token_expired")
    return claims
