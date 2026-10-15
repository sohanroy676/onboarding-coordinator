# ADR-0006: Evidence rebuild and the coordination multiple

## Status
Accepted

## Date
2026-10-15

## Context
v0.7 has to show two things from real runs: that one run can be rebuilt from
the three domain ledgers, and what the coordination cost is. Both are
claims a faculty reviewer will check, so the counting rules and the limits
are fixed here before the numbers are shown.

## Decision
- Coordination multiple = token exchanges counted by the coordinator's real
  counter (TokenMinter.exchange_count) over N clean runs, divided by
  N x 1, where 1 is the single authorization a monolith would make per run.
  Expected value for the six-action plan: 3.0. The denominator is a stated
  assumption, not a measurement of a monolith.
- The counter is read from the minter, never computed from the number of
  domains or runs. The five-run check uses one minter, so the counter is
  cumulative within one process.
- reconstruct (ledger/reconstruct.py) is read-only. For each domain it reads
  the ledger, verifies the hash chain, and counts only lines with the run ID.
- Action outcomes are counted per (jti, action); the last line wins.
  A handler fault writes action_executed and then action_failed, so the
  action counts once, as failed.
- token_rejected lines are counted apart from action lines.
- A domain whose chain is broken is reported with its position; its lines are
  not counted, and the command exits non-zero.
- Every rebuild prints the same limits, so the output cannot be read without
  them: end-of-file truncation is undetectable; deleting a consumed approval
  marker re-opens replay; an aborted run leaves no ledger line; a
  not_executed action leaves no ledger line; token_rejected lines can be added
  by anyone with write access.

## Alternatives considered
- Count every action line. Rejected: a handler fault would count the same
  action twice.
- Persist the exchange counter across processes. Rejected for v0.7: it needs a
  new store and a new trust boundary. The counter is per process, and the
  demo and G5 both run in one process.
- Compute the multiple from the plan (3 domains x runs). Rejected: it is not
  evidence; a counter that disagrees with the plan would be hidden.

## Consequences
- The multiple is only as good as the monolith denominator. A reviewer who
  disputes "one authorization per run" can change MONOLITH_AUTHORIZATIONS_PER_RUN
  and see the effect directly.
- A process restart resets the counter, so a multi-process count needs a new
  design.
- The auditor cannot prove completeness. It can show that a run's lines are
  intact and where they are missing, and it says so.
