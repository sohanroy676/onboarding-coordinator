"""Demo: run every scenario against real domain processes and print the traces.

Run from the project root with: python demo.py

Starts the three domains on the demo ports (8101 HR, 8102 IT, 8103
Facilities), runs four scenarios, then stops them. Every status and count
printed here comes from the run itself. Save the output as a trace only
from a real run.

    1. clean run: six supported actions, expect success
    2. grant_admin_access run: the same six plus one will_not action, expect partial
    3. replay of the approval from scenario 2, expect aborted
    4. five clean runs on a fresh minter: coordination multiple from the real
       counter, expect 3.0; then the scenario 1 run rebuilt from the ledgers

The coordinator process holds the exchange and approval secrets in memory
only (provision.py). The domains never see either secret.
"""

import sys
import time

from coordinator.approval import ApprovalGate, Approver
from coordinator.planner import build_plan, warnings
from coordinator.registry import Registry
from coordinator.run import coordination_multiple, run_plan
from coordinator.tokens import TokenMinter
from ledger.reconstruct import format_rebuild, reconstruct
from provision import Provisioner, ProvisionError

SUBJECT = "new.hire@example.test"
FIVE_RUNS = 5
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

    _scenario_cost(provisioner, registry, approver, gate, clock, clean.run_id)
    return 0


def _scenario_cost(provisioner, registry, approver, gate, clock, clean_run_id):
    print()
    print("== scenario 4: five clean runs, coordination multiple")
    minter = TokenMinter(provisioner.exchange_secret, clock)
    for number in range(FIVE_RUNS):
        plan = build_plan(registry, SUBJECT, SUPPORTED_REQUESTS)
        approval = approver.approve(plan)
        report = run_plan(plan, approval, gate=gate, minter=minter,
                          ports=provisioner.ports, subject=SUBJECT)
        print("run %d: run id %s  status %s  exchanges so far %d"
              % (number + 1, report.run_id, report.status, report.exchange_count))
    print("coordination multiple: %.1f  (%d exchanges / %d runs / 1 monolith authorization)"
          % (coordination_multiple(minter.exchange_count, FIVE_RUNS),
             minter.exchange_count, FIVE_RUNS))
    print()
    print("== scenario 1 rebuilt from the domain ledgers")
    for line in format_rebuild(reconstruct(clean_run_id, provisioner.state_dir)):
        print(line)


if __name__ == "__main__":
    sys.exit(main())
