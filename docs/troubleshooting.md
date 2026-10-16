# Troubleshooting

Each entry lists a symptom, the cause this project has actually hit, and the fix.
Causes that are not verified are not listed.

## Provisioning

### `provision failed: ... did not become ready`

**Cause:** a domain process from an earlier run is still alive and holds port
8102 or 8103. The new child cannot bind, so it never prints READY. The provisioner
stops that child after a short wait and prints its stderr after the error, so the
bind message is shown (the cause above is the usual one).

**Fix:** find and stop the process holding the port, then run again.

```
netstat -ano | findstr :8102
taskkill /PID <pid> /F
```

Check the other ports (8101, 8103) the same way. Or set `OC_PORT_HR`, `OC_PORT_IT`
or `OC_PORT_FAC` to free ports.

### Setting `OC_EXCHANGE_SECRET` or `OC_APPROVAL_SECRET` has no effect

**Cause:** the two secrets are not environment variables. `provision.py` creates
them in memory each time it starts, and no code reads them from the environment.
Nothing reports a missing one, because nothing reads one.

**Fix:** do not set them. Start the system with `python provision.py` or
`python demo.py`. Only the domain processes read environment variables.

### `OC_DOMAIN_KEY is missing or not 64 hex digits`

**Cause:** a domain process was started by hand, without the key that
`provision.py` gives each child. The process exits with code 2 before it binds a
port, and this message is written to stderr.

**Fix:** start the domains through `python provision.py`, which derives and passes
each key. Do not run `python -m domains.hr_agent` by itself for a demo run.

### `cannot start <domain>: ...`

**Cause:** the domain could not bind its port or could not open its ledger. The
text after the colon names the error, for example a port in use or a corrupt ledger.

**Fix:** for a port, see the `did not become ready` entry above. For a ledger, see
`python -m ledger.reconstruct` in the Ledgers and audit section.

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
around it: the domains also refuse the reused approval (`approval_replayed`), so
the run executes nothing.

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

## Upgrading from v1.0

### Old `state/` from v1.0 is not reused by v1.1

**Cause:** v1.1 changed the token and approval formats. A v1.0 token has no
`approval_id` claim, and a v1.0 approval has no `issued_at` field.

**What you see:** a domain refuses an old token as `malformed_token`, and the
coordinator refuses an old approval as `invalid_approval_tag` before any marker
is written. Nothing runs under an old approval.

**What is still readable:** the v1.0 ledgers. Checked on a real v1.0 run: the
v1.1 auditor (`python -m ledger.reconstruct <run_id>`) rebuilt all six actions
with every hash chain `ok`.

**Fix:** delete the old runtime folder and start fresh. `state/` is runtime only
and is not in git.

## Onboarding CLI (`python onboard.py`)

### Exit 2: `input error: ...`

- `subject is empty`, `subject must be printable ASCII with no spaces`, `subject is longer than 254 characters`,
  or `subject must contain exactly one @`: fix the `--subject` value. Nothing is started and no prompt is shown.
- `request must be domain:action`, `unknown domain`, or `action must match [a-z_]{1,40}`: fix the `--request` value.
  Domains are `hr`, `it` and `facilities`, lower case.

### Exit 2: `plan refused: ...`

- `<domain> does not offer <action>`: the action is not in that domain's capability declaration. Check the
  spelling against `python -m unittest` tests or the declarations in `domains/`.
- `declaration is N s old, TTL is 60s`: the domain's declaration is older than its TTL when the plan is built.
  Only a clock that moved between the refresh and the plan can cause this inside one run; start again.
- `unknown domain: <name>`: a domain name outside the three configured ones.

No prompt is shown for either form of exit 2.

### Exit 3: `not approved: nothing was approved, minted or sent`

- The answer was not `y` (any case). `n`, an empty line, or any other word is a decline.
- Input ended (`EOFError`), for example a piped run with no answer. The saved trace
  `traces/v1-2-onboard-declined.txt` shows this with exit code 3.
- Ctrl-C at the prompt is also a decline. No approval marker, no POST and no ledger line are written.

### Exit 4: `domains did not start: ...`

- `<domain> did not become ready: <stderr>`: a child process did not print READY. Its stderr is shown. The
  usual cause is a port already in use. Stop the stale domain processes and try again, or set `OC_PORT_HR`,
  `OC_PORT_IT` or `OC_PORT_FAC` to free ports.
- `<domain>: connection refused` (or another `OSError`) from the registry: the domain started but did not answer
  its declaration. The run stops before any prompt.
- `<domain>: HTTP <code>` or an invalid declaration: the domain answered with something the registry refuses.

### Exit 5: `model planner failed: ...`

- `no .env file; copy .env.example to .env and set GROQ_API_KEY`: `--planner model` needs a `.env` file
  in the project root with `GROQ_API_KEY=<your key>`. The file is git-ignored; never commit it. The saved
  trace `traces/v3-0-onboard-model-no-key.txt` shows this with exit code 5. No domain was started.
- `rate limit exceeded (HTTP 429)`, `HTTP <code>: <provider text>`, or `model call failed: <ErrorName>`: the
  call was refused or did not complete. The provider's error text is shown (cut to 200 characters, key
  redacted). Nothing is retried and nothing falls back to the deterministic planner. Run again later, or
  choose `--planner deterministic` yourself. An `Invalid API Key` or similar message means the key is not
  a Groq key (a Groq key starts with `gsk_`). A message that the model does not exist means `--model` names
  a model your key cannot use; preview models can be withdrawn.
- `model proposal ...` or `model proposed an unusable request`: the reply did not match the strict
  shape. Nothing was approved, minted or sent. Rephrase the request text and run again.

### Exit 1 after approval: `interrupted after approval`

- Ctrl-C after the answer `y` stops the coordinator while domains may be partly done. Rebuild the run with the
  printed `python -m ledger.reconstruct <run id>`. Nothing is retried or rolled back.

## Traces

Save a trace only from a real run, with shell redirection from the project root.
Never edit one by hand, because the checklist cites them as real output.
