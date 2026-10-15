# ADR-0004: Plan shape, approval format and consumed-marker rule

## Status
Accepted

## Date
2026-10-15

## Context
v0.5 adds one plan across HR, IT and Facilities and one approval that covers it.
The approval is the only authority for a run, and replay protection relies on
its consumed markers. The plan shape, the signed fields and the replay key are
hard to change once runs are recorded, so they are fixed here.

## Decision
- Plan: `{"subject", "steps": [{"domain", "action", "params", "classification"}]}`.
  Steps are grouped in the order HR, IT, Facilities; request order is kept
  within a domain. `classification` is `supported` or `will_not`, read from
  the registry. An action neither supported nor on will_not is refused at
  planning. Warnings are advisory text and are not part of the hash.
- Plan hash: SHA-256 of the canonical JSON of the whole plan (ADR-0002).
- Approval: `{"approval_id", "plan_hash", "expires_at", "tag"}`.
  `approval_id` is 32 lowercase hex characters from `secrets`, so every approval
  is new even for the same plan. `expires_at` is an integer from the injected clock.
  `tag` is hex HMAC-SHA256 over the canonical JSON of
  `{approval_id, plan_hash, expires_at}`, keyed by
  `HMAC-SHA256(approval secret, b"oc-approval|")`.
- Verification order: tag, then expiry (`now >= expires_at` is expired), then
  re-derived plan hash, then consume. Each failure has a fixed code:
  `invalid_approval_tag`, `approval_expired`, `plan_changed_since_approval`,
  `approval_already_consumed`.
- Consume: exclusive create of `<state>/approvals/<approval_id>.consumed`. A
  check that fails writes nothing. The marker is written only after all checks
  pass. If a write fails after the file is created, the approval counts as used.
- The coordinator's MAC primitive lives in `coordinator/tokens.py`
  (`keyed_digest`, `constant_time_equal`), so the rule that only `tokens.py`
  and `domain_agent.py` use HMAC still holds. `approval.py` calls them.
- v0.5 writes no ledger events. Approval events are the v0.7 auditor's concern.

## Alternatives considered
- Key replay on the plan hash. Rejected: a second run of the same plan would
  need a different plan, which breaks repeated runs and the five-run counter.
- Let the approval cover only one domain. Rejected: G3 requires one approval for the whole plan.
- Store the approval in a ledger line. Rejected: the coordinator writes only marker files.
- Silently skip unsupported actions. Rejected: a plan with an action no domain offers is a planning error.

## Consequences
- Deleting a consumed marker re-opens replay at the coordinator only. Amendment
  (fix/approval-replay-domain): each domain also refuses an `approval_id` it has
  already executed, so the replay is refused at the domains. Deleting every marker
  and every domain ledger is still a stated limit (local files).
- A clock moving backwards keeps an approval valid longer, but only when it is
  rewound to a time still after `issued_at`. A rewind before `issued_at` is refused.
  The rewind window stays a stated limit.

## Amendment (fix/clock-backwards): issued_at
- Approval fields are now `{"approval_id", "plan_hash", "issued_at", "expires_at", "tag"}`.
  `issued_at` is the integer clock time at approve(); it is covered by the tag.
- Verification order: tag, then clock (`now < issued_at` is `approval_clock_regressed`,
  nothing consumed), then expiry, then plan hash, then consume.
- Approvals in the old format (no `issued_at`) fail the field check as `invalid_approval_tag`.
- The registry refuses a declaration whose receipt time is after the current clock
  (`DeclarationStale`, "clock moved backwards").
- Approvals are signed with a secret only the coordinator and approver hold.
  Domain processes never receive it (provision.py, G2).
