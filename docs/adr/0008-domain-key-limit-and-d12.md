# ADR-0008: Accept the domain-key limit for v1 and fix D12 in the docs

## Status
Accepted

## Date
2026-10-15

## Context
ADR-0007 found that `TokenMinter` holds the exchange secret and derives every
domain key in memory (`coordinator/tokens.py:88`). The projectBrief success
criterion says "zero domain credentials in coordinator/". The G6 scan proves
that `coordinator/` never stores or reads a domain key, not that the coordinator
cannot compute one.

Deliverable D12 asked the troubleshooting guide to name a missing
`OC_EXCHANGE_SECRET` or `OC_APPROVAL_SECRET`. The design never reads those from
the environment: `provision.py` creates both in memory. The guide was corrected
in v1.0 but the requirement itself was never changed.

## Decision
1. The domain-key limit stays a stated limit for v1. The code is unchanged.
   The "zero domain credentials" claim is narrowed to: the coordinator stores,
   reads from the environment and names no domain key. It can still derive one
   in memory, and ADR-0007 says so.
2. D12 is met by the docs. The requirement changed: the guide documents that
   the two secrets are not environment variables and cannot be missing from one.
   The only missing-variable message is for `OC_DOMAIN_KEY`, which is real.
   No code check for the in-memory secrets is added, because an env-var check
   would bring back the design that was removed.

## Alternatives considered
- Per-domain keys held by `provision.py` and given to the coordinator: the
  coordinator would then hold domain credentials, which breaks the claim more
  directly.
- Asymmetric signing (the coordinator signs, domains verify with a public key):
  not in the standard library. A third-party package is not allowed.
- A separate signing broker process: a new process and a new trust boundary.
  The projectBrief excludes extra services, so it is out of scope for v1.
- Adding an env-var check for the two secrets: reintroduces env vars that the
  design removed, and tests a state that cannot occur.

## Consequences
- The faculty review hears the limit stated plainly, not a claim the code cannot
  keep. The limit is the same as in ADR-0007.
- A future version that needs a strict "the coordinator cannot mint" property
  must add a signing broker or a third-party package. That is a new ADR and a
  scope change.
- D12 is "met with note" because the requirement was reworded, and the note says so.
