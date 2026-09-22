"""Offline regressions for exploration policy; no FPGA tools are required.

Authored with the integration. Execute in the authorized test environment.
"""

import unittest
from types import SimpleNamespace

from src.pact_search import EnablingPool, diverse_beam
from src.scoring import ValidationStatus


def candidate(name, wns=-1., spread=100, fanout=500):
    return SimpleNamespace(checkpoint_sha256=name, wns=wns,
                           validation=ValidationStatus(par_routed=True, par_drc_clean=True,
                                                       hold_passed=True, pulse_width_passed=True),
                           evidence={"path_spread": {"avg_distance": spread},
                                     "congestion": {"max_level": 4},
                                     "high_fanout_candidates": [{"fanout": fanout}]})


class EnablingPolicyTests(unittest.TestCase):
    def test_neutral_timing_requires_physical_evidence(self):
        pool = EnablingPool()
        root = candidate("root")
        self.assertFalse(pool.retain(root, candidate("inert"), "PATH_LOCAL_REPLACE", 0))
        self.assertTrue(pool.retain(root, candidate("useful", spread=70), "PATH_LOCAL_REPLACE", 0))
        move = pool.take(1)[0]
        self.assertEqual(move.followup, "CRITICAL_NET_REROUTE")
        self.assertEqual(pool.take(2), [])

    def test_bad_timing_and_expired_candidates_are_excluded(self):
        pool = EnablingPool(lifetime=10)
        self.assertFalse(pool.retain(candidate("a"), candidate("b", wns=-2, spread=40), "PATH_LOCAL_REPLACE", 0))
        self.assertTrue(pool.retain(candidate("a"), candidate("c", spread=40), "PATH_LOCAL_REPLACE", 0))
        self.assertEqual(pool.take(10), [])

    def test_diversity_preserves_best_and_a_different_physical_state(self):
        best = candidate("best", wns=-.5)
        similar = candidate("similar", wns=-.6, spread=99)
        different = candidate("different", wns=-.7, spread=30)
        selected = diverse_beam([best, similar, different], 2, lambda c: c.wns)
        self.assertEqual([c.checkpoint_sha256 for c in selected], ["best", "different"])

    def test_missing_evidence_does_not_create_an_enabling_move(self):
        child = candidate("child")
        child.evidence = None
        self.assertFalse(EnablingPool().retain(candidate("root"), child, "PATH_LOCAL_REPLACE", 0))


if __name__ == "__main__":
    unittest.main()
