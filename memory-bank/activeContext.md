# Active Context

## Current focus
v3.0.0 CLI model planner is implemented on feat/model-planner (commits not merged, not pushed). Single next step: the user puts XAI_API_KEY in .env (git-ignored), then run python onboard.py --subject <id> --planner model --request-text "..." for real, save the transcripts as traces/v3-0-onboard-model-*.txt (labelled single live runs, key absent), confirm the API response shape in the ADR, then ask to merge. Web UI selector is a later step.
ADR-0011 is Accepted on branch docs/adr-0011-api (not merged, not pushed); main holds the merged draft at b41543f (not pushed). Single next step: on your go-ahead merge and push, then start feat/model-planner with the new-feature workflow (plan in the session plan file: app/model_planner.py, exit code 5, G6 .env rules, new gate G7). Older paragraphs below are superseded where they conflict.
Main is at d8e3460 (v2.0.1 archive record merged, CI green); v2.0.1 is the version for the faculty review. Next idea, drafted only: v3.0.0 opt-in model planner (docs/adr/0011-model-planner.md, Proposed; ROADMAP Next) on branch docs/v3-model-planner-draft (not merged). Single next step: merge the draft with approval, then check the xAI API docs, accept ADR-0011 and start feat/model-planner with the new-feature workflow. The paragraphs below are older state.
v2.0.1 is RELEASED: tag v2.0.1 at e263319 pushed, CI green on main (38896917099) and on the tag (38897682783). Archive rebuilt from the tag, SHA-256 303691BD016A1AEDB8DB4F9E18505D65549A7A55804A5B48F655550682BB2063, extracted copy 392 tests OK, gates OK (traces/v2-0-1-archive-tests.txt). Record is on branch docs/v2-0-1-archive (merge and push need approval). Single next step: rehearse the faculty review with docs/review-guide.md (note: its step 1 cites 388 tests; the live suite prints 392). The older paragraphs below describe the state before the tag and are superseded where they say the tag is not created.
v2.0.1 prep is merged to main and pushed (changelog, review guide, roadmap; suite 392 OK). Tag v2.0.1 is NOT created yet: ask the user, then tag the merge commit, push the tag, dispatch CI on it (`gh workflow run ci.yml --ref v2.0.1`), rebuild dist/onboarding_coordinator.zip from the tag, check an extracted copy and record the SHA-256 (progress.md, checklist D1 row, traces/v2-0-1-archive-tests.txt). Faculty prep is in docs/review-guide.md.
Final audit is done and merged to main at 3d4140e, pushed to origin (see docs/final-audit.md). CI is green for 3d4140e and 637b40a (checked with gh, which is installed and logged in; use `gh run list --branch main`). The v2.0.1 tag is decided (yes); the tag itself still waits for the user's go-ahead.
v2.0.0 (local web UI) is released: merged to main at e1d262d, tag v2.0.0 pushed, CI green on main and on the tag. Suite 385 OK, gates G1 15, G2 11, G3 10, G4 7, G5 7, G6 11. ADR-0010 accepted. Archive rebuilt from the tag (see the checklist, D1). Nothing is planned after it; see ROADMAP.
v1.2.0 (CLI and onboarding core) is released: merged to main at 4005885, tag v1.2.0 pushed, CI green, release checks passed (clone and extracted archive: 324 tests OK, gates OK; demo exit 0). Release traces traces/v1-2-release-*.txt. Next: v2.0.0 (local web UI, ADR-0010 draft, not started). Pending housekeeping on branch docs/v1-2-release-record: these memory-bank updates.
Planning decisions are recorded: CLI and web UI both kept; the UI releases as v2.0.0 (local, standard library, port 8110); no browser tool as a dependency; UI evidence as saved HTTP transcripts. ADR-0009 is accepted (v1.2.0); ADR-0010 is still a draft (Proposed). v1.1.0 is released: tag at 122e735, pushed to origin, CI passed on the tagged commit (dispatch run 38719865085) and on main. Suite 279 passing on Python 3.14.2; gates G1 15, G2 11, G3 10, G4 7, G5 7, G6 11; traces traces/v1-1-*.txt. Archive in dist/ (SHA-256 in progress.md). Changelog entry is in CHANGELOG.md. The v1.0.0 tag is at a93b5f9 and its archive SHA is in progress.md. CI on Python 3.12 is the 3.12 check (local py -3.12 still broken); it runs on pushes to main, PRs and manual dispatch, not on tag pushes.

