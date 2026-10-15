# Progress

<!-- Running log. Append, don't rewrite history. Newest at top.
     This tracks WORK STATUS (agent-facing, session to session).
     For the forward-looking feature plan, see ROADMAP.md instead —
     don't duplicate the full plan here, just what's actually in motion. -->

## Done

- v0.3 Registry (M2) - coordinator/registry.py (HTTP fetch of /capabilities, receipt time from injected clock, TTL staleness refused, KeyError for unknown domain, supports/classify/will_not with will_not reported not dropped), 21 unit tests and 15 G1 gate tests (real domain servers and provision port-0 children) passing, 116 tests in full suite, 2026-10-15. Suite run on Python 3.14.2 only; 3.12 not yet verified locally (CI pins 3.12).
- v0.2 Domain agents (M1) - domains/domain_agent.py (verifier, will_not, ledger, HTTP), hr/it/facilities agents, provision.py (READY handshake, explicit child env), ADR-0003, 80 unit tests passing, 2026-10-15. CI compileall no longer lists demo.py until it exists (v0.6).
- v0.1 Foundations — canonical JSON and plan hash (coordinator/planner.py), hash-chained ledger (ledger/ledger.py), key derivation, minting and exchange counter (coordinator/tokens.py), ADR-0002, 38 unit tests passing, 2026-10-15
- v0.0 Spikes — python -m with namespace packages OK; unittest discover OK; exclusive-create race-safe (8 procs x 20 rounds, one winner each); child env needs SYSTEMROOT (sockets fail without it), 2026-10-15. Note: local python is 3.14.2, py -3.12 launcher is broken; CI pins 3.12.

## In progress

- (none)
