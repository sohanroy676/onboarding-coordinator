"""Unit tests for ledger/reconstruct.py: counting rules, chain checks, read-only.

Ledgers are written with the real Ledger class on an injected clock, in a
temporary state folder. Nothing here starts a server or sleeps.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ledger.ledger import Ledger
from ledger.reconstruct import LIMITS, format_rebuild, main, reconstruct
from tests.helpers import FakeClock

RUN = "unit-run-1"


class StateFolder(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)
        self.clock = FakeClock()

    def write(self, domain, run_id, event, jti=None, action=None, **extra):
        ledger = Ledger(self.state / domain / "ledger.jsonl", self.clock)
        data = dict(extra)
        if jti is not None:
            data["jti"] = jti
        if action is not None:
            data["action"] = action
        ledger.append(run_id, event, data)
        self.clock.advance(1)

    def ledger_path(self, domain):
        return self.state / domain / "ledger.jsonl"


class CountingRules(StateFolder):
    def test_each_executed_action_is_counted_once(self):
        self.write("hr", RUN, "action_executed", jti="j1", action="create_record")
        self.write("hr", RUN, "action_executed", jti="j1", action="enroll_benefits")
        result = reconstruct(RUN, self.state)
        hr = result.domains[0]
        self.assertEqual(hr.outcomes["executed"], 2)
        self.assertTrue(result.chain_ok)

    def test_executed_then_failed_for_the_same_action_counts_once_as_failed(self):
        self.write("it", RUN, "action_executed", jti="j2", action="create_account")
        self.write("it", RUN, "action_failed", jti="j2", action="create_account",
                   reason="handler_error")
        it = reconstruct(RUN, self.state).domains[1]
        self.assertEqual(it.outcomes["failed"], 1)
        self.assertEqual(it.outcomes["executed"], 0)

    def test_refused_actions_are_counted_as_refused(self):
        self.write("it", RUN, "action_refused", jti="j3", action="grant_admin_access",
                   reason="will_not")
        it = reconstruct(RUN, self.state).domains[1]
        self.assertEqual(it.outcomes["refused"], 1)
        self.assertEqual(it.outcomes["executed"], 0)

    def test_token_rejected_is_counted_apart_from_actions(self):
        self.write("facilities", RUN, "token_rejected", reason="domain_mismatch")
        facilities = reconstruct(RUN, self.state).domains[2]
        self.assertEqual(facilities.rejected, 1)
        self.assertEqual(sum(facilities.outcomes.values()), 0)

    def test_other_run_ids_are_ignored(self):
        self.write("hr", "other-run", "action_executed", jti="j4", action="create_record")
        self.write("hr", RUN, "action_executed", jti="j5", action="create_record")
        hr = reconstruct(RUN, self.state).domains[0]
        self.assertEqual(hr.outcomes["executed"], 1)

    def test_unknown_run_id_gives_zero_counts_and_a_valid_chain(self):
        self.write("hr", RUN, "action_executed", jti="j6", action="create_record")
        result = reconstruct("no-such-run", self.state)
        self.assertTrue(result.chain_ok)
        self.assertEqual(sum(sum(d.outcomes.values()) for d in result.domains), 0)
        lines = format_rebuild(result)
        self.assertIn("no ledger lines carry this run id", lines)

    def test_missing_state_folder_gives_zero_counts_and_creates_nothing(self):
        missing = self.state / "does-not-exist"
        result = reconstruct(RUN, missing)
        self.assertTrue(result.chain_ok)
        self.assertFalse(missing.exists())


class ChainChecks(StateFolder):
    def test_tampered_line_breaks_only_that_domain(self):
        self.write("hr", RUN, "action_executed", jti="j7", action="create_record")
        self.write("it", RUN, "action_executed", jti="j8", action="create_account")
        path = self.ledger_path("hr")
        path.write_text(path.read_text(encoding="ascii").replace(
            '"action_executed"', '"action_refused"'), encoding="ascii")
        result = reconstruct(RUN, self.state)
        hr, it = result.domains[0], result.domains[1]
        self.assertFalse(hr.chain_ok)
        self.assertIn("chain broken at entry 0", hr.chain_error)
        self.assertEqual(sum(hr.outcomes.values()), 0)
        self.assertTrue(it.chain_ok)
        self.assertEqual(it.outcomes["executed"], 1)
        self.assertFalse(result.chain_ok)

    def test_truncated_last_line_is_reported_not_counted(self):
        self.write("hr", RUN, "action_executed", jti="j9", action="create_record")
        path = self.ledger_path("hr")
        raw = path.read_bytes()
        path.write_bytes(raw[:-1])
        hr = reconstruct(RUN, self.state).domains[0]
        self.assertFalse(hr.chain_ok)
        self.assertIn("truncated", hr.chain_error)

    def test_reconstruct_never_changes_a_ledger_file(self):
        self.write("hr", RUN, "action_executed", jti="j10", action="create_record")
        path = self.ledger_path("hr")
        before = path.read_bytes()
        reconstruct(RUN, self.state)
        self.assertEqual(path.read_bytes(), before)


class Output(StateFolder):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([*args, "--state-dir", str(self.state)])
        return code, out.getvalue()

    def test_limits_are_printed_with_every_rebuild(self):
        code, text = self.run_main(RUN)
        self.assertEqual(code, 0)
        for limit in LIMITS:
            self.assertIn(limit, text)

    def test_broken_chain_gives_exit_code_one_and_says_not_verified(self):
        self.write("hr", RUN, "action_executed", jti="j11", action="create_record")
        path = self.ledger_path("hr")
        path.write_text(path.read_text(encoding="ascii").replace("create_record", "x"),
                        encoding="ascii")
        code, text = self.run_main(RUN)
        self.assertEqual(code, 1)
        self.assertIn("not verified", text)

    def test_output_is_ascii_only(self):
        self.write("hr", RUN, "action_executed", jti="j12", action="create_record")
        _, text = self.run_main(RUN)
        text.encode("ascii")
