# Implementation

This document describes the prototype as built. The decisions behind it are in
`docs/adr/`. The acceptance results are in `docs/acceptance-checklist.md`, and the
problems you may hit are in `docs/troubleshooting.md`.

## Purpose

A federated, least-privilege onboarding coordinator for a new hire (problem
statement PS3). One coordinator process and three domain agent processes (HR,
IT, Facilities) complete onboarding. No single process holds all domain
authority, and no language model is used anywhere in the system.

The prototype runs locally only. It uses real processes and real HTTP on
127.0.0.1, but no real HR, IT or Facilities system and no live employee data.

## Stack

- Python 3.12 or newer, standard library only (`http.server`, `urllib.request`,
  `hmac`, `hashlib`, `secrets`, `json`, `pathlib`, `unittest`).
- No third-party packages, no `requirements.txt`, no database, no `.env` file.
- Ports: 8101 HR, 8102 IT, 8103 Facilities. Override with `OC_PORT_HR`,
  `OC_PORT_IT`, `OC_PORT_FAC`.

## Components

| Path | Role |
| --- | --- |
| `domains/domain_agent.py` | Shared domain runtime: HTTP server, token check, `will_not` check, ledger write. The only place tokens are verified. |
| `domains/hr_agent.py` | HR identity, capabilities, `will_not` list, simulated actions. |
| `domains/it_agent.py` | IT, same shape. |
| `domains/facilities_agent.py` | Facilities, same shape. |
| `coordinator/registry.py` | Capability declarations from `GET /capabilities`, with a receipt time and a TTL. Refuses stale declarations, raises `KeyError` for an unknown domain. |
| `coordinator/planner.py` | One consolidated plan in HR, IT, Facilities order, canonical JSON, one SHA-256 plan hash. Keeps `will_not` actions with a warning. |
| `coordinator/approval.py` | Signs the plan hash once. Verifies the tag, expiry and re-derived hash, then consumes the approval by exclusive create. |
| `coordinator/tokens.py` | Derives per-domain keys, mints one short token per domain, runs the real exchange counter. The only place tokens are minted. |
| `coordinator/run.py` | Runs one onboarding in order and reports the status. |
| `ledger/ledger.py` | Append-only JSON Lines with a hash chain. |
| `ledger/reconstruct.py` | Read-only auditor. Rebuilds one run by run ID from the three ledgers and checks each chain. |
| `provision.py` | Operator. Creates the secrets in memory, starts and stops the domains, waits for a READY line from each. |
| `demo.py` | Runs the scenarios against real domain processes and prints the traces. |

The three source folders hold exactly 11 files and no `__init__.py`. They are
namespace packages, so every command runs from the project root with `python -m`.

## One onboarding run

1. **Discover.** The coordinator calls `GET /capabilities` on each domain. The
   registry stores each declaration with its own receipt time.
2. **Plan.** The planner builds one plan covering all domains. It refuses stale
   or unknown domains and unsupported actions, and hashes the plan once. Actions
   on a domain's `will_not` list stay in the plan with a warning.
3. **Approve.** The approver signs the plan hash once, with a fresh approval ID
   and an expiry.
4. **Verify.** The coordinator checks, in order, the approval tag, the expiry and
   the re-derived plan hash. Then it consumes the approval by creating a marker
   file in exclusive mode. A refused approval aborts the run before any token is
   minted.
5. **Mint and execute.** Only after approval, the coordinator mints one token per
   domain just before calling it. Subject is the new hire, actor is the
   coordinator, audience is that domain, scope is that domain's plan actions. It
   calls `POST /execute` on HR, then IT, then Facilities, once each.
6. **Decide at the domain.** The domain checks the token (`malformed_token`,
   `domain_mismatch`, `invalid_signature`, `token_expired`, `token_replayed`),
   then each action (`out_of_scope`, `will_not`, `unsupported_action`). It writes
   its ledger line, then acts.
