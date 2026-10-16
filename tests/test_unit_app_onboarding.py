"""Unit tests for app/onboarding.py: input rules, the approval prompt, exit codes.

The domains, provisioner and registry fetch are fakes, so no process starts
and no port is opened. The approval gate, approver and minter are the real
coordinator classes over a temporary state folder and an injected clock.
"""

import contextlib
import functools
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import onboarding
from app.onboarding import (
    EXIT_BAD_INPUT,
    EXIT_NOT_APPROVED,
    EXIT_NOT_SUCCESS,
    EXIT_NO_DOMAINS,
    EXIT_SUCCESS,
    InputError,
    parse_request,
    run_onboarding,
    validate_subject,
)
from coordinator.registry import Registry
from coordinator.run import new_run_id
from provision import ProvisionError
from tests.helpers import FakeClock

SUBJECT = "new.hire@example.test"
PORTS = {"hr": 8001, "it": 8002, "facilities": 8003}
CAPABILITIES = {
    8001: {"domain": "hr", "capabilities": ["create_record", "enroll_benefits"],
           "will_not": []},
    8002: {"domain": "it", "capabilities": ["create_account", "assign_laptop"],
           "will_not": ["grant_admin_access"]},
    8003: {"domain": "facilities", "capabilities": ["issue_badge", "assign_desk"],
           "will_not": []},
}
DOMAIN_OF_PORT = {port: domain for domain, port in PORTS.items()}


class FakeProvisioner:
    """Stands in for provision.Provisioner; records start and stop."""

    def __init__(self, state_dir=None, ports=None):
        self.state_dir = Path(state_dir)
        self.ports = dict(PORTS)
        self.exchange_secret = "unit-exchange-secret"
        self.approval_secret = "unit-approval-secret"
        self.start_error = None
        self.started = False
        self.stopped = False

    def start(self):
        if self.start_error:
            raise self.start_error
        self.started = True
        return dict(self.ports)

    def stop(self):
        self.stopped = True


class FakePost:
    """Records each POST /execute; answers every action with the given outcome."""

    def __init__(self, outcomes=None, error=None):
        self.calls = []
        self.outcomes = outcomes or {}
        self.error = error

    def __call__(self, port, body, timeout):
        self.calls.append((port, body))
        if self.error:
            raise self.error
        results = []
        for action in body["actions"]:
            outcome = self.outcomes.get(action["name"], "executed")
            results.append({"action": action["name"], "outcome": outcome,
                            "reason": None if outcome == "executed" else "will_not"})
        return 200, json.dumps({"results": results}).encode("utf-8")

    def actions_for(self, domain):
        port = PORTS[domain]
        names = []
        for called_port, body in self.calls:
            if called_port == port:
                names.extend(action["name"] for action in body["actions"])
        return names


def fake_fetch(port, timeout):
    if port not in CAPABILITIES:
        raise OSError("no domain on this port")
    return 200, json.dumps(CAPABILITIES[port]).encode("utf-8")


