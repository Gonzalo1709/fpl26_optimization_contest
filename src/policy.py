"""Deterministic recipe admissibility gates."""

from dataclasses import dataclass, field
from math import inf
from typing import Iterable

from src.analysis import DesignSignature
from src.scoring import ValidationStatus


@dataclass(frozen=True)
class BudgetState:
    remaining_runtime_seconds: float = inf
    remaining_cost_usd: float = inf
    validation_reserve_seconds: float = 600.0


@dataclass(frozen=True)
class EligibleAction:
    strategy: str
    default_args: dict = field(default_factory=dict)
    allowed_args: dict = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class PhysOptAttempt:
    """One independently measured phys-opt portfolio member."""

    name: str
    tool_args: dict


def plan_phys_opt_portfolio(
    budget: BudgetState,
    history: Iterable[dict] = (),
    validation: ValidationStatus | None = None,
) -> tuple[PhysOptAttempt, ...]:
    """Return low-to-high-risk phys-opt attempts supported by current evidence."""
    history = tuple(history)
    validation = validation or ValidationStatus()
    attempts = [
        PhysOptAttempt(
            name="RuntimeOptimized",
            tool_args={"directive": "RuntimeOptimized"},
        )
    ]

    prior_gain = any(
        float(
            item.get("delta_vs_peak")
            or item.get("delta_vs_best")
            or item.get("delta_wns")
            or 0.0
        )
        > 0.0
        for item in history
    )
    if not prior_gain:
        return tuple(attempts)

    reserve = budget.validation_reserve_seconds
    hold_pulse_not_failed = (
        validation.hold_passed is not False
        and validation.pulse_width_passed is not False
    )
    if (
        hold_pulse_not_failed
        and budget.remaining_runtime_seconds >= reserve + 300
    ):
        attempts.extend(
            [
                PhysOptAttempt(
                    name="CriticalPin",
                    tool_args={"critical_pin_opt": True},
                ),
                PhysOptAttempt(
                    name="PlacementRouting",
                    tool_args={"placement_opt": True, "routing_opt": True},
                ),
            ]
        )

    if (
        hold_pulse_not_failed
        and budget.remaining_runtime_seconds >= reserve + 600
    ):
        attempts.append(
            PhysOptAttempt(name="Explore", tool_args={"directive": "Explore"})
        )

    clean_hold_pulse = (
        validation.hold_passed is True
        and validation.pulse_width_passed is True
    )
    if (
        clean_hold_pulse
        and budget.remaining_runtime_seconds >= reserve + 900
    ):
        attempts.append(
            PhysOptAttempt(
                name="AggressiveExplore",
                tool_args={"directive": "AggressiveExplore"},
            )
        )

    return tuple(attempts)


def gate_actions(
    signature: DesignSignature,
    budget: BudgetState | None = None,
    history: Iterable[dict] = (),
    validation: ValidationStatus | None = None,
) -> tuple[EligibleAction, ...]:
    """Return only recipes supported by current evidence and remaining budget."""
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

    phys_opt_attempts = plan_phys_opt_portfolio(
        budget,
        history=history,
        validation=validation,
    )
    actions = [
        EligibleAction(
            strategy="PHYS_OPT",
            default_args={"directive": phys_opt_attempts[0].name},
            allowed_args={
                "directive": [attempt.name for attempt in phys_opt_attempts]
            },
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
