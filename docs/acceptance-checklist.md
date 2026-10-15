# Acceptance checklist

Every row names the test that proves the result and the saved trace that shows
it. Results come from the code and from real runs, never from the expected value.
Trace files are in `traces/` and were captured with shell redirection, unedited.

Run on Python 3.14.2 locally. The Python 3.12 check is CI on `main`.

## Gates

| Gate | Command | Result | Trace |
| --- | --- | --- | --- |
| G1 domains and registry | `python -m unittest discover -s tests -p "test_g1_*.py" -v` | OK | `traces/v1-2-g1.txt` |
| G2 delegation | `python -m unittest discover -s tests -p "test_g2_*.py" -v` | OK | `traces/v1-2-g2.txt` |
| G3 one approval | `python -m unittest discover -s tests -p "test_g3_*.py" -v` | OK | `traces/v1-2-g3.txt` |
| G4 honest refusal | `python -m unittest discover -s tests -p "test_g4_*.py" -v` | OK | `traces/v1-2-g4.txt` |
| G5 evidence and cost | `python -m unittest discover -s tests -p "test_g5_*.py" -v` | OK | `traces/v1-2-g5.txt` |
| G6 perimeters | `python -m unittest discover -s tests -p "test_g6_*.py" -v` | OK | `traces/v1-2-g6.txt` |
| Full suite | `python -m unittest discover -s tests -v` | Ran 323 tests, OK | `traces/v1-2-tests.txt` |
| Syntax check | `python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app` | Clean | (no output) |

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
| No domain key stored or read in `coordinator/` (the coordinator can derive one; see ADR-0008) | `test_g6_perimeters.StaticCredentialScan.test_coordinator_has_no_domain_key_or_env_read` | `v0-9-g6.txt` |
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
archive is `dist/onboarding_coordinator.zip`, built with `git archive`. Its
SHA-256 is recorded in `memory-bank/progress.md`, not here, because the archive
contains this file.

Python 3.12 is not verified locally. The 3.12 check runs in CI on pushes to `main`.

## Deliverables D1 to D12

The project brief requires deliverables D1 to D12, each traced to a real run. The list
below is the project's deliverable list, supplied by the author. Status words mean:
**met** (the evidence shows it), **met with note** (met, with a stated difference),
**partly met** and **not met** (a gap, stated plainly). Every trace is from a real run.