class Answers:
    """An ask() that returns scripted answers and records every prompt."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class OnboardingCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_dir = Path(tmp.name)
        self.provisioner = None
        self.post = FakePost()
        self.clock = FakeClock()
        patches = [
            mock.patch.object(onboarding, "Provisioner", self._make_provisioner),
            mock.patch.object(onboarding, "Registry",
                              functools.partial(Registry, fetch=fake_fetch)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _make_provisioner(self, state_dir=None, ports=None):
        self.provisioner = FakeProvisioner(state_dir=self.state_dir, ports=ports)
        return self.provisioner

    def run_flow(self, ask, request_texts=None, subject=SUBJECT, post=None, run_id=None,
                 **options):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_onboarding(
                subject, request_texts, ask=ask, post=post or self.post,
                clock=self.clock, state_dir=self.state_dir, run_id=run_id, **options)
        return code, out.getvalue()

    def markers(self):
        folder = self.state_dir / "approvals"
        return sorted(folder.glob("*.consumed")) if folder.exists() else []


class SubjectRules(unittest.TestCase):
    def test_a_plain_address_is_accepted(self):
        self.assertEqual(validate_subject(SUBJECT), SUBJECT)

    def test_empty_subject_is_refused(self):
        with self.assertRaisesRegex(InputError, "empty"):
            validate_subject("")

    def test_254_characters_is_the_longest_accepted(self):
        subject = "a" * 248 + "@x.org"
        self.assertEqual(len(subject), 254)
        self.assertEqual(validate_subject(subject), subject)

    def test_255_characters_is_refused(self):
        subject = "a" * 249 + "@x.org"
        self.assertEqual(len(subject), 255)
        with self.assertRaisesRegex(InputError, "longer than 254"):
            validate_subject(subject)

    def test_a_space_is_refused(self):
        with self.assertRaisesRegex(InputError, "no spaces"):
            validate_subject("new hire@example.test")

    def test_a_tab_or_control_character_is_refused(self):
        for bad in ("new\thire@example.test", "new\x00hire@example.test"):
            with self.subTest(bad=bad), self.assertRaises(InputError):
                validate_subject(bad)

    def test_non_ascii_is_refused(self):
        with self.assertRaises(InputError):
            validate_subject("n\u00e9w@example.test")

    def test_no_at_sign_is_refused(self):
        with self.assertRaisesRegex(InputError, "exactly one @"):
            validate_subject("newhire.example.test")

    def test_two_at_signs_are_refused(self):
        with self.assertRaisesRegex(InputError, "exactly one @"):
            validate_subject("a@b@example.test")


class RequestRules(unittest.TestCase):
    def test_a_valid_request_has_empty_params(self):
        self.assertEqual(parse_request("it:create_account"),
                         ("it", "create_account", {}))

    def test_underscores_and_single_letters_are_allowed(self):
        self.assertEqual(parse_request("hr:a_b")[1], "a_b")

    def test_a_missing_colon_is_refused(self):
        with self.assertRaisesRegex(InputError, "domain:action"):
            parse_request("it create_account")

    def test_an_unknown_domain_is_refused(self):
        with self.assertRaisesRegex(InputError, "unknown domain"):
            parse_request("legal:create_record")

    def test_domain_names_are_case_sensitive(self):
        with self.assertRaises(InputError):
            parse_request("HR:create_record")

    def test_uppercase_action_is_refused(self):
        with self.assertRaisesRegex(InputError, r"\[a-z_\]"):
            parse_request("it:Create_account")

    def test_digits_and_dashes_in_action_are_refused(self):
        for bad in ("it:create1", "it:create-account", "it:create account"):
            with self.subTest(bad=bad), self.assertRaises(InputError):
                parse_request(bad)

    def test_empty_action_is_refused(self):
        with self.assertRaises(InputError):
            parse_request("it:")

    def test_forty_one_characters_is_refused_and_forty_is_accepted(self):
        self.assertEqual(len(parse_request("it:" + "a" * 40)[1]), 40)
        with self.assertRaises(InputError):
            parse_request("it:" + "a" * 41)


class ApprovalPrompt(OnboardingCase):
    def test_y_in_any_case_approves_and_runs(self):
        for answer in ("y", "Y", " y "):
            with self.subTest(answer=answer):
                self.post = FakePost()
                ask = Answers(answer)
                code, _out = self.run_flow(ask)
                self.assertEqual(code, EXIT_SUCCESS)
                self.assertEqual(len(self.post.calls), 3)
                self.assertEqual(len(self.markers()), 1)
                self.assertEqual(self.provisioner.stopped, True)
                for marker in self.markers():
                    marker.unlink()

    def test_anything_else_is_not_approved_and_sends_nothing(self):
        for answer in ("n", "", "yes", "no", "Y es"):
            with self.subTest(answer=answer):
                self.post = FakePost()
                code, out = self.run_flow(Answers(answer))
                self.assertEqual(code, EXIT_NOT_APPROVED)
                self.assertEqual(self.post.calls, [])
                self.assertEqual(self.markers(), [])
                self.assertIn("not approved", out)

    def test_end_of_input_is_not_approved(self):
        code, _out = self.run_flow(Answers(EOFError()))
        self.assertEqual(code, EXIT_NOT_APPROVED)
        self.assertEqual(self.post.calls, [])
        self.assertEqual(self.markers(), [])

    def test_ctrl_c_at_the_prompt_is_not_approved(self):
        code, _out = self.run_flow(Answers(KeyboardInterrupt()))
        self.assertEqual(code, EXIT_NOT_APPROVED)
        self.assertEqual(self.post.calls, [])
        self.assertEqual(self.markers(), [])

    def test_the_prompt_is_asked_exactly_once(self):
        ask = Answers("n")
        self.run_flow(ask)
        self.assertEqual(ask.prompts, [onboarding.APPROVE_PROMPT])

    def test_the_plan_is_printed_before_the_prompt(self):
        out = io.StringIO()
        seen = {}

        def ask(prompt):
            seen["before_prompt"] = out.getvalue()
            return "n"

        with contextlib.redirect_stdout(out):
            run_onboarding(SUBJECT, None, ask=ask, post=self.post, clock=self.clock,
                           state_dir=self.state_dir)
        self.assertIn("plan for " + SUBJECT, seen["before_prompt"])
        self.assertIn("create_record", seen["before_prompt"])
        self.assertNotIn("run id:", seen["before_prompt"])


class ExitCodes(OnboardingCase):
    def test_bad_subject_exits_2_before_any_start_or_prompt(self):
        ask = Answers("y")
        code, out = self.run_flow(ask, subject="no-at-sign")
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("input error", out)
        self.assertEqual(ask.prompts, [])
        self.assertIsNone(self.provisioner)

    def test_bad_request_exits_2_before_any_prompt(self):
        ask = Answers("y")
        code, _out = self.run_flow(ask, request_texts=["legal:create_record"])
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertEqual(ask.prompts, [])
        self.assertEqual(self.post.calls, [])

    def test_unknown_domain_or_unsupported_action_exits_2_before_any_prompt(self):
        for text in ("it:launch_rocket",):
            with self.subTest(text=text):
                ask = Answers("y")
                code, out = self.run_flow(ask, request_texts=[text])
                self.assertEqual(code, EXIT_BAD_INPUT)
                self.assertIn("plan refused", out)
                self.assertEqual(ask.prompts, [])
                self.assertEqual(self.post.calls, [])

    def test_stale_declaration_exits_2_before_any_prompt(self):
        ticks = iter([1000.0, 1000.0, 1000.0] + [2000.0] * 50)
        self.clock = lambda: next(ticks)
        ask = Answers("y")
        code, out = self.run_flow(ask)
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("plan refused", out)
        self.assertIn("TTL is", out)
        self.assertEqual(ask.prompts, [])
        self.assertEqual(self.post.calls, [])

    def test_domains_that_do_not_start_exit_4_before_any_prompt(self):
        def make(state_dir=None, ports=None):
            self.provisioner = FakeProvisioner(state_dir=self.state_dir)
            self.provisioner.start_error = ProvisionError("it did not become ready")
            return self.provisioner

        with mock.patch.object(onboarding, "Provisioner", make):
            ask = Answers("y")
            code, out = self.run_flow(ask)
        self.assertEqual(code, EXIT_NO_DOMAINS)
        self.assertIn("domains did not start", out)
        self.assertEqual(ask.prompts, [])

    def test_a_domain_that_does_not_answer_its_declaration_exits_4(self):
        def fetch(port, timeout):
            if port == PORTS["it"]:
                raise OSError("connection refused")
            return fake_fetch(port, timeout)

        with mock.patch.object(onboarding, "Registry",
                               functools.partial(Registry, fetch=fetch)):
            ask = Answers("y")
            code, _out = self.run_flow(ask)
        self.assertEqual(code, EXIT_NO_DOMAINS)
        self.assertEqual(ask.prompts, [])
        self.assertTrue(self.provisioner.stopped)

    def test_fully_executed_run_exits_0(self):
        code, out = self.run_flow(Answers("y"))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("status: success", out)

    def test_refused_action_exits_1_and_is_reported(self):
        post = FakePost(outcomes={"grant_admin_access": "refused"})
        code, out = self.run_flow(
            Answers("y"), request_texts=list(onboarding.DEFAULT_REQUEST_TEXTS)
            + ["it:grant_admin_access"], post=post)
        self.assertEqual(code, EXIT_NOT_SUCCESS)
        self.assertIn("status: partial", out)
        self.assertIn("refused 1", out)

    def test_interrupt_after_approval_exits_1_and_prints_the_run_id(self):
        post = FakePost(error=KeyboardInterrupt())
        run_id = new_run_id()
        code, out = self.run_flow(Answers("y"), post=post, run_id=run_id)
        self.assertEqual(code, EXIT_NOT_SUCCESS)
        self.assertIn("run id: " + run_id, out)
        self.assertIn("python -m ledger.reconstruct " + run_id, out)
        self.assertEqual(len(self.markers()), 1)
        self.assertTrue(self.provisioner.stopped)


class PlanContent(OnboardingCase):
    def test_default_requests_are_the_six_supported_actions(self):
        code, out = self.run_flow(Answers("y"))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(self.post.actions_for("hr"),
                         ["create_record", "enroll_benefits"])
        self.assertEqual(self.post.actions_for("it"),
                         ["create_account", "assign_laptop"])
        self.assertEqual(self.post.actions_for("facilities"),
                         ["issue_badge", "assign_desk"])

    def test_given_requests_replace_the_defaults(self):
        self.run_flow(Answers("y"), request_texts=["hr:create_record"])
        self.assertEqual(self.post.actions_for("hr"), ["create_record"])
        self.assertEqual(self.post.actions_for("it"), [])
        self.assertEqual(self.post.actions_for("facilities"), [])

    def test_will_not_warning_is_printed_and_the_step_stays_in_the_plan(self):
        code, out = self.run_flow(Answers("y"),
                                  request_texts=["it:grant_admin_access"])
        self.assertIn("warning: it: grant_admin_access is on the domain's will_not list",
                      out)
        self.assertEqual(self.post.actions_for("it"), ["grant_admin_access"])

    def test_the_run_id_is_printed_before_any_domain_is_called(self):
        out = io.StringIO()
        seen = []

        def post(port, body, timeout):
            seen.append(out.getvalue())
            return FakePost()(port, body, timeout)

        with contextlib.redirect_stdout(out):
            run_onboarding(SUBJECT, None, ask=Answers("y"), post=post,
                           clock=self.clock, state_dir=self.state_dir,
                           run_id="abc123")
        self.assertTrue(seen)
        self.assertIn("run id: abc123", seen[0])


if __name__ == "__main__":
    unittest.main()
