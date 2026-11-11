"""Resolve recorded admitted checkpoints without guessing files from names."""

import math
from functools import lru_cache
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


def legacy_candidates(run):
    root = run.resolve()
    folder = (root / "admission").resolve()
    if folder.is_relative_to(root):
        for candidate in sorted(folder.glob("*.dcp")):
            path = candidate.resolve()
            if path.is_relative_to(root) and path.is_file():
                yield path


@lru_cache(maxsize=256)
def legacy_digest(path, size, modified):
    # Discovery is cached, never admission: enqueue re-hashes the selected bytes.
    return file_hash(path)


def checkpoint_path(run, event, field="checkpoint_path", *, locate_legacy=False):
    relative = event.get(field)
    if not relative and field == "checkpoint_path" and locate_legacy and event.get("checkpoint_sha256"):
        for candidate in legacy_candidates(run):
            status = candidate.stat()
            if legacy_digest(candidate, status.st_size, status.st_mtime_ns) == event["checkpoint_sha256"]:
                return candidate
        raise ValueError("The saved checkpoint matching this node is missing")
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
    path = checkpoint_path(run, event, locate_legacy=True)
    if not event.get("checkpoint_sha256") or file_hash(path) != event["checkpoint_sha256"]:
        raise ValueError("Checkpoint bytes differ from their admitted identity")
    if event.get("equivalence_proof_ref"):
        golden = checkpoint_path(run, event, "golden_checkpoint_path")
        if not event.get("golden_checkpoint_sha256") or file_hash(golden) != event["golden_checkpoint_sha256"]:
            raise ValueError("Original equivalence checkpoint is missing or changed")
    return path, event


def checkpoint_options(run, snapshot):
    """Cheap availability for graph actions; checksums are verified on enqueue."""
    imported = (run / ".imported.json").is_file()
    demo = snapshot["summary"].get("config", {}).get("demo") or any(
        e.get("config", {}).get("demo") for e in snapshot["events"])
    entries = []
    legacy_available = not imported and not demo and any(legacy_candidates(run))
    for event in snapshot["events"]:
        if event["event"] != "candidate_admitted":
            continue
        reason = None
        try:
            if imported:
                raise ValueError("Analysis ZIPs do not include checkpoint binaries")
            if demo:
                raise ValueError("This demo has no saved checkpoints")
            if event.get("checkpoint_path") or not legacy_available:
                checkpoint_path(run, event)
            if not event.get("checkpoint_sha256"):
                raise ValueError("Checkpoint has no recorded checksum")
            if event.get("equivalence_proof_ref"):
                checkpoint_path(run, event, "golden_checkpoint_path")
        except ValueError as exc:
            reason = str(exc)
        entries.append({"candidate_id": event["candidate_id"], "available": reason is None,
                        "reason": reason, "checkpoint_sha256": event.get("checkpoint_sha256")})
    return entries
