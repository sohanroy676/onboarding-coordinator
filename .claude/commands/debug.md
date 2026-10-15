---
description: Fix a bug with reproduction, root cause, regression test and fix commit
argument-hint: <bug description or failing test>
---

Fix this bug: $ARGUMENTS

Follow these steps in order. Rules from CLAUDE.md apply throughout.

1. Reproduce the failure first (run the app or tests) and confirm you can see it before changing anything.
2. Isolate the root cause by tracing logs, stack traces and code. Do not patch symptoms.
3. State the root cause in one or two sentences before writing the fix.
4. Implement the minimal fix. Do not refactor unrelated code.
5. Add a regression test that would have caught this bug, plus any other needed coverage. Never weaken or delete an existing test.
6. Run the full suite (`python -m unittest discover -s tests -v`) and the syntax check (`python -m compileall -q domains coordinator ledger provision.py demo.py`).
7. Review the diff as a strict reviewer.
8. Commit with a `fix(scope):` message that references the root cause in the body. Work on a `fix/short-name` branch, not `main`. Do not push.
9. Append what was fixed to `memory-bank/progress.md`.
