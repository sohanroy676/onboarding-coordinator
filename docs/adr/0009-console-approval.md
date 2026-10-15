# ADR-0009: Approval is given by the operator at the console

## Status
Accepted (in v1.2.0, branch feat/onboarding-core)

## Date
2026-10-15

## Context
Until v1.1, the only approval path was `demo.py`, which approves in code. A real
onboarding needs a person to see the consolidated plan and its warnings (for
example a `will_not` action) and decide. The approval must stay bound to the plan
the person saw, and the coordinator must still be the only process that signs
and consumes approvals (ADR-0004).

## Decision
The operator approves at the console. `app/onboarding.py` prints the plan and its
warnings, then asks `Approve this plan? [y/N]`. Only `y` (any case) continues. Any
other answer, end of input, or Ctrl-C ends with nothing approved, minted or sent.
The approval is signed by the same process that runs the plan, with the existing
`Approver` and `ApprovalGate`. The approver is therefore the operator at the
console of the coordinator process, not a separate authority.

## Alternatives considered
- **A separate approver process with its own secret.** Stronger separation, but it
  adds a second secret holder and a transport, and the brief has no requirement for
  it. Deferred.
- **Auto-approve for scripts.** Rejected: an approval must be a human decision.
  Scripts can pipe `y` into the prompt, which the trace makes visible.
- **Approve by editing a file.** Rejected: that is a configuration-file workflow, which is out of scope.

## Consequences
- The trust statement is narrow: the operator and the coordinator share one trust
  domain. The docs must say so, and the faculty can dispute it.
- The prompt is the only human check, so the plan printout must show every step and
  warning before the question.
- Declined and interrupted runs leave no marker and no ledger line (tested).
- The same flow backs the web UI (ADR-0010), so the approval rule is written once.
