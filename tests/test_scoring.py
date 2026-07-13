import json
import tempfile
import unittest
from pathlib import Path

from src.scoring import (
    ContestScoreInput,
    ValidationStatus,
    calculate_contest_score,
    target_clock_fmax_mhz,
)
from src.llm_optimizer import DCPOptimizer


class ContestScoringTests(unittest.TestCase):
    def test_zero_fmax_delta_scores_zero(self):
        result = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=0.0,
                llm_cost_usd=0.25,
                runtime_seconds=1200.0,
            )
        )

        self.assertEqual(result.projected_score, 0.0)

    def test_official_example_includes_cost_and_runtime_penalties(self):
        result = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=50.0,
                llm_cost_usd=0.25,
                runtime_seconds=1200.0,
            )
        )

        self.assertAlmostEqual(result.runtime_hours, 1.0 / 3.0)
        self.assertAlmostEqual(result.penalty_multiplier, 0.9416666666666667)
        self.assertAlmostEqual(result.projected_score, 47.083333333333336)

    def test_negative_raw_score_is_clamped_to_zero(self):
        result = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=10.0,
                llm_cost_usd=20.0,
                runtime_seconds=3600.0,
            )
        )

        self.assertLess(result.penalty_multiplier, 0.0)
        self.assertEqual(result.projected_score, 0.0)

    def test_target_clock_fmax_uses_period_minus_wns(self):
        self.assertAlmostEqual(
            target_clock_fmax_mhz(period_ns=2.0, wns_ns=-0.5),
            400.0,
        )

    def test_incomplete_validation_keeps_validated_score_unknown(self):
        result = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=5.0,
                llm_cost_usd=0.0,
                runtime_seconds=0.0,
            )
        )

        self.assertFalse(result.validation.complete)
        self.assertIsNone(result.validated_score)

    def test_failed_validation_forces_validated_score_to_zero(self):
        result = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=5.0,
                llm_cost_usd=0.0,
                runtime_seconds=0.0,
                validation=ValidationStatus(
                    par_routed=True,
                    par_drc_clean=True,
                    hold_passed=False,
                    pulse_width_passed=True,
                    structural_passed=True,
                    simulation_passed=True,
                ),
            )
        )

        self.assertTrue(result.validation.complete)
        self.assertFalse(result.validation.passed)
        self.assertEqual(result.validated_score, 0.0)

    def test_token_report_contains_projected_score_and_validation_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.target_clock = "clk_fpl26contest"
            optimizer.clock_period = 2.0
            optimizer.initial_wns = -0.5
            optimizer.best_wns = -0.25
            optimizer.start_time = 100.0
            optimizer.end_time = 1300.0
            optimizer.total_cost = 0.25
            report_path = Path(temporary_directory) / "token_usage.json"

            optimizer.save_token_usage_report(report_path)
            summary = json.loads(report_path.read_text())["summary"]

            self.assertEqual(summary["target_clock"], "clk_fpl26contest")
            self.assertAlmostEqual(
                summary["projected_contest_score"],
                (444.44444444444446 - 400.0) * 0.9416666666666667,
            )
            self.assertIsNone(summary["validated_contest_score"])
            self.assertEqual(
                summary["validation"],
                {
                    "par_routed": None,
                    "par_drc_clean": None,
                    "hold_passed": None,
                    "pulse_width_passed": None,
                    "structural_passed": None,
                    "simulation_passed": None,
                    "complete": False,
                    "passed": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