## Recent decisions
- v0.8: perimeter checks are stdlib tests in tests/perimeter_scan.py, not a module in the source folders (11-file rule). ADR-0007.
- v0.8: the credential scan exempts test fixture placeholders by exact quoted value only (FIXTURE_SECRETS). Any other secret-shaped literal fails.
- v0.8: write scan compares every write call site to an exact allowlist (approval marker, ledger append). Runtime check diffs a state/ snapshot around one run.
- v0.8: found, not fixed: TokenMinter holds the exchange secret and derives each domain key in memory (coordinator/tokens.py:88). G6 proves coordinator/ never stores or reads a domain key, not that it cannot compute one. ADR-0007 records it; closing it is a key-design decision.
- v0.7: coordination multiple = exchanges / (runs x 1), the 1 being the monolith's single authorization per run (ADR-0006). Stated assumption for the faculty to dispute.
- v0.7: the auditor counts actions per (jti, action), last line wins, because a handler fault writes action_executed then action_failed.
- v0.7: a broken domain chain is reported and its lines are not counted; reconstruct exits 1.
- v0.6: domain failure does not stop the run; its actions are not_executed and later domains still run. No retries. ADR-0005.
- v0.6: tokens minted per domain just before each call; aborted runs (approval refused) mint nothing and leave no ledger line.
- v0.6: provision.py "did not become ready" gives no detail while the child is still alive. Diagnostic gap, not fixed.
- v0.5: approval replay key is approval_id, not plan hash (a second run of the same plan needs a fresh approval). ADR-0004.
- v0.5: approval consume is an exclusive-create marker, written only after tag, expiry and plan-hash checks pass.
- v0.5: coordinator MAC primitives (keyed_digest, constant_time_equal) live in tokens.py.
- v0.5: unsupported actions are refused at planning; will_not actions stay in the plan.
- HTTP contract, ledger events and per-domain actions fixed in docs/adr/0003-domain-http-contract.md.
- Rejected tokens write a token_rejected ledger line (attack evidence); an attacker can add such lines, so the auditor counts them separately.
- Domain servers set allow_reuse_address False (Windows SO_REUSEADDR would allow port shadowing).
- provision.py waits for a READY line from each child instead of sleeping; tests bind port 0.
- Registry refuses stale declarations (raises DeclarationStale) instead of returning False from supports().
- Staleness is strictly greater than TTL (age equal to TTL is fresh).

## Blockers / open questions
- Coordinator can derive domain keys from the exchange secret. Decided for v1 in ADR-0008: stated limit, claim narrowed to "stores and reads no domain key". Strict version needs a broker or a third-party package (future ADR).
- Local `py -3.12` launcher is broken (python is 3.14.2); the 3.12 suite runs in CI (green on the v1.1.0 tagged commit), not locally.
- Hash chain cannot detect removal of the last entries; the auditor states that limit.
- Replay protection after restart depends on an intact ledger.
- Clock moving backwards is treated as fresh (registry staleness and approval expiry).
- Deleting a consumed approval marker alone no longer re-opens replay (domains refuse reused approval_id). Deleting every marker and domain ledger still does; local files.
- Write scan does not see Path.open with a non-literal mode; the runtime snapshot covers only the in-process run.
- ci.yml compileall now includes demo.py (v0.6 onward).

## Next step
Known-gap fixes merged to main via integrate/ps3-gaps and pushed to origin: 279 tests OK, gates G1 to G6 pass, traces traces/v1-1-*.txt. Next step: see the continuation prompt; confirm CI for the pushed head with gh run list.
