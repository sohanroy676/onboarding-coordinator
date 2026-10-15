# Active Context

<!-- Update this at the end of every session. This is the first thing to read when resuming. -->

## Current focus
v0.1 Foundations is implemented on branch feature/v0-1-foundations and awaits review.

## Recent decisions
- Wire formats fixed in docs/adr/0002-wire-formats.md (canonical JSON, ledger lines, key derivation, token format).
- Canonical JSON helper lives in coordinator/planner.py; ledger/ledger.py keeps its own copy because ledger/ must not import coordinator/.
- Domain keys are derived from OC_EXCHANGE_SECRET with HMAC-SHA256 and a fixed label.
- state/ added to .gitignore.

## Blockers / open questions
- Local `py -3.12` launcher is broken (python is 3.14.2); suite not yet run on 3.12.
- Hash chain cannot detect removal of the last entries; v0.7 auditor must state that limit.

## Next step
Review and merge feature/v0-1-foundations, then start v0.2 (domain_agent.py, three agent files, provision.py).
