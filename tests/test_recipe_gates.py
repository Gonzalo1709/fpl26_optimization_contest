import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.analysis import DesignSignature
from src.llm_optimizer import DCPOptimizer
from src.parsers import parse_critical_route_net_report
from src.policy import (
    BudgetState,
    gate_actions,
    select_route_preserve_nets,
    validate_route_net_set,
)


def make_signature(*, congestion: str | None = None) -> DesignSignature:
    return DesignSignature.from_reports(
        target_clock="clk_fpl26contest",
        clock_period_ns=1.57,
        wns_ns=-1.0,
        tns_ns=-100.0,
        failing_endpoints=100,
        high_fanout_report="",
        spread_report=json.dumps(
            {
                "max_distance_found": 93,
                "avg_max_distance": 53.5,
                "paths_analyzed": 50,
            }
        ),
        analysis_duration_seconds=1.0,
        congestion_report=congestion,
    )


class PreservedRouteGateTests(unittest.TestCase):
    def test_timing_report_collects_delay_and_shared_path_evidence(self):
        report = """
Slack (VIOLATED)
  net (fo=2, routed) 0.340 0.500 top/shared_net
  net (fo=1, routed) 0.120 0.620 top/other_net
Slack (VIOLATED)
  net (fo=2, routed) 0.410 0.700 top/shared_net
"""

        candidates = parse_critical_route_net_report(report)

        self.assertEqual(candidates[0]["net_name"], "top/shared_net")
        self.assertEqual(candidates[0]["critical_path_count"], 2)
        self.assertEqual(candidates[0]["net_delay_ns"], 0.410)

    def test_locked_and_noncritical_nets_are_rejected(self):
        selected = select_route_preserve_nets(
            [
                {
                    "net_name": "top/locked",
                    "critical_path_count": 5,
                    "net_delay_ns": 0.8,
                    "is_route_fixed": True,
                },
                {
                    "net_name": "top/not_on_target_path",
                    "critical_path_count": 0,
                    "net_delay_ns": 2.0,
                    "is_route_fixed": False,
                },
                {
                    "net_name": "top/eligible",
                    "critical_path_count": 3,
                    "net_delay_ns": 0.4,
                    "is_route_fixed": False,
                },
            ],
            max_nets=4,
        )

        self.assertEqual(selected, ("top/eligible",))

    def test_reroute_set_above_hard_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at most 8"):
            validate_route_net_set([f"top/net_{index}" for index in range(9)])

    def test_route_preserve_requires_congestion_evidence(self):
        no_congestion = {
            action.strategy for action in gate_actions(make_signature())
        }
        severe_congestion = {
            action.strategy
            for action in gate_actions(
                make_signature(congestion="Global Horizontal Congestion: 6"),
                budget=BudgetState(remaining_runtime_seconds=1200),
            )
        }

        self.assertNotIn("ROUTE_PRESERVE", no_congestion)
        self.assertIn("ROUTE_PRESERVE", severe_congestion)


class PreservedRouteExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_critical_pin_action_exposes_only_pin_swapping(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.v = AsyncMock(
                side_effect=[
                    "saved baseline",
                    "baseline report",
                    "pin optimization complete",
                    "improved report",
                ]
            )
            optimizer._measure_current_metrics = AsyncMock(
                side_effect=[
                    {"wns": -0.3, "tns": -3.0, "failing_endpoints": 5},
                    {"wns": -0.2, "tns": -2.0, "failing_endpoints": 4},
                ]
            )

            report = await optimizer.run_critical_pin_flow()

        self.assertEqual(report, "improved report")
        phys_opt_call = optimizer.v.await_args_list[2]
        self.assertEqual(phys_opt_call.args, ("phys_opt_design", {"critical_pin_opt": True}))

    async def test_non_improving_route_restores_saved_baseline(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.v = AsyncMock(
                side_effect=[
                    "saved baseline",
                    "baseline report",
                    json.dumps(
                        [
                            {
                                "net_name": "top/critical_net",
                                "critical_path_count": 3,
                                "net_delay_ns": 0.5,
                                "is_route_fixed": False,
                            }
                        ]
                    ),
                    "selected nets routed",
                    "remaining routes preserved",
                    "regressed report",
                    "restored baseline",
                ]
            )
            optimizer._measure_current_metrics = AsyncMock(
                side_effect=[
                    {"wns": -0.2, "tns": -2.0, "failing_endpoints": 4},
                    {"wns": -0.3, "tns": -3.0, "failing_endpoints": 5},
                ]
            )

            report = await optimizer.run_route_preserve_flow(max_nets=4)

        self.assertEqual(report, "baseline report")
        route_call = optimizer.v.await_args_list[3]
        self.assertEqual(route_call.args[0], "route_design")
        self.assertEqual(route_call.args[1]["nets"], ["top/critical_net"])
        self.assertTrue(route_call.args[1]["auto_delay"])
        self.assertEqual(optimizer.v.await_args_list[-1].args[0], "open_checkpoint")


if __name__ == "__main__":
    unittest.main()
