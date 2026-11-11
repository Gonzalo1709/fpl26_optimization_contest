"""Resolve recorded admitted checkpoints without guessing files from names."""

import math
from pathlib import Path

from framework.config import file_hash
from src.scoring import target_clock_fmax_mhz


def node_frequencies(snapshot):
    metrics = snapshot["summary"].get("metrics", {})
    events = snapshot["events"]
    period = metrics.get("clock_period_ns") or next((e.get("clock_period_ns") for e in events if e["event"] == "baseline_measured"), None)
    initial = metrics.get("initial_wns_ns")
    if initial is None:
        initial = next((e.get("metrics", {}).get("wns") for e in events if e["event"] == "candidate_admitted" and not e.get("parent_id")), None)

    def frequency(wns):
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (period, wns)):
            return None
        value = target_clock_fmax_mhz(period, wns)
        return value if value is not None and math.isfinite(value) else None

    return frequency, frequency(initial)


def checkpoint_path(run, event, field="checkpoint_path"):
    relative = event.get(field)
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("This run has no recorded checkpoint path; legacy logs cannot locate checkpoint bytes reliably")
    root = run.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".dcp" or not path.is_file():
        raise ValueError("Checkpoint is missing or outside the run directory")
    return path


def resolve_checkpoint(run, snapshot, candidate_id):
    if (run / ".imported.json").is_file():
        raise ValueError("Imported analysis snapshots do not include checkpoint binaries")
    if snapshot["summary"].get("config", {}).get("demo") or any(e.get("config", {}).get("demo") for e in snapshot["events"]):
        raise ValueError("Synthetic demonstrations cannot launch real experiments")
    event = next((e for e in snapshot["events"] if e["event"] == "candidate_admitted" and e.get("candidate_id") == candidate_id), None)
    if event is None:
        raise ValueError("Choose an admitted candidate checkpoint")
    path = checkpoint_path(run, event)
    if not event.get("checkpoint_sha256") or file_hash(path) != event["checkpoint_sha256"]:
        raise ValueError("Checkpoint bytes differ from their admitted identity")
    if event.get("equivalence_proof_ref"):
        golden = checkpoint_path(run, event, "golden_checkpoint_path")
        if not event.get("golden_checkpoint_sha256") or file_hash(golden) != event["golden_checkpoint_sha256"]:
            raise ValueError("Original equivalence checkpoint is missing or changed")
    return path, event
