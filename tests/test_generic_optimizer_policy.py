"""Focused tests for generic timing classification and lane action policy."""

import json
import unittest

from src.analysis import DesignSignature
from src.parsers import parse_critical_hard_block_topology, parse_timing_anatomy_report
from src.policy import (
    BudgetState,
    EligibleAction,
    apply_action_cooldowns,
    gate_actions,
    should_attempt_reimplementation,
)


def signature(*, timing_anatomy_report=None, paths=None, primitive_cells=1000, avg_spread=45):
    return DesignSignature.from_reports(
        target_clock="clk_fpl26contest",
        clock_period_ns=2.0,
        wns_ns=-0.5,
        tns_ns=-2.0,
        failing_endpoints=3,
        high_fanout_report="",
        spread_report=json.dumps({
            "max_distance_found": 80,
            "avg_max_distance": avg_spread,
            "paths_analyzed": 4,
        }),
        analysis_duration_seconds=1.0,
        critical_paths_report=json.dumps(paths) if paths is not None else None,
        primitive_cell_count=primitive_cells,
        timing_anatomy_report=timing_anatomy_report,
    )


class GenericClassificationTests(unittest.TestCase):
    def test_timing_anatomy_detects_route_dominated_paths(self):
        anatomy = parse_timing_anatomy_report(
            "Data Path Delay: 2.0ns (logic 0.4ns (20.0%) route 1.6ns (80.0%))"
        )
        self.assertEqual(anatomy["paths_analyzed"], 1)
        self.assertTrue(anatomy["route_dominated"])

    def test_topology_requires_a_real_resource_boundary(self):
        topology = parse_critical_hard_block_topology(
            json.dumps([["top/DSP48E2/P", "top/logic_reg"], ["top/RAMB36E2/DO", "top/out"]])
        )
        self.assertEqual(topology["hard_block_paths"], 2)
        self.assertEqual(topology["boundary_transitions"], 2)

    def test_reimplementation_needs_anatomy_and_safe_budget(self):
        route_heavy = signature(
            timing_anatomy_report="logic 0.4ns (20.0%) route 1.6ns (80.0%)"
        )
        self.assertTrue(
            should_attempt_reimplementation(route_heavy, BudgetState(remaining_runtime_seconds=2000))
        )
        self.assertFalse(
            should_attempt_reimplementation(route_heavy, BudgetState(remaining_runtime_seconds=700))
        )

    def test_hard_block_recipe_needs_a_resource_boundary(self):
        no_boundary = signature(
            paths=[["top/DSP48E2/a", "top/DSP48E2/b"]], avg_spread=90
        )
        actions = gate_actions(
            no_boundary,
            budget=BudgetState(remaining_runtime_seconds=2000),
        )
        self.assertNotIn("HARD_BLOCK", {action.strategy for action in actions})


class LaneActionMemoryTests(unittest.TestCase):
    def test_inert_directive_is_removed_but_another_is_kept(self):
        actions = [
            EligibleAction(
                strategy="PHYS_OPT",
                default_args={"directive": "RuntimeOptimized"},
                allowed_args={"directive": ["RuntimeOptimized", "Explore"]},
            )
        ]
        filtered = apply_action_cooldowns(
            actions,
            [{"strategy": "PHYS_OPT", "args": {"directive": "RuntimeOptimized"}, "wns": -1.0, "delta_wns": 0.0}],
        )
        self.assertEqual(filtered[0].allowed_args["directive"], ["Explore"])
        self.assertEqual(filtered[0].default_args, {"directive": "Explore"})


if __name__ == "__main__":
    unittest.main()
