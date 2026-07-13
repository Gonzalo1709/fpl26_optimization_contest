import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.analysis import DesignSignature
from src.llm_optimizer import DCPOptimizer
from src.policy import BudgetState, plan_phys_opt_portfolio
from src.scoring import ValidationStatus


def complete_validation(value: bool) -> ValidationStatus:
    return ValidationStatus(
        par_routed=value,
        par_drc_clean=value,
        hold_passed=value,
        pulse_width_passed=value,
        structural_passed=value,
        simulation_passed=value,
    )


class PhysOptPortfolioPolicyTests(unittest.TestCase):
    def test_orders_attempts_from_low_to_high_risk_after_measured_gain(self):
        attempts = plan_phys_opt_portfolio(
            BudgetState(remaining_runtime_seconds=1800.0),
            history=[{"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2}],
            validation=complete_validation(True),
        )

        self.assertEqual(
            [attempt.name for attempt in attempts],
            [
                "RuntimeOptimized",
                "CriticalPin",
                "PlacementRouting",
                "Explore",
                "AggressiveExplore",
            ],
        )

    def test_skips_escalation_without_gain_or_clean_hold_pulse(self):
        without_gain = plan_phys_opt_portfolio(
            BudgetState(remaining_runtime_seconds=1800.0),
            history=[{"strategy": "PHYS_OPT", "delta_vs_peak": 0.0}],
            validation=complete_validation(True),
        )
        unknown_signoff = plan_phys_opt_portfolio(
            BudgetState(remaining_runtime_seconds=1800.0),
            history=[{"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2}],
            validation=ValidationStatus(),
        )

        self.assertEqual([attempt.name for attempt in without_gain], ["RuntimeOptimized"])
        self.assertNotIn("AggressiveExplore", [attempt.name for attempt in unknown_signoff])

        failed_signoff = plan_phys_opt_portfolio(
            BudgetState(remaining_runtime_seconds=1800.0),
            history=[{"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2}],
            validation=complete_validation(False),
        )
        self.assertEqual([attempt.name for attempt in failed_signoff], ["RuntimeOptimized"])

    def test_low_runtime_keeps_only_runtime_optimized(self):
        attempts = plan_phys_opt_portfolio(
            BudgetState(remaining_runtime_seconds=850.0),
            history=[{"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2}],
            validation=complete_validation(True),
        )

        self.assertEqual([attempt.name for attempt in attempts], ["RuntimeOptimized"])

    def test_planner_schema_and_sanitizer_share_the_gated_modes(self):
        signature = DesignSignature.from_reports(
            target_clock="clk_fpl26contest",
            clock_period_ns=1.57,
            wns_ns=-1.0,
            tns_ns=-10.0,
            failing_endpoints=10,
            high_fanout_report="",
            spread_report=None,
            analysis_duration_seconds=1.0,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.design_signature = signature
            optimizer.history.append(
                {"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2}
            )

            decision_input = optimizer._build_decision_input("analysis", 0, [])
            strategy, args = optimizer.sanitize_action(
                {"strategy": "PHYS_OPT", "args": {"directive": "AggressiveExplore"}}
            )

        self.assertEqual(
            decision_input["available_strategies"]["PHYS_OPT"]["directive"],
            ["RuntimeOptimized", "CriticalPin", "PlacementRouting", "Explore"],
        )
        self.assertEqual(strategy, "PHYS_OPT")
        self.assertEqual(args, {"directive": "RuntimeOptimized"})


class PhysOptPortfolioExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_negative_target_clock_delta_restores_baseline(self):
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
                    "phys opt complete",
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

            report = await optimizer.run_phys_opt_flow(directive="RuntimeOptimized")

        self.assertEqual(report, "baseline report")
        phys_calls = [
            call
            for call in optimizer.v.await_args_list
            if call.args and call.args[0] == "phys_opt_design"
        ]
        self.assertEqual(len(phys_calls), 1)
        self.assertEqual(phys_calls[0].args[1], {"directive": "RuntimeOptimized"})
        self.assertEqual(optimizer.v.await_args_list[-1].args[0], "open_checkpoint")


if __name__ == "__main__":
    unittest.main()
