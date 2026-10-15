"""Unit tests for coordination_multiple in coordinator/run.py."""

import unittest

from coordinator.run import MONOLITH_AUTHORIZATIONS_PER_RUN, coordination_multiple


class CoordinationMultiple(unittest.TestCase):
    def test_three_exchanges_per_run_gives_three(self):
        self.assertEqual(coordination_multiple(15, 5), 3.0)

    def test_monolith_authorizes_once_per_run(self):
        self.assertEqual(MONOLITH_AUTHORIZATIONS_PER_RUN, 1)

    def test_one_run_with_three_exchanges_gives_three(self):
        self.assertEqual(coordination_multiple(3, 1), 3.0)

    def test_zero_runs_is_refused(self):
        with self.assertRaises(ValueError):
            coordination_multiple(0, 0)

    def test_fewer_exchanges_than_expected_gives_a_smaller_multiple(self):
        self.assertLess(coordination_multiple(12, 5), 3.0)
