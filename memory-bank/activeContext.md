# Active Context

## Current focus
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
