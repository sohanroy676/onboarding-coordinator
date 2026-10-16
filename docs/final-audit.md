# Final audit against the PS3 problem statement

Every figure below is copied from a trace in `traces/final-audit-*.txt`, captured from
real runs on the audited tree. Status words: **met**, **met with note**, **not
reproduced** (the statement describes an event this build did not have), **requirement
changed** (decided and recorded in an ADR).

## 1. Scope and environment

- Audited revision: `main` at dd4bf11 (v2.0.0 plus release records), plus the two audit
  commits on `docs/final-audit`: 0df779a (test) and dbbbb1e (fix). Nothing is merged,
  tagged or pushed.
- Python 3.13.1 (`python`) and 3.12.3 (`py -3.12`), Windows 11. The 3.12 suite now runs
  locally, so the old "3.12 only in CI" note is closed for this audit.
- Standard library only: no `requirements.txt`, no tracked file under `venv/`
  (`traces/final-audit-layout.txt`).
- Layout: 11 source files in `domains/` (4), `coordinator/` (5) and `ledger/` (2), and no
  `__init__.py` (`traces/final-audit-layout.txt`).

## 2. What the audit changed

| Change | Why | Evidence |
| --- | --- | --- |
| New test `test_g1_domains_registry.DomainsDiscoveryTests.test_rubric_figures_declaration_0_1s_old_with_max_0_01s_is_refused` | The statement names a declaration 0.1 s old with a 0.01 s maximum. G1 only used a 60 s TTL. The registry already handled it; no production change. | `traces/final-audit-g1.txt` (16 tests, was 15) |
| Fix in `app/server.py` and `domains/domain_agent.py` (HTTP handlers) | **A real defect found by the audit.** A refused POST left its body unread. On Windows the close then sent a TCP reset and the client lost the 403, 404 or 405. The suite passed on 3.13 and failed intermittently on 3.12 (`ConnectionAbortedError: WinError 10053` in `test_unit_app_server` and `test_unit_domain_http`). It never touched a gate. | Two regression tests, `test_unit_app_server.OriginAndCsrfTests.test_refusal_of_a_post_with_a_body_is_always_readable` and `test_unit_domain_http.HttpEdgeTests.test_refused_post_with_a_body_is_always_answered`. The domain test failed 4 of 4 runs without the fix and passed 4 of 4 with it. The UI handler tests failed intermittently on the baseline (for example 2 of 6 runs) and passed 16 of 16 repeated runs on 3.12 and 3.13 after the fix. |

The fix has two parts. The domain handler reads (bounded) the declared body of a refused
POST before it replies. The UI handler stops sending, reads what is left (bounded) and
only then closes. Behaviour, status codes and bodies are unchanged.

Process note: my first version of the UI fix referenced a constant that a failed text
replace never defined. It still passed because the `shutdown` call ran before the error.
I found it in the diff review, defined the constant, and repeated all runs. The traces in
this audit are from the corrected code.

## 3. Requirements 1 to 7

| # | Requirement | Verdict | Code | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Three independent domain agents, own capabilities and `will_not`, enforced at execution | met | `domains/*_agent.py`, `domains/domain_agent.py` | `final-audit-g1.txt`, `final-audit-g4.txt` (the IT ledger shows the refusal) |
| 2 | Registry with real staleness; unknown domain raises | met | `coordinator/registry.py` | `final-audit-g1.txt`, including the 0.1 s / 0.01 s case |
| 3 | Token exchange, subject and actor, one domain, verified by each domain | met | `coordinator/tokens.py` (mint), `domains/domain_agent.py` (verify) | `final-audit-g2.txt` |
| 4 | One consolidated plan, one hash | met | `coordinator/planner.py` | `final-audit-g3.txt`, `test_unit_planner` in `final-audit-tests.txt` |
| 5 | One approval; hash re-derived; replay and changed sub-plan fail closed | met | `coordinator/approval.py` | `final-audit-g3.txt`; demo scenario 3 `aborted (approval_already_consumed)` in `final-audit-demo.txt` |
| 6 | Honest partial failure | met | `coordinator/run.py` | demo scenario 2: `status: partial  executed 6  refused 1`, `it grant_admin_access refused will_not` |
| 7 | One correlation ID across three ledgers; measured cost | met | `ledger/reconstruct.py`, `coordinator/run.py` | `final-audit-reconstruct.txt`, `final-audit-g5.txt`, demo scenario 4 |

## 4. Expected outcomes 1 to 9

