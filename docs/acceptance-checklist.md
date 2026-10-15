# Acceptance checklist

Every row names the test that proves the result and the saved trace that shows
it. Results come from the code and from real runs, never from the expected value.
Trace files are in `traces/` and were captured with shell redirection, unedited.

Run on Python 3.14.2 locally. The Python 3.12 check is CI on `main`.

## Gates

| Gate | Command | Result | Trace |
| --- | --- | --- | --- |
| G1 domains and registry | `python -m unittest discover -s tests -p "test_g1_*.py" -v` | OK | `traces/v0-9-g1.txt` |
| G2 delegation | `python -m unittest discover -s tests -p "test_g2_*.py" -v` | OK | `traces/v0-9-g2.txt` |
| G3 one approval | `python -m unittest discover -s tests -p "test_g3_*.py" -v` | OK | `traces/v0-9-g3.txt` |
| G4 honest refusal | `python -m unittest discover -s tests -p "test_g4_*.py" -v` | OK | `traces/v0-9-g4.txt` |
| G5 evidence and cost | `python -m unittest discover -s tests -p "test_g5_*.py" -v` | OK | `traces/v0-9-g5.txt` |
| G6 perimeters | `python -m unittest discover -s tests -p "test_g6_*.py" -v` | OK | `traces/v0-9-g6.txt` |
| Full suite | `python -m unittest discover -s tests -v` | Ran 256 tests, OK | `traces/v0-9-tests.txt` |
| Syntax check | `python -m compileall -q domains coordinator ledger provision.py demo.py` | Clean | (no output) |

## Expected results

Each expected result from the project brief, in the order the brief lists them.

| Expected result | Proven by test | Shown in trace |
| --- | --- | --- |
| Forced-stale declaration refused | `test_g1_domains_registry.test_forced_stale_declaration_is_refused_then_refreshed` | `v0-9-g1.txt` |
| Unknown domain raises `KeyError` | `test_g1_domains_registry.test_unknown_domain_raises_keyerror`, and `test_g3_approval.test_unknown_domain_raises_keyerror_at_planning` | `v0-9-g1.txt`, `v0-9-g3.txt` |
| Wrong-domain token gives `domain_mismatch` | `test_g2_delegation.test_token_for_one_domain_is_refused_by_each_other_domain` (all six wrong-domain pairs) | `v0-9-g2.txt` |
| Missing token gives `malformed_token` | `test_g2_delegation.test_missing_or_broken_tokens_are_malformed` | `v0-9-g2.txt` |
| Replay gives `approval_already_consumed` | `test_g4_refusal.test_replayed_approval_aborts_and_leaves_domain_ledgers_untouched`, and `test_g3_approval.test_replay_after_restart_is_refused` | `v0-9-g4.txt`, `v0-9-demo.txt` (scenario 3) |
| Changed sub-plan gives `plan_changed_since_approval` | `test_g4_refusal.test_changed_plan_aborts_before_any_token_is_minted`, and `test_g3_approval.test_changed_sub_plan_in_one_domain_is_refused` | `v0-9-g4.txt`, `v0-9-g3.txt` |
| `grant_admin_access` run gives status partial, executed 6, refused 1 | `test_g4_refusal.test_grant_admin_access_run_is_partial_six_executed_one_refused` | `v0-9-demo.txt` (scenario 2: `status: partial  executed 6  refused 1`) |
| One run ID rebuilds HR 2, IT 2, Facilities 2 | `test_g5_evidence_cost.test_clean_run_rebuilds_hr_2_it_2_facilities_2` | `v0-9-demo.txt` (scenario 1 rebuilt), `v0-9-reconstruct-partial.txt` |
| Five runs give coordination multiple 3.0 from a real counter | `test_g5_evidence_cost.test_five_clean_runs_give_three_exchanges_each_from_the_real_counter` | `v0-9-demo.txt` (scenario 4: `coordination multiple: 3.0`) |
| Zero domain credentials in `coordinator/` | `test_g6_perimeters.StaticCredentialScan.test_coordinator_has_no_domain_key_or_env_read` | `v0-9-g6.txt` |
| Both coordinator secrets rejected as tokens | `test_g6_perimeters.CoordinatorSecretsRefused.test_both_secrets_are_refused_by_every_domain`, and `test_g2_delegation.test_exchange_secret_cannot_sign_a_token`, `test_approval_secret_cannot_sign_a_token` | `v0-9-g6.txt`, `v0-9-g2.txt` |

## Fresh checkout (v1.0)

The v1.0 traces come from a clone of commit `c5c20dc` (the README commit), pinned
detached and run outside the working tree. The code folders (`domains/`,
`coordinator/`, `ledger/`, `tests/`, `provision.py`, `demo.py`) are unchanged in the
release commit that carries these traces, so the traces describe the release code.
Each file was copied byte-for-byte from the clone, and its SHA-256 matched the copy.

| Check | Result | Trace |
| --- | --- | --- |
| Syntax check | Exit 0, no output | (no output) |
| Full suite | Ran 256 tests, OK | `traces/v1-0-tests.txt` |
| G1 domains and registry | Ran 15 tests, OK | `traces/v1-0-g1.txt` |
| G2 delegation | Ran 11 tests, OK | `traces/v1-0-g2.txt` |
| G3 one approval | Ran 9 tests, OK | `traces/v1-0-g3.txt` |
| G4 honest refusal | Ran 7 tests, OK | `traces/v1-0-g4.txt` |
| G5 evidence and cost | Ran 7 tests, OK | `traces/v1-0-g5.txt` |
| G6 perimeters | Ran 11 tests, OK | `traces/v1-0-g6.txt` |
| Demo, all scenarios | Exit 0; partial 6/1, replay aborted, multiple 3.0 | `traces/v1-0-demo.txt` |
| Rebuild of scenario 1 run | Exit 0; hr 2, it 2, facilities 2, all chains ok | `traces/v1-0-reconstruct.txt` |

The release tag `v1.0.0` points at the commit that adds these traces. The release
archive is `dist/onboarding-coordinator-v1.0.0.zip`, built with `git archive`. Its
SHA-256 is recorded in `memory-bank/progress.md`, not here, because the archive
contains this file.

Python 3.12 is not verified locally. The 3.12 check runs in CI on pushes to `main`.

## Deliverables D1 to D12

The project brief requires deliverables D1 to D12 and says each trace must be
pasted from a real run. The brief does not list the twelve items, and the
repository holds no list of them. This checklist cannot map them until that list
is supplied. Real traces for each gate and the demo are in `traces/v0-9-*.txt`.

## Stated limits (not proven by any gate)

- **The coordinator can derive every domain key.** G6 shows the coordinator never
  stores, reads or names a domain key. It does not show the coordinator cannot
  compute one (`coordinator/tokens.py:88`, ADR-0007).
- **A clock moving backwards is treated as fresh.**
- **Deleting a consumed approval marker re-opens replay.**
- **The hash chain cannot detect truncation from the end.** The auditor prints
  this limit in every rebuild.
- **The write scan does not see non-literal `Path.open` modes.**
- **The monolith denominator (1 per run) is an assumption** for the faculty to
  dispute (ADR-0006).
- **The exchange counter is per process.**
