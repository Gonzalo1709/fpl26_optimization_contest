import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.analysis import DesignSignature
from src.llm_optimizer import DCPOptimizer
from src.policy import BudgetState, gate_actions
from src.search import SearchCandidate


def make_signature(
    *,
    high_fanout_report: str = "",
    spread: dict | None = None,
    critical_paths: list[list[str]] | None = None,
    congestion_report: str | None = None,
) -> DesignSignature:
    return DesignSignature.from_reports(
        target_clock="clk_fpl26contest",
        clock_period_ns=1.57,
        wns_ns=-1.0,
        tns_ns=-100.0,
        failing_endpoints=100,
        high_fanout_report=high_fanout_report,
        spread_report=json.dumps(spread) if spread else None,
        analysis_duration_seconds=1.0,
        critical_paths_report=json.dumps(critical_paths) if critical_paths else None,
        congestion_report=congestion_report,
    )


class RecipePolicyTests(unittest.TestCase):
    def test_expensive_recipe_gates_and_placement_diversification(self):
        signature = make_signature()
        short_budget = BudgetState(remaining_runtime_seconds=800, validation_reserve_seconds=60)
        self.assertNotIn(
            "PLACEMENT_SHOT",
            {action.strategy for action in gate_actions(signature, budget=short_budget)},
        )

        long_budget = BudgetState(remaining_runtime_seconds=1200, validation_reserve_seconds=60)
        actions = gate_actions(
            signature,
            budget=long_budget,
            history=[{"strategy": "PLACEMENT_SHOT", "args": {"directive": "ExtraNetDelay_low"}}],
        )
        by_strategy = {action.strategy: action for action in actions}
        self.assertIn("PHYS_OPT_REROUTE", by_strategy)
        self.assertIn("PLACEMENT_SHOT", by_strategy)
        self.assertNotIn(
            "ExtraNetDelay_low",
            by_strategy["PLACEMENT_SHOT"].allowed_args["directive"],
        )

    def test_pblock_requires_extreme_multi_path_spread(self):
        logicnets_like = make_signature(
            spread={
                "max_distance_found": 198,
                "avg_max_distance": 111.86,
                "paths_analyzed": 50,
            }
        )
        rosetta_like = make_signature(
            spread={
                "max_distance_found": 283,
                "avg_max_distance": 131.38,
                "paths_analyzed": 50,
            }
        )
        congested = make_signature(
            spread={
                "max_distance_found": 150,
                "avg_max_distance": 85.0,
                "paths_analyzed": 20,
            },
            congestion_report="Global Horizontal Congestion: 6",
        )

        self.assertNotIn(
            "PBLOCK", {action.strategy for action in gate_actions(logicnets_like)}
        )
        self.assertIn(
            "PBLOCK", {action.strategy for action in gate_actions(rosetta_like)}
        )
        self.assertNotIn(
            "PBLOCK", {action.strategy for action in gate_actions(congested)}
        )

    def test_specialists_remain_disabled_without_proof_gate(self):
        strategies = {
            action.strategy
            for action in gate_actions(
                make_signature(
                    spread={
                        "max_distance_found": 300,
                        "avg_max_distance": 150,
                        "paths_analyzed": 50,
                    },
                    critical_paths=[["top/RAMB36E2", "top/out_reg"]],
                    congestion_report="Global Horizontal Congestion: 6",
                )
            )
        }

        self.assertNotIn("LUT_MERGE", strategies)
        self.assertNotIn("RETIME", strategies)
        self.assertNotIn("CONGESTION_SPREAD", strategies)

    def test_rejects_pblock_for_local_moderate_spread(self):
        signature = make_signature(
            spread={
                "max_distance_found": 93,
                "avg_max_distance": 53.5,
                "paths_analyzed": 50,
            }
        )

        strategies = {action.strategy for action in gate_actions(signature)}

        self.assertNotIn("PBLOCK", strategies)
        self.assertIn("CELL_RELOCATE", strategies)

    def test_rejects_fanout_without_critical_nonclock_candidate(self):
        strategies = {action.strategy for action in gate_actions(make_signature())}

        self.assertNotIn("FANOUT", strategies)

    def test_rejects_hard_block_without_critical_incidence(self):
        no_hard_block = {action.strategy for action in gate_actions(make_signature())}
        with_bram = {
            action.strategy
            for action in gate_actions(
                make_signature(
                    critical_paths=[["cache/RAMB36E2", "top/out_reg"]],
                    spread={
                        "max_distance_found": 180,
                        "avg_max_distance": 90,
                        "paths_analyzed": 20,
                    },
                )
            )
        }

        self.assertNotIn("HARD_BLOCK", no_hard_block)
        self.assertIn("HARD_BLOCK", with_bram)

    def test_rejects_hard_block_for_low_spread_congestion_only_signature(self):
        vex_like = make_signature(
            critical_paths=[["cache/RAMB36E2", "top/out_reg"]],
            spread={
                "max_distance_found": 93,
                "avg_max_distance": 53.5,
                "paths_analyzed": 50,
            },
            congestion_report="Global Horizontal Congestion: 5",
        )

        strategies = {action.strategy for action in gate_actions(vex_like)}

        self.assertNotIn("HARD_BLOCK", strategies)

    def test_phys_opt_remains_eligible_on_ambiguous_inputs(self):
        strategies = {
            action.strategy
            for action in gate_actions(
                make_signature(),
                budget=BudgetState(
                    remaining_runtime_seconds=900.0,
                    remaining_cost_usd=0.05,
                ),
            )
        }

        self.assertIn("PHYS_OPT", strategies)

    def test_neutral_phys_opt_fallback_is_exposed_only_without_fanout(self):
        neutral_history = [
            {
                "strategy": "PHYS_OPT",
                "args": {"directive": "RuntimeOptimized"},
                "wns": -1.0,
                "delta_wns": 0.0,
            }
        ]
        budget = BudgetState(remaining_runtime_seconds=900.0, remaining_cost_usd=0.01)
        no_fanout = gate_actions(make_signature(), budget=budget, history=neutral_history)
        with_fanout = gate_actions(
            make_signature(
                high_fanout_report=(
                    "Paths Fanout Parent Net Name\n"
                    "1 100 top/critical_net\n"
                    "===\n"
                )
            ),
            budget=budget,
            history=neutral_history,
        )

        no_fanout_phys = next(action for action in no_fanout if action.strategy == "PHYS_OPT")
        fanout_phys = next(action for action in with_fanout if action.strategy == "PHYS_OPT")
        self.assertEqual(no_fanout_phys.allowed_args["directive"], ["RuntimeOptimized", "CriticalPin"])
        self.assertEqual(fanout_phys.allowed_args["directive"], ["RuntimeOptimized"])

    def test_neutral_fallback_does_not_duplicate_positive_portfolio_critical_pin(self):
        history = [
            {"strategy": "CELL_RELOCATE", "delta_vs_peak": 0.2},
            {
                "strategy": "PHYS_OPT",
                "args": {"directive": "RuntimeOptimized"},
                "wns": -1.0,
                "delta_wns": 0.0,
            },
        ]

        actions = gate_actions(
            make_signature(),
            budget=BudgetState(remaining_runtime_seconds=900.0, remaining_cost_usd=0.01),
            history=history,
        )

        phys_opt = next(action for action in actions if action.strategy == "PHYS_OPT")
        self.assertEqual(
            phys_opt.allowed_args["directive"],
            ["RuntimeOptimized", "CriticalPin", "PlacementRouting"],
        )

    def test_neutral_phys_opt_history_does_not_change_pblock_or_hard_block_gates(self):
        neutral_history = [
            {
                "strategy": "PHYS_OPT",
                "args": {"directive": "RuntimeOptimized"},
                "wns": -1.0,
                "delta_wns": 0.0,
            }
        ]
        signatures = [
            make_signature(),
            make_signature(
                spread={"max_distance_found": 200, "avg_max_distance": 130, "paths_analyzed": 10},
                critical_paths=[["cache/RAMB36E2", "top/out_reg"]],
            ),
        ]
        budget = BudgetState(remaining_runtime_seconds=900.0, remaining_cost_usd=0.01)

        for signature in signatures:
            before = {action.strategy for action in gate_actions(signature, budget=budget)}
            after = {
                action.strategy
                for action in gate_actions(signature, budget=budget, history=neutral_history)
            }
            self.assertEqual(before & {"PBLOCK", "HARD_BLOCK"}, after & {"PBLOCK", "HARD_BLOCK"})

    def test_sanitizer_rejects_critical_pin_when_neutral_gate_is_false(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.design_signature = make_signature()

            strategy, args = optimizer.sanitize_action(
                {"strategy": "PHYS_OPT", "args": {"directive": "CriticalPin"}}
            )

        self.assertEqual(strategy, "PHYS_OPT")
        self.assertEqual(args, {"directive": "RuntimeOptimized"})

    def test_validation_reserve_allows_only_no_op(self):
        actions = gate_actions(
            make_signature(),
            budget=BudgetState(
                remaining_runtime_seconds=600.0,
                remaining_cost_usd=0.05,
                validation_reserve_seconds=600.0,
            ),
        )

        self.assertEqual([action.strategy for action in actions], ["NO_OP"])

    def test_exhausted_llm_budget_allows_only_no_op(self):
        actions = gate_actions(
            make_signature(),
            budget=BudgetState(
                remaining_runtime_seconds=900.0,
                remaining_cost_usd=0.0,
            ),
        )

        self.assertEqual([action.strategy for action in actions], ["NO_OP"])

    def test_planner_and_sanitizer_receive_only_eligible_actions(self):
        signature = make_signature(
            spread={
                "max_distance_found": 93,
                "avg_max_distance": 53.5,
                "paths_analyzed": 50,
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.design_signature = signature

            decision_input = optimizer._build_decision_input("analysis", 0, [])
            strategy, args = optimizer.sanitize_action(
                {"strategy": "PBLOCK", "args": {}}
            )

        self.assertEqual(
            set(decision_input["available_strategies"]),
            {"PHYS_OPT", "CRITICAL_PIN", "CELL_RELOCATE"},
        )
        self.assertEqual(strategy, "PHYS_OPT")
        self.assertEqual(args, {"directive": "RuntimeOptimized"})

    def test_forced_branch_diversity_cannot_bypass_policy(self):
        signature = make_signature(
            spread={
                "max_distance_found": 93,
                "avg_max_distance": 53.5,
                "paths_analyzed": 50,
            }
        )
        root = SearchCandidate(
            candidate_id="root",
            dcp_path=Path("root.dcp"),
            wns=-1.0,
            tns=-100.0,
            failing_endpoints=100,
            peak_wns=-1.0,
            generation=0,
            parent_id=None,
            branch_index=0,
            steps_taken=0,
            steps_since_peak=0,
            summary="root",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.design_signature = signature

            strategy, _ = optimizer._forced_branch_strategy(1, root, 1, 1)

        self.assertIn(strategy, {"PHYS_OPT", "CELL_RELOCATE"})
        self.assertNotEqual(strategy, "PBLOCK")


class NoOpExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_op_measures_without_running_a_transform(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=Path(temporary_directory),
                system_prompt="test planner prompt",
            )
            optimizer.v = AsyncMock(return_value="timing report")
            optimizer._measure_current_wns = AsyncMock(return_value=-1.0)

            result, wns = await optimizer._execute_strategy("NO_OP", {})

        optimizer.v.assert_awaited_once_with("report_timing_summary")
        self.assertEqual(result, "timing report")
        self.assertEqual(wns, -1.0)


if __name__ == "__main__":
    unittest.main()
