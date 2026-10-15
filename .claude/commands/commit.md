---
description: Review, verify and commit current changes (no push)
argument-hint: [optional scope or note for the message]
---

Commit the current changes. Note: $ARGUMENTS

1. Run `git status` and `git diff` to review all changes.
2. Run the full suite (`python -m unittest discover -s tests -v`) and the syntax check (`python -m compileall -q domains coordinator ledger provision.py demo.py`). Do not commit failing tests.
3. Review the diff as a strict reviewer, including a scan for anything that looks like a secret.
4. Make sure you are not on `main`; if you are, create a `feature/` or `fix/` branch first (ask if unsure).
5. Stage the relevant files explicitly (never a blind `git add .`).
6. Write a Conventional Commits message: `type(scope): summary` under 50 chars, imperative, plus a 1-3 line body explaining why. The summary must make sense standalone in a changelog.
7. Commit. Do not push without explicit approval.
8. `CHANGELOG.md` is generated from commit history, never hand-written. Tools like git-cliff are third-party, so ask before using one; otherwise leave it.