| D | Deliverable | Status | Evidence | Note |
| --- | --- | --- | --- | --- |
| D1 | Source archive | met with note | `dist/onboarding_coordinator.zip`, built with `git archive` from tag `v1.0.0` | Holds the 11 source files (domains 4, coordinator 5, ledger 2), plus `provision.py`, `demo.py`, `tests/`, `docs/`, `traces/`. Name follows the deliverable list. |
| D2 | Implementation document | met with note | `docs/implementation.md`; traces `v0-6-*` to `v0-9-*`, `v1-0-*`, and re-runs at the milestone tags: `traces/rerun-v0-2-tests.txt` (80 OK), `rerun-v0-3-tests.txt` (116 OK), `rerun-v0-3-g1.txt`, `rerun-v0-4-tests.txt` (126 OK), `rerun-v0-4-g2.txt`, `rerun-v0-5-tests.txt` (168 OK), `rerun-v0-5-g3.txt` | The v0.2 to v0.5 traces were not saved at the time the milestones were built. They are re-runs of the tagged code in fresh clones, and say so in their names. |
| D3 | Domain agents (M1) | met | `test_g1_domains_registry` (`traces/v1-0-g1.txt`); will_not refusal in `test_g4_refusal` (`traces/v1-0-g4.txt`) | Three processes, each with its declaration and its will_not list. |
| D4 | Capability registry (M2) | met with note | `test_g1_domains_registry.test_exact_ttl_age_is_fresh_and_one_more_second_is_stale`, `test_g1_domains_registry.test_forced_stale_declaration_is_refused_then_refreshed`, `test_g1_domains_registry.test_unknown_domain_raises_keyerror` (`traces/v1-0-g1.txt`) | The expected figures (0.1 s old, 0.01 s max) are not used. Tests use a 60 s TTL and an injected clock. |
| D5 | Token exchange (M3) | met | `test_g2_delegation.test_token_for_one_domain_is_refused_by_each_other_domain` (domain_mismatch), `test_g2_delegation.test_missing_or_broken_tokens_are_malformed`, `test_g2_delegation.test_exchange_secret_cannot_sign_a_token`, `test_g4_refusal` (correct token executes) (`traces/v1-0-g2.txt`) | |
| D6 | Consolidated planning (M4) | met | `test_unit_planner` (one plan, one hash); `test_g3_approval` (`traces/v1-0-g3.txt`) | |
| D7 | Plan approval (M5) | met | `test_g3_approval.test_replay_after_restart_is_refused` (approval_already_consumed), `test_g3_approval.test_changed_sub_plan_in_one_domain_is_refused` (plan_changed_since_approval) (`traces/v1-0-g3.txt`); demo scenario 3 (`traces/v1-0-demo.txt`) | |
| D8 | Execution and refusal (M6) | met | `test_g4_refusal.test_grant_admin_access_run_is_partial_six_executed_one_refused` (`traces/v1-0-g4.txt`); demo scenario 2 names `it grant_admin_access refused will_not` (`traces/v1-0-demo.txt`) | |
| D9 | Ledger and cost (M7) | met | `test_g5_evidence_cost.test_clean_run_rebuilds_hr_2_it_2_facilities_2`, `test_g5_evidence_cost.test_five_clean_runs_give_three_exchanges_each_from_the_real_counter` (`traces/v1-0-g5.txt`); `traces/v1-0-reconstruct.txt`; demo scenario 4 `coordination multiple: 3.0 (15 exchanges / 5 runs)` | Five runs give 15 exchanges against 5 monolith authorizations (one per run, ADR-0006). |
| D10 | Two-perimeters test (M8) | met with note | `test_g6_perimeters.StaticCredentialScan.test_coordinator_has_no_domain_key_or_env_read`, `test_g6_perimeters.CoordinatorSecretsRefused.test_both_secrets_are_refused_by_every_domain` (`traces/v1-0-g6.txt`) | The coordinator-env scan reads `coordinator/` only. The credential scan covers every project text file. Both keep their patterns in `tests/`. The coordinator can still derive domain keys (ADR-0007). |
| D11 | Acceptance checklist | met | This file: the six gate commands and their observed results (`traces/v1-0-g1.txt` to `traces/v1-0-g6.txt`). | |
| D12 | Troubleshooting guide | met with note | `docs/troubleshooting.md`: entries for `OC_DOMAIN_KEY is missing or not 64 hex digits`, for setting the two secrets (no effect), for `cannot start <domain>`, and for imports from the project root. Real run: `traces/v1-0-d12-missing-key.txt` (console exit 2). | Requirement changed (ADR-0008). The original list named `OC_EXCHANGE_SECRET` and `OC_APPROVAL_SECRET` as variables to report missing. The design does not use them: `provision.py` creates both in memory, and no code reads them from the environment. The guide says so, and no code check is added. The only missing-variable message is for `OC_DOMAIN_KEY`, which is shown above. Docs that named them as variables (`memory-bank/tech-stack.md`, `docs/implementation.md`) are corrected. |

## Stated limits (not proven by any gate)

- **The coordinator can derive every domain key.** G6 shows the coordinator never
  stores, reads or names a domain key. It does not show the coordinator cannot
  compute one (`coordinator/tokens.py:88`, ADR-0007).
- **A clock moving backwards.** Fixed for a declaration or approval received
  after the current time (refused). A rewind to a time still after the approval's
  issue time extends its life; this is not detected (ADR-0004 amendment).
- **Deleting a consumed approval marker.** The coordinator's marker is not the
  only record: each domain refuses an `approval_id` it has already executed
  (`approval_replayed`, `test_g3_approval.DomainReplayTests`). Deleting the
  marker alone no longer re-opens replay. Deleting every marker and every domain
  ledger still does, because a local administrator can do that.
- **The hash chain cannot detect truncation from the end.** The auditor prints
  this limit in every rebuild.
- **The write scan does not see non-literal `Path.open` modes.**
- **The monolith denominator (1 per run) is an assumption** for the faculty to
  dispute (ADR-0006).
