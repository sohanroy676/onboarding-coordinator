# Onboarding coordinator

A federated, least-privilege employee onboarding coordinator for problem statement PS3.
A coordinator process plans one onboarding run across three domain agents (HR, IT and
Facilities). Each domain checks its own tokens, enforces its own refusals and writes its
own ledger. The coordinator stores and reads no domain key; it can derive one in memory,
a stated limit (ADR-0008).

You can run it from a local web UI (v2.0.0) or from the console (v1.2). Both use the same
flow: plan, approve, run, rebuild.

This is an academic prototype for an Agentic AI course. It runs only on 127.0.0.1 and
uses simulated actions. It contains no language model and no real HR, IT or Facilities
system.

## Requirements

- Python 3.12 or newer, on Windows. The project uses the standard library only, so there
  is nothing to download or install with pip.
- Local development and the v1.0 checks used Python 3.14.2. CI runs the Python 3.12 check
  on pushes to `main`.

## Setup

### 1. Clone the repository

```
git clone https://github.com/sohanroy676/onboarding-coordinator.git
cd onboarding-coordinator
```

To run the released version, check out its tag. This leaves the repository in a
"detached HEAD" state, which is fine for running and testing:

```
git checkout v2.0.0
```

### 2. Create a virtual environment

A virtual environment is optional here, since there are no packages to install. It keeps
the interpreter for this project separate from the rest of your machine. Create it in the
project root; the folder name `venv` is already git-ignored.

```
python -m venv venv
```

If `python` is not on PATH, use `py -3.12 -m venv venv`.

### 3. Activate it

Activate it in the shell you will run the project from:

| Shell | Command |
| --- | --- |
| PowerShell | `.\venv\Scripts\Activate.ps1` |
| Command Prompt (cmd) | `venv\Scripts\activate.bat` |
| Git Bash | `source venv/Scripts/activate` |

If PowerShell refuses to run the script, the execution policy is blocking it. Either run
`venv\Scripts\activate.bat` from cmd, or allow local scripts for your user only with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Check the interpreter:

```
python --version
```

It must print Python 3.12 or newer.

### 4. Nothing to install

The venv has no packages to download. Do not install anything into it: the project forbids
third-party packages, and there is no `requirements.txt`.

## Run the web UI (v2.0.0)

```
python -m app.server
```

Then open <http://127.0.0.1:8110/> in your browser. The default port is 8110. To use
another port, add `--port <number>`.

On the page:

1. Under **Domains**, start HR, IT and Facilities. A plan needs all three running.
2. Under **New onboarding**, enter the new hire's subject and the requests, one
   `domain:action` per line. The default requests are the six supported actions.
3. **Make plan** shows the steps and any warnings, and the plan hash.
4. **Approve and run this plan** signs that exact hash and runs it. A plan can be approved
   only once and expires after 5 minutes.
5. The run view shows each action's outcome, and the rebuild of each domain's ledger.
   **Look up a run** shows the rebuild of any run by its 16-character id.

Press Ctrl-C in the terminal to stop the UI. It also stops any domains it started.

The UI binds 127.0.0.1 only and checks the Host, Origin and CSRF token on every request.
Open it through `127.0.0.1` or `localhost`. Pending plans are held in memory, so a restart
of the UI drops them; make the plan again after a restart.

## Run from the console (v1.2)

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

## Other commands

Run every command from the project root, with the venv active.

```
python provision.py                                          # start, health-check and stop the domains
python demo.py                                               # run every scenario and print the traces
python -m ledger.reconstruct <run_id>                        # rebuild one run from the domain ledgers
python -m unittest discover -s tests -v                      # full test suite (about 3 minutes)
python -m unittest discover -s tests -p "test_g1_*.py" -v    # one gate (g1 to g6)
python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app   # syntax check
python -m tests.ui_transcript                                # run the UI for real; rewrites traces/v2-0-ui-transcript.txt
```

Do not run `demo.py`, `provision.py` or `onboard.py` while the web UI is running: they
all use the domain ports 8101 to 8103, and the second start fails with "did not become
ready". The web UI's own domains use the same ports.

Runtime files are written under `state/` (approvals, exchange counter and one ledger per
domain). It is git-ignored; delete it to start from an empty state.

## Documentation

- `docs/implementation.md`: how the system is built, its trust boundaries and its limits.
- `docs/acceptance-checklist.md`: each expected result, the test that proves it and the
  saved trace that shows it.
- `docs/troubleshooting.md`: verified causes for common failures.
- `docs/adr/`: architecture decisions (ADR-0010 is the web UI).
- `ROADMAP.md`: the version plan and what is not planned.
- `traces/`: terminal output and HTTP transcripts saved from real runs.

## Stated limits

- The coordinator can derive every domain key from the exchange secret. Tests show it
  never stores or reads one, but not that it cannot compute one (ADR-0007).
- A clock that moves backwards is treated as fresh.
- Deleting a consumed approval marker alone does not re-open replay; deleting every marker and domain ledger does.
- The hash chain cannot detect truncation from the end of a ledger.
- The monolith denominator in the coordination multiple (one authorization per run) is
  an assumption for the faculty to dispute (ADR-0006).
- The web UI runs in the coordinator process, so the operator and the coordinator share
  one trust domain (ADR-0009, ADR-0010). Its CSRF token is embedded in the page by design.
- The web UI's page has not been tested in a real browser; its behaviour is covered by
  the HTTP tests and the saved transcript.
