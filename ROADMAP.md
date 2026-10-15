# Roadmap

## Now
- Review and merge v0.1 (feature/v0-1-foundations).

## Done
- v0.0 Setup and spikes: namespace packages, unittest discovery, race-safe exclusive-create markers and child env needs confirmed.
- v0.1 Foundations: canonical JSON and plan hash, ledger.py with hash chain, tokens.py (key derivation, mint, counter), with unit tests.

## Next
- v0.2 Domain agents (M1): domain_agent.py, the three agent files, provision.py; full request pipeline.
- v0.3 Registry (M2): staleness, unknown domain, supports(). Closes G1.
- v0.4 Delegation proven (M3): token attack tests against all three domains. Closes G2.
- v0.5 Plan and approval (M4, M5): planner and approval, including replay, tamper and race tests. Closes G3.
- v0.6 Run and refusal (M6): run.py and demo.py clean and partial runs. Closes G4. First end-to-end demonstration.
- v0.7 Evidence and cost (M7): reconstruct.py and the counter-based coordination multiple. Closes G5.
- v0.8 Perimeters and hardening: credential scan with planted-credential control, import scan, allowed-writes check. Closes G6.
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