- **The exchange counter resets only if its file is removed.** With `count_path`,
  each exchange is one line in a file (fix/exchange-counter-persist). A restarted
  coordinator resumes the count. A local user can still edit or delete that file.

## Gap fixes after v1.0

Each gap was fixed on its own `fix/` branch, then merged on `integrate/ps3-gaps`
for the traces below. Every trace is a real run of the merged tree (`traces/v1-1-*.txt`).
The suite has 279 tests; the gates are G1 15, G2 11, G3 10, G4 7, G5 7, G6 11.

| Gap | Fix | Test | Evidence |
|---|---|---|---|
| Write scan missed `Path.open` with a non-literal mode | Non-literal method-open mode counts as a write; urllib `opener` is exempt by name | `test_unit_perimeter_scan.WriteSiteRules.test_path_open_with_non_literal_mode_is_reported` | `traces/v1-1-g6.txt` |
| Provisioner gave no detail while the child was alive | Child killed after a short wait; its stderr is in the error | `test_unit_provision.ReadyFailureTests.test_silent_child_is_killed_and_its_stderr_is_reported` | `traces/v1-1-tests.txt` |
| Clock moving backwards treated as fresh | Declaration received after now is refused; approval used before `issued_at` is refused | `test_unit_registry.StalenessTests.test_clock_moved_backwards_is_refused_not_fresh`, `test_unit_approval.ClockTests.test_clock_set_back_before_issue_is_refused_and_writes_no_marker` | `traces/v1-1-tests.txt` |
| Exchange counter reset on restart | Counter file, one line per exchange, written before the token is returned | `test_unit_tokens.PersistentCounterTests.test_count_survives_a_new_minter_on_the_same_file`, `test_g6_perimeters.RuntimeWrites.test_one_run_changes_only_its_marker_ledgers_and_exchange_count` | `traces/v1-1-demo.txt` (scenario 4: 15 / 5, multiple 3.0) |
| Deleting a consumed marker re-opened replay | `approval_id` is a token claim; each domain refuses a reused approval (`approval_replayed`) | `test_g3_approval.DomainReplayTests.test_deleted_marker_does_not_re_open_replay_at_the_domains`, `test_unit_domain_http.ApprovalReuseTests.test_second_run_with_the_same_approval_is_refused` | `traces/v1-1-g3.txt`, `traces/v1-1-demo.txt` |

Stated limits that remain after these fixes: a clock rewound to a time still after
`issued_at` extends an approval (ADR-0004); a local administrator who deletes every
approval marker and every domain ledger can still replay (ADR-0004, ADR-0003); the
counter file and the ledgers are plain local files, so they are not tamper-evident
(ADR-0006); the hash chain cannot detect truncation from the end (ADR-0006).

## v1.2 Onboarding core and CLI

Run from the project root with `python onboard.py --subject <id>`. The flow is
`app/onboarding.py`; the approval is given at the console (ADR-0009). Each row
names the test that proves it and the saved trace. Traces were captured with
shell redirection and the scripted answer is piped in; nothing was edited.

