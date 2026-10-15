"""Live tests for app/onboarding.py: real domain processes on port 0.

The three domains are child processes started by provision.Provisioner with
EPHEMERAL ports and a temporary state folder. The clock is time.time because
the child processes read real time for token expiry; the approval and the
minter use the same clock, so the two agree. Nothing sleeps.
"""

import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path

from app.onboarding import EXIT_NOT_APPROVED, EXIT_NOT_SUCCESS, EXIT_SUCCESS, run_onboarding
from coordinator.run import new_run_id
from ledger.reconstruct import LEDGER_NAME, reconstruct

EPHEMERAL = {"hr": 0, "it": 0, "facilities": 0}
DOMAINS = ("hr", "it", "facilities")


class LiveOnboarding(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_dir = Path(tmp.name)

    def run_flow(self, answer, request_texts=None, run_id=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_onboarding(
                "new.hire@example.test", request_texts,
                ask=lambda prompt: answer, clock=time.time,
                ports=EPHEMERAL, state_dir=self.state_dir,
                run_id=run_id or new_run_id())
        return code, out.getvalue()

    def ledger_lines_for(self, run_id):
        """Return {domain: count} of ledger lines that carry this run id."""
        counts = {}
        for domain in DOMAINS:
            path = self.state_dir / domain / LEDGER_NAME
            if not path.exists():
                counts[domain] = 0
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            counts[domain] = sum(1 for line in lines if run_id in line)
        return counts

    def markers(self):
        folder = self.state_dir / "approvals"
        return sorted(folder.glob("*.consumed")) if folder.exists() else []


class ApprovedRun(LiveOnboarding):
    def test_approved_default_run_writes_six_ledger_lines(self):
        run_id = new_run_id()
        code, out = self.run_flow("y", run_id=run_id)
        self.assertEqual(code, EXIT_SUCCESS, out)
        self.assertIn("status: success  executed 6  refused 0  not_executed 0", out)
        self.assertEqual(self.ledger_lines_for(run_id),
                         {"hr": 2, "it": 2, "facilities": 2})
        self.assertEqual(len(self.markers()), 1)

    def test_the_approved_run_rebuilds_from_the_ledgers(self):
        run_id = new_run_id()
        self.run_flow("y", run_id=run_id)
        rebuild = reconstruct(run_id, self.state_dir)
        self.assertTrue(rebuild.chain_ok)
        self.assertEqual(sum(d.outcomes["executed"] for d in rebuild.domains), 6)
        self.assertEqual(sum(d.outcomes["refused"] for d in rebuild.domains), 0)


class DeclinedRun(LiveOnboarding):
    def test_declined_run_writes_no_ledger_line_and_no_marker(self):
        run_id = new_run_id()
        code, out = self.run_flow("n", run_id=run_id)
        self.assertEqual(code, EXIT_NOT_APPROVED, out)
        self.assertEqual(self.ledger_lines_for(run_id),
                         {"hr": 0, "it": 0, "facilities": 0})
        self.assertEqual(self.markers(), [])
        self.assertIn("not approved", out)


class PartialRun(LiveOnboarding):
    def test_will_not_request_gives_partial_with_one_refusal_in_it(self):
        run_id = new_run_id()
        requests = [
            "hr:create_record", "hr:enroll_benefits",
            "it:create_account", "it:assign_laptop", "it:grant_admin_access",
            "facilities:issue_badge", "facilities:assign_desk",
        ]
        code, out = self.run_flow("y", request_texts=requests, run_id=run_id)
        self.assertEqual(code, EXIT_NOT_SUCCESS, out)
        self.assertIn("status: partial  executed 6  refused 1  not_executed 0", out)
        self.assertIn("warning: it: grant_admin_access is on the domain's will_not list",
                      out)
        rebuild = reconstruct(run_id, self.state_dir)
        it = next(d for d in rebuild.domains if d.domain == "it")
        self.assertEqual(it.outcomes["refused"], 1)
        self.assertEqual(it.outcomes["executed"], 2)
        refused_lines = [line for line in
                         (self.state_dir / "it" / LEDGER_NAME).read_text(
                             encoding="utf-8").splitlines()
                         if run_id in line and "grant_admin_access" in line]
        self.assertEqual(len(refused_lines), 1)


if __name__ == "__main__":
    unittest.main()
