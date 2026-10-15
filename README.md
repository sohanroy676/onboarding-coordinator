# Onboarding coordinator

A federated, least-privilege employee onboarding coordinator for problem statement PS3.
A coordinator process plans one onboarding run across three domain agents (HR, IT and
Facilities). Each domain checks its own tokens, enforces its own refusals and writes its
own ledger. The coordinator stores and reads no domain key; it can derive one in memory,
a stated limit (ADR-0008).

This is an academic prototype for an Agentic AI course. It runs only on 127.0.0.1 and
uses simulated actions. It contains no language model and no real HR, IT or Facilities
system.

## Requirements

- Python 3.12 or newer on Windows. Standard library only: nothing to install.
- Local development and the v1.0 checks used Python 3.14.2. The Python 3.12 check runs
  in CI on pushes to `main`.

## Commands

Run every command from the project root.

```
python provision.py                                      # start, health-check and stop the domains
python demo.py                                           # run every scenario and print the traces
python onboard.py --subject <id>                        # plan, approve at the console, run, rebuild
python -m unittest discover -s tests -v                  # full test suite
python -m unittest discover -s tests -p "test_g1_*.py" -v   # one gate (g1 to g6)
python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app   # syntax check
python -m ledger.reconstruct <run_id>                    # rebuild one run from the domain ledgers
```

If `python` is not on PATH, use `py -3.12`.

## Onboarding from the console (v1.2)

```
python onboard.py --subject new.hire@example.test
python onboard.py --subject new.hire@example.test --request it:create_account --request it:grant_admin_access
```

The default requests are the six supported actions. `--request DOMAIN:ACTION` (repeatable)
replaces them. The plan and its warnings are printed, then the prompt
`Approve this plan? [y/N]` asks the operator. Only `y` (any case) approves; any other
answer, end of input or Ctrl-C ends with nothing approved, minted or sent.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | every action executed (status success) |
| 1 | partial, failed or aborted run, or a run interrupted after approval |
| 2 | bad subject or request, or the plan was refused before the prompt |
| 3 | not approved |
| 4 | the domains did not start or did not give a valid declaration |

Every run ends with the rebuild from the three ledgers and the run id. See
`docs/troubleshooting.md` for the causes of each code.

## Documentation

- `docs/implementation.md`: how the system is built, its trust boundaries and its limits.
- `docs/acceptance-checklist.md`: each expected result, the test that proves it and the
  saved trace that shows it.
- `docs/troubleshooting.md`: verified causes for common failures.
- `docs/adr/`: architecture decisions.
- `ROADMAP.md`: the version plan and what is not planned.
- `traces/`: terminal output saved from real runs.

## Stated limits

- The coordinator can derive every domain key from the exchange secret. Tests show it
  never stores or reads one, but not that it cannot compute one (ADR-0007).
- A clock that moves backwards is treated as fresh.
- Deleting a consumed approval marker alone does not re-open replay; deleting every marker and domain ledger does.
- The hash chain cannot detect truncation from the end of a ledger.
- The monolith denominator in the coordination multiple (one authorization per run) is
  an assumption for the faculty to dispute (ADR-0006).
