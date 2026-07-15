import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from RapidWrightMCP.rapidwright_tools import _move_within_radius
from src.llm_optimizer import DCPOptimizer
from src.policy import rank_fanout_candidates


class FanoutSelectionTests(unittest.TestCase):
    def test_shared_target_clock_paths_beat_merely_large_fanout(self):
        ranked = rank_fanout_candidates(
            [
                {
                    "net_name": "top/huge_but_sparse",
                    "fanout": 5000,
                    "critical_path_count": 1,
                    "is_clock": False,
                    "sink_span": 20,
                },
                {
                    "net_name": "top/shared_control",
                    "fanout": 500,
                    "critical_path_count": 18,
                    "is_clock": False,
                    "sink_span": 120,
                },
            ]
        )

        self.assertEqual(ranked[0]["net_name"], "top/shared_control")

    def test_clock_and_blacklisted_nets_are_rejected(self):
        ranked = rank_fanout_candidates(
            [
                {
                    "net_name": "top/clk_buf",
                    "fanout": 4000,
                    "critical_path_count": 30,
                    "is_clock": True,
                    "sink_span": 200,
                },
                {
                    "net_name": "top/rejected",
                    "fanout": 1000,
                    "critical_path_count": 20,
                    "is_clock": False,
                    "sink_span": 100,
                },
                {
                    "net_name": "top/eligible",
                    "fanout": 300,
                    "critical_path_count": 10,
                    "is_clock": False,
                    "sink_span": 80,
                },
            ],
            blacklist={"top/rejected"},
        )

        self.assertEqual([item["net_name"] for item in ranked], ["top/eligible"])


class CellRelocationRadiusTests(unittest.TestCase):
    def test_rejects_move_beyond_configured_local_radius(self):
        self.assertTrue(_move_within_radius(18, 30))
        self.assertTrue(_move_within_radius(30, 30))
        self.assertFalse(_move_within_radius(31, 30))


class CellRelocationRollbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_negative_target_clock_delta_restores_saved_baseline(self):
        detour_payload = json.dumps(
            {
                "candidates": [
                    {"path": 1, "cell": "top/candidate", "max_detour_ratio": 3.0}
                ]
            }
        )
        relocation_payload = json.dumps(
            {
                "status": "success",
                "results": [
                    {
                        "cell": "top/candidate",
                        "status": "success",
                        "message": "Moved locally",
                    }
                ],
            }
        )
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
                    "pins extracted",
                    "opened candidate",
                    "restored baseline",
                ]
            )
            optimizer.rw = AsyncMock(
                side_effect=[detour_payload, relocation_payload, "wrote candidate"]
            )
            optimizer._measure_current_metrics = AsyncMock(
                side_effect=[
                    {"wns": -0.2, "tns": -2.0, "failing_endpoints": 4},
                    {"wns": -0.3, "tns": -3.0, "failing_endpoints": 5},
                ]
            )
            optimizer._reroute_and_measure = AsyncMock(
                return_value=("regressed report", -0.3)
            )

            report = await optimizer.run_cell_relocation_flow(
                max_cells=1,
                max_move_distance=30,
            )

        self.assertEqual(report, "baseline report")
        placement_call = optimizer.rw.await_args_list[1]
        self.assertEqual(placement_call.args[1]["max_move_distance"], 30)
        self.assertEqual(optimizer.v.await_args_list[-1].args[0], "open_checkpoint")


if __name__ == "__main__":
    unittest.main()
