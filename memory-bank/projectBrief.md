# Project brief

## What and who
A federated, least-privilege employee onboarding coordinator (problem statement PS3) that completes HR, IT and Facilities onboarding without any single process holding all domain authority. It is an academic prototype for an Agentic AI course, built to be demonstrated and defended in a faculty review.

## Goal and success criteria (done for v1)
v1 is done only when all of the following are true, shown by real terminal runs:
- All seven milestones run end to end: domain agents, capability registry, token exchange, consolidated planning, plan approval, execution with refusal, cross-domain ledger and cost.
- All six acceptance gates pass with their exact commands (our own definitions, since the statement does not define them):
  G1 domains and registry, G2 delegation, G3 one approval, G4 honest refusal, G5 evidence and cost, G6 perimeters.
- Expected results appear exactly: forced-stale declaration refused; unknown domain raises KeyError; wrong-domain token gives domain_mismatch; missing token gives malformed_token; replay gives approval_already_consumed; changed sub-plan gives plan_changed_since_approval; the grant_admin_access run gives status partial, executed 6, refused 1; one run ID rebuilds hr 2, it 2, facilities 2; five runs give coordination_multiple 3.0 from a real counter; zero domain credentials in coordinator/; both coordinator secrets rejected as tokens.
- Deliverables D1 to D12 exist, with every trace pasted from a real run.

## Out of scope
- Production infrastructure, real HR, IT or Facilities systems, and live employee data.
- Third-party packages of any kind.
- Retries, rollback or compensation of partial runs.
- Parallel dispatch to domains.
- A web interface, a database or configuration files.
- Signed capability declarations (a stated limitation).
- A monolith baseline implementation (G5 compares against a hypothetical monolith count).
- Any language model in the system.