| # | Outcome | Verdict | Observed |
| --- | --- | --- | --- |
| 1 | Domain agents with enforced `will_not` | met | G1 16 OK; G4 7 OK; refusal written by IT, not the coordinator |
| 2 | Forced-stale declaration refused; unknown domain `KeyError` | met | New G1 test uses the exact figures (0.1 s old, 0.01 s max) and asserts both numbers in the message |
| 3 | Wrong-domain `domain_mismatch`, forged token on signature, missing token `malformed_token`, correct token executes | met | G2 11 OK |
| 4 | First use succeeds, replay `approval_already_consumed`, changed sub-plan `plan_changed_since_approval` | met | G3 10 OK; demo scenario 3 |
| 5 | Partial: `status: partial`, executed 6, refused 1, domain and reason named | met | demo scenario 2, exit 0 |
| 6 | One run ID rebuilds hr 2, it 2, facilities 2 | met | `final-audit-reconstruct.txt`: hr 2, it 2, facilities 2, chains ok. The partial run (`final-audit-reconstruct-partial.txt`) gives it executed 2, refused 1 |
| 7 | Five runs, 15 exchanges, multiple 3.0 from a real counter | met with note | `coordination multiple: 3.0  (15 exchanges / 5 runs / 1 monolith authorization)`. The denominator of 1 per run is an assumption stated in ADR-0006 |
| 8 | Zero credential matches in `coordinator/`; both coordinator secrets refused as tokens | met with note | G6 11 OK. `final-audit-coordinator-grep.txt`: a value-level grep (32+ hex digits, key blocks, cloud key ids) has zero matches. A name-level grep finds 4 lines in `coordinator/tokens.py` (a function name, a docstring and the minter holding the exchange secret). They hold no value, but they are the known limit that the coordinator can derive domain keys (ADR-0007, ADR-0008) |
| 9 | A self-matching scan defect found and fixed by excluding the test file | not reproduced | This build never had the defect. The scanner keeps its patterns in `tests/perimeter_scan.py`, exempts fixtures by exact quoted value only and does not exclude any file from itself. Planted controls in `tests/test_unit_perimeter_scan.py` show the scan fails on a real literal. The defect story in the statement is not claimed for this project |

## 5. Deliverables D1 to D12

| D | Status | Evidence |
| --- | --- | --- |
| D1 Source archive | met with note | `dist/onboarding_coordinator.zip` is git-ignored and was missing on disk. It was rebuilt from the audit branch and checked from an extracted copy (`final-audit-archive-tests.txt`; SHA-256 in `memory-bank/progress.md`) |
| D2 Implementation document | met with note | `docs/implementation.md`; traces from v0.6 on, and re-runs for v0.2 to v0.5 (they were not saved at the time) |
| D3 to D9 Milestones M1 to M7 | met | Sections 3 and 4 |
| D10 Two-perimeters test | met with note | Section 4, outcome 8; ADR-0008 narrowed the claim to "stores and reads no domain key" |
| D11 Acceptance checklist | met | `docs/acceptance-checklist.md` plus the section "Final audit" |
| D12 Troubleshooting guide | requirement changed | The statement lists a missing `OC_EXCHANGE_SECRET` or `OC_APPROVAL_SECRET`. By design both secrets exist only in memory in `provision.py`, so no such message exists. The guide says so (ADR-0008) and shows the one real missing-variable message, for `OC_DOMAIN_KEY` (`traces/v1-0-d12-missing-key.txt`). If the faculty want the original messages, this needs a design decision, not a docs fix |

## 6. Success criterion

| Clause | Verdict |
| --- | --- |
| All six gates pass under their exact commands | met: G1 16, G2 11, G3 10, G4 7, G5 7, G6 11, each OK |
| All seven milestones run end to end | met: demo exit 0 and one console onboarding, exit 0 (`final-audit-onboard.txt`) |
| `will_not` enforced at the domain | met |
| Tokens verified independently by each domain | met |
| One approval binds the whole plan; replay and tamper rejected | met |
| Partial failure reported honestly | met |
| Cost measured, not asserted | met with note (assumption in ADR-0006) |
| No domain credential in the coordinator | met with note: stores and reads none, but can derive keys (ADR-0007, ADR-0008) |

Full suite: 388 tests OK on Python 3.13.1 and on 3.12.3. `compileall` exit 0.

## 7. Stated limits (unchanged, not hidden)

- The coordinator can derive every domain key from the exchange secret. Closing it needs
  a broker process or a third-party package.
- A clock rewind to a time still after an approval's issue time extends its life.
- The hash chain cannot see removed last lines.
- Deleting every approval marker and every domain ledger re-opens replay.
- The UI's CSRF token is in the page by design; the UI shares the coordinator's trust domain.
- No browser test of the web page; it is covered by HTTP tests and a transcript.
- The demo uses fixed ports 8101 to 8103. Domain agents left running from earlier
  sessions block it with `WinError 10048`; stop them first.

## 8. Verdict

All six gates pass, all seven milestones run end to end, and every expected result in the
statement is reproduced from real runs, with three differences stated openly:
outcome 9 is not reproduced (the build never had that defect), D12 is a recorded
requirement change, and the "zero credentials" claim is the narrowed form in ADR-0008.
The audit found and fixed one real defect (refused POSTs could be lost to a connection
reset on Windows) that the earlier single-Python runs did not show.
