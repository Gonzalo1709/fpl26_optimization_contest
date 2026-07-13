"""Deterministic recipe admissibility gates."""

from dataclasses import dataclass, field
from math import inf
from typing import Iterable

from src.analysis import DesignSignature


@dataclass(frozen=True)
class BudgetState:
    remaining_runtime_seconds: float = inf
    remaining_cost_usd: float = inf
    validation_reserve_seconds: float = 600.0


@dataclass(frozen=True)
class EligibleAction:
    strategy: str
    default_args: dict = field(default_factory=dict)
    reason: str = ""


def gate_actions(
    signature: DesignSignature,
    budget: BudgetState | None = None,
    history: Iterable[dict] = (),
) -> tuple[EligibleAction, ...]:
    """Return only recipes supported by current evidence and remaining budget."""
    del history  # Reserved for measured per-recipe suppression in later tasks.
    budget = budget or BudgetState()
    if (
        budget.remaining_runtime_seconds <= budget.validation_reserve_seconds
        or budget.remaining_cost_usd <= 0
    ):
        reason = (
            "OpenRouter cost budget exhausted; retain the legal incumbent"
            if budget.remaining_cost_usd <= 0
            else "validation reserve reached; retain the legal incumbent"
        )
        return (
            EligibleAction(
                strategy="NO_OP",
                reason=reason,
            ),
        )

    actions = [
        EligibleAction(
            strategy="PHYS_OPT",
            default_args={"directive": "Default"},
            reason="low-risk physical optimization remains the deterministic fallback",
        )
    ]

    if signature.high_fanout_candidates:
        actions.append(
            EligibleAction(
                strategy="FANOUT",
                default_args={"top_n_nets": min(5, len(signature.high_fanout_candidates))},
                reason="target-clock critical non-clock high-fanout candidates exist",
            )
        )

    spread = signature.path_spread
    if spread and spread.paths_analyzed > 0 and spread.max_distance >= 40:
        actions.append(
            EligibleAction(
                strategy="CELL_RELOCATE",
                default_args={
                    "num_paths": min(10, spread.paths_analyzed),
                    "detour_threshold": 2.0,
                    "max_cells": 3,
                },
                reason="target-clock paths have measurable physical spread",
            )
        )

    if signature.critical_hard_block_types:
        actions.append(
            EligibleAction(
                strategy="HARD_BLOCK",
                default_args={
                    "hard_block_types": list(signature.critical_hard_block_types)
                },
                reason="target-clock critical paths include hard-block resources",
            )
        )

    if (
        spread
        and spread.avg_distance > 70
        and spread.paths_analyzed >= 5
        and budget.remaining_runtime_seconds >= budget.validation_reserve_seconds + 180
    ):
        actions.append(
            EligibleAction(
                strategy="PBLOCK",
                reason="multiple target-clock paths have strong physical spread",
            )
        )

    return tuple(actions)
