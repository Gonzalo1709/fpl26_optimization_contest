"""Generation-search configuration and candidate state."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GenerationSearchConfig:
    """Configuration for branch-and-generation LLM search."""

    enabled: bool = True
    branch_factor: int = 2
    beam_width: int = 2
    max_generations: int = 3
    max_steps_per_branch: int = 3
    max_steps_without_improvement: int = 3
    max_llm_calls: int = 50
    min_wns_delta: float = 0.001
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
