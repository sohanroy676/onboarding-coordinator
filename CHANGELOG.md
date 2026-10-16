# Changelog

All notable changes to this project are documented here.
Format follows Keep a Changelog. Generated from Conventional Commits — regenerate via `/commit` workflow, do not hand-edit.

## [Unreleased]

## [2.0.1] - 2026-10-16

Patch release from the final audit. No change to behaviour, status codes or bodies.

### Fixed
- A refused POST left its body unread; on Windows the close then sent a TCP reset and the client could lose the 403, 404 or 405. The domain handler now drains the declared body and the UI handler reads the rest (bounded) before closing (`dbbbb1e`, `app/server.py`, `domains/domain_agent.py`).

### Added
- G1 test for a declaration 0.1 s old with a 0.01 s maximum (`0df779a`).
- Final audit against the PS3 statement: `docs/final-audit.md` and `traces/final-audit-*.txt`.
- `docs/review-guide.md`: demo script and answers to likely review questions.

### Stated limits
- Unchanged from 1.1.0; see `docs/final-audit.md` section 7.

## [2.0.0] - 2026-10-15

Local web UI. Major release: it reverses the "no web interface" scope for this version only (ADR-0010).

### Added
- `python -m app.server` on 127.0.0.1, default port 8110: domain start and stop, new onboarding, plan with warnings, separate approve step that sends the plan hash the user saw, run view with per-domain rebuild.
- UI security: Host allowlist, per-start CSRF token, Origin check, JSON only, 16 KB body limit, fixed static table, no secret in responses.
- `Provisioner.start_domain`, `stop_domain`, `running`, `check_domain_health`.
- Tests `tests/test_unit_app_server.py`; transcript `traces/v2-0-ui-transcript.txt`.

### Changed
- `app/onboarding.py` split into `plan` and `execute_plan`; CLI behaviour unchanged.
- The G6 scan also covers `.html`, `.css` and `.js`.

## [1.2.0] - 2026-10-15

### Added
- `python onboard.py --subject <id>`: the onboarding flow from the console. It validates the subject and requests, prints the plan and its warnings, asks for approval, runs the plan and rebuilds it from the ledgers (ADR-0009, `app/onboarding.py`).
- Exit codes 0 to 4 for the CLI (success, not successful, bad input or plan refused, not approved, domains did not start).
- Tests: `tests/test_unit_app_onboarding.py` (fake prompt and domains), `tests/test_unit_app_live.py` (real domains on port 0).
- G6 import scan covers `app/`: it may not import `domains` or `ledger.ledger`.

## [1.1.0] - 2026-10-15

Known-gap fixes after v1.0. Minor release: the token and approval formats changed.

### Changed
- Approvals carry `issued_at`; an approval used before its issue time is refused (ADR-0004).
- Tokens carry an `approval_id` claim; each domain refuses a reused approval (`approval_replayed`) and rebuilds that memory from its own ledger (ADR-0003, ADR-0004).
- The exchange counter is kept in a file, one line per exchange, and survives a coordinator restart (ADR-0006).

### Fixed
- The write scan flags `Path.open` with a non-literal mode as a write (`898bb49`).
- The provisioner kills a child that never reports READY and shows its stderr (`807fc60`).
- A clock moved backwards is refused for declarations and approvals instead of being treated as fresh (`9826566`).
- A deleted consumed-approval marker no longer re-opens replay at the domains (`27b0e7c`).

### Added
- Release evidence: fresh-clone checks and traces `traces/v1-1-*.txt` (`7b1ad88`).
- Gap-fix checklist section mapping each fix to its test and trace (`921e624`).

### Stated limits
- The coordinator can derive domain keys from the exchange secret (ADR-0007, ADR-0008).
- A clock rewound to a time still after `issued_at` extends an approval (ADR-0004).
- Someone with local administrator rights who deletes every approval marker and domain ledger can replay (ADR-0003, ADR-0004).
- The counter file and ledgers are local and not tamper-evident; the hash chain cannot detect truncation at the end (ADR-0006).

## [1.0.0]

- v1.0 freeze: fresh-checkout evidence, deliverables D1 to D12 mapped in the acceptance checklist, source archive (`d706058`).
