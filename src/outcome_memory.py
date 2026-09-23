"""Persistent, feature-based recipe outcomes. No benchmark-name retrieval."""

import json
import math
import sqlite3
import statistics
import time
from pathlib import Path


def usable_record(row: object) -> bool:
    if not isinstance(row, dict) or row.get("schema_version", 1) != 1:
        return False
    if not isinstance(row.get("strategy"), str) or not isinstance(row.get("args"), dict):
        return False
    features = row.get("features")
    if not isinstance(features, dict) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in features.values()):
        return False
    for name in ("elapsed_seconds", "llm_cost_usd"):
        value = row.get(name)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return False
    gain = row.get("delta_fmax_mhz")
    return gain is None or (isinstance(gain, (int, float)) and math.isfinite(gain))


def feature_vector(signature) -> dict:
    if signature is None:
        return {}
    spread = signature.path_spread
    anatomy = signature.timing_anatomy or {}
    period = signature.clock_period_ns
    wns = signature.wns_ns
    raw = {
        "log_cells": math.log1p(signature.primitive_cell_count) if signature.primitive_cell_count is not None else None,
        "log_failing": math.log1p(signature.failing_endpoints) if signature.failing_endpoints is not None else None,
        "spread": spread.avg_distance / 100 if spread else None,
        "route_fraction": anatomy.get("avg_route_delay_pct", 0) / 100 if anatomy else None,
        "frequency_ratio": period / (period - wns) if period and wns is not None and period > wns else None,
        "log_fanout": math.log1p(max((net.fanout for net in signature.high_fanout_candidates), default=0)),
    }
    return {key: float(value) for key, value in raw.items()
            if value is not None and math.isfinite(value)}


def feature_distance(left: dict, right: dict) -> float:
    common = left.keys() & right.keys()
    if len(common) < 3:
        return math.inf
    scales = {"log_cells": 2, "log_failing": 2, "log_fanout": 2}
    return math.sqrt(sum(((left[key] - right[key]) / scales.get(key, 1)) ** 2
                         for key in common) / len(common))


class OutcomeMemory:
    """SQLite transactions preserve concurrent appenders and interrupted runs.

    A record attributes an outcome to a complete controller recipe, not to the
    last Tcl call. Only outcomes with affirmative implementation validation
    supply positive gain. Failed and invalid attempts still teach cost/risk.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS outcomes (id INTEGER PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def append(self, record: dict):
        payload = {"schema_version": 1, **record}
        if not usable_record(payload):
            raise ValueError("Outcome does not satisfy the finite, versioned memory schema")
        with self.connect() as db:
            db.execute("INSERT INTO outcomes(created,payload) VALUES (?,?)",
                       (time.time(), json.dumps(payload, allow_nan=False, sort_keys=True)))

    def records(self, limit: int = 5000) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM outcomes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        records = []
        for row in rows:
            try:
                payload = json.loads(row[0])
                if usable_record(payload):
                    records.append(payload)
            except (ValueError, TypeError):
                continue
        return records


def forecast(records: list[dict], features: dict, strategy: str, args: dict,
             tool_version: str | None = None, part: str | None = None) -> dict | None:
    neighbors = []
    for row in records:
        if row.get("tool_session_uncertain") is True:
            # Interrupted recipes remain auditable but have censored runtimes.
            continue
        if row.get("llm_cost_verified") is False:
            continue
        if row.get("strategy") != strategy or row.get("args") != args:
            continue
        # Different tool releases can change directive behavior substantially.
        if tool_version and row.get("tool_version") != tool_version:
            continue
        if part and row.get("part") != part:
            continue
        distance = feature_distance(features, row.get("features", {}))
        if (distance <= 0.6 and isinstance(row.get("elapsed_seconds"), (int, float))
                and math.isfinite(row["elapsed_seconds"]) and row["elapsed_seconds"] >= 0):
            neighbors.append((distance, row))
    samples = [row for _, row in sorted(neighbors, key=lambda pair: pair[0])[:20]]
    if not samples:
        return None
    gains = [max(0.0, row.get("delta_fmax_mhz") or 0.0) if row.get("implementation_passed") is True else 0.0
             for row in samples]
    mean = statistics.fmean(gains)
    stderr = statistics.stdev(gains) / math.sqrt(len(gains)) if len(gains) > 1 else math.inf
    durations = sorted(max(0.0, row["elapsed_seconds"]) for row in samples)
    # Runtime includes analysis, checks and checkpoint I/O, not just the transform.
    p90 = durations[min(len(durations) - 1, math.ceil(0.9 * len(durations)) - 1)]
    return {
        "samples": len(samples), "expected_gain_mhz": mean,
        "optimistic_gain_mhz": mean + 2 * stderr if math.isfinite(stderr) else None,
        "seconds": p90, "cost_usd": statistics.fmean(row.get("llm_cost_usd", 0.0) for row in samples),
        "success_rate": sum(gain > 0 for gain in gains) / len(gains),
    }
