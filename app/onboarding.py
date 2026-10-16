"""The one onboarding flow: validate, start domains, plan, approve, run, rebuild.

Used by onboard.py (the console) and by the tests. The operator approves at
the console (ADR-0009); the approval is signed and consumed by the same
process that runs the plan. Nothing is approved, minted or sent unless the
answer is y. This module imports coordinator, ledger.reconstruct and the
operator modules only; it never imports domains or ledger internals.
"""

import json
import re
import time

from app.model_planner import (
    DEFAULT_MODEL,
    ENV_PATH,
    GroqClient,
    ModelPlannerError,
    build_system_prompt,
    parse_proposal,
    read_key,
)
from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan, warnings
from coordinator.registry import Registry, RegistryError
from coordinator.run import SUCCESS, new_run_id, post_execute, run_plan
from coordinator.tokens import TokenMinter
from demo import SUPPORTED_REQUESTS, print_report
from ledger.reconstruct import format_rebuild, reconstruct
from provision import Provisioner, ProvisionError

EXIT_SUCCESS = 0
EXIT_NOT_SUCCESS = 1
EXIT_BAD_INPUT = 2
EXIT_NOT_APPROVED = 3
EXIT_NO_DOMAINS = 4
EXIT_MODEL_FAILED = 5

DOMAINS = ("hr", "it", "facilities")
SUBJECT_MAX_LENGTH = 254
SUBJECT_PATTERN = re.compile(r"[\x21-\x7e]+")
ACTION_PATTERN = re.compile(r"[a-z_]{1,40}")
REQUEST_TEXT_MAX_LENGTH = 1000
REQUEST_TEXT_PATTERN = re.compile(r"[ -~]+")
PLANNERS = ("deterministic", "model")
APPROVE_PROMPT = "Approve this plan? [y/N] "
DEFAULT_REQUEST_TEXTS = tuple(
    "%s:%s" % (domain, action) for domain, action, _params in SUPPORTED_REQUESTS
)


class InputError(ValueError):
    """The subject or a request is not acceptable input."""


def validate_subject(subject):
    """Return the subject if it is one ASCII token with exactly one @."""
    if not subject:
        raise InputError("subject is empty")
    if len(subject) > SUBJECT_MAX_LENGTH:
        raise InputError("subject is longer than %d characters" % SUBJECT_MAX_LENGTH)
    if not SUBJECT_PATTERN.fullmatch(subject):
        raise InputError("subject must be printable ASCII with no spaces")
    if subject.count("@") != 1:
        raise InputError("subject must contain exactly one @")
    return subject


def parse_request(text):
    """Return (domain, action, params) for one "domain:action" request."""
    domain, separator, action = text.partition(":")
    if not separator:
        raise InputError("request must be domain:action, got %r" % text)
    if domain not in DOMAINS:
        raise InputError("unknown domain %r; use one of %s" % (domain, ", ".join(DOMAINS)))
    if not ACTION_PATTERN.fullmatch(action):
        raise InputError("action must match [a-z_]{1,40}, got %r" % action)
    return (domain, action, {})


def validate_request_text(text):
    """Return the free text for the model planner if it is short printable ASCII."""
    if not text or not text.strip():
        raise InputError("request text is empty")
    if len(text) > REQUEST_TEXT_MAX_LENGTH:
        raise InputError("request text is longer than %d characters"
                         % REQUEST_TEXT_MAX_LENGTH)
    if not REQUEST_TEXT_PATTERN.fullmatch(text):
        raise InputError("request text must be printable ASCII on one line")
    return text


def run_onboarding(subject, request_texts=None, *, ask=input, post=post_execute,
                   clock=time.time, ports=None, state_dir=None, run_id=None,
                   planner="deterministic", request_text=None, model=DEFAULT_MODEL,
                   client=None, env_path=ENV_PATH):
    """Run one onboarding and return the exit code (see onboard.py).

    planner "model" asks the model (ADR-0011) for the requests instead of using
    the defaults or request_texts. client is injected in tests; otherwise the
    key is read from env_path. In deterministic mode neither is touched.
    """
    try:
        validate_subject(subject)
        if planner not in PLANNERS:
            raise InputError("planner must be one of %s" % ", ".join(PLANNERS))
        if planner == "model":
            if request_texts:
                raise InputError("--request cannot be combined with the model planner")
            validate_request_text(request_text)
            requests = None
        else:
            if request_text is not None:
                raise InputError("request text needs the model planner")
            texts = list(request_texts) if request_texts else list(DEFAULT_REQUEST_TEXTS)
            requests = [parse_request(text) for text in texts]
    except InputError as exc:
        print("input error: %s" % exc)
        return EXIT_BAD_INPUT
    if planner == "model" and client is None:
        try:
            client = GroqClient(read_key(env_path), model)
        except ModelPlannerError as exc:
            print("model planner failed: %s" % exc)
            return EXIT_MODEL_FAILED
    model_input = (client, request_text) if planner == "model" else None
    provisioner = Provisioner(state_dir=state_dir, ports=ports)
    try:
        provisioner.start()
    except ProvisionError as exc:
        print("domains did not start: %s" % exc)
        return EXIT_NO_DOMAINS
    try:
        return _plan_approve_run(provisioner, subject, requests, ask, post, clock,
                                 run_id, model_input)
    finally:
        provisioner.stop()
        print("all domains stopped")


