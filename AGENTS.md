# AGENTS.md

Federated least-privilege onboarding coordinator (PS3): a coordinator plus HR, IT and Facilities agent processes that complete onboarding without concentrating domain credentials.

Stack: Python 3.12+ on Windows, standard library only, HTTP+JSON on 127.0.0.1, unittest.

- Run: python provision.py | python demo.py
- Test: python -m unittest discover -s tests -v
- Check: python -m compileall -q domains coordinator ledger provision.py demo.py

- Standard library only; never add a third-party package.
- No secret or key in any file; the coordinator never holds a domain credential.
- Refusals are enforced inside each domain; the coordinator never filters or skips them.
- Never fake, edit or stage traces or results, and never weaken a test to make it pass.

Detailed rules: see .clinerules/