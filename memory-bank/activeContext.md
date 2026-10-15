# Active Context

<!-- Update this at the end of every session. This is the first thing to read when resuming. -->

## Current focus
v0.7 Evidence and cost (M7, gate G5) is implemented on feature/v0-7-evidence-cost (not committed, not merged, not pushed). Full suite 220 tests passing on Python 3.14.2; compileall clean. traces/v0-7-demo.txt and traces/v0-7-reconstruct.txt are from real runs. CI on Python 3.12 is the 3.12 check (local py -3.12 still broken). v0.6 merged to main (15de14a) with CI green on 3.12.

## Recent decisions
- v0.6: domain failure does not stop the run; its actions are not_executed and later domains still run. No retries. ADR-0005.
- v0.6: tokens minted per domain just before each call; aborted runs (approval refused) mint nothing and leave no ledger line.
- v0.6: G4 tests run domains in process with the injected clock; provision.py children use the real clock, so real processes are only exercised by demo.py.
- v0.6: provision.py "did not become ready" gives no detail while the child is still alive. Diagnostic gap, not fixed.
- v0.5: approval replay key is approval_id, not plan hash (a second run of the same plan needs a fresh approval). ADR-0004.
- v0.5: approval consume is an exclusive-create marker, written only after tag, expiry and plan-hash checks pass.
- v0.5: coordinator MAC primitives (keyed_digest, constant_time_equal) live in tokens.py, keeping the only-tokens-and-domain-agent-use-HMAC boundary test true.
- v0.5: unsupported actions (neither supported nor will_not) are refused at planning; will_not actions stay in the plan.
- HTTP contract, ledger events and per-domain actions fixed in docs/adr/0003-domain-http-contract.md.
- Rejected tokens write a token_rejected ledger line (attack evidence); an attacker can add such lines, so the v0.7 auditor must count them separately.
- Domain servers set allow_reuse_address False (Windows SO_REUSEADDR would allow port shadowing).
- provision.py waits for a READY line from each child instead of sleeping; tests bind port 0.
- ci.yml compileall dropped demo.py (file does not exist before v0.6); add it back then.

## Blockers / open questions
- Local `py -3.12` launcher is broken (python is 3.14.2); suite not yet run on 3.12.
- Hash chain cannot detect removal of the last entries; v0.7 auditor must state that limit.
- Replay protection after restart depends on an intact ledger.

- Registry refuses stale declarations (raises DeclarationStale) instead of returning False from supports(); a False would look like "action not offered".
- Failed refresh keeps the last good declaration; TTL ages out a permanently dead domain.
- Staleness is strictly greater than TTL (age equal to TTL is fresh). Negative age (clock moved back) is treated as fresh; known gap.

- Deleting a consumed approval marker in state/approvals re-opens replay. Markers are plain files, not hash-chained; v0.7 auditor must report this.
- Approval expiry uses the same clock rule as the registry: a clock moving backwards keeps an approval valid longer.

## Next step
Review feature/v0-7-evidence-cost and merge to main after approval (plain-English summary first). Then start v0.8 Perimeters and hardening (M8, gate G6): credential scan with a planted-credential control, import scan, allowed-writes check. Local py -3.12 still needs reinstalling; CI is the 3.12 check.

## Decisions (v0.7)
- Coordination multiple = exchanges / (runs x 1), the 1 being the monolith's single authorization per run (ADR-0006). Stated assumption for the faculty to dispute.
- The auditor counts actions per (jti, action), last line wins, because a handler fault writes action_executed then action_failed.
- A broken domain chain is reported and its lines are not counted; reconstruct exits 1.
