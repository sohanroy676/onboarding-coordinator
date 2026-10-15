# ADR-0002: Canonical JSON, ledger, key and token formats

## Status
Accepted

## Date
2026-10-15

## Context
Several modules must agree byte for byte on how plans are hashed, how ledger
lines are chained and how tokens are built and keyed, but the project brief did
not fix these formats. They are hard to change once domains and auditors depend
on them.

## Decision
- Canonical JSON: sorted keys, separators "," and ":", ASCII-only escapes, NaN
  and Infinity rejected. Plan hash is SHA-256 hex of those bytes.
- Ledger: JSON Lines, fields seq (from 0), ts, run_id, event, data, prev_hash,
  hash. hash is SHA-256 of the canonical entry without hash. The first prev_hash
  is 64 zeros.
- Domain key: hex of HMAC-SHA256(exchange secret, "oc-domain-key|" + domain).
- Token: b64url(canonical claims) + "." + b64url(HMAC-SHA256(domain key,
  payload)). Claims: sub, act, aud, scope, iat, exp, jti, run_id, approval_id
  (approval_id added in the fix/approval-replay-domain amendment).
- Exchange counter: incremented once per successfully minted token.

## Alternatives considered
- JWT or HKDF libraries: third-party or heavier, and the project is stdlib only.
- Independent random domain keys: would need distribution outside provision.py;
  derivation keeps one secret to provision.

## Consequences
- ledger/ repeats the small canonical encoder because it may not import from
  coordinator/.
- A hash chain cannot detect removal of entries from the end of a ledger; the
  auditor must state this limit.
- The coordinator holds the exchange secret, from which domain keys derive; this
  is the stated trust model of the prototype.
