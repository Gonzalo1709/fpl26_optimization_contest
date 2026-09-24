"""Inspect and verify a deep optimizer run log without loading FPGA dependencies.

Examples:
  python tools/inspect_run.py dcp_optimizer_run-... --verify
  python tools/inspect_run.py dcp_optimizer_run-... --decision decision-...
  python tools/inspect_run.py dcp_optimizer_run-... --evidence <sha256>
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def load_events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evidence_refs(value):
    if isinstance(value, dict):
        if {"sha256", "path", "kind", "bytes"} <= value.keys():
            yield value
        else:
            for item in value.values():
                yield from evidence_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from evidence_refs(item)


def read_evidence(run_dir: Path, ref: dict):
    path = (run_dir / ref["path"]).resolve()
    path.relative_to((run_dir / "evidence").resolve())
    data = gzip.decompress(path.read_bytes())
    digest = hashlib.sha256(data).hexdigest()
    if digest != ref["sha256"] or len(data) != ref["bytes"]:
        raise ValueError(f"Evidence hash or length mismatch: {ref['path']}")
    text = data.decode("utf-8")
    return json.loads(text) if ref["kind"] == "json" else text


def expand_evidence(run_dir: Path, value):
    if isinstance(value, dict):
        if {"sha256", "path", "kind", "bytes"} <= value.keys():
            return {"reference": value, "content": read_evidence(run_dir, value)}
        return {key: expand_evidence(run_dir, item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_evidence(run_dir, item) for item in value]
    return value


def verify_run(run_dir: Path) -> dict:
    events = load_events(run_dir)
    errors = []
    run_ids = {event.get("run_id") for event in events}
    sequences = [event.get("sequence") for event in events]
    if len(run_ids) != 1:
        errors.append("events contain multiple run IDs")
    if sequences != list(range(1, len(events) + 1)):
        errors.append("event sequence has gaps or duplicates")
    refs = {ref["sha256"]: ref for event in events for ref in evidence_refs(event)}
    for ref in refs.values():
        try:
            read_evidence(run_dir, ref)
        except (OSError, ValueError, KeyError, EOFError) as exc:
            errors.append(f"{ref.get('path')}: {exc}")
    summary_path = run_dir / "run_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("run_id") not in run_ids:
            errors.append("run summary ID differs from event ID")
        if summary.get("event_count") != len(events):
            errors.append("run summary event count differs from log")
    return {"ok": not errors, "events": len(events), "evidence_blobs": len(refs),
            "summary_present": summary_path.exists(), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--decision")
    selector.add_argument("--attempt")
    selector.add_argument("--policy")
    selector.add_argument("--candidate")
    selector.add_argument("--event")
    selector.add_argument("--evidence", help="SHA-256 of a stored evidence blob")
    selector.add_argument("--verify", action="store_true")
    parser.add_argument("--expand", action="store_true", help="Inline referenced evidence in selected events")
    args = parser.parse_args()
    if args.verify:
        report = verify_run(args.run_dir)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["ok"] else 1)
    events = load_events(args.run_dir)
    if args.evidence:
        refs = [ref for event in events for ref in evidence_refs(event) if ref["sha256"] == args.evidence]
        if not refs:
            parser.error("evidence SHA-256 is not referenced by this run")
        print(json.dumps(read_evidence(args.run_dir, refs[0]), indent=2, ensure_ascii=False))
        return
    if args.decision:
        policy_ids = {event.get("policy_eval_id") for event in events
                      if event.get("decision_id") == args.decision and event.get("policy_eval_id")}
        events = [event for event in events if event.get("decision_id") == args.decision
                  or event.get("policy_eval_id") in policy_ids]
    elif args.attempt:
        events = [event for event in events if event.get("attempt_id") == args.attempt]
    elif args.policy:
        events = [event for event in events if event.get("policy_eval_id") == args.policy]
    elif args.candidate:
        events = [event for event in events if args.candidate in (
            event.get("candidate_id"), event.get("seed_candidate_id"),
            event.get("parent_candidate_id"), event.get("best_candidate_id"))]
    elif args.event:
        events = [event for event in events if event.get("event") == args.event]
    for event in events:
        print(json.dumps(expand_evidence(args.run_dir, event) if args.expand else event,
                         ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
