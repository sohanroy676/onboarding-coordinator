# Roadmap

## Now
- v2.0.1 (patch: the Windows reset fix from the final audit, changelog, review guide) is released (tag v2.0.1 at e263319, pushed, CI green on the tag). v2.0.0 is released (tag v2.0.0 at e1d262d, pushed). Nothing else is planned; see Later / ideas.

## Done
- v2.0.1 Final audit patch: refused POSTs answered without a connection reset on Windows (`app/server.py`, `domains/domain_agent.py`), G1 test for the 0.1 s / 0.01 s stale case, `docs/final-audit.md`, `docs/review-guide.md`. Suite 388 plus the review-guide docs tests.
- v2.0 Local web UI (major): `python -m app.server` on 127.0.0.1, port 8110. Plan, approve (the plan hash the user saw), run, and per-domain rebuild, over the same flow as the CLI. Tests `tests/test_unit_app_server.py`; transcript `traces/v2-0-ui-transcript.txt`; ADR-0010 accepted. Suite 385 OK, gates unchanged. Merged at e1d262d, tag v2.0.0, CI green on main and the tag.
- v1.2 Onboarding core and CLI: `python onboard.py --subject <id>` runs the one flow in `app/onboarding.py` (validate, plan, console approval per ADR-0009, run, rebuild). Exit codes 0 to 4. Tests `tests/test_unit_app_onboarding.py` and `tests/test_unit_app_live.py`; traces `traces/v1-2-*.txt`. No new gate; the six gates are unchanged. Checklist section v1.2.
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
- **v2.0.0 Local web UI** (major: reverses the "no web interface" scope, local only). `app/server.py` and `app/static/` (vanilla HTML, CSS and JS; no build step, no CDN, ASCII only) on 127.0.0.1, default port 8110. Pages: domain status with start and stop; new onboarding; plan with warnings; a separate approve-and-run button that sends the plan hash the user saw; run view with the per-domain rebuild.
  - Security: Host header check, per-start CSRF token on every POST, Origin check, JSON only, 16 KB body limit, fixed static allowlist, no secret in the page.
  - Acceptance: `tests/test_unit_app_server.py` (HTTP on port 0) and the live flow against real domains, plus a saved HTTP transcript from a real run (`traces/v2-0-ui-transcript.txt`). No browser tool is a project dependency; screenshots stay out of git.
  - Decision record: ADR-0010 (draft: local web UI).
  - Release steps as for v1.1: branch, merge after approval, tag, fresh-clone check, archive, extract check, approvals to push and tag, CI on the tag.

## Later / ideas
- Monolith baseline for a side-by-side measurement.
- Signed capability declarations.

## Explicitly not planned
- Retries, rollback or compensation of partial runs.
- Parallel dispatch.
- Database, configuration files.
- Third-party web frameworks, npm or CDN assets (the v2.0.0 UI is standard library only).

## Scope change
- A web interface is planned for v2.0.0 as a local, standard-library UI that runs alongside the CLI. The brief's "no web interface" line is reversed for v2.0.0 only; see ADR-0010 (draft). The brief and this file are updated together.
- Any third-party package or language model.
- Real systems or real employee data.