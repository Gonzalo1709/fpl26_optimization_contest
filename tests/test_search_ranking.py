import tempfile
import unittest
from pathlib import Path

from src.llm_optimizer import DCPOptimizer
from src.scoring import ContestScoreInput, ValidationStatus, calculate_contest_score
from src.search import SearchCandidate


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


if __name__ == "__main__":
    unittest.main()
