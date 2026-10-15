# Progress

<!-- Running log. Append, don't rewrite history. Newest at top.
     This tracks WORK STATUS (agent-facing, session to session).
     For the forward-looking feature plan, see ROADMAP.md instead —
     don't duplicate the full plan here, just what's actually in motion. -->

## Done

- v0.5 Plan and approval (M4, M5) - coordinator/planner.py gains build_plan (one plan, HR, IT, Facilities order; registry refuses stale and unknown; will_not kept with advisory warning; unsupported action refused at planning) and warnings(). coordinator/approval.py (new): Approver signs plan hash with fresh approval_id and integer expiry; ApprovalGate verifies tag, expiry, re-derived hash, then consumes by exclusive create of state/approvals/<id>.consumed. Named errors carry ledger-style codes. provision.py generates OC_APPROVAL_SECRET in memory (not passed to children). tokens.py exports keyed_digest and constant_time_equal, the coordinator's only MAC primitives, so the HMAC boundary test still holds. Tests: test_unit_planner (15), test_unit_approval (16 incl. race of 8 contenders x 20 rounds), test_g3_approval (9 gate tests on three real domains), G2 gains test_approval_secret_cannot_sign_a_token (approval secret and derived approval key both refused). Full suite 168 tests passing on Python 3.14.2; compileall clean (demo.py still absent, as before v0.6). Mutation checks: disabling consume fails 13 G3 tests; disabling the plan re-derivation fails 2. ADR-0004 records plan shape, approval fields and replay key. Known gaps added: deleting a consumed marker re-opens replay; clock moving backwards keeps approval valid. Merged to main with tag v0.5.0 and pushed to origin, 2026-10-15. CI on Python 3.12 is the 3.12 check.
- v0.4 Delegation (M3) - tests/test_g2_delegation.py: 10 G2 tests running real HR, IT and Facilities domains in process (port 0, injected clock). Covers wrong-domain (domain_mismatch, all six pairs), malformed and missing tokens, exchange secret and derived keys refused (invalid_signature), widened or edited scope, expiry boundary, replay before and after restart, will_not and out_of_scope refusals; each rejection writes one token_rejected line and nothing executes. No production code change. Full suite 126 tests passing on Python 3.14.2 locally. Mutation check: disabling the replay check fails a G2 test. Approval secret half of the coordinator-secret check waits for v0.5 (approval.py). Merged to main with tag v0.4.0, 2026-10-15. CI on Python 3.12 runs on the main push.
- v0.3 Registry (M2) - coordinator/registry.py (HTTP fetch of /capabilities, receipt time from injected clock, TTL staleness refused, KeyError for unknown domain, supports/classify/will_not with will_not reported not dropped), 21 unit tests and 15 G1 gate tests (real domain servers and provision port-0 children) passing, 116 tests in full suite, 2026-10-15. Suite run on Python 3.14.2 only; 3.12 not yet verified locally (CI pins 3.12).
- v0.2 Domain agents (M1) - domains/domain_agent.py (verifier, will_not, ledger, HTTP), hr/it/facilities agents, provision.py (READY handshake, explicit child env), ADR-0003, 80 unit tests passing, 2026-10-15. CI compileall no longer lists demo.py until it exists (v0.6).
- v0.1 Foundations — canonical JSON and plan hash (coordinator/planner.py), hash-chained ledger (ledger/ledger.py), key derivation, minting and exchange counter (coordinator/tokens.py), ADR-0002, 38 unit tests passing, 2026-10-15
- v0.0 Spikes — python -m with namespace packages OK; unittest discover OK; exclusive-create race-safe (8 procs x 20 rounds, one winner each); child env needs SYSTEMROOT (sockets fail without it), 2026-10-15. Note: local python is 3.14.2, py -3.12 launcher is broken; CI pins 3.12.

## In progress

- (none)
