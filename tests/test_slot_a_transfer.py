"""Unit coverage for the deterministic Slot-A transfer."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.llm_optimizer import DCPOptimizer
from src.search import GenerationSearchConfig


class SlotATransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary_directory.name)
        self.optimizer = DCPOptimizer(
            api_key="test-key",
            run_dir=self.run_dir,
            generation_config=GenerationSearchConfig(
                wall_clock_limit_seconds=3600,
                validation_reserve_seconds=60,
            ),
            system_prompt="test planner prompt",
        )
        self.optimizer.start_time = time.time()

    async def asyncTearDown(self):
        self.temporary_directory.cleanup()

    async def test_publish_writes_only_a_checked_candidate_atomically(self):
        output = self.run_dir / "optimized.dcp"
        self.optimizer.output_dcp = output

        async def fake_v(name, arguments=None):
            arguments = arguments or {}
            if name == "run_tcl":
                command = arguments["command"]
                if "FPL26_PORT_COUNT" in command:
                    return "FPL26_PORT_COUNT=7"
                if "FPL26_HOLD_WNS" in command:
                    return "FPL26_HOLD_WNS=0.025"
                if "report_pulse_width" in command or "report_drc" in command:
                    return ""
            if name == "report_route_status":
                return (
                    "Number of Failed Nets = 0\n"
                    "Number of Unrouted Nets = 0\n"
                    "Number of Partially Routed Nets = 0\n"
                    "Number of Fully Routed Nets = 12\n"
                    "Number of Routable Nets = 12\n"
                )
            if name == "write_checkpoint":
                Path(arguments["dcp_path"]).write_bytes(b"accepted checkpoint")
                return "Wrote checkpoint"
            raise AssertionError(f"Unexpected Vivado call: {name}")

        self.optimizer.v = fake_v

        published = await self.optimizer._publish_current_candidate(
            {"wns": -0.12, "tns": -1.0, "failing_endpoints": 1},
            allow_equal=True,
        )

        self.assertTrue(published)
        self.assertEqual(output.read_bytes(), b"accepted checkpoint")
        self.assertFalse((self.run_dir / ".optimized.dcp.wip").exists())
        self.assertEqual(self.optimizer._published_wns, -0.12)

    async def test_publish_rejects_hold_violation_without_replacing_incumbent(self):
        output = self.run_dir / "optimized.dcp"
        output.write_bytes(b"existing incumbent")
        self.optimizer.output_dcp = output

        async def fake_v(name, arguments=None):
            arguments = arguments or {}
            if name == "run_tcl":
                command = arguments["command"]
                if "FPL26_PORT_COUNT" in command:
                    return "FPL26_PORT_COUNT=7"
                if "FPL26_HOLD_WNS" in command:
                    return "FPL26_HOLD_WNS=-0.010"
                if "report_pulse_width" in command or "report_drc" in command:
                    return ""
            if name == "report_route_status":
                return "Number of Failed Nets = 0\nNumber of Fully Routed Nets = 12\nNumber of Routable Nets = 12"
            raise AssertionError(f"Unexpected Vivado call: {name}")

        self.optimizer.v = fake_v

        published = await self.optimizer._publish_current_candidate(
            {"wns": -0.10, "tns": -1.0, "failing_endpoints": 1},
            allow_equal=True,
        )

        self.assertFalse(published)
        self.assertEqual(output.read_bytes(), b"existing incumbent")

    async def test_reimplementation_uses_explore_and_keeps_an_improved_result(self):
        baseline = self.run_dir / "baseline.dcp"
        baseline.write_bytes(b"baseline")
        calls = []

        async def fake_v(name, arguments=None):
            arguments = arguments or {}
            calls.append((name, arguments))
            if name == "report_timing_summary":
                return "timing report"
            if name == "run_tcl":
                command = arguments["command"]
                if "FPL26_REIMPL_CELLS" in command:
                    return "FPL26_REIMPL_CELLS=100,100"
                return ""
            if name in {"place_design", "phys_opt_design"}:
                return ""
            raise AssertionError(f"Unexpected Vivado call: {name}")

        self.optimizer.v = fake_v
        self.optimizer._measure_current_metrics = AsyncMock(
            side_effect=[
                {"wns": -0.30, "tns": -4.0, "failing_endpoints": 3},
                {"wns": -0.20, "tns": -3.0, "failing_endpoints": 2},
            ]
        )

        result = await self.optimizer.run_reimplementation_flow(baseline)

        self.assertEqual(result, "timing report")
        commands = [arguments["command"] for name, arguments in calls if name == "run_tcl"]
        self.assertTrue(any("opt_design -directive Explore" in command for command in commands))
        self.assertTrue(any("route_design -directive Explore -tns_cleanup" in command for command in commands))
        self.assertIn(
            ("place_design", {"directive": "Explore", "timeout": 3600}),
            calls,
        )


if __name__ == "__main__":
    unittest.main()
