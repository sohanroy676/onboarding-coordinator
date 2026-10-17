# Changelog

All notable changes to this project are documented here.
Format follows Keep a Changelog. Generated from Conventional Commits — regenerate via `/commit` workflow, do not hand-edit.

## [Unreleased]

Web UI redesign (planned as 3.2.0, front-end only; the API and the server are unchanged): one lane per domain, the plan hash drawn as a seal, Start all and Stop all, busy states, a plan expiry countdown, a Discard plan button, a message log and a list of runs from the page. Eight page-contract tests added (477 total).

## [3.1.0] - 2026-10-16

Web UI planner selector. Minor release; the model planner of 3.0.0 is now also available on the local page (ADR-0011 amendment).

### Added
- `POST /api/plans` takes `planner` (`deterministic` default, or `model`) and `request_text`; the response names the planner. A failed model call returns 502 `model_failed`, stores no plan and does not fall back.
- Planner selector and request-text box on the page, with a note that the text leaves the machine.
- `app.onboarding.propose_requests`: the non-printing core shared by the console and the UI.
- The model is told each domain's `will_not` actions in a separate, labelled prompt block, and the strict schema limits `action` to the declared names. A request for admin access now reaches the IT agent and is refused there (`partial`) instead of being dropped by the model. Not a new check: the parser, registry and domain refusals are unchanged (`f59ecbf`, ADR-0011 amendment).
- 17 UI tests with a fake client (no network) and `tests/ui_model_transcript.py`, which saved `traces/v3-1-ui-model-transcript.txt` from one real run.

### Stated limits
- Unchanged from 3.0.0. The key is read in `app/` only and never sent to the browser.

## [3.0.0] - 2026-10-16

Opt-in model planner on the CLI. Major release: it reverses the "no language model" scope for this version only (ADR-0011). Deterministic mode, the gates' expected results and `demo.py` never use a model. The web UI selector is not part of this release.

### Added
- `python onboard.py --subject <id> --planner model --request-text "..." [--model <name>]`: a Groq model (default `qwen/qwen3.8-27b`) turns free text into (domain, action) requests. It only proposes; the registry, the plan hash, the human approval, scoped tokens and each domain's refusals decide what runs (`84e6f9f`, `1f0c01f`).
- `app/model_planner.py`: strict `.env` reader, Groq client over `urllib` with an injected transport, strict proposal parser. `.env.example` holds a placeholder.
- Exit code 5: the model call failed (no key, network, rate limit or unusable reply). It ends the run before the approval prompt; no retry, no fallback.
- Gate G7, "the model cannot widen authority": 8 tests with a fake client and real domain processes (`c69ae59`).
- Live Groq transcripts `traces/v3-0-onboard-model-*.txt` (single runs, not reproducible byte for byte, key absent).

### Changed
- G6: the credential scan exempts the `.env` path by exact path only, adds a `gsk_` rule, and `scan_model_env_use` allows only `app/` and `onboard.py` to name the key or import the planner.
- Scope documents (brief, tech stack, architecture, CLAUDE.md, AGENTS.md, ROADMAP) updated together with ADR-0011.

### Stated limits
- Model output is untrusted and not reproducible; a valid but wrong proposal is caught only at the approval step.
- Request text leaves the machine for Groq; the prototype uses synthetic data only.
- Unchanged from 2.0.1; see `docs/final-audit.md` section 7.

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
