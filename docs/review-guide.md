# Faculty review guide

A short demo script and answers to the likely questions. Every figure below is copied
from a saved real run; the trace that shows it is named next to it. Nothing here is a
new claim: the limits are the ones in `docs/final-audit.md` section 7.

## Before you start

- Run everything from the project root.
- Ports 8101 to 8103 (domains) and 8110 (UI) must be free. A domain agent or the UI left
  over from an earlier session fails the demo with `WinError 10048`. Stop it first.
- If `python` is not on PATH, use `py -3.12`.

## Demo script (about 13 minutes)

1. **The suite and the syntax check** (1 min).
   `python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app`
   then `python -m unittest discover -s tests -v`. Point at: 469 tests, OK
   (`traces/v3-1-0-archive-tests.txt`, which also shows compileall exit 0 and gates G1
   to G7 on the v3.1.0 archive).
2. **Every scenario** (3 min). `python demo.py` (`traces/v3-0-demo.txt`). Point at:
   - Scenario 1: `status: success  executed 6  refused 0`.
   - Scenario 2: `it grant_admin_access will_not refused`, then
     `status: partial  executed 6  refused 1`. The IT agent refused it, not the
     coordinator, and the plan still carried the action with a warning.
   - Scenario 3: replay of the approval gives `aborted (approval_already_consumed)`.
   - Scenario 4: `coordination multiple: 3.0  (15 exchanges / 5 runs / 1 monolith authorization)`.
3. **One run rebuilt from three ledgers** (1 min).
   `python -m ledger.reconstruct <run_id>` with a run id printed by the demo. Point at:
   hr 2, it 2, facilities 2, all chains ok, and the five printed limits
   (`traces/final-audit-reconstruct.txt`, `traces/final-audit-reconstruct-partial.txt`).
4. **One onboarding from the console** (2 min).
   `python onboard.py --subject audit.001@example.test`. Answer `y` to approve; run it a
   second time and answer `n` to show exit 3, nothing minted or sent
   (`traces/final-audit-onboard.txt`, `traces/v1-2-onboard-declined.txt`).
5. **A gate live** (1 min). `python -m unittest discover -s tests -p "test_g2_*.py" -v`
   (11 tests: wrong domain, missing token, forged token, replay, both coordinator secrets
   refused; `traces/v3-0-g2.txt`).
6. **Model planner, optional** (2 min, needs network and Groq quota; v3.0.0).
   `python onboard.py --subject review.001@example.test --planner model --request-text "New engineer. Needs an HR record, a laptop, an IT account and a badge."`
   Point at: the line `planner: model (qwen/qwen3.8-27b), N requests proposed`, the plan
   the model proposed, then the same `Approve this plan? [y/N]`. The reply varies from run
   to run. If Groq is down or the limit is hit, the run ends with exit 5 before the prompt,
   with nothing minted or sent; show the saved runs instead
   (`traces/v3-0-onboard-model-approved.txt`, `traces/v3-0-onboard-model-injection.txt`,
   `traces/v3-0-onboard-model-no-key.txt`).
   To show a refusal with the model, use the text "New engineer needs a laptop and admin
   access on their machine." The model usually proposes `it:grant_admin_access`; the plan
   keeps it with a warning and the IT agent refuses it (`partial`, executed 1, refused 1;
   `traces/v3-1-onboard-model-admin.txt`). The model's choice varies, so if it leaves the
   step out, say so and show the deterministic run in step 2 instead.
7. **Gate G7 live** (1 min). `python -m unittest discover -s tests -p "test_g7_*.py" -v`
   (8 tests, fake model client, no network: hostile model output cannot widen authority;
   `traces/v3-0-g7.txt`).
8. **Optional: the web UI** (1 min). `python -m app.server`, open
   `http://127.0.0.1:8110`. Same flow as step 4. Evidence is an HTTP transcript
   (`traces/v2-0-ui-transcript.txt`); there is no browser test. Since v3.1.0 the page has
   a Planner selector: choose `model`, enter the request text and make the plan. Real run
   through the UI: `traces/v3-1-ui-model-transcript.txt` (steps 11 and 12 show the admin
   request refused by the IT agent).

