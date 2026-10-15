---
description: Implement a new feature end-to-end following the project workflow
argument-hint: <feature description or roadmap item, e.g. v0.2 domain agents>
---

Implement this feature: $ARGUMENTS

Follow these steps in order. Rules from CLAUDE.md apply throughout.

1. Restate the acceptance criteria (inputs/outputs, edge cases, what "done" looks like). If the request is vague, ask for the missing specifics before writing code.
2. Check `memory-bank/architecture.md`, `memory-bank/systemPatterns.md` and `ROADMAP.md` to confirm the feature follows existing conventions and matches planned scope.
3. Create a branch `feature/short-name`. Never work on `main`.
4. Implement with minimal, targeted changes. Standard library only.
5. Write or update tests (adversarial: happy path, edge cases, failure paths) and run the full suite: `python -m unittest discover -s tests -v`.
6. Run the syntax check: `python -m compileall -q domains coordinator ledger provision.py demo.py`.
7. Review the diff as a strict reviewer: secrets, silent failures, complexity, duplication, consistency, dead code, debug prints.
8. Commit with a Conventional Commits message (stage files explicitly). Do not push.
9. Update `memory-bank/progress.md` and `memory-bank/activeContext.md`, and move the feature out of "Now"/"Next" in `ROADMAP.md`.
10. Summarize the change in plain English and say it is ready for review. Do not push or merge without approval.
