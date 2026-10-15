# Progress

<!-- Running log. Append, don't rewrite history. Newest at top.
     This tracks WORK STATUS (agent-facing, session to session).
     For the forward-looking feature plan, see ROADMAP.md instead —
     don't duplicate the full plan here, just what's actually in motion. -->

## Done

- v0.1 Foundations — canonical JSON and plan hash (coordinator/planner.py), hash-chained ledger (ledger/ledger.py), key derivation, minting and exchange counter (coordinator/tokens.py), ADR-0002, 38 unit tests passing, 2026-10-15
- v0.0 Spikes — python -m with namespace packages OK; unittest discover OK; exclusive-create race-safe (8 procs x 20 rounds, one winner each); child env needs SYSTEMROOT (sockets fail without it), 2026-10-15. Note: local python is 3.14.2, py -3.12 launcher is broken; CI pins 3.12.

## In progress

- (none)
