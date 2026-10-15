# Roadmap

## Now
- (none)

## Done
- v1.1 Known-gap fixes: five gaps closed on main (1f6ac88), 279 tests, gates G1 15, G2 11, G3 10, G4 7, G5 7, G6 11, traces traces/v1-1-*.txt. Fixed: write scan missed Path.open with a non-literal mode; provisioner gave no detail for a silent child; a clock moved backwards was treated as fresh; the exchange counter reset on restart; a deleted consumed approval marker re-opened replay at the domains (approval_id is now a token claim, ADR-0003, ADR-0004, ADR-0006). Token format changed, so this is a minor release. Stated limits stay as in the checklist "Stated limits" section (ADR-0004, ADR-0006, ADR-0007, ADR-0008).
- v1.0 Freeze: all six gates and demo.py pass on a fresh checkout; source archive; checklist maps D1 to D12.
- v0.9 Traces and documents (M9): merged to main (c415761), tagged v0.9.0. Real traces, implementation document, acceptance checklist, troubleshooting guide.
- v0.8 Perimeters and hardening (M8): merged to main (5f82863), tagged v0.8.0. Closes G6. ADR-0007.
- v0.7 Evidence and cost (M7): ledger rebuild and coordination multiple (tests/test_g5_evidence_cost.py). Closes G5. ADR-0006.
- v0.0 Setup and spikes: namespace packages, unittest discovery, race-safe exclusive-create markers and child env needs confirmed.
- v0.1 Foundations: canonical JSON and plan hash, ledger.py with hash chain, tokens.py (key derivation, mint, counter), with unit tests.
- v0.2 Domain agents (M1): domain_agent.py, the three agent files, provision.py; token and action pipeline with ledger writes.
- v0.3 Registry (M2): staleness, unknown domain, supports(). Closes G1.
- v0.4 Delegation proven (M3): token attack tests against all three domains (tests/test_g2_delegation.py). Closes G2.
- v0.5 Plan and approval (M4, M5): one plan across domains, one signed approval with tamper, expiry, replay and race tests (tests/test_g3_approval.py). Closes G3. ADR-0004.
- v0.6 Run and refusal (M6): run.py, demo.py with clean, partial and replay scenarios, honest refusal tests (tests/test_g4_refusal.py). Closes G4. ADR-0005.

## Next
- (none after v1.1)

## Later / ideas
- Monolith baseline for a side-by-side measurement.
- Interactive approver prompt for the live demo.
- Signed capability declarations.

## Explicitly not planned
- Retries, rollback or compensation of partial runs.
- Parallel dispatch.
- Web interface, database, configuration files.
- Any third-party package or language model.
- Real systems or real employee data.