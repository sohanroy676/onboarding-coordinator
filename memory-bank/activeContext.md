# Active Context

<!-- Update this at the end of every session. This is the first thing to read when resuming. -->

## Current focus
v0.4 Delegation (M3, gate G2) is merged to main and tagged v0.4.0, pushed to origin. G2 passes on Python 3.14.2 (126 tests in full suite). CI on Python 3.12.10 has passed for every main push so far, including v0.3.

## Recent decisions
- HTTP contract, ledger events and per-domain actions fixed in docs/adr/0003-domain-http-contract.md.
- Rejected tokens write a token_rejected ledger line (attack evidence); an attacker can add such lines, so the v0.7 auditor must count them separately.
- Domain servers set allow_reuse_address False (Windows SO_REUSEADDR would allow port shadowing).
- provision.py waits for a READY line from each child instead of sleeping; tests bind port 0.
- ci.yml compileall dropped demo.py (file does not exist before v0.6); add it back then.

## Blockers / open questions
- Local `py -3.12` launcher is broken (python is 3.14.2); suite not yet run on 3.12.
- Hash chain cannot detect removal of the last entries; v0.7 auditor must state that limit.
- Replay protection after restart depends on an intact ledger.

- Registry refuses stale declarations (raises DeclarationStale) instead of returning False from supports(); a False would look like "action not offered".
- Failed refresh keeps the last good declaration; TTL ages out a permanently dead domain.
- Staleness is strictly greater than TTL (age equal to TTL is fresh). Negative age (clock moved back) is treated as fresh; known gap.

## Next step
Start v0.5 Plan and approval (M4, M5) on feature/v0-5-plan-approval from main: planner and approval, with replay, tamper and race tests (ROADMAP.md). Add the approval-secret half of the coordinator-secret check to G2 when approval.py exists. Local py -3.12 still needs reinstalling; CI is the 3.12 check.
