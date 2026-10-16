"""Unit tests for the model planner path of app/onboarding.py.

Same fakes as test_unit_app_onboarding (no process, no port, no network). The
model client is a fake that returns scripted text or raises.
"""

import json
import unittest
from unittest import mock

from app import onboarding
from app.model_planner import ModelPlannerError
from app.onboarding import (
    EXIT_BAD_INPUT,
    EXIT_MODEL_FAILED,
    EXIT_NOT_APPROVED,
    EXIT_NOT_SUCCESS,
    EXIT_SUCCESS,
    InputError,
    validate_request_text,
)
from tests.test_unit_app_onboarding import Answers, OnboardingCase, SUBJECT

TEXT = "new engineer, needs a laptop and a badge"


def proposal(*pairs):
    return json.dumps({"requests": [{"domain": d, "action": a} for d, a in pairs]})


class FakeClient:
    model = "fake-model"

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []
        self.schemas = []

    def propose(self, system_prompt, user_text, schema=None):
        self.calls.append((system_prompt, user_text))
        self.schemas.append(schema)
        if self.error:
            raise self.error
        return self.reply


class RequestTextRules(unittest.TestCase):
    def test_plain_text_is_accepted(self):
        self.assertEqual(validate_request_text(TEXT), TEXT)

    def test_bad_text_is_refused(self):
        for bad in ("", "   ", None, "a" * 1001, "line one\nline two", "caf" + chr(233)):
            with self.subTest(bad=bad), self.assertRaises(InputError):
                validate_request_text(bad)

    def test_1000_characters_is_the_longest_accepted(self):
        self.assertEqual(len(validate_request_text("a" * 1000)), 1000)


