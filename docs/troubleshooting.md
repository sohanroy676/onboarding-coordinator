# Troubleshooting

Each entry lists a symptom, the cause this project has actually hit, and the fix.
Causes that are not verified are not listed.

## Provisioning

### `provision failed: ... did not become ready`

**Cause:** a domain process from an earlier run is still alive and holds port
8102 or 8103. The new child cannot bind, so it never prints READY. The error
gives no detail while the child is still alive (known diagnostic gap).

**Fix:** find and stop the process holding the port, then run again.

```
netstat -ano | findstr :8102
taskkill /PID <pid> /F
```

Check the other ports (8101, 8103) the same way. Or set `OC_PORT_HR`, `OC_PORT_IT`
or `OC_PORT_FAC` to free ports.

### Domain processes start but requests fail with socket errors

**Cause:** the child environment lacks `SYSTEMROOT`. `provision.py` gives each
child a short allowlist (`SYSTEMROOT`, `PATH`) plus its own key, and sockets fail
without `SYSTEMROOT` on Windows.

**Fix:** start the domains with `python provision.py`, which passes `SYSTEMROOT`
and `PATH` to each child with its own key. Do not start them by hand.

### Imports fail when a file is run from another folder

**Cause:** the source folders are namespace packages with no `__init__.py`, so
their imports resolve from the project root.

**Fix:** start everything from the project root with `python -m`, for example
`python -m domains.hr_agent`, or let `python provision.py` start them.

### `py -3.12` does not start Python 3.12

**Cause:** the local `py` launcher on the development machine is broken. The
interpreter on PATH is 3.14.2.

**Fix:** use `python`. The 3.12 check is CI on `main`, not a local run.

## Runs and refusals

### `status: aborted (approval_already_consumed)`

**Cause:** the approval for this plan was already used. Each approval is
consumed once, and the replay check holds after a restart.

**Fix:** this is the expected result for a replay (demo scenario 3). To run the
same plan again, sign a fresh approval. Do not delete the consumed marker to get
around it: deleting it re-opens replay (see the limits).

### `status: aborted (plan_changed_since_approval)`

**Cause:** the plan changed after it was signed, so the re-derived hash does not
match.

**Fix:** build the plan again and sign a new approval for it.

### `status: partial` with `refused 1`

**Cause:** an action is on a domain's `will_not` list. The coordinator keeps it in
the plan with a warning, and the domain refuses it. This is expected for
`grant_admin_access` (demo scenario 2).

**Fix:** none needed. Read the `warning:` line and the refused row in the table.

### `status: partial` with `not_executed`

**Cause:** a domain was unreachable or answered badly. Its actions are
`not_executed` with a reason (`domain_unreachable`, `domain_error:<code>`,
`bad_response`). The run goes on to later domains. There are no retries.

**Fix:** check that the domain process is running (`python provision.py` checks
health). Then run again with a fresh approval. The run does not retry.

## Ledgers and audit

### `python -m ledger.reconstruct` exits 1 and reports a broken chain

**Cause:** a domain ledger line was changed or a line in the middle was removed.
The auditor reports the position and does not count the broken lines.

**Fix:** do not edit the ledger. Keep the file as evidence and note the position
the auditor printed.

### A rebuilt run shows fewer lines than expected

**Cause:** an aborted run leaves no ledger line, and a `not_executed` action
leaves none either. Both are expected (printed as limits by every rebuild).

## Traces

Save a trace only from a real run, with shell redirection from the project root.
Never edit one by hand, because the checklist cites them as real output.
