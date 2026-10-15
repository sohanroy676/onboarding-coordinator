# Architecture

One coordinator process and three independent domain agent processes (HR, IT, Facilities), all on one Windows machine, talking HTTP with JSON on 127.0.0.1. The coordinator holds zero domain credentials. Each domain verifies its own tokens, enforces its own will_not list and writes its own ledger.

## Folder structure
onboarding_coordinator/
  domains/
    domain_agent.py       shared domain runtime: HTTP server, token check, will_not, ledger write
    hr_agent.py           HR identity, capabilities, will_not, simulated actions
    it_agent.py           IT, same shape
    facilities_agent.py   Facilities, same shape
  coordinator/
    registry.py           capability declarations, TTL staleness, KeyError for unknown domain, supports()
    planner.py            one consolidated plan, canonical JSON, one SHA-256 plan hash, advisory warnings
    approval.py           sign approval; verify tag, expiry, re-derived hash; consume once
    tokens.py             derive per-domain keys, mint one-domain tokens, real exchange counter
    run.py                runs one onboarding in order and reports status
  ledger/
    ledger.py             append-only JSON Lines with a hash chain
    reconstruct.py        read-only auditor: rebuilds a run by correlation ID
  provision.py            operator: makes secrets in memory, starts and stops the domains
  demo.py                 runs every scenario and prints the traces
  tests/                  unit tests and the six gate tests
  docs/                   implementation document, acceptance checklist, troubleshooting guide
  traces/                 saved real terminal output
  state/                  runtime only, git-ignored (approvals/, one folder per domain)
The three source folders hold exactly 11 files and no __init__.py (namespace packages). Every process starts from the project root with python -m.

## Data flow (one onboarding run)
1. Discover: coordinator calls GET /capabilities on each domain; registry stores each declaration with its own receipt time.
2. Plan: planner builds one plan covering all domains, refuses stale or unknown domains, and hashes it once. Actions on a domain's will_not list stay in the plan with a warning; the coordinator never drops them.
3. Approve: the approver signs the plan hash once.
4. Verify: coordinator checks, in order, the approval tag, expiry, re-derived plan hash, then consumes it by creating a marker file in exclusive mode.
5. Mint and execute: only after approval, coordinator mints one short token per domain (subject = new hire, actor = coordinator, audience = that domain, scope = that domain's actions) and calls POST /execute on HR, then IT, then Facilities.
6. Decide at the domain: check token (malformed_token, domain_mismatch, invalid_signature, token_expired, token_replayed), then each action (out_of_scope, will_not, unsupported_action), write the ledger line, then act.
7. Report: coordinator sets status success, partial, failed or aborted from the per-action outcomes and prints the exchange count. No retries, no rollback.
8. Audit: ledger/reconstruct.py reads the three ledgers by run ID and checks each hash chain.

## Module responsibilities and boundaries
- domains/ never imports from coordinator/; coordinator/ never imports from domains/. Only domains and the auditor use ledger/.
- Token verification lives only in domain_agent.py; minting lives only in tokens.py. A unit test proves the two agree.
- Each domain is the only authority for its refusals and the only writer of its ledger.
- The coordinator writes only approval marker files.

## Third-party services, APIs and secrets
- No third-party services or APIs.
- No .env file and no secret in any file. Secrets exist only in process environment variables created in memory by provision.py.
- Never hardcode a secret or key. .env is still listed in .gitignore as a guard.