class ModelFlow(OnboardingCase):
    def run_model(self, client, ask=None, **kwargs):
        kwargs.setdefault("request_text", TEXT)
        return self.run_flow(ask or Answers("y"), planner="model", client=client, **kwargs)

    def test_approved_model_run_executes_the_proposed_actions(self):
        client = FakeClient(proposal(("it", "assign_laptop"), ("facilities", "issue_badge")))
        code, out = self.run_model(client)
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("planner: model (fake-model), 2 requests proposed", out)
        self.assertEqual(self.post.actions_for("it"), ["assign_laptop"])
        self.assertEqual(self.post.actions_for("facilities"), ["issue_badge"])
        self.assertEqual(self.post.actions_for("hr"), [])

    def test_only_the_request_text_and_action_names_are_sent_to_the_model(self):
        client = FakeClient(proposal(("it", "assign_laptop")))
        self.run_model(client)
        system_prompt, user_text = client.calls[0]
        self.assertEqual(user_text, TEXT)
        self.assertNotIn(SUBJECT, system_prompt + user_text)
        self.assertIn("it: assign_laptop, create_account", system_prompt)
        supported, _marker, refused = system_prompt.partition(
            "Actions the domain will refuse")
        self.assertNotIn("grant_admin_access", supported)
        self.assertIn("it: grant_admin_access", refused)

    def test_the_model_is_sent_every_declared_action_as_the_allowed_enum(self):
        client = FakeClient(proposal(("it", "assign_laptop")))
        self.run_model(client)
        schema = client.schemas[0]
        action = schema["properties"]["requests"]["items"]["properties"]["action"]
        self.assertEqual(action["enum"], sorted([
            "create_record", "enroll_benefits", "create_account", "assign_laptop",
            "grant_admin_access", "issue_badge", "assign_desk"]))
        self.assertTrue(schema["additionalProperties"] is False)

    def test_a_refused_action_proposed_by_the_model_stays_in_the_plan(self):
        client = FakeClient(proposal(("it", "assign_laptop"), ("it", "grant_admin_access")))
        _code, out = self.run_model(client)
        self.assertIn("it          grant_admin_access will_not", out)
        self.assertIn("grant_admin_access is on the domain's will_not list", out)

    def test_declined_model_plan_sends_nothing(self):
        client = FakeClient(proposal(("it", "assign_laptop")))
        code, out = self.run_model(client, ask=Answers("n"))
        self.assertEqual(code, EXIT_NOT_APPROVED)
        self.assertEqual(self.post.calls, [])
        self.assertEqual(self.markers(), [])

    def test_will_not_action_stays_in_the_plan_with_a_warning(self):
        client = FakeClient(proposal(("it", "grant_admin_access")))
        code, out = self.run_model(client, ask=Answers("n"))
        self.assertEqual(code, EXIT_NOT_APPROVED)
        self.assertIn("grant_admin_access", out)
        self.assertIn("warning:", out)

    def test_unknown_action_is_refused_by_the_existing_planner(self):
        client = FakeClient(proposal(("it", "delete_everything")))
        ask = Answers()
        code, out = self.run_model(client, ask=ask)
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("plan refused", out)
        self.assertEqual(ask.prompts, [])
        self.assertEqual(self.post.calls, [])

    def test_each_model_failure_ends_before_the_prompt_with_exit_5(self):
        hostile = {
            "client error": FakeClient(error=ModelPlannerError("rate limit exceeded")),
            "malformed json": FakeClient("not json"),
            "extra field": FakeClient(json.dumps(
                {"requests": [{"domain": "it", "action": "assign_laptop", "params": {}}]})),
            "unknown domain": FakeClient(proposal(("payroll", "pay_me"))),
            "bad action name": FakeClient(proposal(("it", "Assign Laptop"))),
            "colon trick": FakeClient(proposal(("hr", "a:b"))),
            "empty list": FakeClient(proposal()),
        }
        for name, client in hostile.items():
            with self.subTest(name):
                ask = Answers()
                code, out = self.run_model(client, ask=ask)
                self.assertEqual(code, EXIT_MODEL_FAILED)
                self.assertIn("model planner failed", out)
                self.assertIn("nothing was approved, minted or sent", out)
                self.assertEqual(ask.prompts, [])
                self.assertEqual(self.post.calls, [])
                self.assertEqual(self.markers(), [])
                self.assertTrue(self.provisioner.stopped)

    def test_missing_key_ends_before_any_domain_starts(self):
        out_code = self.run_flow(Answers(), planner="model", request_text=TEXT,
                                 env_path=self.state_dir / "absent.env")
        self.assertEqual(out_code[0], EXIT_MODEL_FAILED)
        self.assertIn("no absent.env file", out_code[1])
        self.assertIsNone(self.provisioner)

    def test_key_from_env_file_builds_the_client_without_printing_it(self):
        env = self.state_dir / "model.env"
        env.write_text("GROQ_API_KEY=unit-key-value\n", encoding="ascii")
        with mock.patch.object(onboarding, "GroqClient") as groq:
            groq.return_value = FakeClient(proposal(("it", "assign_laptop")))
            code, out = self.run_flow(Answers("y"), planner="model",
                                      request_text=TEXT, env_path=env, model="m1")
        self.assertEqual(code, EXIT_SUCCESS)
        groq.assert_called_once_with("unit-key-value", "m1")
        self.assertNotIn("unit-key-value", out)


class PlannerOptionRules(OnboardingCase):
    def test_bad_combinations_are_exit_2_and_start_nothing(self):
        cases = {
            "model without text": dict(planner="model"),
            "model with blank text": dict(planner="model", request_text="  "),
            "model with --request": dict(planner="model", request_text=TEXT,
                                         request_texts=["it:create_account"]),
            "text without model": dict(request_text=TEXT),
            "unknown planner": dict(planner="oracle", request_text=TEXT),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                code, out = self.run_flow(Answers(), client=FakeClient("{}"), **kwargs)
                self.assertEqual(code, EXIT_BAD_INPUT)
                self.assertIn("input error", out)
                self.assertIsNone(self.provisioner)

    def test_deterministic_mode_never_reads_the_env_file_or_builds_a_client(self):
        with mock.patch.object(onboarding, "read_key") as read_key, \
                mock.patch.object(onboarding, "GroqClient") as groq:
            code, out = self.run_flow(Answers("y"))
        self.assertEqual(code, EXIT_SUCCESS)
        read_key.assert_not_called()
        groq.assert_not_called()
        self.assertNotIn("planner:", out)
        self.assertEqual(len(self.post.actions_for("hr")), 2)

    def test_exit_codes_are_distinct(self):
        codes = {EXIT_SUCCESS, EXIT_NOT_SUCCESS, EXIT_BAD_INPUT, EXIT_NOT_APPROVED,
                 EXIT_MODEL_FAILED}
        self.assertEqual(len(codes), 5)


if __name__ == "__main__":
    unittest.main()
