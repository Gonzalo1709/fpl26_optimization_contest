"""Separate sunk-cost artifact ranking from incremental exploration decisions."""

import math


def break_even_gain(bank_gain_mhz: float, penalty: float,
                    seconds: float, dollars: float) -> float:
    if not all(math.isfinite(v) for v in (bank_gain_mhz, penalty, seconds, dollars)):
        return math.inf
    additional_penalty = 0.1 * (max(0, seconds) / 3600 + max(0, dollars))
    if penalty <= additional_penalty:
        return math.inf
    return max(0, bank_gain_mhz) * additional_penalty / (penalty - additional_penalty)


def forecast_admission(estimate: dict | None, *, bank_gain_mhz: float,
                       penalty: float, available_seconds: float, available_dollars: float,
                       incumbent_deficit_mhz: float = 0.0,
                       min_samples: int = 3) -> tuple[bool, str]:
    """Unknown gains permit exploration; well-observed negative ROI does not.

    Use an optimistic gain bound to avoid stopping on a noisy mean. Costs are
    still feasibility constraints when gain is unknown.
    """
    if estimate is None:
        return True, "no comparable outcomes; exploration remains eligible"
    seconds, dollars = estimate["seconds"], estimate["cost_usd"]
    if seconds > available_seconds or dollars > available_dollars:
        return False, "measured cost does not fit the remaining budget and reserve"
    optimistic = estimate.get("optimistic_gain_mhz")
    if estimate["samples"] < min_samples or optimistic is None:
        return True, "insufficient comparable outcomes for an economic stop"
    hurdle = max(0, incumbent_deficit_mhz) + break_even_gain(bank_gain_mhz, penalty, seconds, dollars)
    if optimistic <= hurdle:
        return False, f"optimistic gain {optimistic:.3f} MHz does not exceed break-even {hurdle:.3f} MHz"
    return True, f"optimistic gain {optimistic:.3f} MHz exceeds break-even {hurdle:.3f} MHz"
