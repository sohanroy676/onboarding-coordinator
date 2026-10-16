# ADR-0011: An opt-in model planner (scope change)

## Status
Accepted (v3.0.0; implementation starts on feat/model-planner after the faculty review)

## Date
2026-10-16

## Context
The brief, CLAUDE.md and ROADMAP say "no language model anywhere", and the system today
is deterministic code in separate processes. The faculty may require a model in an
"Agentic AI" project. The project owner wants one, but switchable at will: the
deterministic path must stay available, and the six gates and the exact expected results
(partial 6/1, multiple 3.0 from 15/5, and so on) must not depend on a model. The model
provider is Grok (xAI). It has daily usage limits, so a limit may be hit mid-demo.

Constraints that stay: standard library only (no SDK, `urllib.request` for HTTP), no
secret in any tracked file, no domain credential in the coordinator, refusals decided by
the domains, no retries, no rollback, no parallel dispatch.

## Decision
Add a planner that is chosen per run and defaults to the current one:

- `python onboard.py --subject <id> --planner deterministic|model`, with the free text in
  `--request-text "..."`. `--subject` stays required; the text produces actions only
  (taking the subject from the text is a later option). The web UI gets the same selector
  after the CLI works.
- The model turns the text into a list of (domain, action) requests across HR, IT and
  Facilities. Its output is untrusted input. It is parsed strictly (JSON, a size limit,
  known fields only) and then goes through the existing planner: the registry refuses
  unknown or unsupported actions, `will_not` actions stay in the plan with a warning, the
  plan is hashed once, a human approves, tokens are scoped to the approved plan, and each
  domain decides its own refusals. The model never gains authority.
- No silent fallback. A rate limit, network error, missing key or malformed output ends
  the run before approval with a clear message, with nothing minted or sent. The user
  switches to the deterministic planner by choice.
- The API key is `XAI_API_KEY` in a git-ignored `.env` in the project root. A few-line
  standard-library parser reads it in the app layer only (`app/`, `onboard.py`), never in
  `coordinator/` or `domains/`, and passes it to the model client as an argument. Domain
  processes never receive it (the explicit child environment allowlist is unchanged). It
  is never printed, logged or written to a trace or an error message. A tracked
  `.env.example` holds a placeholder. Deterministic mode never reads the file.
- The G6 credential scan exempts the `.env` path by exact path only, with a planted
  control proving that any other file holding a key-shaped value still fails.
- A seventh gate, G7 "the model cannot widen authority", runs a fake model client (no
  network) that returns hostile output: an action outside the registry,
  `grant_admin_access`, malformed JSON, an oversized plan, extra fields. Each case must be
  refused at planning, or stay in the plan with a warning and be refused at the domain.
- The provider sits behind a small client interface, so Grok can be replaced. Tests use
  an injected fake client and never touch the network.
- Evidence: real Grok transcripts are saved as traces, labelled as single runs that are
  not reproducible byte for byte, with the key absent.

- A failed model call ends the run with exit code 5, before any approval prompt. The
  console prints which planner produced the plan.

## xAI API facts (read from docs.x.ai on 2026-10-16, not yet exercised)
- Base URL `https://api.x.ai/v1`, header `Authorization: Bearer <key>`. The project uses
  `POST /v1/chat/completions` (the docs list `/v1/completions`, `/v1/complete` as legacy and
  `/v1/messages` as deprecated; chat/completions carries no such notice). `/v1/responses`
  also exists and is not used.
- Structured output: `response_format` = `{"type": "json_schema", "json_schema": {"name":
  ..., "schema": ..., "strict": true}}`. The docs show it only for `grok-4.7`. The default
  model is therefore `grok-4.7`, overridable with `--model`. Whether cheaper models
  (`grok-4.3`, `grok-build-0.1`) accept the schema is unverified; the first real run decides.
- Schema limits that matter here: `maxItems` up to 256 and `maxLength` up to 2048 are
  enforced; the plan schema stays far below them.
- A 429 is reported as "Rate limit exceeded" (`rate_limit_error`). The client does not retry.
- Not found in the docs, to be confirmed by the first real call: the response field
  carrying the text (assumed OpenAI-compatible `choices[0].message.content`), the
  rate-limit numbers, and the exact error body. The parser treats the reply as hostile
  whether or not the schema was enforced, so schema support is a convenience only.
- Sources: docs.x.ai/docs/guides/structured-outputs, /docs/models, /docs/api-reference and
  /developers/rest-api-reference/inference/legacy.

## Alternatives considered
- **A model inside each domain agent.** More agentic, but the model would sit next to the
  authority that enforces refusals. Deferred to a later ADR, for one domain, behind the
  token and `will_not` checks. The interface here does not block it.
- **A model that replaces the deterministic planner.** Simpler, but it puts the gates,
  `demo.py` and the faculty demo at the mercy of a daily limit and the network. Rejected.
- **Automatic fallback to the deterministic planner when the model fails.** It would hide
  which planner produced the plan. Rejected: the failure is reported and the user chooses.
- **A vendor SDK.** Breaks the standard-library rule. Rejected.
- **Typing the key at a hidden prompt (`getpass`) instead of a `.env` file.** Keeps the
  rule of no `.env`, but the owner prefers `.env`. Rejected by the owner.
- **Keeping the `.env` outside the project folder.** The scan would never see it, but it is
  less convenient. Rejected in favour of an exact-path exemption.

## Consequences
- The brief's "no language model" line, CLAUDE.md's "no `.env`" line and the tech-stack
  and ROADMAP lines are reversed for v3.0.0 only, when this ADR is accepted. They are
  updated together with it: `memory-bank/projectBrief.md`, `memory-bank/tech-stack.md`,
  `CLAUDE.md`, `AGENTS.md` and `ROADMAP.md`.
- The faculty claim changes from "no model anywhere" to "an optional model proposes the
  actions, and the same deterministic checks and human approval decide what runs".
- A new exit code, 5, means "the model planner failed"; code 2 still covers a plan the
  existing planner refuses.
- Employee data in the request text leaves the machine for xAI. The prototype uses
  synthetic data only, and the docs say so.
- Model runs cost quota and are not reproducible. Gate results and the exact expected
  results come from the deterministic path and the fake client, never from a live model.
- The perimeter scans gain one exemption (the `.env` path) and one rule (only the app
  layer reads it); a new import and environment scan rule enforces this.
- Stated limit: a model can propose a plan that is valid but wrong for the new hire (for
  example a missing action). The approval step is where a human catches that.
