# ADR-0010: A local web UI for the onboarding flow (scope change)

## Status
Accepted (in v2.0.0, branch feat/web-ui; the code and tests landed there)

## Date
2026-10-15

## Context
The brief and ROADMAP said "no web interface", and the faculty case relied on that
scope. The project owner has decided that an end-to-end project should have a UI,
so that onboarding does not need manual commands. The scope change must stay small:
no third-party packages (the brief forbids them), no database, no configuration
files, and no browser dependency in the test suite.

## Decision
Add a local UI served by the standard library (`http.server` with
`ThreadingHTTPServer`) on 127.0.0.1, default port 8110. The UI is a thin layer
over `app/onboarding.py`, the same flow the CLI uses (ADR-0009). Its front end is
vanilla HTML, CSS and JavaScript with no build step, no CDN assets, and ASCII-only
source. The UI server is the coordinator process, so the exchange and approval
secrets stay in the `Provisioner` in memory, as now. The browser never receives a
secret or key.

Security rules for the UI:
- bind 127.0.0.1 only, and reject any Host header other than `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding);
- a per-start CSRF token (`secrets.token_urlsafe`), embedded in the page and required on every POST, and an Origin check;
- JSON only, a 16 KB body limit, the same input validation as the CLI;
- no file paths from the browser; static files come from a fixed allowlist;
- approve is a separate action that sends the plan hash the user saw, and `run_plan` still refuses a changed plan.

Boundaries: `app/` may import `coordinator`, `ledger.reconstruct`, `provision` (the
operator's Provisioner) and `demo` (for `print_report`), but not `domains` or ledger
internals. A G6 import-scan rule enforces this. The v1.2 CLI (ADR-0009) needed the
last two imports; this is the amendment.

## Alternatives considered
- **A third-party web framework (Flask, FastAPI).** Simpler to write, but it breaks the standard-library rule. Rejected.
- **A desktop GUI (tkinter).** Standard library, but harder to test and to present, and it does not give a browser UI. Rejected.
- **A static report page that reads trace files.** It cannot start or approve a run, so it does not remove the manual commands. Rejected.
- **A browser test tool (Playwright) in the suite.** It needs an external install and a browser. Deferred: a one-off check can be added later with approval, and it would stay out of the project's dependencies.

## Consequences
- The brief's out-of-scope line is reversed for v2.0.0 only, and the docs say so. The
  faculty claim changes from "no web interface" to "a local, standard-library UI
  that calls the same flow as the CLI".
- UI evidence is saved HTTP transcripts from real runs, in the same trace format.
  Screenshots stay out of git.
- The server can run one approval at a time through the coordinator's existing
  marker logic (exclusive create), so concurrent approvals are still refused on replay.
- Dispatch stays sequential (no parallel dispatch, ADR-0005), so a slow domain
  makes the UI request wait, and this is stated in the UI.
