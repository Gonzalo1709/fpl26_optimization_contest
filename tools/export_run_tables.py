"""Export one or more optimizer run directories as plot-ready CSV tables.

Usage: python -m tools.export_run_tables --out analysis_tables dcp_optimizer_run-*
"""

import argparse
import csv
import json
from pathlib import Path

from tools.inspect_run import load_events


EVENT_TABLES = {
    "decisions": {"action_selected", "action_sanitized", "decision_skipped"},
    "attempts": {"recipe_attempt", "attempt_aborted", "attempt_returned"},
    "tools": {"tool_call_finished"},
    "llm_calls": {"llm_call_finished"},
    "policy_variants": {"policy_variant"},
    "candidates": {"candidate_admitted", "incumbent_selected", "artifact_published", "publish_rejected"},
    "beams": {"beam_selected"},
}


def flatten(value: dict, prefix: str = "") -> dict:
    row = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict) and name in {"metrics", "usage", "config"}:
            row.update(flatten(item, name + "_"))
        elif isinstance(item, (dict, list)):
            row[name] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        else:
            row[name] = item
    return row


def build_tables(run_dirs: list[Path]) -> dict[str, list[dict]]:
    tables = {name: [] for name in ("runs", "events", *EVENT_TABLES,
                                    "tree_nodes", "tree_edges", "beam_memberships")}
    for run_dir in run_dirs:
        resolved_dir = str(run_dir.resolve())
        summary_path = run_dir / "run_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            tables["runs"].append(flatten(summary) | {"run_dir": resolved_dir})
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            continue
        events = load_events(run_dir)
        decisions = {event["attempt_id"]: event for event in events
                     if event["event"] == "action_selected" and event.get("attempt_id")}
        outcomes = {event["attempt_id"]: event for event in events
                    if event["event"] == "recipe_attempt" and event.get("attempt_id")}
        admitted_attempts = {event["attempt_id"] for event in events
                             if event["event"] == "candidate_admitted" and event.get("attempt_id")}
        aborted_attempts = {event["attempt_id"]: event for event in events
                            if event["event"] == "attempt_aborted" and event.get("attempt_id")}
        refreshed_evidence = {event["candidate_id"]: event for event in events
                              if event["event"] == "evidence_refreshed" and event.get("candidate_id")}
        selected_incumbents = {event["candidate_id"] for event in events
                               if event["event"] == "incumbent_selected" and event.get("candidate_id")}
        published_candidates = {event["candidate_id"] for event in events
                                if event["event"] == "artifact_published" and event.get("candidate_id")}
        rejections = {}
        for event in events:
            if event["event"] == "publish_rejected" and event.get("candidate_id"):
                rejections.setdefault(event["candidate_id"], []).append(event.get("reason"))
        for event in events:
            row = flatten(event) | {"run_dir": resolved_dir}
            tables["events"].append(row)
            for name, kinds in EVENT_TABLES.items():
                if event.get("event") in kinds:
                    tables[name].append(row)
            if event["event"] == "candidate_admitted":
                attempt_id = event.get("attempt_id")
                decision = decisions.get(attempt_id, {})
                outcome = outcomes.get(attempt_id, {})
                evidence = refreshed_evidence.get(event["candidate_id"], {})
                node = row | {
                    "node_id": event["candidate_id"],
                    "node_type": "candidate",
                    "parent_node_id": event.get("parent_id"),
                    "wns_ns": event.get("metrics", {}).get("wns"),
                    "tns_ns": event.get("metrics", {}).get("tns"),
                    "failing_endpoints": event.get("metrics", {}).get("failing_endpoints"),
                    "strategy": decision.get("strategy"),
                    "action_args": json.dumps(decision.get("args"), ensure_ascii=False, sort_keys=True)
                    if decision.get("args") is not None else None,
                    "decision_budget": json.dumps(decision.get("budget"), ensure_ascii=False, sort_keys=True)
                    if decision.get("budget") is not None else None,
                    "alternatives_ref": json.dumps(decision.get("alternatives_ref"), ensure_ascii=False,
                                                    sort_keys=True) if decision.get("alternatives_ref") else None,
                    "selection_source": decision.get("source"),
                    "search_generation": decision.get("generation"),
                    "search_branch": decision.get("branch"),
                    "search_step": decision.get("step"),
                    "recipe_status": outcome.get("status"),
                    "recipe_seconds": outcome.get("recipe_seconds"),
                    "delta_wns_ns": outcome.get("delta_wns_ns"),
                    "outcome_ref": json.dumps(outcome.get("outcome_ref"), ensure_ascii=False,
                                              sort_keys=True) if outcome.get("outcome_ref") else None,
                    "design_evidence_ref": json.dumps(evidence.get("evidence_ref"), ensure_ascii=False,
                                                      sort_keys=True) if evidence.get("evidence_ref") else None,
                    "evidence_unavailable": json.dumps(evidence.get("unavailable"), ensure_ascii=False)
                    if evidence.get("unavailable") is not None else None,
                    "selected_as_incumbent": event["candidate_id"] in selected_incumbents,
                    "published": event["candidate_id"] in published_candidates,
                    "publication_rejections": json.dumps(rejections.get(event["candidate_id"], [])),
                }
                tables["tree_nodes"].append(node)
                if event.get("parent_id"):
                    tables["tree_edges"].append({
                        "run_id": event["run_id"], "run_dir": resolved_dir,
                        "edge_type": "candidate",
                        "source_id": event["parent_id"], "target_id": event["candidate_id"],
                        "decision_id": event.get("decision_id"), "attempt_id": attempt_id,
                        "strategy": decision.get("strategy"),
                        "selection_source": decision.get("source"),
                        "search_generation": decision.get("generation"),
                        "search_branch": decision.get("branch"),
                        "search_step": decision.get("step"),
                        "recipe_status": outcome.get("status"),
                        "recipe_seconds": outcome.get("recipe_seconds"),
                        "delta_wns_ns": outcome.get("delta_wns_ns"),
                        "timestamp_utc": event.get("timestamp_utc"),
                    })
            elif event["event"] == "beam_selected":
                selected = set(event.get("candidate_ids", []))
                for candidate_id in sorted(set(event.get("considered_candidate_ids", [])) | selected):
                    tables["beam_memberships"].append({
                        "run_id": event["run_id"], "run_dir": resolved_dir,
                        "sequence": event["sequence"], "timestamp_utc": event["timestamp_utc"],
                        "stage": event.get("stage"), "generation": event.get("generation"),
                        "candidate_id": candidate_id, "selected": candidate_id in selected,
                    })
        for attempt_id, decision in decisions.items():
            if attempt_id in admitted_attempts:
                continue
            outcome = outcomes.get(attempt_id, {})
            aborted = aborted_attempts.get(attempt_id, {})
            seed_id = decision.get("seed_candidate_id")
            leaf = {
                "run_id": decision["run_id"], "run_dir": resolved_dir,
                "node_id": attempt_id, "node_type": "attempt_without_candidate",
                "parent_node_id": seed_id, "decision_id": decision.get("decision_id"),
                "attempt_id": attempt_id, "strategy": decision.get("strategy"),
                "action_args": json.dumps(decision.get("args"), ensure_ascii=False, sort_keys=True)
                if decision.get("args") is not None else None,
                "decision_budget": json.dumps(decision.get("budget"), ensure_ascii=False, sort_keys=True)
                if decision.get("budget") is not None else None,
                "selection_source": decision.get("source"),
                "search_generation": decision.get("generation"),
                "search_branch": decision.get("branch"), "search_step": decision.get("step"),
                "recipe_status": "aborted" if aborted else outcome.get("status", "no_candidate"),
                "recipe_seconds": outcome.get("recipe_seconds"),
                "outcome_ref": json.dumps(outcome.get("outcome_ref"), ensure_ascii=False,
                                          sort_keys=True) if outcome.get("outcome_ref") else None,
                "error_ref": json.dumps(aborted.get("error_ref"), ensure_ascii=False,
                                        sort_keys=True) if aborted.get("error_ref") else None,
                "timestamp_utc": decision.get("timestamp_utc"),
            }
            tables["tree_nodes"].append(leaf)
            if seed_id:
                tables["tree_edges"].append({
                    "run_id": decision["run_id"], "run_dir": resolved_dir,
                    "edge_type": "attempt_without_candidate",
                    "source_id": seed_id, "target_id": attempt_id,
                    "decision_id": decision.get("decision_id"), "attempt_id": attempt_id,
                    "strategy": decision.get("strategy"),
                    "selection_source": decision.get("source"),
                    "search_generation": decision.get("generation"),
                    "search_branch": decision.get("branch"), "search_step": decision.get("step"),
                    "recipe_status": leaf["recipe_status"],
                    "recipe_seconds": outcome.get("recipe_seconds"),
                    "timestamp_utc": decision.get("timestamp_utc"),
                })
    return tables


def write_tables(tables: dict[str, list[dict]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    first_columns = ["run_id", "sequence", "timestamp_utc", "elapsed_seconds", "event",
                     "decision_id", "attempt_id", "candidate_id", "strategy", "run_dir"]
    for name, rows in tables.items():
        if not rows:
            continue
        columns = [key for key in first_columns if any(key in row for row in rows)]
        columns.extend(sorted({key for row in rows for key in row} - set(columns)))
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    write_tables(build_tables(args.run_dirs), args.out)


if __name__ == "__main__":
    main()