def _plan_approve_run(provisioner, subject, requests, ask, post, clock, run_id,
                      model_input=None):
    registry = Registry(provisioner.ports, clock)
    try:
        registry.refresh_all()
    except RegistryError as exc:
        print("domains did not start: %s" % exc)
        return EXIT_NO_DOMAINS
    if model_input is not None:
        try:
            requests = _model_requests(registry, *model_input)
        except ModelPlannerError as exc:
            print("model planner failed: %s" % exc)
            print("nothing was approved, minted or sent")
            return EXIT_MODEL_FAILED
    try:
        plan = build_plan(registry, subject, requests)
    except (ValueError, KeyError, RegistryError) as exc:
        print("plan refused: %s" % exc)
        return EXIT_BAD_INPUT
    _print_plan(plan)
    if not _approved(ask):
        print("not approved: nothing was approved, minted or sent")
        return EXIT_NOT_APPROVED
    run_id = run_id or new_run_id()
    print("run id: " + run_id)
    try:
        report = execute_plan(provisioner, plan, post=post, clock=clock,
                              run_id=run_id)
    except KeyboardInterrupt:
        print("interrupted after approval; the run may be partial. Rebuild with:")
        print("python -m ledger.reconstruct " + run_id)
        return EXIT_NOT_SUCCESS
    print_report("onboarding run", report)
    for line in format_rebuild(reconstruct(report.run_id, provisioner.state_dir)):
        print(line)
    return EXIT_SUCCESS if report.status == SUCCESS else EXIT_NOT_SUCCESS


def propose_requests(registry, client, request_text):
    """Ask the model for requests and return them as (domain, action, params).

    Only the offered action names and the free text leave the machine; the
    subject does not. A pair that parse_request rejects is a bad model reply.
    Prints nothing; the console and the web UI both call it.
    """
    offered = {domain: registry.declaration(domain).capabilities for domain in DOMAINS}
    reply = client.propose(build_system_prompt(offered), request_text)
    try:
        return [parse_request(text) for text in parse_proposal(reply)]
    except InputError as exc:
        raise ModelPlannerError("model proposed an unusable request: %s" % exc) from None


def _model_requests(registry, client, request_text):
    requests = propose_requests(registry, client, request_text)
    print("planner: model (%s), %d requests proposed" % (client.model, len(requests)))
    return requests


def execute_plan(provisioner, plan, *, post, clock, run_id):
    """Sign the approval for this plan and run it. Prints nothing.

    Both the console (after a y) and the web UI (after the approve button)
    call this. run_plan verifies the approval, its expiry and the plan hash
    before anything is minted or sent.
    """
    approver = Approver(provisioner.approval_secret, clock)
    gate = ApprovalGate(provisioner.approval_secret, clock,
                        provisioner.state_dir / "approvals")
    minter = TokenMinter(provisioner.exchange_secret, clock,
                         count_path=provisioner.state_dir / "exchanges.log")
    approval = approver.approve(plan)
    return run_plan(plan, approval, gate=gate, minter=minter,
                    ports=provisioner.ports, subject=plan["subject"],
                    run_id=run_id, post=post)


def _approved(ask):
    """True only for a y (any case). End of input and Ctrl-C count as no."""
    try:
        answer = ask(APPROVE_PROMPT)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() == "y"


def _print_plan(plan):
    print("plan for %s" % plan["subject"])
    for step in plan["steps"]:
        params = json.dumps(step["params"], sort_keys=True)
        print("  %-11s %-18s %-14s %s" % (step["domain"], step["action"],
                                          step["classification"], params))
    for line in warnings(plan):
        print("warning: " + line)
