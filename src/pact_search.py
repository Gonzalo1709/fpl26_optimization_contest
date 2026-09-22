"""Bounded physical diversity and evidence-backed enabling moves.

Exploration selection is deliberately independent of publication ranking.
"""

import math
from dataclasses import dataclass


def physical_features(candidate):
    evidence = candidate.evidence or {}
    spread = evidence.get("path_spread") or {}
    congestion = evidence.get("congestion") or {}
    anatomy = evidence.get("timing_anatomy") or {}
    nets = evidence.get("high_fanout_candidates") or []
    values = {
        "spread": spread.get("avg_distance"),
        "congestion": congestion.get("max_level"),
        "route_fraction": anatomy.get("avg_route_delay_pct"),
        "fanout": max((n.get("fanout", 0) for n in nets), default=None),
    }
    return {k: float(v) for k, v in values.items()
            if isinstance(v, (float, int)) and math.isfinite(v)}


def physical_distance(left, right):
    a, b = physical_features(left), physical_features(right)
    common = a.keys() & b.keys()
    if len(common) < 2:
        return 0.0  # Missing evidence never earns diversity credit.
    scales = {"spread": 100, "congestion": 5, "route_fraction": 100, "fanout": 500}
    return math.sqrt(sum(((a[k] - b[k]) / scales[k]) ** 2 for k in common) / len(common))


def diverse_beam(candidates, width, rank, enabled=True):
    unique = {c.checkpoint_sha256: c for c in candidates if c.validation.implementation_passed}
    ordered = sorted(unique.values(), key=rank, reverse=True)
    if not enabled or width <= 1:
        return ordered[:width]
    selected = ordered[:1]
    remaining = ordered[1:max(width * 3, width)]
    while remaining and len(selected) < width:
        chosen = max(remaining, key=lambda c: (min(physical_distance(c, s) for s in selected), rank(c)))
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


@dataclass
class EnablingMove:
    candidate: object
    followup: str
    reason: str
    deadline: float
    depth: int


class EnablingPool:
    def __init__(self, capacity=4, max_depth=2, lifetime=600, max_regression_ns=.01):
        self.capacity = capacity
        self.max_depth = max_depth
        self.lifetime = lifetime
        self.max_regression_ns = max_regression_ns
        self.moves = {}
        self.depths = {}
        self.events = []

    def retain(self, parent, child, strategy, now):
        if self.capacity <= 0 or not child.validation.implementation_passed:
            return False
        if child.wns < parent.wns - self.max_regression_ns:
            return False
        depth = self.depths.get(parent.checkpoint_sha256, 0) + 1
        if depth > self.max_depth:
            return False
        before, after = physical_features(parent), physical_features(child)
        reason = None
        for key, fraction in (("spread", .05), ("fanout", .1), ("congestion", .1)):
            if key in before and key in after and before[key] > 0 and after[key] <= before[key] * (1-fraction):
                reason = f"{key} reduced from {before[key]:.3f} to {after[key]:.3f}"
                break
        if reason is None or strategy not in {"PATH_LOCAL_REPLACE", "PARTIAL_REPLACE", "TARGETED_REPLICATION", "CELL_RELOCATE", "PBLOCK"}:
            return False
        key = child.checkpoint_sha256
        if key in self.moves:
            return False
        while len(self.moves) >= self.capacity:
            old = next(iter(self.moves))
            self.events.append({"state": old, "status": "retired_capacity"})
            del self.moves[old]
        self.moves[key] = EnablingMove(child, "CRITICAL_NET_REROUTE", reason, now+self.lifetime, depth)
        self.depths[key] = depth
        self.events.append({"state": key, "status": "retained", "reason": reason, "depth": depth})
        return True

    def take(self, now):
        active = []
        for key, move in list(self.moves.items()):
            del self.moves[key]
            expired = now >= move.deadline
            self.events.append({"state": key, "status": "expired" if expired else "followup_selected"})
            if not expired:
                active.append(move)
        return active
