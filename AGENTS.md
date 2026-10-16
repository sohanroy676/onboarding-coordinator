# AGENTS.md

Federated least-privilege onboarding coordinator (PS3): a coordinator plus HR, IT and Facilities agent processes that complete onboarding without concentrating domain credentials.

Stack: Python 3.12+ on Windows, standard library only, HTTP+JSON on 127.0.0.1, unittest.

- Run: python provision.py | python demo.py | python onboard.py --subject <id>
- Test: python -m unittest discover -s tests -v
- Check: python -m compileall -q domains coordinator ledger provision.py demo.py onboard.py app

- Standard library only; never add a third-party package.
- No secret or key in any tracked file; the coordinator never holds a domain credential. v3.0.0 only (ADR-0011): `GROQ_API_KEY` may sit in a git-ignored `.env`, read by `app/` only, for the opt-in `--planner model`; the model only proposes actions.
- Refusals are enforced inside each domain; the coordinator never filters or skips them.
- Never fake, edit or stage traces or results, and never weaken a test to make it pass.

Detailed rules: see .clinerules/