"""Disposable browser-test server; optimizer execution is the only stubbed boundary."""
import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn

from framework.web import create_app
from framework.config import file_hash
from tools.create_gui_demo import create_demo


def main():
    with TemporaryDirectory(prefix="optimizer-browser-") as folder:
        root = Path(folder)
        create_demo(root / "history")
        (root / "fixture.dcp").write_bytes(b"synthetic checkpoint for queue tests")
        run = root / "history" / "a-playground-fixture"
        (run / "admission").mkdir(parents=True)
        checkpoint = run / "admission" / "baseline.dcp"
        checkpoint.write_bytes(b"synthetic checkpoint; test scheduler is disabled")
        (run / "events.jsonl").write_text(json.dumps({
            "schema_version": 1, "run_id": "synthetic-playground", "sequence": 1,
            "event": "candidate_admitted", "candidate_id": "baseline", "parent_id": None,
            "metrics": {"wns": -1}, "checkpoint_path": "admission/baseline.dcp",
            "checkpoint_sha256": file_hash(checkpoint),
        }) + "\n")
        (run / "run_summary.json").write_text(json.dumps({
            "schema_version": 1, "status": "completed", "config": {"fixture": True},
            "metrics": {"clock_period_ns": 2, "initial_wns_ns": -1},
        }))
        app = create_app(root / "jobs", [root / "history"])
        with patch.object(app.state.manager, "ensure_scheduler"):
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("OPTIMIZER_TEST_PORT", "8766")), log_level="warning")


if __name__ == "__main__":
    main()
