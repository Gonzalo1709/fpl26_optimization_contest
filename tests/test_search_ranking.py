import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.llm_optimizer import DCPOptimizer
from src.scoring import ContestScoreInput, ValidationStatus, calculate_contest_score
from src.search import GenerationSearchConfig, SearchCandidate, should_stop_fast_search


def validation_status(value: bool | None) -> ValidationStatus:
    return ValidationStatus(
        par_routed=value,
        par_drc_clean=value,
        hold_passed=value,
        pulse_width_passed=value,
        structural_passed=value,
        simulation_passed=value,
    )


def candidate(
    candidate_id: str,
    *,
    delta_fmax_mhz: float,
    runtime_seconds: float,
    llm_cost_usd: float,
    validation: ValidationStatus | None = None,
    wns: float = -0.1,
) -> SearchCandidate:
    status = validation or validation_status(None)
    score = calculate_contest_score(
        ContestScoreInput(
            delta_fmax_mhz=delta_fmax_mhz,
            runtime_seconds=runtime_seconds,
            llm_cost_usd=llm_cost_usd,
            validation=status,
        )
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        dcp_path=Path(f"{candidate_id}.dcp"),
        wns=wns,
        tns=-1.0,
        failing_endpoints=1,
        peak_wns=wns,
        generation=1,
        parent_id="root",
        branch_index=1,
        steps_taken=1,
        steps_since_peak=0,
        summary="test candidate",
        elapsed_seconds=runtime_seconds,
        llm_cost_usd=llm_cost_usd,
        projected_score=score.projected_score,
        validation=status,
        validated_score=score.validated_score,
    )


class CandidateRankingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.optimizer = DCPOptimizer(
            api_key="test-key",
            run_dir=Path(self.temporary_directory.name),
            system_prompt="test planner prompt",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_lower_fmax_gain_wins_when_runtime_and_cost_raise_projected_score(self):
        fast = candidate(
            "fast",
            delta_fmax_mhz=10.0,
            runtime_seconds=60.0,
            llm_cost_usd=0.0,
            wns=-0.2,
        )
        slow = candidate(
            "slow",
            delta_fmax_mhz=11.0,
            runtime_seconds=3600.0,
            llm_cost_usd=1.0,
            wns=-0.1,
        )

        self.assertGreater(fast.projected_score, slow.projected_score)
        self.assertGreater(
            self.optimizer._candidate_sort_key(fast),
            self.optimizer._candidate_sort_key(slow),
        )

    def test_unvalidated_candidate_cannot_replace_validated_incumbent(self):
        incumbent = candidate(
            "validated",
            delta_fmax_mhz=1.0,
            runtime_seconds=300.0,
            llm_cost_usd=0.01,
            validation=validation_status(True),
        )
        speculative = candidate(
            "speculative",
            delta_fmax_mhz=20.0,
            runtime_seconds=300.0,
            llm_cost_usd=0.01,
            validation=validation_status(None),
            wns=0.1,
        )

        self.assertGreater(
            self.optimizer._candidate_sort_key(incumbent),
            self.optimizer._candidate_sort_key(speculative),
        )


class FastSearchStopTests(unittest.TestCase):
    def setUp(self):
        self.root = candidate(
            "root",
            delta_fmax_mhz=0.0,
            runtime_seconds=0.0,
            llm_cost_usd=0.0,
            wns=-0.2,
        )
        self.best = candidate(
            "best",
            delta_fmax_mhz=5.0,
            runtime_seconds=60.0,
            llm_cost_usd=0.0,
            wns=-0.1,
        )

    def test_fast_positive_score_and_accepted_wns_gain_stops_search(self):
        config = GenerationSearchConfig(budget_profile="fast", min_wns_delta=0.05)

        self.assertTrue(should_stop_fast_search(config, self.root, self.best))

    def test_fast_zero_score_does_not_stop_search(self):
        config = GenerationSearchConfig(budget_profile="fast", min_wns_delta=0.05)
        self.best.projected_score = 0.0

        self.assertFalse(should_stop_fast_search(config, self.root, self.best))

    def test_fast_sub_threshold_wns_gain_does_not_stop_search(self):
        config = GenerationSearchConfig(budget_profile="fast", min_wns_delta=0.11)

        self.assertFalse(should_stop_fast_search(config, self.root, self.best))

    def test_non_fast_budget_profiles_do_not_stop_search(self):
        for budget_profile in ("balanced", "cost", "quality"):
            with self.subTest(budget_profile=budget_profile):
                config = GenerationSearchConfig(
                    budget_profile=budget_profile,
                    strategy_effort="fast",
                    min_wns_delta=0.05,
                )

                self.assertFalse(should_stop_fast_search(config, self.root, self.best))

    def test_fast_negative_score_or_unknown_wns_does_not_stop_search(self):
        config = GenerationSearchConfig(budget_profile="fast", min_wns_delta=0.05)
        self.best.projected_score = -1.0
        self.assertFalse(should_stop_fast_search(config, self.root, self.best))

        self.best.projected_score = 1.0
        self.root.wns = None
        self.assertFalse(should_stop_fast_search(config, self.root, self.best))

        self.root.wns = -0.2
        self.best.wns = None
        self.assertFalse(should_stop_fast_search(config, self.root, self.best))


class FastSearchStopIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_positive_first_generation_candidate_skips_later_fast_expansion(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = Path(temporary_directory)
            output_dcp = run_dir / "best.dcp"
            config = GenerationSearchConfig(
                budget_profile="fast",
                branch_factor=2,
                beam_width=1,
                max_generations=2,
                min_wns_delta=0.05,
                stop_when_timing_met=False,
            )
            optimizer = DCPOptimizer(
                api_key="test-key",
                run_dir=run_dir,
                generation_config=config,
                system_prompt="test planner prompt",
            )
            optimizer.initial_wns = -0.2
            optimizer.initial_tns = -1.0
            optimizer.initial_failing_endpoints = 1
            optimizer.best_wns = -0.2
            candidate_path = run_dir / "generation_search" / "positive.dcp"
            entered_generations = []

            async def return_positive_candidate(**kwargs):
                entered_generations.append(kwargs["generation"])
                candidate_path.write_bytes(b"positive checkpoint")
                positive = candidate(
                    "positive",
                    delta_fmax_mhz=5.0,
                    runtime_seconds=60.0,
                    llm_cost_usd=0.0,
                    wns=-0.1,
                )
                positive.dcp_path = candidate_path
                positive.generation = kwargs["generation"]
                optimizer.best_candidate = positive
                optimizer.search_candidates.append(positive)
                return positive

            optimizer._save_vivado_checkpoint = AsyncMock(return_value=True)
            optimizer._run_generation_branch = AsyncMock(side_effect=return_positive_candidate)
            optimizer._print_optimization_summary = lambda **kwargs: None

            with patch("builtins.print") as print_mock:
                result = await optimizer._optimize_generational(
                    run_dir / "input.dcp",
                    output_dcp,
                    "initial analysis",
                )

            self.assertTrue(result)
            self.assertEqual(entered_generations, [1])
            self.assertEqual(optimizer.best_candidate.candidate_id, "positive")
            self.assertEqual(output_dcp.read_bytes(), b"positive checkpoint")
            log_output = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
            self.assertIn("positive", log_output)
            self.assertIn("projected score", log_output)
            self.assertIn("later fast-profile expansion is skipped", log_output)


if __name__ == "__main__":
    unittest.main()
