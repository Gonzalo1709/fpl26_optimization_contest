"""Disposable browser-test server; optimizer execution is the only stubbed boundary."""
import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import nullcontext
from unittest.mock import patch

import uvicorn

from framework.web import create_app
from framework.config import file_hash
from src.run_logging import RunRecorder
from tools.create_gui_demo import create_demo


def seed_history(root):
    create_demo(root / "history")
    (root / "fixture.dcp").write_bytes(b"synthetic checkpoint for queue tests")
    run = root / "history" / "Workshop example"
    (run / "admission").mkdir(parents=True)
    checkpoint = run / "admission" / "baseline.dcp"
    checkpoint.write_bytes(b"synthetic checkpoint; test scheduler is disabled")
    events = [{
        "schema_version": 1, "run_id": "synthetic-playground", "sequence": 1,
        "event": "candidate_admitted", "candidate_id": "baseline", "parent_id": None,
        "generation": 0, "metrics": {"wns": -1}, "checkpoint_path": "admission/baseline.dcp",
        "checkpoint_sha256": file_hash(checkpoint),
    }]
    middle = run / "admission" / "middle.dcp"
    middle.write_bytes(b"synthetic intermediate checkpoint")
    events.append({"event": "action_selected", "attempt_id": "auto-middle", "seed_candidate_id": "baseline", "generation": 1, "strategy": "PHYS_OPT", "source": "llm"})
    events.append({
        "schema_version": 1, "run_id": "synthetic-playground", "sequence": 2,
        "event": "candidate_admitted", "candidate_id": "middle", "parent_id": "baseline",
        "attempt_id": "auto-middle",
        "metrics": {"wns": -1.5}, "checkpoint_path": "admission/middle.dcp",
        "checkpoint_sha256": file_hash(middle),
    })
    tip = run / "admission" / "automatic-result.dcp"
    tip.write_bytes(b"synthetic automatic continuation")
    events.extend([
        {"event": "recipe_attempt", "attempt_id": "auto-middle", "status": "measured"},
        {"event": "action_selected", "attempt_id": "auto-tip", "seed_candidate_id": "middle", "generation": 2, "strategy": "ROUTE_PRESERVE", "source": "llm"},
        {"event": "candidate_admitted", "candidate_id": "automatic-result", "parent_id": "middle", "attempt_id": "auto-tip", "metrics": {"wns": -.7}, "checkpoint_path": "admission/automatic-result.dcp", "checkpoint_sha256": file_hash(tip)},
        {"event": "recipe_attempt", "attempt_id": "auto-tip", "status": "measured"},
    ])
    for sequence, event in enumerate(events, 1):
        event.update(sequence=sequence, run_id="synthetic-workshop", schema_version=1)
    (run / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (run / "run_summary.json").write_text(json.dumps({
        "schema_version": 1, "status": "completed", "config": {"fixture": True},
        "best_candidate_id": "automatic-result",
        "metrics": {"clock_period_ns": 2, "initial_wns_ns": -1, "final_fmax_mhz": 1000 / 2.7},
    }))


def main():
    existing = os.environ.get("OPTIMIZER_DEMO_ROOT")
    with (nullcontext(existing) if existing else TemporaryDirectory(prefix="optimizer-browser-")) as folder:
        root = Path(folder)
        if not existing:
            seed_history(root)
        app = create_app(root / "jobs", [root / "history"])

        @app.post("/__test__/manual/{job_id}/{phase}")
        def advance_manual(job_id: str, phase: str):
            # Only this disposable fixture exposes synthetic worker transitions.
            manager = app.state.manager
            job = manager.get(job_id)
            if phase == "running":
                manager.update(job_id, status="running")
            elif phase == "completed":
                config = job["config"]
                directory = Path(job["directory"]) / "run"
                (directory / "admission").mkdir(parents=True, exist_ok=True)
                source = config["parent_checkpoint"]
                source_events = [json.loads(line) for line in (Path(source["run_path"]) / "events.jsonl").read_text().splitlines()]
                seed = next(e for e in source_events if e.get("candidate_id") == source["candidate_id"] and e["event"] == "candidate_admitted")
                initial = seed["metrics"]["wns"]
                recorder = RunRecorder(directory, "manual", Path(config["input_dcp"]), directory.parent / "optimized.dcp")
                recorder.record("baseline_measured", wns_ns=initial, clock_period_ns=2)
                baseline = directory / "admission" / "baseline.dcp"
                baseline.write_bytes(b"synthetic reloaded baseline")
                recorder.record("candidate_admitted", candidate_id="baseline", parent_id=None, generation=0, metrics={"wns": initial}, checkpoint_path="admission/baseline.dcp", checkpoint_sha256=file_hash(baseline))
                parent = "baseline"
                for index, step in enumerate(config["manual_plan"], 1):
                    candidate = f"manual-result-{index}"
                    checkpoint = directory / "admission" / f"{candidate}.dcp"
                    checkpoint.write_bytes(f"synthetic manual result {job_id} {index}".encode())
                    attempt = f"attempt-{index}"
                    recorder.record("action_selected", attempt_id=attempt, decision_id=f"decision-{index}", seed_candidate_id=parent, generation=index, strategy=step["strategy"], args=step["args"], source="manual_workshop", alternatives_ref=recorder.capture({"note": "Manual branch fixture evidence"}))
                    recorder.record("candidate_admitted", candidate_id=candidate, parent_id=parent, generation=index, attempt_id=attempt, decision_id=f"decision-{index}", metrics={"wns": initial + index * .55}, checkpoint_path=f"admission/{candidate}.dcp", checkpoint_sha256=file_hash(checkpoint))
                    recorder.record("recipe_attempt", attempt_id=attempt, status="measured")
                    parent = candidate
                manager.update(job_id, status="completed")
            return {"status": manager.get(job_id)["status"]}

        with patch.object(app.state.manager, "ensure_scheduler"):
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("OPTIMIZER_TEST_PORT", "8766")), log_level="warning")


if __name__ == "__main__":
    main()
