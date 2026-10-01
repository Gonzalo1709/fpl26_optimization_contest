"""Versioned run queries, monitoring, comparisons, and portable reports."""

import csv
import html
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from tools.export_run_tables import build_tables
from tools.inspect_run import expand_evidence, load_events


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


class RunService:
    def discover(self, root: Path) -> list[Path]:
        root = Path(root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Run folder does not exist: {root}")
        if (root / "events.jsonl").is_file():
            return [root]
        # Include framework-managed jobs without recursively traversing FPGA projects.
        runs = {path.parent for pattern in ("*/events.jsonl", "*/run/events.jsonl")
                for path in root.glob(pattern)}
        return sorted(runs, key=lambda path: str(path), reverse=True)

    def snapshot(self, run: Path):
        run = Path(run)
        events = load_events(run, live=True)
        if any(not isinstance(event, dict) or event.get("schema_version", 1) != 1 for event in events):
            raise ValueError("Unsupported event schema; upgrade the run reader")
        summary = read_json(run / "run_summary.json")
        if summary.get("schema_version", 1) != 1:
            raise ValueError("Unsupported summary schema")
        return {"run": run, "events": events, "summary": summary,
                "artifact": read_json(run / "published_artifact.json"),
                "manifest": read_json(run.parent / "manifest.json"),
                "tables": build_tables([run], live=True)}

    def monitor(self, snapshot):
        events, summary = snapshot["events"], snapshot["summary"]
        candidates = [event for event in events if event["event"] == "candidate_admitted"]
        metrics = summary.get("metrics", {})
        measured = [(event, event.get("metrics", {}).get("wns")) for event in candidates
                    if event.get("metrics", {}).get("wns") is not None]
        timing = []
        best = None
        for event, wns in measured:
            best = wns if best is None else max(best, wns)
            timing.append({"sequence": event["sequence"], "elapsed_seconds": event.get("elapsed_seconds"),
                           "candidate_wns_ns": wns, "best_wns_ns": best})
        decisions = [event for event in events if event["event"] == "action_selected"]
        beams = [event for event in events if event["event"] == "beam_selected"]
        budget_events = [event for event in events if isinstance(event.get("budget"), dict)]
        usage = summary.get("usage", {})
        calls = [event for event in events if event["event"] == "llm_call_finished"]
        costs = [event["usage"].get("cost") if isinstance(event.get("usage"), dict) else None for event in calls]
        cost = usage.get("cost_usd")
        if cost is None and costs and all(value is not None for value in costs):
            cost = sum(costs)
        return {"status": summary.get("status", "No final summary"),
                "elapsed_seconds": summary.get("runtime_seconds", events[-1].get("elapsed_seconds") if events else None),
                "initial_wns_ns": metrics.get("initial_wns_ns", measured[0][1] if measured else None),
                "best_wns_ns": best, "final_wns_ns": metrics.get("final_wns_ns"),
                "final_fmax_mhz": metrics.get("final_fmax_mhz"),
                "projected_score": metrics.get("projected_score"), "validated_score": metrics.get("validated_score"),
                "cost_usd": cost, "llm_calls": usage.get("llm_calls", len(calls)),
                "cost_verified": usage.get("cost_verified", all(event.get("cost_verified", False) for event in calls) if calls else None),
                "current_action": decisions[-1] if decisions else {},
                "latest_beam": beams[-1] if beams else {},
                "budget": budget_events[-1]["budget"] if budget_events else {}, "timing": timing}

    def linked_events(self, snapshot, node):
        candidate_id = node.get("candidate_id")
        attempt_id = node.get("attempt_id")
        decision_id = node.get("decision_id")
        policy_ids = {event.get("policy_eval_id") for event in snapshot["events"]
                      if decision_id and event.get("decision_id") == decision_id}
        return [event for event in snapshot["events"]
                if (candidate_id and candidate_id in [event.get(key) for key in ("candidate_id", "seed_candidate_id", "parent_candidate_id", "best_candidate_id")])
                or (attempt_id and event.get("attempt_id") == attempt_id)
                or (decision_id and event.get("decision_id") == decision_id)
                or (event.get("policy_eval_id") and event.get("policy_eval_id") in policy_ids)]

    def evidence(self, run, event):
        return expand_evidence(Path(run), event)

    def compare(self, runs):
        snapshots = [self.snapshot(Path(run)) for run in runs]
        rows = []
        for snapshot in snapshots:
            summary = snapshot["summary"]
            monitor = self.monitor(snapshot)
            source = next((event for event in snapshot["events"] if event["event"] == "run_started"), {})
            rows.append({"run": str(snapshot["run"]), "input_dcp": summary.get("input_dcp", source.get("input_dcp")),
                         "input_sha256": summary.get("input_sha256", source.get("input_identity", {}).get("sha256")),
                         "tool_version": summary.get("tool_version", snapshot["artifact"].get("tool_version")),
                         "status": monitor["status"], "initial_wns_ns": monitor["initial_wns_ns"],
                         "final_wns_ns": monitor["final_wns_ns"], "best_wns_ns": monitor["best_wns_ns"],
                         "final_fmax_mhz": monitor["final_fmax_mhz"],
                         "projected_score": monitor["projected_score"], "validated_score": monitor["validated_score"],
                         "output_validated": summary.get("output_validated"), "cost_usd": monitor["cost_usd"],
                         "runtime_seconds": monitor["elapsed_seconds"]})
        warnings = []
        for key, label in [("input_sha256", "input checkpoint"), ("tool_version", "tool version"), ("output_validated", "validation status")]:
            values = {row[key] for row in rows}
            if None in values:
                warnings.append(f"Some {label} values are unknown.")
            if len(values - {None}) > 1:
                warnings.append(f"Selected runs have different {label} values.")
        configs = {str(snapshot["run"]): snapshot["manifest"].get("config", snapshot["summary"].get("config", {})) for snapshot in snapshots}
        return {"rows": rows, "warnings": warnings, "configurations": configs}

    def report(self, run):
        snapshot = self.snapshot(Path(run))
        monitor = self.monitor(snapshot)
        data = {"schema_version": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(), "run": str(run), "summary": snapshot["summary"],
                "artifact": snapshot["artifact"], "manifest": snapshot["manifest"], "monitor": monitor}
        body = html.escape(json.dumps(data, indent=2, ensure_ascii=False))
        return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Optimizer experiment report</title>"
                "<style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px}pre{white-space:pre-wrap;background:#f3f5f7;padding:20px}</style>"
                "<h1>Optimizer experiment report</h1><p>Timing gain and validated score are separate measurements. "
                "Unknown values remain null. Referenced evidence is available in the original run.</p><pre>" + body + "</pre></html>")

    def export_tables(self, runs):
        """Portable ZIP of derived CSV tables, preserving original logs separately."""
        tables = build_tables([Path(run) for run in runs], live=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, rows in tables.items():
                if not rows:
                    continue
                stream = io.StringIO()
                writer = csv.DictWriter(stream, sorted({key for row in rows for key in row}))
                writer.writeheader()
                writer.writerows(rows)
                archive.writestr(f"{name}.csv", stream.getvalue())
        return buffer.getvalue()

    def configuration(self, snapshot):
        """Recover supported CLI settings, leaving final validation to the caller."""
        from framework.config import RunConfig, INTEGER_OPTIONS, NONNEGATIVE_OPTIONS, CHOICE_OPTIONS
        if snapshot["manifest"].get("config"):
            return RunConfig.from_dict(snapshot["manifest"]["config"])
        summary = snapshot["summary"]
        source = next((event for event in snapshot["events"] if event["event"] == "run_started"), {})
        recorded = summary.get("config", source.get("config", {}))
        generation = recorded.get("generation_config", {})
        advanced = {key: value for key, value in generation.items()
                    if key in INTEGER_OPTIONS | NONNEGATIVE_OPTIONS | CHOICE_OPTIONS.keys() and value is not None}
        aliases = {"branch_factor": "branches", "max_generations": "generations", "max_steps_per_branch": "steps_per_branch", "max_steps_without_improvement": "steps_without_improvement"}
        advanced.update({new: generation[old] for old, new in aliases.items() if old in generation})
        if advanced.get("max_llm_calls") == 0:
            advanced.pop("max_llm_calls")
        mode = "test" if summary.get("mode", source.get("mode")) == "test" else "single" if recorded.get("method") else "deterministic" if recorded.get("no_llm") else "llm"
        config = RunConfig(input_dcp=summary.get("input_dcp", source.get("input_dcp", "")), mode=mode,
                           profile=recorded.get("budget_profile", "fast"), model=recorded.get("model", ""),
                           method=recorded.get("method", "PHYS_OPT"), advanced=advanced,
                           max_runtime_minutes=generation.get("max_runtime_minutes") or 60,
                           max_cost=generation.get("max_cost"))
        return config.validate(check_files=False)
