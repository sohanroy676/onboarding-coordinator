"""Key derivation and one-domain token minting.

Minting lives only here; verification lives only in
domains/domain_agent.py. Token format:

    b64url(canonical claims) + "." + b64url(HMAC-SHA256(domain key, payload))

Claims: sub (new hire), act (coordinator), aud (one domain), scope
(sorted unique actions of that domain), iat, exp, jti, run_id.
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading

from coordinator.planner import canonical_json

DOMAIN_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
KEY_LABEL = b"oc-domain-key|"
ACTOR = "coordinator"
DEFAULT_TTL_SECONDS = 60


def _check_domain(domain):
    if not isinstance(domain, str) or not DOMAIN_NAME.fullmatch(domain):
        raise ValueError("invalid domain name")


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def keyed_digest(key, message):
    """Raw HMAC-SHA256. The coordinator's only MAC primitive, shared with approval."""
    return hmac.new(key, message, hashlib.sha256).digest()


def constant_time_equal(expected, given):
    """Compare two ASCII strings or two byte strings without leaking timing."""
    return hmac.compare_digest(expected, given)


def derive_domain_key(exchange_secret, domain):
    """Return the domain's key as a hex string (the OC_DOMAIN_KEY value)."""
    if not isinstance(exchange_secret, str) or not exchange_secret:
        raise ValueError("exchange secret must be a non-empty string")
    _check_domain(domain)
    digest = hmac.new(
        exchange_secret.encode("utf-8"),
        KEY_LABEL + domain.encode("ascii"),
        hashlib.sha256,
    )
    return digest.hexdigest()


class TokenMinter:
    """Mints short one-domain tokens and counts every exchange."""

    def __init__(self, exchange_secret, clock, ttl_seconds=DEFAULT_TTL_SECONDS):
        if not isinstance(exchange_secret, str) or not exchange_secret:
            raise ValueError("exchange secret must be a non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl must be positive")
        self._secret = exchange_secret
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._count = 0

    @property
    def exchange_count(self):
        with self._lock:
            return self._count

    def mint(self, subject, domain, scope, run_id, approval_id):
        """Mint one token for one domain; count it only once it is built."""
        if not isinstance(subject, str) or not subject:
            raise ValueError("subject must be a non-empty string")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(approval_id, str) or not approval_id:
            raise ValueError("approval_id must be a non-empty string")
        if isinstance(scope, str) or not scope:
            raise ValueError("scope must be a non-empty list of actions")
        if not all(isinstance(item, str) and item for item in scope):
            raise ValueError("scope entries must be non-empty strings")
        key = derive_domain_key(self._secret, domain)
        now = int(self._clock())
        claims = {
            "sub": subject,
            "act": ACTOR,
            "aud": domain,
            "scope": sorted(set(scope)),
            "iat": now,
            "exp": now + self._ttl,
            "jti": secrets.token_hex(16),
            "run_id": run_id,
            "approval_id": approval_id,
        }
        payload = _b64(canonical_json(claims))
        signature = hmac.new(
            bytes.fromhex(key), payload.encode("ascii"), hashlib.sha256
        ).digest()
        token = payload + "." + _b64(signature)
        with self._lock:
            self._count += 1
        return token
