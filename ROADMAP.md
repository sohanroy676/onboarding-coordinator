# Roadmap

## Now
- v0.8 Perimeters and hardening (M8): implemented on feature/v0-8-perimeters, committed, awaiting review and merge. Closes G6. ADR-0007.

## Done
- v0.7 Evidence and cost (M7): ledger rebuild and coordination multiple (tests/test_g5_evidence_cost.py). Closes G5. ADR-0006.
- v0.0 Setup and spikes: namespace packages, unittest discovery, race-safe exclusive-create markers and child env needs confirmed.
- v0.1 Foundations: canonical JSON and plan hash, ledger.py with hash chain, tokens.py (key derivation, mint, counter), with unit tests.
- v0.2 Domain agents (M1): domain_agent.py, the three agent files, provision.py; token and action pipeline with ledger writes.
- v0.3 Registry (M2): staleness, unknown domain, supports(). Closes G1.
- v0.4 Delegation proven (M3): token attack tests against all three domains (tests/test_g2_delegation.py). Closes G2.
- v0.5 Plan and approval (M4, M5): one plan across domains, one signed approval with tamper, expiry, replay and race tests (tests/test_g3_approval.py). Closes G3. ADR-0004.
- v0.6 Run and refusal (M6): run.py, demo.py with clean, partial and replay scenarios, honest refusal tests (tests/test_g4_refusal.py). Closes G4. ADR-0005.

## Next
- v0.9 Traces and documents: saved real traces, implementation document, acceptance checklist, troubleshooting guide.
- v1.0 Freeze: all six gates and demo.py pass on a fresh checkout; source archive.

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