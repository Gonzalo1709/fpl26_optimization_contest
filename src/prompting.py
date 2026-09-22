"""Prompt loading and planner prompt assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional


DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "SYSTEM_PROMPT.TXT"


PLANNER_OUTPUT_CONTRACT = """
PLANNER OUTPUT CONTRACT:

Choose exactly one next optimization recipe and return only JSON:
{
  "strategy": "one key from available_strategies",
  "args": { ... }
}

Rules for the controller interface:
- You do not have direct access to Vivado or RapidWright tools in this call.
- Choose only among the provided recipes.
- Treat available_strategies as a strict allow-list; never name an omitted recipe.
- Do not describe tool calls, command sequences, or chain-of-thought.
- Use timing metrics holistically: WNS first, then TNS, then failing endpoints.
- Prefer PBLOCK when the analysis shows spread-out critical paths or explicitly recommends PBLOCK.
- Prefer FANOUT when critical high-fanout nets are present, not blacklisted, and placement spread is not the main issue.
- Prefer PHYS_OPT when placement spread is low, after PBLOCK/FANOUT changed the design, or when recent steps stagnate.
- If stagnation >= 2, switch strategy if possible.
- FANOUT args: {"top_n_nets": int from 1 to 10}
- PHYS_OPT args: {"directive": one value provided by the PHYS_OPT schema}
- PBLOCK args: {}
- CELL_RELOCATE args: {"num_paths": int from 3 to 20, "detour_threshold": float from 1.2 to 4.0, "max_cells": int from 1 to 5, "max_move_distance": int from 5 to 80 tiles}
- HARD_BLOCK args: {"hard_block_types": subset of the provided eligible resource types}
- CRITICAL_PIN args: {}
- ROUTE_PRESERVE args: {"max_nets": int from 1 to 8, "min_net_delay_ns": float from 0.05 to 2.0}
- GRANULAR_PHYS_OPT args: {"flag": one of the provided flags}
- SCOPED_PHYS_OPT, PARTIAL_REPLACE, TARGETED_REPLICATION: use the controller's provided operand counts.
- RETIME args: {"directive": one of the provided retiming directives}; never choose it if omitted.
- Prefer feature-matched measured outcomes and the provided recipe order when available.
- NO_OP args: {}
- CRITICAL_NET_REROUTE, CRITICAL_BRANCH_REROUTE and PATH_LOCAL_REPLACE: use the provided counts; the controller selects current-checkpoint targets.
- Return ONLY JSON.
""".strip()


def load_system_prompt(prompt_path: Optional[Path] = None) -> str:
    """Load the base system prompt from disk."""
    resolved_path = prompt_path or DEFAULT_SYSTEM_PROMPT_PATH
    try:
        return resolved_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"System prompt file not found: {resolved_path}") from None


def build_planner_system_prompt(
    base_prompt: Optional[str] = None,
    prompt_path: Optional[Path] = None,
) -> str:
    """Build the prompt used by the recipe-selection LLM call."""
    prompt = base_prompt if base_prompt is not None else load_system_prompt(prompt_path)
    return f"{prompt.rstrip()}\n\n{PLANNER_OUTPUT_CONTRACT}\n"


def prompt_sha256(prompt: str) -> str:
    """Return a stable short hash for prompt provenance."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
