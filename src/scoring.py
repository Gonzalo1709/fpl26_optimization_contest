"""Pure contest-score and target-clock frequency calculations."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationStatus:
    """Validation gates required before a projected score becomes official."""

    par_routed: bool | None = None
    par_drc_clean: bool | None = None
    hold_passed: bool | None = None
    pulse_width_passed: bool | None = None
    structural_passed: bool | None = None
    simulation_passed: bool | None = None

    @property
    def complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.par_routed,
                self.par_drc_clean,
                self.hold_passed,
                self.pulse_width_passed,
                self.structural_passed,
                self.simulation_passed,
            )
        )

    @property
    def passed(self) -> bool:
        return self.complete and all(
            (
                self.par_routed,
                self.par_drc_clean,
                self.hold_passed,
                self.pulse_width_passed,
                self.structural_passed,
                self.simulation_passed,
            )
        )


@dataclass(frozen=True)
class ContestScoreInput:
    """Inputs to the official FPL'26 per-benchmark score formula."""

    delta_fmax_mhz: float
    llm_cost_usd: float
    runtime_seconds: float
    validation: ValidationStatus = field(default_factory=ValidationStatus)


@dataclass(frozen=True)
class ContestScore:
    """Projected and, when validation is complete, validated contest score."""

    delta_fmax_mhz: float
    runtime_hours: float
    llm_cost_usd: float
    penalty_multiplier: float
    projected_score: float
    validation: ValidationStatus
    validated_score: float | None
    score_status: str


def target_clock_fmax_mhz(period_ns: float, wns_ns: float) -> float | None:
    """Convert target-clock period and WNS to achievable Fmax in MHz."""
    achievable_period_ns = period_ns - wns_ns
    if period_ns <= 0 or achievable_period_ns <= 0:
        return None
    return 1000.0 / achievable_period_ns


def classify_score_status(
    delta_fmax_mhz: float,
    projected_score: float,
    validation: ValidationStatus,
) -> str:
    """Explain whether a score is positive, clamped, pending, or invalid."""
    if validation.complete and not validation.passed:
        return "validation_failed"
    if delta_fmax_mhz < 0:
        return "negative_gain_clamped"
    if delta_fmax_mhz == 0:
        return "no_fmax_gain"
    if not validation.complete:
        return "validation_pending"
    return "positive"


def calculate_contest_score(score_input: ContestScoreInput) -> ContestScore:
    """Apply the official cost/runtime penalties and clamp the score at zero."""
    runtime_hours = score_input.runtime_seconds / 3600.0
    penalty_multiplier = (
        1.0
        - 0.1 * score_input.llm_cost_usd
        - 0.1 * runtime_hours
    )
    projected_score = max(
        0.0,
        score_input.delta_fmax_mhz * penalty_multiplier,
    )

    if score_input.validation.complete:
        validated_score = projected_score if score_input.validation.passed else 0.0
    else:
        validated_score = None
    score_status = classify_score_status(
        score_input.delta_fmax_mhz,
        projected_score,
        score_input.validation,
    )

    return ContestScore(
        delta_fmax_mhz=score_input.delta_fmax_mhz,
        runtime_hours=runtime_hours,
        llm_cost_usd=score_input.llm_cost_usd,
        penalty_multiplier=penalty_multiplier,
        projected_score=projected_score,
        validation=score_input.validation,
        validated_score=validated_score,
        score_status=score_status,
    )
