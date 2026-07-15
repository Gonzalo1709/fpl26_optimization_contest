import json
import tempfile
import unittest
from pathlib import Path

from src.analysis import DesignSignature, require_target_clock_wns
from src.base import DCPOptimizerBase
from src.llm_optimizer import DCPOptimizer
from src.parsers import (
    parse_high_fanout_nets_report,
    parse_critical_hard_block_types,
    parse_congestion_report,
    parse_spread_analysis,
    parse_target_clock_report,
    spread_recommends_pblock,
)


class AnalysisParserTests(unittest.TestCase):
    def test_parses_explicit_contest_clock(self):
        clock_name, period_ns = parse_target_clock_report(
            "CLOCK:clk_fpl26contest\n1.570\n"
        )

        self.assertEqual(clock_name, "clk_fpl26contest")
        self.assertEqual(period_ns, 1.570)

    def test_parses_high_fanout_rows(self):
        report = """
Paths Fanout Parent Net Name
----- ------ ---------------
7 240 top/control/reset_reg
3 125 top/pipeline/enable_reg
=== End ===
"""

        self.assertEqual(
            parse_high_fanout_nets_report(report),
            [
                ("top/control/reset_reg", 240, 7),
                ("top/pipeline/enable_reg", 125, 3),
            ],
        )

    def test_spread_recommendation_requires_strong_average_and_multiple_paths(self):
        strong = parse_spread_analysis(
            json.dumps(
                {
                    "max_distance_found": 120,
                    "avg_max_distance": 75.5,
                    "paths_analyzed": 12,
                }
            )
        )
        local = parse_spread_analysis(
            json.dumps(
                {
                    "max_distance_found": 93,
                    "avg_max_distance": 53.5,
                    "paths_analyzed": 50,
                }
            )
        )

        self.assertTrue(spread_recommends_pblock(strong))
        self.assertFalse(spread_recommends_pblock(local))

    def test_missing_reports_produce_serializable_unknowns(self):
        self.assertEqual(parse_target_clock_report("ERROR: unavailable"), (None, None))
        self.assertEqual(parse_high_fanout_nets_report(""), [])
        self.assertIsNone(parse_spread_analysis("not-json"))

        signature = DesignSignature.from_reports(
            target_clock="clk_fpl26contest",
            clock_period_ns=2.0,
            wns_ns=-0.5,
            tns_ns=None,
            failing_endpoints=None,
            high_fanout_report="",
            spread_report=None,
            analysis_duration_seconds=1.25,
        )
        payload = signature.to_dict()

        self.assertEqual(payload["target_clock"], "clk_fpl26contest")
        self.assertEqual(payload["fmax_mhz"], 400.0)
        self.assertEqual(payload["high_fanout_candidates"], [])
        self.assertIsNone(payload["path_spread"])
        self.assertIn("path_spread", payload["unavailable"])

    def test_detects_hard_blocks_and_severe_congestion(self):
        critical_paths = json.dumps(
            [
                ["top/dsp48_mult/P", "top/logic_reg"],
                ["cache/data/RAMB36E2", "top/logic_reg"],
                ["memory/URAM288_inst/DOUT", "top/out_reg"],
            ]
        )

        self.assertEqual(
            parse_critical_hard_block_types(critical_paths),
            ("BRAM", "DSP", "URAM"),
        )
        self.assertEqual(
            parse_congestion_report(
                "Global Horizontal Congestion: 6\nGlobal Vertical Congestion: 4"
            ),
            {"max_level": 6, "severe": True},
        )

        signature = DesignSignature.from_reports(
            target_clock="clk_fpl26contest",
            clock_period_ns=2.0,
            wns_ns=-0.5,
            tns_ns=-2.0,
            failing_endpoints=4,
            high_fanout_report="",
            spread_report=None,
            analysis_duration_seconds=1.0,
            critical_paths_report=critical_paths,
            congestion_report="Global Horizontal Congestion: 6",
        ).to_dict()

        self.assertEqual(signature["critical_hard_block_types"], ["BRAM", "DSP", "URAM"])
        self.assertEqual(signature["congestion"], {"max_level": 6, "severe": True})

    def test_token_report_contains_design_signature(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.target_clock = "clk_fpl26contest"
            optimizer.clock_period = 2.0
            optimizer.initial_wns = -0.5
            optimizer.best_wns = -0.5
            optimizer.start_time = 100.0
            optimizer.end_time = 101.0
            optimizer.design_signature = DesignSignature.from_reports(
                target_clock="clk_fpl26contest",
                clock_period_ns=2.0,
                wns_ns=-0.5,
                tns_ns=-2.0,
                failing_endpoints=4,
                high_fanout_report="",
                spread_report=None,
                analysis_duration_seconds=0.75,
            )
            report_path = Path(temporary_directory) / "token_usage.json"

            optimizer.save_token_usage_report(report_path)
            report = json.loads(report_path.read_text())

            self.assertEqual(
                report["design_signature"]["target_clock"],
                "clk_fpl26contest",
            )
            self.assertEqual(
                report["design_signature"]["analysis_duration_seconds"],
                0.75,
            )


class TargetClockCollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_contest_clock_wns_is_fatal(self):
        self.assertEqual(require_target_clock_wns(-0.5), -0.5)
        with self.assertRaisesRegex(RuntimeError, "clk_fpl26contest"):
            require_target_clock_wns(None)

    async def test_clock_collection_never_falls_back_to_another_clock(self):
        commands = []

        async def call_tool(_name, arguments):
            commands.append(arguments["command"])
            return "ERROR: clk_fpl26contest unavailable"

        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizerBase(run_dir=Path(temporary_directory))
            period = await optimizer.get_clock_period(call_tool)

        self.assertIsNone(period)
        self.assertEqual(len(commands), 1)
        self.assertIn("clk_fpl26contest", commands[0])
        self.assertNotIn("ENDPOINT_CLOCK", commands[0])

    async def test_wns_collection_never_uses_overall_timing_fallback(self):
        commands = []

        async def call_tool(_name, arguments):
            commands.append(arguments["command"])
            return "ERROR: clk_fpl26contest unavailable"

        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizerBase(run_dir=Path(temporary_directory))
            wns = await optimizer.get_wns_for_target_clock(call_tool)

        self.assertIsNone(wns)
        self.assertEqual(len(commands), 1)
        self.assertIn("clk_fpl26contest", commands[0])
        self.assertNotIn("slack_lesser_than", commands[0])


if __name__ == "__main__":
    unittest.main()
