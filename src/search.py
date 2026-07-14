"""Generation-search configuration and candidate state."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.scoring import ValidationStatus


@dataclass
class GenerationSearchConfig:
    """Configuration for branch-and-generation LLM search."""

    enabled: bool = True
    budget_profile: str = "balanced"
    strategy_effort: str = "balanced"
    branch_factor: int = 2
    beam_width: int = 2
    max_generations: int = 3
    max_steps_per_branch: int = 3
    max_steps_without_improvement: int = 3
    max_llm_calls: int = 50
    min_wns_delta: float = 0.001
    min_wns_per_minute: float = 0.0
    max_runtime_minutes: Optional[float] = None
    max_cost: Optional[float] = None
    stop_when_timing_met: bool = True
    wall_clock_limit_seconds: float = 3600.0


@dataclass
class SearchCandidate:
    """A saved checkpoint and score in the generation search tree."""

    candidate_id: str
    dcp_path: Path
    wns: Optional[float]
    tns: Optional[float]
    failing_endpoints: Optional[int]
    peak_wns: Optional[float]
    generation: int
    parent_id: Optional[str]
    branch_index: int
    steps_taken: int
    steps_since_peak: int
    summary: str
    elapsed_seconds: float = 0.0
    llm_cost_usd: float = 0.0
    projected_score: float = 0.0
    validation: ValidationStatus = field(default_factory=ValidationStatus)
    validated_score: Optional[float] = None


def should_stop_fast_search(
    config: GenerationSearchConfig,
    root: SearchCandidate,
    best: SearchCandidate,
) -> bool:
    """Return whether a scored fast search has earned early termination."""
    return (
        config.budget_profile == "fast"
        and best.projected_score > 0
        and root.wns is not None
        and best.wns is not None
        and best.wns >= root.wns + config.min_wns_delta
    )
