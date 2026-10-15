# ADR-0003: Domain HTTP contract and ledger events

## Status
Accepted

## Date
2026-10-15

## Context
The coordinator (v0.3 onwards) and the domain agents must agree on the
request and response shapes, the error codes and the ledger events. ADR-0002
fixed the token and the ledger line but not these. They are hard to change
once the registry, run and auditor depend on them.

## Decision
- `GET /capabilities` returns 200 `{"domain", "capabilities", "will_not"}`
  (sorted lists, no timestamp; the registry stamps its own receipt time).
  The two lists are disjoint.
- `POST /execute` takes `{"token", "actions": [{"name", "params"?}]}`. Subject
  and run ID come only from the verified token, never from the body.
- Token failures return `{"error": code}`: malformed_token 400,
  domain_mismatch 403, invalid_signature 401, token_expired 401,
  token_replayed 401, approval_replayed 401. Checked in that order. A missing
  token is malformed. (Amendment, fix/approval-replay-domain: `approval_id` is a
  required claim; a domain refuses an approval it has already executed, rebuilt
  from its own ledger on start.)
- A valid token returns 200 `{"domain", "run_id", "results": [...]}`. Each
  result has `action` and `outcome` (executed, refused or failed); refused
  results carry `reason` (out_of_scope, will_not, unsupported_action, checked
  in that order); failed carries `handler_error`. A refusal does not stop the
  remaining actions.
- Bad JSON, a wrong shape or a body over 64 KiB returns 400 `bad_request`
  and does not consume the token. Wrong method 405, unknown path 404.
- Ledger events written by the domain: `action_executed` and `action_refused`
  (one per action, written before the action runs), `action_failed` (after a
  handler fault) and `token_rejected` (reason only). Action lines carry
  action, subject and jti; params are not recorded. A rejected token takes
  its run ID from its claims when they parse, otherwise `unknown`.
- A token is consumed (jti remembered) once it passes all token checks and
  the action list is well formed, even if every action is refused. The seen
  set is rebuilt from the ledger at start-up, so a restart does not reopen
  replay.
- A domain process announces `READY <port>` on stdout once bound; provision.py
  waits for that line instead of sleeping.
- Actions per domain: HR create_record, enroll_benefits (will_not
  change_payroll); IT create_account, assign_laptop (will_not
  grant_admin_access); Facilities issue_badge, assign_desk (will_not
  disable_alarm). All are simulated.

## Alternatives considered
- Putting subject and run ID in the body: lets a caller disagree with the
  token; rejected.
- Not ledgering rejected tokens: loses attack evidence, so rejections are
  recorded, at the cost of an attacker being able to add such lines.
- A fixed delay after spawning a domain: slower and flaky; READY line instead.

## Consequences
- Anyone who can reach a domain port can append `token_rejected` lines. The
  chain stays valid, and the auditor (v0.7) should count them separately.
- Replay protection survives restart only while the ledger is intact.
- A hung or crashed handler is reported per action; there is no retry.
