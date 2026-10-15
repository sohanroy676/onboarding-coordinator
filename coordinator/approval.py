"""Plan approval: sign one plan hash, verify it in order, consume it once.

The approver signs the plan hash. The coordinator verifies, in this order:
tag, expiry, re-derived plan hash, then consumes it by creating a marker
file in exclusive mode. Exactly one concurrent consume can win, and a
replay is refused even after a restart because the marker is on disk.
A check that fails writes no marker. Format is fixed in ADR-0004.

    tag = HMAC-SHA256(approval key, canonical({approval_id, plan_hash, expires_at}))
    approval key = HMAC-SHA256(approval secret, b"oc-approval|")
"""

import re
import secrets
from pathlib import Path

from coordinator.planner import canonical_json, plan_hash
from coordinator.tokens import constant_time_equal, keyed_digest

APPROVAL_LABEL = b"oc-approval|"
APPROVAL_ID = re.compile(r"[0-9a-f]{32}")
APPROVAL_FIELDS = frozenset({"approval_id", "plan_hash", "expires_at", "tag"})
DEFAULT_TTL_SECONDS = 300


class ApprovalError(Exception):
    """Base class for every approval refusal; code is the ledger-visible name."""

    code = "approval_error"


class ApprovalTagInvalid(ApprovalError):
    code = "invalid_approval_tag"


class ApprovalExpired(ApprovalError):
    code = "approval_expired"


class PlanChangedSinceApproval(ApprovalError):
    code = "plan_changed_since_approval"


class ApprovalAlreadyConsumed(ApprovalError):
    code = "approval_already_consumed"


def _check_secret(approval_secret):
    if not isinstance(approval_secret, str) or not approval_secret:
        raise ValueError("approval secret must be a non-empty string")


def derive_approval_key(approval_secret):
    """Return the approval signing key as bytes."""
    _check_secret(approval_secret)
    return keyed_digest(approval_secret.encode("utf-8"), APPROVAL_LABEL)


def _tag(key, approval_id, digest, expires_at):
    message = canonical_json({
        "approval_id": approval_id,
        "plan_hash": digest,
        "expires_at": expires_at,
    })
    return keyed_digest(key, message).hex()


class Approver:
    """Signs the hash of one plan. Used by the approver step only."""

    def __init__(self, approval_secret, clock, ttl_seconds=DEFAULT_TTL_SECONDS):
        self._key = derive_approval_key(approval_secret)
        if ttl_seconds <= 0:
            raise ValueError("ttl must be positive")
        self._clock = clock
        self._ttl = ttl_seconds

    def approve(self, plan):
        """Return a fresh approval for this plan; each call gets a new id."""
        digest = plan_hash(plan)
        approval_id = secrets.token_hex(16)
        expires_at = int(self._clock()) + self._ttl
        return {
            "approval_id": approval_id,
            "plan_hash": digest,
            "expires_at": expires_at,
            "tag": _tag(self._key, approval_id, digest, expires_at),
        }


class ApprovalGate:
    """Verifies an approval against a plan and consumes it once."""

    def __init__(self, approval_secret, clock, markers_dir):
        self._key = derive_approval_key(approval_secret)
        self._clock = clock
        self._markers = Path(markers_dir)

    def verify_and_consume(self, approval, plan):
        """Raise an ApprovalError subclass, or consume the approval and return."""
        approval_id, digest, expires_at = self._check_tag(approval)
        if int(self._clock()) >= expires_at:
            raise ApprovalExpired("approval has expired")
        if plan_hash(plan) != digest:
            raise PlanChangedSinceApproval("the plan differs from the approved plan")
        self._consume(approval_id, digest)

    def _check_tag(self, approval):
        if not isinstance(approval, dict) or set(approval) != APPROVAL_FIELDS:
            raise ApprovalTagInvalid("approval has the wrong fields")
        approval_id = approval["approval_id"]
        digest = approval["plan_hash"]
        expires_at = approval["expires_at"]
        tag = approval["tag"]
        if not isinstance(approval_id, str) or not APPROVAL_ID.fullmatch(approval_id):
            raise ApprovalTagInvalid("approval id is malformed")
        if not isinstance(digest, str) or not isinstance(tag, str) or not tag.isascii():
            raise ApprovalTagInvalid("approval fields have the wrong type")
        if not isinstance(expires_at, int) or isinstance(expires_at, bool):
            raise ApprovalTagInvalid("expiry must be an integer")
        expected = _tag(self._key, approval_id, digest, expires_at)
        if not constant_time_equal(expected, tag):
            raise ApprovalTagInvalid("approval tag does not verify")
        return approval_id, digest, expires_at

    def _consume(self, approval_id, digest):
        self._markers.mkdir(parents=True, exist_ok=True)
        path = self._markers / (approval_id + ".consumed")
        try:
            with open(path, "x", encoding="ascii") as handle:
                record = canonical_json({"approval_id": approval_id,
                                         "plan_hash": digest})
                handle.write(record.decode("ascii") + "\n")
        except FileExistsError as exc:
            raise ApprovalAlreadyConsumed("approval was already consumed") from exc
