"""Service contracts and real detached process lifecycle checks without FPGA tools."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from framework import JobManager, RunConfig, RunService
from framework.config import expand_sweep
from src.run_logging import RunRecorder


class ConfigurationTests(unittest.TestCase):
    def test_optimizer_cli_contract_and_empty_run_directory_gate(self):
        from src.llm_optimizer import SUPPORTED_SINGLE_METHODS
        from framework.config import METHODS
        self.assertEqual(set(METHODS), set(SUPPORTED_SINGLE_METHODS))
        repository = Path(__file__).resolve().parents[1]
        help_result = subprocess.run([sys.executable, str(repository / "dcp_optimizer.py"), "--help"], capture_output=True, text=True, timeout=15)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--run-dir", help_result.stdout)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            marker = run / "existing.txt"
            marker.write_text("preserve")
            result = subprocess.run([sys.executable, str(repository / "dcp_optimizer.py"), "missing.dcp", "--run-dir", str(run)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertIn("empty directory", result.stderr)
            self.assertEqual(marker.read_text(), "preserve")

    def test_invalid_settings_and_argv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "design with spaces.dcp"
            source.write_bytes(b"checkpoint")
            config = RunConfig(str(source), advanced={"branches": 2, "debug": True})
            argv = config.argv(root, root / "out.dcp")
            self.assertIn(str(source), argv)
            self.assertIn("--no-llm", argv)
            self.assertIn("--run-dir", argv)
            for setting in ({"api_key": "secret"}, {"branches": 0}, {"branches": 1.5}, {"debug": 1}, []):
                with self.assertRaises(ValueError):
                    RunConfig(str(source), advanced=setting).validate()
            for budget in (0, -1, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    RunConfig(str(source), max_runtime_minutes=budget).validate()
            configs = expand_sweep(config, [str(source)], {"profile": ["fast", "quality"], "beam_width": [1, 2]})
            self.assertEqual(len(configs), 4)
            self.assertEqual({item.advanced["beam_width"] for item in configs}, {1, 2})
            self.assertNotIn("beam_width", config.advanced)
            with self.assertRaises(ValueError):
                expand_sweep(config, [str(source)], {"profile": ["fast"] * 257})

    def test_queue_persistence_presets_and_atomic_batch_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "design.dcp"
            source.write_bytes(b"checkpoint")
            manager = JobManager(root / "jobs")
            config = RunConfig(str(source))
            with self.assertRaises(ValueError):
                manager.enqueue([config, RunConfig("missing.dcp")], start=False)
            self.assertEqual(manager.list(), [])
            job_id = manager.enqueue([config], start=False)[0]
            reopened = JobManager(manager.root)
            self.assertEqual(reopened.get(job_id)["status"], "queued")
            reopened.cancel(job_id)
            self.assertEqual(manager.get(job_id)["status"], "cancelled")
            manager.save_config("fast-design", config)
            self.assertEqual(manager.presets()["fast-design"].input_dcp, str(source))
            with self.assertRaises(ValueError):
                manager.save_config("../escape", config)


class RunServiceTests(unittest.TestCase):
    def test_live_cost_and_cooperative_optimizer_boundary(self):
        from unittest.mock import patch
        from src.llm_optimizer import DCPOptimizer
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recorder = RunRecorder(root, "generations", root / "input.dcp", root / "output.dcp", {"model": "test-model", "no_llm": False, "budget_profile": "quality"})
            recorder.record("llm_call_finished", usage={"cost": 0.03}, cost_verified=True)
            service = RunService()
            snapshot = service.snapshot(root)
            self.assertEqual(service.monitor(snapshot)["cost_usd"], 0.03)
            self.assertEqual(service.configuration(snapshot).profile, "quality")
            recorder.record("llm_call_finished", usage=None, cost_verified=False)
            self.assertIsNone(service.monitor(service.snapshot(root))["cost_usd"])
            cancel = root / "cancel.request"
            cancel.touch()
            with patch.dict(os.environ, {"OPTIMIZER_CANCEL_FILE": str(cancel)}):
                optimizer = DCPOptimizer(api_key="test", run_dir=root / "optimizer")
                self.assertEqual(optimizer._budget_stop_reason(), "cancellation requested")

    def test_monitor_comparison_links_and_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runs = []
            for index in range(2):
                source = root / f"design-{index}.dcp"
                source.write_bytes(bytes([index]))
                run = root / f"run-{index}"
                recorder = RunRecorder(run, "generations", source, root / "output.dcp")
                recorder.record("candidate_admitted", candidate_id="baseline", metrics={"wns": -0.5})
                recorder.record("action_selected", decision_id="d1", attempt_id="a1", strategy="PHYS_OPT", budget={"remaining_runtime_seconds": 100})
                recorder.record("candidate_admitted", candidate_id="child", parent_id="baseline", attempt_id="a1", decision_id="d1", metrics={"wns": -0.2})
                recorder.record("candidate_admitted", candidate_id="worse", parent_id="baseline", metrics={"wns": -0.8})
                recorder.finish("completed")
                runs.append(run)
            service = RunService()
            snapshot = service.snapshot(runs[0])
            monitor = service.monitor(snapshot)
            self.assertEqual(monitor["best_wns_ns"], -0.2)
            self.assertEqual([point["best_wns_ns"] for point in monitor["timing"]], [-0.5, -0.2, -0.2])
            self.assertIsNone(monitor["validated_score"])
            node = next(node for node in snapshot["tables"]["tree_nodes"] if node["node_id"] == "child")
            self.assertIn("action_selected", {event["event"] for event in service.linked_events(snapshot, node)})
            comparison = service.compare(runs)
            self.assertIn("Selected runs have different input checkpoint values.", comparison["warnings"])
            self.assertIn("Some tool version values are unknown.", comparison["warnings"])
            self.assertIn("Optimizer experiment report", service.report(runs[0]))
            with zipfile.ZipFile(io.BytesIO(service.export_tables(runs))) as archive:
                self.assertIn("tree_nodes.csv", archive.namelist())
                self.assertIn("runs.csv", archive.namelist())


STUB = '''import argparse,json,os,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("input");p.add_argument("--output");p.add_argument("--run-dir");p.add_argument("--model",default="");a,_=p.parse_known_args()
run=Path(a.run_dir);run.mkdir(parents=True,exist_ok=True)
Path(a.output).write_bytes(b"published-baseline")
(run/"executions.txt").open("a").write("once\\n")
child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
(run/"child.json").write_text(json.dumps({"pid":child.pid}))
(run/"events.jsonl").write_text(json.dumps({"schema_version":1,"sequence":1,"run_id":"stub","event":"run_started"})+"\\n")
print("stub started",flush=True)
deadline=time.time()+(30 if a.model in {"wait","stubborn"} else 1)
while time.time()<deadline and (a.model=="stubborn" or not Path(os.environ["OPTIMIZER_CANCEL_FILE"]).exists()): time.sleep(.05)
(run/"run_summary.json").write_text(json.dumps({"schema_version":1,"status":"completed","metrics":{}}))
sys.exit(7 if a.model=="fail" else 0)
'''


class DetachedWorkerTests(unittest.TestCase):
    def setUp(self):
        import psutil
        self.psutil = psutil
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.manager = JobManager(self.root / "jobs")
        self.source = self.root / "input.dcp"
        self.source.write_bytes(b"checkpoint")
        self.stub = self.root / "stub.py"
        self.stub.write_text(STUB, encoding="utf-8")

    def tearDown(self):
        from framework.worker import cleanup_processes, process_identity
        for row in self.manager.list():
            for prefix in ("child", "worker"):
                process = process_identity(row[f"{prefix}_pid"], row[f"{prefix}_created"])
                if process:
                    cleanup_processes([process, *process.children(recursive=True)])
        metadata = self.manager.root / "scheduler.json"
        if metadata.exists():
            identity = json.loads(metadata.read_text(encoding="utf-8"))
            process = process_identity(identity["pid"], identity["created"])
            if process:
                cleanup_processes([process])
        self.folder.cleanup()

    def queue_stub(self, mode=""):
        job_id = self.manager.enqueue([RunConfig(str(self.source), model=mode)], start=False)[0]
        path = Path(self.manager.get(job_id)["directory"]) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["argv"][2] = str(self.stub)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return job_id

    def wait_for(self, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        self.fail(f"Timed out: {self.manager.list()}")

    def test_concurrency_failure_and_duplicate_scheduler_launch(self):
        from framework.jobs import TERMINAL
        self.manager.set_concurrency(2)
        ids = [self.queue_stub(), self.queue_stub("fail"), self.queue_stub()]
        self.manager.ensure_scheduler()
        self.manager.ensure_scheduler()
        self.wait_for(lambda: all(self.manager.get(job_id)["status"] in TERMINAL for job_id in ids))
        rows = [self.manager.get(job_id) for job_id in ids]
        self.assertEqual([row["status"] for row in rows], ["completed", "failed", "completed"])
        self.assertEqual(rows[1]["exit_code"], 7)
        for row in rows:
            run = Path(row["directory"]) / "run"
            self.assertEqual((run / "executions.txt").read_text(), "once\n")
            pid = json.loads((run / "child.json").read_text())["pid"]
            self.assertFalse(self.psutil.pid_exists(pid))
        boundaries = [(row["started"], 1) for row in rows] + [(row["finished"], -1) for row in rows]
        active = maximum = 0
        for _, delta in sorted(boundaries):
            active += delta
            maximum = max(maximum, active)
        self.assertEqual(maximum, 2)

    def test_cooperative_cancel_preserves_published_checkpoint(self):
        job_id = self.queue_stub("wait")
        self.manager.ensure_scheduler()
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "running" and (Path(self.manager.get(job_id)["directory"]) / "run" / "child.json").exists())
        self.manager.cancel(job_id)
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "cancelled")
        directory = Path(self.manager.get(job_id)["directory"])
        self.assertEqual((directory / "optimized.dcp").read_bytes(), b"published-baseline")
        pid = json.loads((directory / "run" / "child.json").read_text())["pid"]
        self.assertFalse(self.psutil.pid_exists(pid))

    def test_input_change_and_missing_handle_recovery(self):
        from framework.worker import process_identity
        job_id = self.queue_stub()
        self.source.write_bytes(b"changed")
        self.manager.ensure_scheduler()
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "failed")
        self.assertIn("checkpoint changed", self.manager.get(job_id)["error"])
        second = self.queue_stub()
        self.manager.update(second, status="running", worker_pid=99999999, worker_created=1, started=time.time())
        self.wait_for(lambda: self.manager.get(second)["status"] == "interrupted")
        self.assertIsNone(process_identity(os.getpid(), 0))
        self.assertFalse((Path(self.manager.get(second)["directory"]) / "run").exists())

    def test_forced_cancellation_of_stuck_process_preserves_output(self):
        job_id = self.queue_stub("stubborn")
        code = "from pathlib import Path; import sys; from framework.jobs import JobManager; from framework.worker import run_job; run_job(JobManager(Path(sys.argv[1])),sys.argv[2],cancellation_grace=.2,interrupt_grace=.2)"
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        supervisor = subprocess.Popen([sys.executable, "-c", code, str(self.manager.root), job_id], cwd=self.manager.repository, **options)
        directory = Path(self.manager.get(job_id)["directory"])
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "running" and (directory / "run" / "child.json").exists())
        self.manager.cancel(job_id)
        supervisor.wait(timeout=15)
        self.assertEqual(self.manager.get(job_id)["status"], "cancelled")
        self.assertEqual((directory / "optimized.dcp").read_bytes(), b"published-baseline")
        pid = json.loads((directory / "run" / "child.json").read_text())["pid"]
        self.assertFalse(self.psutil.pid_exists(pid))

    @unittest.skipUnless(os.name == "nt", "Windows Job Object crash containment")
    def test_supervisor_crash_kills_descendants_without_rerunning(self):
        job_id = self.queue_stub("wait")
        self.manager.ensure_scheduler()
        directory = Path(self.manager.get(job_id)["directory"])
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "running" and (directory / "run" / "child.json").exists())
        row = self.manager.get(job_id)
        worker = self.psutil.Process(row["worker_pid"])
        worker.kill()
        worker.wait(timeout=5)
        self.wait_for(lambda: self.manager.get(job_id)["status"] == "interrupted")
        pid = json.loads((directory / "run" / "child.json").read_text())["pid"]
        self.assertFalse(self.psutil.pid_exists(pid))
        self.assertEqual((directory / "run" / "executions.txt").read_text(), "once\n")


if __name__ == "__main__":
    unittest.main()