7. **Report.** The coordinator sets the status to `success`, `partial`, `failed`
   or `aborted` from the per-action outcomes, and prints the exchange count. A
   domain that is unreachable or answers badly marks its actions `not_executed`,
   and the later domains still run. There are no retries and no rollback.
8. **Audit.** `python -m ledger.reconstruct <run_id>` reads the three ledgers and
   checks each hash chain.

## Trust boundaries

- Each domain is the only verifier of its own tokens, the only enforcer of its
  own `will_not` list, and the only writer of its own ledger.
- The coordinator writes only approval marker files.
- `domains/` never imports from `coordinator/`, and `coordinator/` never imports
  from `domains/`. Only the domains and the auditor use `ledger/`.
- Token verification lives only in `domain_agent.py`. Minting lives only in
  `tokens.py`. A unit test checks that the two agree.
- The two coordinator secrets are created in memory by `provision.py` and are not
  environment variables. Nothing is written to a file. No child process receives them.
- Each domain process gets only its own derived key, through the environment.

| Variable | Set by | Read by | Purpose |
| --- | --- | --- | --- |
| `OC_DOMAIN_KEY` | `provision.py`, one per domain | that domain process | That domain's derived key, in hex. |
| `OC_STATE_DIR` | `provision.py`, per domain | domain processes | Where approvals and ledgers live. Default `./state`. |
| `OC_PORT_HR`, `OC_PORT_IT`, `OC_PORT_FAC` | operator, optional | `provision.py` | Port overrides. |

The exchange secret and the approval secret are held in `provision.py`'s process
memory, not in an environment variable. That process is also the coordinator in
`demo.py`, which is why the exchange secret can derive every domain key (ADR-0007).

## Design decisions

The main decisions are recorded as ADRs:

- ADR-0002: wire formats.
- ADR-0003: the domain HTTP contract, ledger events and per-domain actions.
- ADR-0004: plan shape, approval fields and the replay key (`approval_id`).
- ADR-0005: run status vocabulary and no-retry dispatch.
- ADR-0006: the coordination multiple, its counting rules and its limits.
- ADR-0007: perimeter checks as unittest code, and the key-derivation limit below.

## Limits

These are stated, not hidden. Each is also in the acceptance checklist.

- **The coordinator can derive every domain key.** `TokenMinter` holds the
  exchange secret and derives each domain key in memory
  (`coordinator/tokens.py:88`). G6 proves the coordinator never stores, reads
  from the environment, or names a domain key. It does not prove the coordinator
  cannot compute one. Standard library HMAC cannot remove this without a
  different key design (ADR-0007). Accepted as a stated limit for v1 (ADR-0008).
- **Clock moving backwards** is treated as fresh, for registry staleness and
  approval expiry.
- **Deleting a consumed approval marker re-opens replay.** Markers are plain
  files, not in any ledger.
- **Hash chain cannot detect truncation from the end.** Removed last lines are
  invisible to the chain. The auditor states this.
- **Write scan** does not see writes through a non-literal `Path.open` mode. The
  runtime snapshot covers only the in-process run, not the child processes.
- **Exchange counter is per process.** A restarted coordinator starts again.
- **Coordination multiple** divides exchanges by runs and by a monolith
  denominator of 1 authorization per run. That denominator is an assumption for
  the faculty to dispute (ADR-0006).
- **Replay protection after restart** depends on an intact ledger.
- **Provisioner diagnostics.** "did not become ready" gives no detail while the
  child is still alive.
- **Local Python 3.12.** The `py -3.12` launcher is broken on the development
  machine. CI on `main` is the 3.12 check.
- **Signed capability declarations** are not implemented. Declarations are
  trusted as received over localhost.

## Verification

- Full suite: `python -m unittest discover -s tests -v`
- One gate: `python -m unittest discover -s tests -p "test_g2_*.py" -v`
- Syntax check: `python -m compileall -q domains coordinator ledger provision.py demo.py`
- Scenarios: `python demo.py`
- Rebuild one run: `python -m ledger.reconstruct <run_id>`

Saved real output for each is in `traces/v0-9-*.txt`.
