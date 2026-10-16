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
provider was first chosen as Grok (xAI) and is now Groq with a Qwen model (see the
Amendment below). Free tiers have usage limits, so a limit may be hit mid-demo.

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
- The API key is `GROQ_API_KEY` in a git-ignored `.env` in the project root. A few-line
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
- The provider sits behind a small client interface, so the provider can be replaced. Tests use
  an injected fake client and never touch the network.
- Evidence: real Groq transcripts are saved as traces, labelled as single runs that are
  not reproducible byte for byte, with the key absent.

- A failed model call ends the run with exit code 5, before any approval prompt. The
  console prints which planner produced the plan.

## Amendment 2026-10-16: the provider is Groq, not xAI
The first key supplied was a Groq key (`gsk_...`), and the xAI account had no credits
(HTTP 403) and then rejected the Groq key (HTTP 400). The owner chose to use Groq with a
Qwen model and to remove the xAI references. Nothing else in the decision changes: the
planner is opt-in, its output is untrusted, there is no fallback and no retry, and the key
stays in `.env`, read by `app/` only. The key name is now `GROQ_API_KEY`.

## Groq API facts (docs read 2026-10-16; the call was exercised the same day)
- Endpoint `POST https://api.groq.com/openai/v1/chat/completions`, header
  `Authorization: Bearer <key>`. The client also sends a fixed `User-Agent`, because the
  default Python one is the kind some edge services refuse.
- Default model `qwen/qwen3.8-27b` (a preview model on Groq, listed at 0.80 USD input and
  4.00 USD output per 1M tokens, 250K TPM and 1K RPM). It is one of the models documented
  to support `response_format` = `{"type": "json_schema", "json_schema": {"name": ...,
  "schema": ..., "strict": true}}`. The others listed are `openai/gpt-oss-20b`,
  `openai/gpt-oss-120b` and `meta-models/muse-spark-open`. `--model` overrides the default.
  Preview models can change or be withdrawn, so the default may need updating.
- Confirmed by the live runs: the reply text is in `choices[0].message.content`, and the
  strict schema was honoured (the traces show 2 to 4 valid requests each time). The parser
  still treats every reply as hostile, so schema support is a convenience only.
- Error bodies are JSON with an `error` string; the client shows it, cut to 200 characters
  with the key redacted.
- Sources: console.groq.com/docs/structured-outputs and console.groq.com/docs/models.
- The earlier xAI facts (endpoint, `grok-4.7`) are withdrawn and no code refers to them.

## Amendment (v3.1.0): the web UI selector
`POST /api/plans` accepts `planner` ("deterministic" by default, or "model") and
`request_text`. The same rules as the CLI apply: `requests` and `request_text` cannot be
combined, the text must be printable ASCII of at most 1000 characters, and the model
name is not taken from the browser (the default model is used). The key is read from
`.env` by `app/server.py` at plan time, never at start, and is not part of any response
or page. A failed model call (no key, network, rate limit, unusable reply) returns
HTTP 502 `model_failed` before any plan is stored: nothing is approved, minted or sent,
and there is no fallback. The response names the planner that produced the plan.
Evidence: `tests/test_unit_app_server.py` (fake client, no network) and one real run in
`traces/v3-1-ui-model-transcript.txt`.

## Amendment (v3.1.0): the model is told which actions a domain refuses
The first prompt listed only the supported actions. A request such as "give them admin
access" was then either dropped by the model (a refusal nobody sees, against the rule that
the domain is the only authority for its refusals) or turned into an invented name that
ended as `plan_refused`. The prompt now also lists each domain's `will_not` actions in a
separate block, labelled "the domain will refuse these; include one only if the text asks
for it". The strict schema sent with each call limits `action` to the declared names
(supported and refused) with a per-call enum. Neither is a check: the parser and the
registry still treat the reply as untrusted, a name outside the enum or a wrong
domain/action pair is still refused at planning, and a refused action stays in the plan
with a warning and is refused by the domain. The names sent are the ones in each domain's
public `/capabilities` declaration. Evidence: `tests/test_unit_model_planner.py`,
`tests/test_unit_app_model.py`, and the real runs `traces/v3-1-onboard-model-admin.txt`
and `traces/v3-1-ui-model-transcript.txt` (steps 11 and 12: the model proposed
`it:grant_admin_access`, the plan carried a warning, the IT agent refused it, status
`partial`). Live output varies, so these are single runs.

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
- Employee data in the request text leaves the machine for Groq. The prototype uses
  synthetic data only, and the docs say so.
- Model runs cost quota and are not reproducible. Gate results and the exact expected
  results come from the deterministic path and the fake client, never from a live model.
- The perimeter scans gain one exemption (the `.env` path) and one rule (only the app
  layer reads it); a new import and environment scan rule enforces this.
- Stated limit: a model can propose a plan that is valid but wrong for the new hire (for
  example a missing action). The approval step is where a human catches that.
