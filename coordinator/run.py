"""Run one approved plan: verify, mint per domain, dispatch in order, report.

The approval is verified and consumed before anything is minted or sent.
Domains are called in DOMAIN_ORDER (HR, IT, Facilities), one token each,
minted just before its call. There are no retries, no rollback and no
parallel dispatch. The coordinator writes no ledger lines; each domain is
the only writer of its own ledger and the only authority for its refusals.

A domain that cannot be reached or answers badly has its actions reported
as not_executed, and the run goes on to the next domain. Steps on a domain's
will_not list are sent like any other step: the coordinator never filters.

Status comes from the per-action outcomes: success (all executed), partial
(some executed, some not), failed (none executed). aborted means the approval
was refused, so nothing was minted or sent.
"""

import json
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from coordinator.approval import ApprovalError
from coordinator.planner import DOMAIN_ORDER

HOST = "127.0.0.1"
EXECUTE_PATH = "/execute"
HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 64 * 1024
DOMAIN_OUTCOMES = ("executed", "refused", "failed")
NOT_EXECUTED = "not_executed"

SUCCESS = "success"
PARTIAL = "partial"
FAILED = "failed"
ABORTED = "aborted"


class DomainCallFailed(Exception):
    """A domain did not answer with a well-formed result list. reason is the row reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ActionRow:
    domain: str
    action: str
    classification: str
    outcome: str
    reason: str | None


@dataclass
class RunReport:
    run_id: str
    status: str
    abort_code: str | None
    rows: list = field(default_factory=list)
    exchange_count: int = 0

    def count(self, outcome):
        return sum(1 for row in self.rows if row.outcome == outcome)


def new_run_id():
    return secrets.token_hex(8)


def post_execute(port, body, timeout):
    """POST one /execute body; return (status, raw bytes). A non-2xx status is returned."""
    # An empty proxy map stops a system proxy from intercepting 127.0.0.1.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"http://{HOST}:{port}{EXECUTE_PATH}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
        finally:
            exc.close()


def _error_code(raw):
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return "unknown"
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return "unknown"


def parse_results(actions, status, raw):
    """Return (outcome, reason) for each action, in order, or raise DomainCallFailed."""
    if status != 200:
        raise DomainCallFailed(f"domain_error:{_error_code(raw)}")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DomainCallFailed("bad_response")
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise DomainCallFailed("bad_response") from exc
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list) or len(results) != len(actions):
        raise DomainCallFailed("bad_response")
    parsed = []
    for expected, item in zip(actions, results):
        if not isinstance(item, dict) or item.get("action") != expected["name"]:
            raise DomainCallFailed("bad_response")
        if item.get("outcome") not in DOMAIN_OUTCOMES:
            raise DomainCallFailed("bad_response")
        parsed.append((item["outcome"], item.get("reason")))
    return parsed


def _status(rows):
    executed = sum(1 for row in rows if row.outcome == "executed")
    if executed == len(rows):
        return SUCCESS
    if executed == 0:
        return FAILED
    return PARTIAL


def run_plan(plan, approval, *, gate, minter, ports, subject, run_id=None,
             post=post_execute, timeout=HTTP_TIMEOUT_SECONDS):
    """Verify the approval, then dispatch the approved plan and return a RunReport."""
    if not plan["steps"]:
        raise ValueError("a plan needs at least one step")
    missing = [domain for domain in DOMAIN_ORDER
               if domain not in ports and any(s["domain"] == domain for s in plan["steps"])]
    if missing:
        raise ValueError(f"no port for domain(s): {', '.join(missing)}")
    run_id = run_id or new_run_id()
    try:
        gate.verify_and_consume(approval, plan)
    except ApprovalError as exc:
        return RunReport(run_id, ABORTED, exc.code, [], minter.exchange_count)

    rows = []
    for domain in DOMAIN_ORDER:
        steps = [step for step in plan["steps"] if step["domain"] == domain]
        if not steps:
            continue
        actions = [{"name": step["action"], "params": step["params"]} for step in steps]
        scope = sorted({step["action"] for step in steps})
        token = minter.mint(subject, domain, scope, run_id)
        try:
            status, raw = post(ports[domain], {"token": token, "actions": actions}, timeout)
            outcomes = parse_results(actions, status, raw)
        except DomainCallFailed as exc:
            outcomes = [(NOT_EXECUTED, exc.reason)] * len(steps)
        except OSError:
            outcomes = [(NOT_EXECUTED, "domain_unreachable")] * len(steps)
        for step, (outcome, reason) in zip(steps, outcomes):
            rows.append(ActionRow(domain, step["action"], step["classification"],
                                  outcome, reason))
    return RunReport(run_id, _status(rows), None, rows, minter.exchange_count)