## Likely questions

**Can the coordinator mint a token for any domain? (key-derivation limit)**
Yes, in memory. The minter in `coordinator/tokens.py` holds the exchange secret and
derives each domain key from it. The coordinator stores no domain key, reads none from
the environment and names none; G6 proves that (`traces/final-audit-g6.txt`,
`traces/final-audit-coordinator-grep.txt`). It does not prove the coordinator cannot
compute one, and we say so. The "zero credentials" claim was narrowed to match
(ADR-0007, ADR-0008). A strict version needs asymmetric signing, which the standard
library does not have, or a separate signing broker process, which is out of scope and
would be a new ADR.

**Why is the monolith denominator 1? (coordination multiple)**
It is an assumption, stated in ADR-0006 and in the demo output: a monolith makes one
authorization per run. The numerator is real: 15 exchanges counted by the minter's
counter, which survives a restart, over 5 runs. Change
`MONOLITH_AUTHORIZATIONS_PER_RUN` in `coordinator/run.py` and the multiple changes
directly. The multiple is only as good as that assumption.

**Why does a `will_not` action stay in the plan?**
The domain is the only authority for its refusals. If the coordinator dropped the action,
the refusal would not be enforced where the action runs and would not appear in the IT
ledger. The planner only warns (`traces/final-audit-g4.txt`).

**Why no retries, rollback or parallel dispatch?**
Out of scope by the brief. A failed or refused action is reported, not hidden. Order is
HR, then IT, then Facilities. A domain failure does not stop later domains (ADR-0005).

**What stops a replayed approval?**
The coordinator consumes the approval by exclusive file create, and each domain refuses a
reused `approval_id` from its own ledger (ADR-0004, ADR-0003). Deleting every approval
marker and every domain ledger re-opens replay; that is a stated limit.

**Can the ledger be tampered with?**
Each ledger is a hash chain, checked on rebuild. It cannot see removed last lines, and
anyone with write access can add `token_rejected` lines. The auditor prints both limits.

**What does the model decide? (v3.0.0)**
Only the list of (domain, action) requests, and only when `--planner model` is chosen.
It is told the actions each domain supports and the ones a domain refuses, so a request
for a refused action is proposed and refused by the domain in the open, not dropped.
Its output is untrusted: it is parsed strictly, then goes through the same registry, plan
hash, human approval, scoped tokens and domain refusals as any other plan. A hostile
proposal (`grant_admin_access`, an unknown action, extra fields) is refused at planning or
stays in the plan with a warning and is refused by the domain (G7, `traces/v3-0-g7.txt`;
`traces/v3-0-onboard-model-injection.txt` shows one real attempt). Deterministic mode, the
gates and `demo.py` never use a model.

**What if Groq fails or the limit is hit?**
The run ends with exit 5 before the approval prompt. There is no retry and no automatic
fallback, so the plan's origin is never hidden; the user chooses the deterministic planner
(ADR-0011, `traces/v3-0-onboard-model-bad-model.txt`).

**Where is the agentic part?**
Two places. With the model planner, a model turns free text into proposed actions. In
every mode the agency is in the separate processes: three domain
agents that each declare capabilities, verify their own tokens, refuse on their own
policy and keep their own ledger, and a coordinator that plans and delegates but holds
no domain authority.

**Outcome 9 (the self-matching scan defect) and D12 (missing secret messages)?**
Outcome 9 is "not reproduced": this build never had that defect, and the audit says so
plainly. D12 is a recorded requirement change: both coordinator secrets exist only in
memory in `provision.py`, so no missing-variable message for them can occur (ADR-0008).
Changing either needs a decision, not a docs edit.

**What did the final audit find?**
One real defect. A refused POST with an unread body let a Windows close send a TCP reset,
so the client lost the 403, 404 or 405. It showed on Python 3.12 and not on 3.13, never
touched a gate, and is fixed in v2.0.1 with two regression tests
(`docs/final-audit.md` section 2).