| Requirement | Test | Trace |
| --- | --- | --- |
| Subject is one ASCII token, one @, at most 254 characters | `test_unit_app_onboarding.SubjectRules.test_254_characters_is_the_longest_accepted`, `test_unit_app_onboarding.SubjectRules.test_255_characters_is_refused`, `test_unit_app_onboarding.SubjectRules.test_a_space_is_refused`, `test_unit_app_onboarding.SubjectRules.test_non_ascii_is_refused`, `test_unit_app_onboarding.SubjectRules.test_two_at_signs_are_refused` | `traces/v1-2-tests.txt` |
| Request is domain:action, domain in hr, it, facilities; action [a-z_]{1,40}; params empty | `test_unit_app_onboarding.RequestRules.test_forty_one_characters_is_refused_and_forty_is_accepted`, `test_unit_app_onboarding.RequestRules.test_digits_and_dashes_in_action_are_refused`, `test_unit_app_onboarding.RequestRules.test_an_unknown_domain_is_refused`, `test_unit_app_onboarding.RequestRules.test_a_valid_request_has_empty_params` | `traces/v1-2-tests.txt` |
| y in any case approves; n, empty, other words, end of input and Ctrl-C do not | `test_unit_app_onboarding.ApprovalPrompt.test_y_in_any_case_approves_and_runs`, `test_unit_app_onboarding.ApprovalPrompt.test_anything_else_is_not_approved_and_sends_nothing`, `test_unit_app_onboarding.ApprovalPrompt.test_end_of_input_is_not_approved`, `test_unit_app_onboarding.ApprovalPrompt.test_ctrl_c_at_the_prompt_is_not_approved` | `traces/v1-2-onboard-declined.txt` |
| Declined run: no POST, no approval marker, no ledger line (real domains) | `test_unit_app_live.DeclinedRun.test_declined_run_writes_no_ledger_line_and_no_marker` | `traces/v1-2-onboard-declined.txt` |
| Approved default run: six executed, two ledger lines per domain, rebuild chains ok | `test_unit_app_live.ApprovedRun.test_approved_default_run_writes_six_ledger_lines`, `test_unit_app_live.ApprovedRun.test_the_approved_run_rebuilds_from_the_ledgers` | `traces/v1-2-onboard-approved.txt`, `traces/v1-2-reconstruct.txt` |
| will_not request stays in the plan with a warning and is refused in IT; status partial, exit 1 | `test_unit_app_live.PartialRun.test_will_not_request_gives_partial_with_one_refusal_in_it`, `test_unit_app_onboarding.PlanContent.test_will_not_warning_is_printed_and_the_step_stays_in_the_plan` | `traces/v1-2-onboard-partial.txt` |
| Unknown domain, unsupported action and stale declaration exit 2 before any prompt | `test_unit_app_onboarding.ExitCodes.test_unknown_domain_or_unsupported_action_exits_2_before_any_prompt`, `test_unit_app_onboarding.ExitCodes.test_stale_declaration_exits_2_before_any_prompt`, `test_unit_app_onboarding.ExitCodes.test_bad_subject_exits_2_before_any_start_or_prompt` | `traces/v1-2-tests.txt` |
| Domains that do not start, or do not answer their declaration, exit 4 before any prompt | `test_unit_app_onboarding.ExitCodes.test_domains_that_do_not_start_exit_4_before_any_prompt`, `test_unit_app_onboarding.ExitCodes.test_a_domain_that_does_not_answer_its_declaration_exits_4` | `traces/v1-2-tests.txt` |
| Interrupt after approval exits 1 and prints the run id to rebuild from | `test_unit_app_onboarding.ExitCodes.test_interrupt_after_approval_exits_1_and_prints_the_run_id`, `test_unit_app_onboarding.PlanContent.test_the_run_id_is_printed_before_any_domain_is_called` | `traces/v1-2-tests.txt` |
| Default requests are the six supported actions; given requests replace them | `test_unit_app_onboarding.PlanContent.test_default_requests_are_the_six_supported_actions`, `test_unit_app_onboarding.PlanContent.test_given_requests_replace_the_defaults` | `traces/v1-2-tests.txt` |
| app/ imports only coordinator, ledger.reconstruct and the operator modules | `test_g6_perimeters.StaticImportScan.test_project_imports_respect_the_boundaries`, `test_unit_perimeter_scan.AppImportRules.test_planted_domains_import_from_app_is_flagged`, `test_unit_perimeter_scan.AppImportRules.test_planted_ledger_internals_import_from_app_is_flagged` | `traces/v1-2-g6.txt` |
| The six gates are unchanged (G1 15, G2 11, G3 10, G4 7, G5 7, G6 11) | `test_g1_domains_registry.py`, `test_g2_delegation.py`, `test_g3_approval.py`, `test_g4_refusal.py`, `test_g5_evidence_cost.py`, `test_g6_perimeters.py` | `traces/v1-2-g1.txt` to `traces/v1-2-g6.txt` |

Stated limits for v1.2 (not proven by a gate): the console answer is the only
human check, and the operator and coordinator share one trust domain (ADR-0009);
the piped answer is not echoed in the saved trace; `--request` replaces the six
defaults, so a subset run is possible but a default-plus-extra run needs every
request listed.
