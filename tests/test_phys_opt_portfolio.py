import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.analysis import DesignSignature
from src.llm_optimizer import DCPOptimizer
from src.policy import (
    BudgetState,
    plan_neutral_phys_opt_fallback,
    plan_phys_opt_portfolio,
)
from src.scoring import ValidationStatus
from src.search import GenerationSearchConfig, SearchCandidate


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
    def test_neutral_runtime_fallback_requires_every_safety_gate(self):
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
        neutral = {
            "strategy": "PHYS_OPT",
            "args": {"directive": "RuntimeOptimized"},
            "wns": -1.0,
            "delta_wns": 0.0,
        }
        eligible_budget = BudgetState(
            remaining_runtime_seconds=900.0,
            remaining_cost_usd=0.01,
            validation_reserve_seconds=600.0,
        )

        attempts = plan_neutral_phys_opt_fallback(
            signature, eligible_budget, [neutral], ValidationStatus()
        )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].name, "CriticalPin")
        self.assertEqual(attempts[0].tool_args, {"critical_pin_opt": True})

        fanout_signature = DesignSignature.from_reports(
            target_clock="clk_fpl26contest",
            clock_period_ns=1.57,
            wns_ns=-1.0,
            tns_ns=-10.0,
            failing_endpoints=10,
            high_fanout_report=(
                "Paths Fanout Parent Net Name\n"
                "1 100 top/critical_net\n"
                "===\n"
            ),
            spread_report=None,
            analysis_duration_seconds=1.0,
        )
        disabled_cases = [
            (signature, eligible_budget, [{**neutral, "delta_wns": 0.1}], ValidationStatus()),
            (fanout_signature, eligible_budget, [neutral], ValidationStatus()),
            (
                signature,
                BudgetState(remaining_runtime_seconds=899.9, remaining_cost_usd=0.01),
                [neutral],
                ValidationStatus(),
            ),
            (
                signature,
                BudgetState(remaining_runtime_seconds=900.0, remaining_cost_usd=0.0),
                [neutral],
                ValidationStatus(),
            ),
            (signature, eligible_budget, [{**neutral, "delta_wns": None}], ValidationStatus()),
            (signature, eligible_budget, [{**neutral, "delta_wns": "missing"}], ValidationStatus()),
            (signature, eligible_budget, [{**neutral, "delta_wns": "0.0"}], ValidationStatus()),
            (signature, eligible_budget, [{**neutral, "delta_wns": False}], ValidationStatus()),
            (signature, eligible_budget, [{**neutral, "wns": None}], ValidationStatus()),
            (signature, eligible_budget, [{**neutral, "error": "failed"}], ValidationStatus()),
            (
                signature,
                eligible_budget,
                [neutral],
                ValidationStatus(hold_passed=False),
            ),
            (
                signature,
                eligible_budget,
                [neutral],
                ValidationStatus(pulse_width_passed=False),
            ),
            (
                signature,
                eligible_budget,
                [neutral, {"strategy": "PHYS_OPT", "args": {"directive": "CriticalPin"}}],
                ValidationStatus(),
            ),
            (
                signature,
                eligible_budget,
                [neutral, {"strategy": "PHYS_OPT", "args": {"directive": "PlacementRouting"}}],
                ValidationStatus(),
            ),
        ]
        for case in disabled_cases:
            with self.subTest(case=case):
                self.assertEqual(plan_neutral_phys_opt_fallback(*case), ())

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
    def _make_neutral_branch(self, temporary_directory):
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
        parent = SearchCandidate(
            candidate_id="root",
            dcp_path=Path("root.dcp"),
            wns=-1.0,
            tns=-10.0,
            failing_endpoints=10,
            peak_wns=-1.0,
            generation=0,
            parent_id=None,
            branch_index=0,
            steps_taken=0,
            steps_since_peak=0,
            summary="root",
        )
        optimizer = DCPOptimizer(
            api_key="test-key",
            run_dir=Path(temporary_directory),
            system_prompt="test planner prompt",
            generation_config=GenerationSearchConfig(
                budget_profile="fast",
                max_steps_per_branch=1,
                max_steps_without_improvement=1,
                wall_clock_limit_seconds=3600.0,
            ),
            force_strategy="PHYS_OPT",
        )
        optimizer.design_signature = signature
        optimizer.best_candidate = parent
        optimizer.initial_wns = -1.0
        optimizer._restore_candidate_state = AsyncMock()
        optimizer._save_vivado_checkpoint = AsyncMock(return_value=True)
        optimizer._measure_current_metrics = AsyncMock(
            return_value={"wns": -1.0, "tns": -10.0, "failing_endpoints": 10}
        )
        return optimizer, parent

    async def test_fast_neutral_runtime_executes_one_critical_pin_before_patience_stop(self):
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
        parent = SearchCandidate(
            candidate_id="root",
            dcp_path=Path("root.dcp"),
            wns=-1.0,
            tns=-10.0,
            failing_endpoints=10,
            peak_wns=-1.0,
            generation=0,
            parent_id=None,
            branch_index=0,
            steps_taken=0,
            steps_since_peak=0,
            summary="root",
        )
        config = GenerationSearchConfig(
            budget_profile="fast",
            max_steps_per_branch=1,
            max_steps_without_improvement=1,
            wall_clock_limit_seconds=3600.0,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
                generation_config=config,
                force_strategy="PHYS_OPT",
            )
            optimizer.design_signature = signature
            optimizer.best_candidate = parent
            optimizer.initial_wns = -1.0
            optimizer._restore_candidate_state = AsyncMock()
            optimizer._save_vivado_checkpoint = AsyncMock(return_value=True)
            optimizer._execute_strategy = AsyncMock(
                side_effect=[("runtime report", -1.0), ("critical report", -0.9)]
            )
            optimizer._measure_current_metrics = AsyncMock(
                side_effect=[
                    {"wns": -1.0, "tns": -10.0, "failing_endpoints": 10},
                    {"wns": -0.9, "tns": -9.0, "failing_endpoints": 9},
                ]
            )

            candidate = await optimizer._run_generation_branch(
                "analysis",
                Path(temporary_directory),
                parent,
                generation=1,
                branch_index=1,
                tried_summaries="",
            )

        self.assertEqual(
            [call.args for call in optimizer._execute_strategy.await_args_list],
            [
                ("PHYS_OPT", {"directive": "RuntimeOptimized"}),
                ("PHYS_OPT", {"directive": "CriticalPin"}),
            ],
        )
        self.assertEqual(len(optimizer.history), 2)
        self.assertEqual(
            [entry["args"]["directive"] for entry in optimizer.history],
            ["RuntimeOptimized", "CriticalPin"],
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.wns, -0.9)
        self.assertIs(optimizer.best_candidate, candidate)

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

    async def test_critical_pin_exception_with_confirmed_restore_keeps_neutral_candidate(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer, parent = self._make_neutral_branch(temporary_directory)
            optimizer._execute_strategy = AsyncMock(
                side_effect=[("runtime report", -1.0), RuntimeError("critical pin failed")]
            )
            optimizer.v = AsyncMock(return_value="opened checkpoint successfully")

            candidate = await optimizer._run_generation_branch(
                "analysis", Path(temporary_directory), parent, 1, 1, ""
            )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.wns, -1.0)
        self.assertEqual(len(optimizer.search_candidates), 1)
        optimizer._save_vivado_checkpoint.assert_awaited_once()
        self.assertEqual(optimizer.history[-1]["error"], "critical pin failed")

    async def test_critical_pin_exception_with_restore_exception_aborts_branch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer, parent = self._make_neutral_branch(temporary_directory)
            optimizer._execute_strategy = AsyncMock(
                side_effect=[("runtime report", -1.0), RuntimeError("critical pin failed")]
            )
            optimizer.v = AsyncMock(side_effect=RuntimeError("restore failed"))

            candidate = await optimizer._run_generation_branch(
                "analysis", Path(temporary_directory), parent, 1, 1, ""
            )

        self.assertIsNone(candidate)
        optimizer._save_vivado_checkpoint.assert_not_awaited()
        self.assertEqual(optimizer.search_candidates, [])

    async def test_critical_pin_exception_with_encoded_restore_error_aborts_branch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer, parent = self._make_neutral_branch(temporary_directory)
            optimizer._execute_strategy = AsyncMock(
                side_effect=[("runtime report", -1.0), RuntimeError("critical pin failed")]
            )
            optimizer.v = AsyncMock(return_value='{"error": "checkpoint restore failed"}')

            candidate = await optimizer._run_generation_branch(
                "analysis", Path(temporary_directory), parent, 1, 1, ""
            )

        self.assertIsNone(candidate)
        optimizer._save_vivado_checkpoint.assert_not_awaited()
        self.assertEqual(optimizer.search_candidates, [])


if __name__ == "__main__":
    unittest.main()
