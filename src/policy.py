"""Deterministic recipe admissibility gates."""

from dataclasses import dataclass, field
from math import inf
from typing import Iterable

from src.analysis import DesignSignature
from src.scoring import ValidationStatus


MAX_ROUTE_PRESERVE_NETS = 8


def validate_route_net_set(
    net_names: Iterable[str],
    hard_limit: int = MAX_ROUTE_PRESERVE_NETS,
) -> tuple[str, ...]:
    """Validate the bounded net set accepted by the preserved-reroute tool."""
    names = tuple(dict.fromkeys(str(name) for name in net_names if str(name)))
    if len(names) > hard_limit:
        raise ValueError(f"Preserved reroute accepts at most {hard_limit} nets")
    if any(any(character in name for character in "{};\r\n") for name in names):
        raise ValueError("Route net names contain unsupported Tcl characters")
    return names


def select_route_preserve_nets(
    candidates: Iterable[dict],
    *,
    max_nets: int = 4,
    min_net_delay_ns: float = 0.2,
) -> tuple[str, ...]:
    """Select unlocked target-clock nets with delay or congestion evidence."""
    if max_nets < 1 or max_nets > MAX_ROUTE_PRESERVE_NETS:
        raise ValueError(f"max_nets must be between 1 and {MAX_ROUTE_PRESERVE_NETS}")
    eligible = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("net_name")
        and int(candidate.get("critical_path_count", 0)) > 0
        and not bool(candidate.get("is_route_fixed"))
        and not bool(candidate.get("is_clock"))
        and (
            float(candidate.get("net_delay_ns", 0.0)) >= min_net_delay_ns
            or bool(candidate.get("congestion_evidence"))
        )
    ]
    eligible.sort(
        key=lambda candidate: (
            float(candidate.get("net_delay_ns", 0.0)),
            int(candidate.get("critical_path_count", 0)),
        ),
        reverse=True,
    )
    return validate_route_net_set(
        [candidate["net_name"] for candidate in eligible[:max_nets]]
    )


def rank_fanout_candidates(
    candidates: Iterable[dict],
    blacklist: Iterable[str] = (),
) -> tuple[dict, ...]:
    """Rank non-clock fanout evidence by shared critical paths and geography."""
    blocked = set(blacklist)
    eligible = [
        dict(candidate)
        for candidate in candidates
        if candidate.get("net_name") not in blocked
        and not bool(candidate.get("is_clock"))
        and int(candidate.get("critical_path_count", 0)) > 0
    ]
    eligible.sort(
        key=lambda candidate: (
            int(candidate.get("critical_path_count", 0)),
            float(candidate.get("sink_span", 0.0)),
            int(candidate.get("fanout", 0)),
        ),
        reverse=True,
    )
    return tuple(eligible)


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

    if (
        signature.wns_ns is not None
        and signature.wns_ns < 0
        and budget.remaining_runtime_seconds >= budget.validation_reserve_seconds + 120
    ):
        actions.append(
            EligibleAction(
                strategy="CRITICAL_PIN",
                reason="the target clock has negative-slack paths eligible for bounded pin swapping",
            )
        )

    if (
        signature.wns_ns is not None
        and signature.wns_ns < 0
        and signature.congestion
        and bool(signature.congestion.get("severe"))
        and budget.remaining_runtime_seconds >= budget.validation_reserve_seconds + 240
    ):
        actions.append(
            EligibleAction(
                strategy="ROUTE_PRESERVE",
                default_args={"max_nets": 4, "min_net_delay_ns": 0.2},
                reason="target-clock violations coincide with severe routing congestion",
            )
        )

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
                    "max_move_distance": 30,
                },
                reason="target-clock paths have measurable physical spread",
            )
        )

    hard_block_locality_evidence = bool(
        spread is not None and spread.avg_distance >= 80
    )
    if (
        signature.critical_hard_block_types
        and hard_block_locality_evidence
        and budget.remaining_runtime_seconds
        >= budget.validation_reserve_seconds + 300
    ):
        actions.append(
            EligibleAction(
                strategy="HARD_BLOCK",
                default_args={
                    "hard_block_types": list(signature.critical_hard_block_types)
                },
                reason="target-clock critical paths include hard-block resources",
            )
        )

    extreme_spread = bool(
        spread
        and spread.avg_distance >= 120
        and spread.max_distance >= 150
    )
    if (
        spread
        and spread.paths_analyzed >= 5
        and extreme_spread
        and budget.remaining_runtime_seconds >= budget.validation_reserve_seconds + 180
    ):
        actions.append(
            EligibleAction(
                strategy="PBLOCK",
                reason="multiple target-clock paths have extreme physical spread",
            )
        )

    return tuple(actions)
