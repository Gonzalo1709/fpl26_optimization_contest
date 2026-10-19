"""HTTP, live state, and evidence contracts; no Vivado or paid LLM calls."""

import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.run_logging import RunRecorder
from tools.create_gui_demo import create_demo
from tools.run_bundle import export_bundle

WEB_AVAILABLE = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
if WEB_AVAILABLE:
    from fastapi.testclient import TestClient
    from framework.web import create_app, run_key

HEADERS = {"X-Optimizer-Client": "web"}


@unittest.skipUnless(WEB_AVAILABLE, "Install requirements-web.txt and httpx")
class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.demo = create_demo(self.root / "history")
        self.app = create_app(self.root / "jobs", [self.demo])
        self.client = TestClient(self.app)
        self.manager = self.app.state.manager
        self.run = self.demo / "demo-run-1"
        self.key = run_key(self.run)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_history_graph_evidence_and_report(self):
        self.assertEqual(len(self.client.get("/api/runs").json()), 2)
        data = self.client.get(f"/api/runs/{self.key}").json()
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["demo"])
        self.assertEqual(len(data["nodes"]), 4)
        self.assertEqual(len(data["edges"]), 3)
        self.assertEqual(next(n for n in data["nodes"] if n["node_id"] == "a3")["state"], "failed")
        event = next(e for e in data["events"] if "alternatives_ref" in e)
        expanded = self.client.get(f"/api/runs/{self.key}/events/{event['sequence']}/evidence").json()
        self.assertIn("Synthetic policy evidence", expanded["alternatives_ref"]["content"]["note"])
        self.assertEqual(self.client.get(f"/api/runs/{self.key}/events/999/evidence").status_code, 404)
        self.assertEqual(self.client.get("/api/runs/not-a-run").status_code, 404)
        self.assertEqual(self.client.get(f"/api/runs/{self.key}/configuration").status_code, 400)
        report = self.client.get(f"/api/runs/{self.key}/report")
        self.assertIn("attachment", report.headers["content-disposition"])
        self.assertIn("Optimizer experiment report", report.text)

    def test_real_queue_validation_preview_and_cancel(self):
        source = self.root / "design with spaces.dcp"
        source.write_bytes(b"test checkpoint")
        config = {"input_dcp": str(source), "advanced": {"beam_width": 2}}
        preview = self.client.post("/api/configuration/preview", json=config, headers=HEADERS)
        self.assertEqual(preview.status_code, 200)
        self.assertIn(str(source), preview.json()["argv"])
        # The scheduler boundary is suppressed; real SQLite queue/config/hash logic runs.
        with patch.object(self.manager, "ensure_scheduler") as scheduler:
            response = self.client.post("/api/jobs", json=config, headers=HEADERS)
        self.assertEqual(response.status_code, 201)
        scheduler.assert_called_once()
        job_id = response.json()["job_id"]
        self.assertEqual(self.manager.get(job_id)["status"], "queued")
        self.assertTrue((Path(self.manager.get(job_id)["directory"]) / "manifest.json").is_file())
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/cancel", json={}, headers=HEADERS).json()["status"], "cancelled")
        self.assertEqual(self.client.post("/api/jobs", json=config | {"max_runtime_minutes": 0}, headers=HEADERS).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", json=config | {"advanced": {"api_key": "not-allowed"}}, headers=HEADERS).status_code, 400)
        self.assertEqual(len(self.manager.list()), 1)

    def test_browser_origin_and_host_boundaries(self):
        for path in ["/api/jobs", "/api/runs/open"]:
            self.assertEqual(self.client.post(path, json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/runs", headers={"Origin": "https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/runs", headers={"Host": "untrusted.example"}).status_code, 400)
        self.assertEqual(self.client.get("/api/runs", headers={"Origin": "http://testserver"}).status_code, 200)

    def test_upload_cloud_archive_and_restart_local_workspace(self):
        archive = self.root / "cloud.zip"
        export_bundle([self.run, self.demo / "demo-run-2"], archive)
        headers = HEADERS | {"Content-Type": "application/zip", "X-Optimizer-Filename": "cloud.zip"}
        self.assertEqual(self.client.post("/api/runs/import", content=b"not a zip", headers=headers).status_code, 400)
        self.assertEqual(self.client.post("/api/runs/import", json={}, headers=HEADERS).status_code, 415)
        with patch("framework.web.MAX_ARCHIVE_BYTES", 2):
            self.assertEqual(self.client.post("/api/runs/import", content=b"large", headers=headers).status_code, 413)
        response = self.client.post("/api/runs/import", content=archive.read_bytes(), headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["count"], 2)
        key = response.json()["id"]
        data = self.client.get(f"/api/runs/{key}").json()
        self.assertEqual(data["imported"]["source_archive"], "cloud.zip")
        self.assertEqual(len(data["nodes"]), 4)
        event = next(e for e in data["events"] if "alternatives_ref" in e)
        self.assertEqual(self.client.get(f"/api/runs/{key}/events/{event['sequence']}/evidence").status_code, 200)
        self.assertEqual(self.client.get(f"/api/runs/{key}/configuration").status_code, 400)
        self.assertEqual(self.manager.list(), [])
        with TestClient(create_app(self.manager.root, [])) as restarted:
            entries = restarted.get("/api/runs").json()
            self.assertEqual(len([entry for entry in entries if entry["source"] == "imported"]), 2)
            self.assertEqual(restarted.get(f"/api/runs/{key}").status_code, 200)

    def test_analysis_zip_download_and_events_path_open(self):
        response = self.client.get(f"/api/runs/{self.key}/bundle")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertIn("attachment", response.headers["content-disposition"])
        opened = self.client.post("/api/runs/open", json={"path": str(self.run / "events.jsonl")}, headers=HEADERS)
        self.assertEqual(opened.json()["id"], self.key)

    def test_open_folder_and_partial_live_write(self):
        root = self.root / "external"
        recorder = RunRecorder(root / "run", "llm", root / "input.dcp", root / "out.dcp")
        recorder.record("candidate_admitted", candidate_id="root", metrics={"wns": -1})
        opened = self.client.post("/api/runs/open", json={"path": str(root)}, headers=HEADERS)
        self.assertEqual(opened.status_code, 200)
        key = opened.json()["id"]
        with (recorder.run_dir / "events.jsonl").open("a") as handle:
            handle.write('{"unfinished":')
        self.assertEqual(self.client.get(f"/api/runs/{key}").status_code, 200)
        self.assertEqual(self.client.post("/api/runs/open", json={"path": str(self.root / "absent")}, headers=HEADERS).status_code, 400)

    def test_active_attempt_not_failed_and_interrupted_not_running(self):
        run = self.manager.root / "managed" / "run"
        recorder = RunRecorder(run, "llm", self.root / "in.dcp", self.root / "out.dcp")
        recorder.record("candidate_admitted", candidate_id="root", metrics={"wns": -1})
        recorder.record("action_selected", decision_id="d1", attempt_id="a1", seed_candidate_id="root", strategy="PHYS_OPT")
        recorder.record("tool_call_started", call_id="t1", attempt_id="a1", tool_name="phys_opt_design")
        key = run_key(run)
        self.client.get("/api/runs")
        from framework.web import present_snapshot
        from framework import RunService
        running = present_snapshot(RunService(), run, {"status": "running"})
        self.assertEqual(next(n for n in running["nodes"] if n["node_id"] == "a1")["state"], "running")
        self.assertEqual(running["activity"][0]["tool_name"], "phys_opt_design")
        failed = present_snapshot(RunService(), run, {"status": "interrupted"})
        self.assertEqual(next(n for n in failed["nodes"] if n["node_id"] == "a1")["state"], "interrupted")
        self.assertEqual(failed["activity"], [])
        self.assertEqual(self.client.get(f"/api/runs/{key}").json()["status"], "unknown")

    def test_stream_reconnect_reconciles_full_snapshot(self):
        class Connected:
            async def is_disconnected(self):
                return False

        async def exercise():
            self.client.get("/api/runs")
            first = self.app.state.stream(self.key, Connected())
            chunk = await anext(first)
            await first.aclose()
            data = json.loads(chunk.split("data: ", 1)[1])
            self.assertIn(f"id: {data['sequence']}", chunk)
            extra = {"schema_version": 1, "run_id": data["events"][0]["run_id"], "sequence": data["sequence"] + 1, "event": "new_event"}
            with (self.run / "events.jsonl").open("a") as handle:
                handle.write(json.dumps(extra) + "\n")
            second = self.app.state.stream(self.key, Connected())
            chunk = await anext(second)
            await second.aclose()
            reconciled = json.loads(chunk.split("data: ", 1)[1])
            self.assertEqual(reconciled["events"][-1], extra)
            self.assertEqual(len({e["sequence"] for e in reconciled["events"]}), len(reconciled["events"]))
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
