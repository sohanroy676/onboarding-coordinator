# Tech stack

## Language and runtime
- Python 3.12 or newer (CPython) on Windows.
- Standard library only. No third-party packages at runtime or in tests. No requirements.txt.
- Main modules: http.server (ThreadingHTTPServer), urllib.request, hmac, hashlib, secrets, json, base64, subprocess, threading, pathlib, time, unittest.
- If `python` is not on PATH, use `py -3.12` in every command below.

## Tests
- Framework: unittest (standard library). pytest is not used.
- Location: tests/ at the project root. No __init__.py.
- Naming: test_unit_*.py for unit tests; test_g1_domains_registry.py, test_g2_delegation.py, test_g3_approval.py, test_g4_refusal.py, test_g5_evidence_cost.py, test_g6_perimeters.py for the six acceptance gates; shared fixtures in tests/helpers.py.
- Run all (from project root): python -m unittest discover -s tests -v
- Run one gate: python -m unittest discover -s tests -p "test_g2_*.py" -v
- Tests use an injected clock, never sleep, and use ports different from the demo ports.

## Lint and format
- No third-party linter or formatter (the project is standard-library only).
- Style: PEP 8 by hand, 4-space indents, ASCII-only source and console output.
- Syntax check: python -m compileall -q domains coordinator ledger provision.py demo.py

## Run commands (from project root, PowerShell or cmd)
- Start the three domains, check health, stop them: python provision.py
- Run every scenario and print the traces: python demo.py
- Rebuild one run from the three ledgers: python -m ledger.reconstruct <run_id>

## Database and external services
- None. No database, no cloud services, no API keys.
- All traffic stays on 127.0.0.1 (ports 8101 HR, 8102 IT, 8103 Facilities; override with OC_PORT_HR, OC_PORT_IT, OC_PORT_FAC).
- Persistent state is plain files under state/: approval marker files and one JSON Lines ledger per domain.

## Environment variables
- OC_EXCHANGE_SECRET: coordinator only. Token-minting secret.
- OC_APPROVAL_SECRET: coordinator and approver step only. Approval-signing secret.
- OC_DOMAIN_KEY: one per domain process. That domain's derived key (hex).
- OC_STATE_DIR: where approvals and ledgers live. Default ./state.
- provision.py creates the secrets in memory and passes each process only its own variables. Nobody sets them by hand.

## Windows notes
- Child processes get an explicit env: a short allowlist of system variables (SYSTEMROOT, PATH) plus that process's own key.
- Use pathlib for every path. Never build paths with string concatenation.