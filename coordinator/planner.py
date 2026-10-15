"""Planner foundations: canonical JSON and the single plan hash.

v0.1 holds only the canonical encoding and hash. Plan building and
advisory warnings arrive in v0.5.
"""

import hashlib
import json


def canonical_json(obj):
    """Return the canonical bytes (pure ASCII) of a JSON value.

    Sorted keys, no whitespace, non-ASCII escaped, NaN and Infinity
    rejected so one value has exactly one encoding.
    """
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def plan_hash(plan):
    """Return the SHA-256 hex digest of the canonical encoding of a plan."""
    return hashlib.sha256(canonical_json(plan)).hexdigest()
