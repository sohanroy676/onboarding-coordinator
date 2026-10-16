# CLAUDE.md

Guidance for Claude Code in this repository. It is generated from the Cline setup
(`AGENTS.md`, `.clinerules/`, `memory-bank/`), which stays the source of truth.
The files imported below with `@` load automatically, so keep editing them rather
than copying their content here.

## Project

@AGENTS.md

Academic prototype (problem statement PS3, Agentic AI course) for a faculty review.
Until v3.0.0 there is no language model in the system. v3.0.0 (ADR-0011, accepted) adds an
opt-in model planner (`--planner model`) that only proposes actions; deterministic mode, the
gates' expected results and demo.py never use a model.

@memory-bank/projectBrief.md

## Architecture and stack

@memory-bank/architecture.md

@memory-bank/tech-stack.md

Key invariants (breaking any of these breaks a gate):
- `domains/` and `coordinator/` never import from each other. Only domains and
  `ledger/reconstruct.py` use `ledger/`.
- Token verification lives only in `domains/domain_agent.py`; minting only in
  `coordinator/tokens.py`.
- The coordinator writes only approval marker files. Each domain is the only writer
  of its own ledger and the only authority for its refusals.
- Actions on a domain's `will_not` list stay in the plan with a warning. The
  coordinator never drops, filters or skips them.
- No retries, no rollback, no parallel dispatch. Order is HR, then IT, then Facilities.
- The three source folders hold exactly 11 files and no `__init__.py` (namespace
  packages). Run everything from the project root with `python -m`.
- Use `pathlib` for every path. Source and console output are ASCII only.

## Commands (run from the project root)

- Tests: `python -m unittest discover -s tests -v`
- One gate: `python -m unittest discover -s tests -p "test_g2_*.py" -v`
- Syntax check (the only "lint"): `python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app`
- Start, health-check and stop domains: `python provision.py`
- All scenarios with traces: `python demo.py`
- Onboard one new hire (plan, console approval, run, rebuild): `python onboard.py --subject <id>`
- Rebuild a run: `python -m ledger.reconstruct <run_id>`
- If `python` is not on PATH, use `py -3.12`.

## Current state

@memory-bank/activeContext.md

@memory-bank/progress.md

See `ROADMAP.md` for the version plan (v0.0 to v1.1) and what is explicitly not planned.
At the start of a session, the memory bank above is already loaded; read `ROADMAP.md`
and `memory-bank/systemPatterns.md` when planning a feature.

## Rules

### Security (non-negotiable)
- No secret, key or token in any file. The two coordinator secrets (`OC_EXCHANGE_SECRET`,
  `OC_APPROVAL_SECRET`) are not environment variables: `provision.py` creates them in
  memory in its own process, and no child process or code reads them from the
  environment. Only each domain's derived key (`OC_DOMAIN_KEY`) is passed as an env var.
  Nobody sets any of these by hand. This project
  does not use a `.env` file for them. The one exception (v3.0.0, ADR-0011): a git-ignored
  `.env` may hold `GROQ_API_KEY` for the model planner, read by `app/` and `onboard.py` only,
  never by `coordinator/`, `domains/`, `provision.py` or `demo.py`, never in a child env,
  never printed or traced. Ignore the other generic ".env" advice in `.clinerules/01-security.md`.
- The coordinator never holds a domain credential. Never log secrets or tokens.
- Before every commit, scan the diff for anything that looks like a secret.
- Validate external input on any path that touches a shell command or file path.

### Dependencies
- Standard library only, at runtime and in tests. Never add a third-party package,
  `requirements.txt`, pytest, ruff, black or any external tool.

### Testing
- unittest only. Tests live in `tests/` (no `__init__.py`): `test_unit_*.py`, the six
  gate files `test_g1_*` to `test_g6_*`, fixtures in `tests/helpers.py`.
- Tests use an injected clock, never sleep, and use ports different from the demo
  ports (8101 HR, 8102 IT, 8103 Facilities).
- Write tests that try to break the feature: happy path, edge cases, failure paths.
- Always run the full suite. Never comment out, delete or weaken a failing test; fix
  the root cause.

### Evidence integrity
- Never fake, edit or stage traces or results. Everything in `traces/` and every trace in
  the documents is pasted from a real run.
- Expected gate results (stale declaration refused, `domain_mismatch`,
  `malformed_token`, `approval_already_consumed`, `plan_changed_since_approval`, partial
  run with executed 6 / refused 1, coordination_multiple 3.0 from a real counter, etc.)
  must come from the code, never be hardcoded to match.

### Code style
- PEP 8 by hand, 4-space indents. Clear, boring code over clever one-liners.
- Minimal, targeted edits. Do not refactor unrelated code while fixing something.
- Before committing, review the diff as a strict reviewer: security, error handling
  (no silent failures), complexity, duplication, consistency with existing patterns,
  dead code and leftover debug prints.

### Git
- Work on a branch: `feature/short-name` or `fix/short-name`. Never commit directly to
  `main` (the repository has no commits yet; ask before making the initial commit).
- Commit only after the full suite and the syntax check pass. Stage files explicitly,
  never a blind `git add .`.
- Conventional Commits: `type(scope): summary` (under 50 chars, imperative; types feat,
  fix, refactor, chore, docs, test, perf, style) plus a 1-3 line body explaining why.
- Never push, merge, force-push, rebase, `reset --hard`, or delete branches or tags
  without explicit approval. Before a merge, give a plain-English summary of the change.
- `CHANGELOG.md` is generated from commit history, not hand-written. Generator tools
  like git-cliff are third-party, so ask before running or installing one.

### Architecture decisions
- Record significant, hard-to-reverse decisions as ADRs in `docs/adr/`, copied from
  `docs/adr/adr-template.md` with the next number. Skip small, reversible choices.

## Workflows

The Cline workflows in `.clinerules/workflows/` apply here too. Read the matching file and
follow its steps when the task fits:
- New feature: `.clinerules/workflows/new-feature.md` (restate acceptance criteria first,
  check architecture and ROADMAP, branch, implement, test, review, commit, update the
  memory bank and ROADMAP, summarize).
- Bug fix: `.clinerules/workflows/debug.md` (reproduce first, state the root cause in one
  or two sentences, minimal fix, regression test, `fix:` commit, update `progress.md`).
- Commit on demand: `.clinerules/workflows/commit.md`.

Where those files say "run lint/format", run the `compileall` syntax check instead.

## Memory bank upkeep

After finishing a feature or fix (or at the end of a session), update
`memory-bank/progress.md` (append, newest at top) and `memory-bank/activeContext.md`
(current focus, decisions, blockers, single next step). Add patterns to
`memory-bank/systemPatterns.md` as they emerge. Then suggest starting a fresh session for
the next feature.

## Known template mismatches

These files are still generic templates and do not match this project yet. Do not
follow them as written; flag them when they become relevant:
- `PRE-DEPLOY-CHECKLIST.md` assumes a public deployment (`.env`, Sentry, production
  config). This prototype only runs locally.
