"""Gate G7: the model cannot widen authority (ADR-0011).

Real domain processes on ephemeral ports run behind the real onboarding flow.
The model is a fake client returning hostile or odd output; nothing touches the
network. Each case must end before approval (exit 5 or 2), or stay in the plan
and be refused by the domain. The subject always comes from --subject.
"""

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import onboarding
from app.model_planner import MAX_PROPOSAL_CHARS, ModelPlannerError
from app.onboarding import (
    EXIT_BAD_INPUT,
    EXIT_MODEL_FAILED,
    EXIT_NOT_APPROVED,
    EXIT_NOT_SUCCESS,
    EXIT_SUCCESS,
    execute_plan,
    run_onboarding,
)
from coordinator.planner import plan_hash
from coordinator.run import new_run_id
from ledger.reconstruct import LEDGER_NAME, reconstruct

SUBJECT = "g7.hire@example.test"
TEXT = "a new engineer who needs a laptop"
EPHEMERAL = {"hr": 0, "it": 0, "facilities": 0}
DOMAINS = ("hr", "it", "facilities")


def proposal(*pairs):
    return json.dumps({"requests": [{"domain": d, "action": a} for d, a in pairs]})


class FakeModel:
    model = "g7-fake"

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = 0
        self.schemas = []

    def propose(self, system_prompt, user_text, schema=None):
        self.calls += 1
        self.schemas.append(schema)
        if self.error:
            raise self.error
        return self.reply


class ModelAuthorityGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_dir = Path(tmp.name)

    def run_flow(self, client, answer="y", run_id=None):
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return answer

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_onboarding(
                SUBJECT, None, ask=ask, clock=time.time, ports=EPHEMERAL,
                state_dir=self.state_dir, run_id=run_id or new_run_id(),
                planner="model", request_text=TEXT, client=client)
        self.asked = asked
        return code, out.getvalue()

    def ledger_line_count(self):
        total = 0
        for domain in DOMAINS:
            path = self.state_dir / domain / LEDGER_NAME
            if path.exists():
                total += len(path.read_text(encoding="utf-8").splitlines())
        return total

    def assert_nothing_happened(self):
        self.assertEqual(self.asked, [])
        self.assertEqual(self.ledger_line_count(), 0)
        self.assertFalse((self.state_dir / "approvals").exists())
        self.assertFalse((self.state_dir / "exchanges.log").exists())

    def test_action_outside_the_registry_is_refused_at_planning(self):
        code, out = self.run_flow(FakeModel(proposal(("it", "delete_everything"))))
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("plan refused", out)
        self.assert_nothing_happened()

    def test_grant_admin_access_stays_in_the_plan_and_the_domain_refuses_it(self):
        run_id = new_run_id()
        code, out = self.run_flow(
            FakeModel(proposal(("it", "create_account"), ("it", "grant_admin_access"))),
            run_id=run_id)
        self.assertEqual(code, EXIT_NOT_SUCCESS)
        self.assertIn("grant_admin_access", out)
        self.assertIn("warning:", out)
        rebuilt = reconstruct(run_id, self.state_dir)
        it = next(d for d in rebuilt.domains if d.domain == "it")
        self.assertEqual(it.outcomes["executed"], 1)
        self.assertEqual(it.outcomes["refused"], 1)
        self.assertTrue(rebuilt.chain_ok)

    def test_malformed_json_ends_the_run_before_approval(self):
        code, out = self.run_flow(FakeModel("{this is not json"))
        self.assertEqual(code, EXIT_MODEL_FAILED)
        self.assertIn("nothing was approved, minted or sent", out)
        self.assert_nothing_happened()

    def test_oversized_or_too_long_proposals_end_the_run_before_approval(self):
        item = ("it", "create_account")
        for name, reply in (
                ("thirteen items", proposal(*[item] * 13)),
                ("oversized text", proposal(("it", "a" * MAX_PROPOSAL_CHARS)))):
            with self.subTest(name):
                code, _out = self.run_flow(FakeModel(reply))
                self.assertEqual(code, EXIT_MODEL_FAILED)
                self.assert_nothing_happened()

    def test_extra_fields_cannot_carry_params_scope_or_a_subject(self):
        for extra in ({"params": {"login": "root"}}, {"scope": ["*"]},
                      {"subject": "boss@example.test"}):
            reply = json.dumps({"requests": [
                dict({"domain": "it", "action": "create_account"}, **extra)]})
            with self.subTest(extra=extra):
                code, _out = self.run_flow(FakeModel(reply))
                self.assertEqual(code, EXIT_MODEL_FAILED)
                self.assert_nothing_happened()
        reply = json.dumps({"subject": "boss@example.test", "requests": [
            {"domain": "it", "action": "create_account"}]})
        code, _out = self.run_flow(FakeModel(reply))
        self.assertEqual(code, EXIT_MODEL_FAILED)
        self.assert_nothing_happened()

    def test_the_plan_subject_and_hash_come_from_the_flow_not_the_model(self):
        seen = []
        real = execute_plan

        def spy(provisioner, plan, **kwargs):
            seen.append(plan)
            return real(provisioner, plan, **kwargs)

        with mock.patch.object(onboarding, "execute_plan", spy):
            code, out = self.run_flow(FakeModel(proposal(
                ("facilities", "issue_badge"), ("hr", "create_record"))))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(len(seen), 1)
        expected = {"subject": SUBJECT, "steps": [
            {"domain": "hr", "action": "create_record", "params": {},
             "classification": "supported"},
            {"domain": "facilities", "action": "issue_badge", "params": {},
             "classification": "supported"},
        ]}
        self.assertEqual(plan_hash(seen[0]), plan_hash(expected))
        self.assertIn("plan for " + SUBJECT, out)

    def test_declining_the_model_plan_mints_and_sends_nothing(self):
        code, _out = self.run_flow(FakeModel(proposal(("it", "create_account"))),
                                   answer="n")
        self.assertEqual(code, EXIT_NOT_APPROVED)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.ledger_line_count(), 0)
        self.assertFalse((self.state_dir / "exchanges.log").exists())

    def test_client_failures_end_the_run_without_retry_or_fallback(self):
        for message in ("rate limit exceeded (HTTP 429)", "model call failed: URLError",
                        "model call failed: TimeoutError"):
            with self.subTest(message):
                model = FakeModel(error=ModelPlannerError(message))
                code, out = self.run_flow(model)
                self.assertEqual(code, EXIT_MODEL_FAILED)
                self.assertEqual(model.calls, 1)
                self.assertIn(message, out)
                self.assertNotIn("planner: deterministic", out)
                self.assert_nothing_happened()


if __name__ == "__main__":
    unittest.main()
