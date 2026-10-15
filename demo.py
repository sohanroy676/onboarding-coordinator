"""Demo: run every scenario against real domain processes and print the traces.

Run from the project root with: python demo.py

Starts the three domains on the demo ports (8101 HR, 8102 IT, 8103
Facilities), runs three scenarios, then stops them. Every status and count
printed here comes from the run itself. Save the output as a trace only
from a real run.

    1. clean run: six supported actions, expect success
    2. grant_admin_access run: the same six plus one will_not action, expect partial
    3. replay of the approval from scenario 2, expect aborted

The coordinator process holds the exchange and approval secrets in memory
only (provision.py). The domains never see either secret.
"""

import sys
import time

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan, warnings
from coordinator.registry import Registry
from coordinator.run import run_plan
from coordinator.tokens import TokenMinter
from provision import Provisioner, ProvisionError

SUBJECT = "new.hire@example.test"
SUPPORTED_REQUESTS = [
    ("hr", "create_record", {"employee": "nh"}),
    ("hr", "enroll_benefits", {"employee": "nh"}),
    ("it", "create_account", {"login": "nh"}),
    ("it", "assign_laptop", {"login": "nh"}),
    ("facilities", "issue_badge", {"floor": 3}),
    ("facilities", "assign_desk", {"floor": 3}),
]
WILL_NOT_REQUEST = ("it", "grant_admin_access", {"login": "nh"})


def print_report(title, report):
    print()
    print("== " + title)
    print("run id: " + report.run_id)
    if report.status == "aborted":
        print("status: aborted (" + report.abort_code + ")")
    else:
        print("%-11s %-18s %-14s %-10s %s" % ("domain", "action", "classification",
                                              "outcome", "reason"))
        for row in report.rows:
            print("%-11s %-18s %-14s %-10s %s" % (row.domain, row.action,
                                                  row.classification, row.outcome,
                                                  row.reason or "-"))
        print("status: %s  executed %d  refused %d  not_executed %d"
              % (report.status, report.count("executed"), report.count("refused"),
                 report.count("not_executed")))
    print("exchanges so far: %d" % report.exchange_count)


def main():
    provisioner = Provisioner(ports={"hr": 8101, "it": 8102, "facilities": 8103})
    try:
        provisioner.start()
    except ProvisionError as exc:
        print("provision failed: " + str(exc))
        return 1
    try:
        return _scenarios(provisioner)
    finally:
        provisioner.stop()
        print()
        print("all domains stopped")


def _scenarios(provisioner):
    clock = time.time
    registry = Registry(provisioner.ports, clock)
    registry.refresh_all()
    approver = Approver(provisioner.approval_secret, clock)
    gate = ApprovalGate(provisioner.approval_secret, clock,
                        provisioner.state_dir / "approvals")
    minter = TokenMinter(provisioner.exchange_secret, clock)

    def run(requests):
        plan = build_plan(registry, SUBJECT, requests)
        approval = approver.approve(plan)
        report = run_plan(plan, approval, gate=gate, minter=minter,
                          ports=provisioner.ports, subject=SUBJECT)
        return plan, approval, report

    _plan, _approval, clean = run(SUPPORTED_REQUESTS)
    print_report("scenario 1: clean run", clean)

    plan, approval, partial = run(SUPPORTED_REQUESTS + [WILL_NOT_REQUEST])
    print_report("scenario 2: grant_admin_access run", partial)
    for line in warnings(plan):
        print("warning: " + line)

    replay = run_plan(plan, approval, gate=gate, minter=minter,
                      ports=provisioner.ports, subject=SUBJECT)
    print_report("scenario 3: replay of the scenario 2 approval", replay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
