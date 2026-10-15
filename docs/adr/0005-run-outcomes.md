# ADR-0005: Run dispatch, outcome vocabulary and aborted runs

## Status
Accepted

## Date
2026-10-15

## Context
v0.6 runs one approved plan across HR, IT and Facilities. The status
vocabulary, the behaviour when a domain fails, and what an aborted run
leaves behind are fixed here. The v0.7 auditor and the G4 gate depend on
them, and they are hard to change once runs are recorded.

## Decision
- Order: approval verified and consumed first. Then, for each domain in
  HR, IT, Facilities order that has steps: mint one token (scope = that
  domain's actions in the plan, will_not included), then one POST /execute.
  A token is minted just before its call, so its 60 s TTL is not spent early.
- Outcomes per action: the domain's own `executed`, `refused` or `failed`.
  The coordinator adds `not_executed` when a domain did not answer with a
  well-formed result list.
- Reasons for `not_executed`: `domain_unreachable` (OS-level error),
  `domain_error:<code>` (non-200 answer, code from the domain's error field,
  or `unknown`), and `bad_response` (200 answer that is not a valid result list
  for the actions sent).
- A domain that fails does not stop the run. Its actions are `not_executed`
  and the next domain is still called. There are no retries.
- Status from per-action outcomes: `success` when every action executed,
  `partial` when some executed and some did not, `failed` when none executed.
  `aborted` only when the approval is refused; then no token is minted and no
  domain is called, and `abort_code` carries the ApprovalError code.
- The coordinator sends will_not steps like any other step. It never filters
  them. The domain refuses them with reason `will_not`.
- The coordinator writes no ledger line. An aborted run leaves no domain
  ledger line; its report is the only record of the abort.

## Alternatives considered
- Stop at the first failing domain. Rejected: it leaves later domains with no
  steps and no record, which is a larger partial state than per-action rows.
- Mint all three tokens right after approval. Rejected: tokens for domains
  that are never reached would be minted and counted, and early minting spends
  the TTL.
- Retry an unreachable domain once. Rejected: the project has no retries
  (ROADMAP "explicitly not planned").
- Write an abort line to a ledger. Rejected: the coordinator writes only
  approval marker files.

## Consequences
- The exchange counter counts every token minted, including tokens whose
  call failed. That matches the five-run counter in G5.
- A run where a domain is down can show `partial` with `domain_unreachable`
  rows. The domain's ledger has no line for those actions, so the auditor
  must rely on the run report or on the absence of a line.
- An aborted run is invisible in the domain ledgers. The v0.7 auditor must
  account for it separately.
