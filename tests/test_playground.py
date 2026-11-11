"""Manual orchestration contracts; FPGA calls are the only execution boundary."""

import json
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from contextlib import redirect_stdout

from fastapi.testclient import TestClient

from framework.config import file_hash
from framework.web import create_app, run_key
from src.recipe_catalog import PARAMETERS, load_catalog, validate_plan

HEADERS = {"X-Optimizer-Client": "web"}
PLAN = [{"strategy": "PHYS_OPT", "args": {"directive": "Explore"}}]


class CatalogTests(unittest.TestCase):
    def test_builtin_contract_and_drop_in_composition(self):
        repository = Path(__file__).resolve().parents[1]
        catalog = load_catalog(repository / "recipes")
        self.assertEqual(catalog["errors"], [])
        self.assertEqual({r["steps"][0]["strategy"] for r in catalog["recipes"]}, set(PARAMETERS))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recipe = {"schema_version": 1, "id": "my-flow", "name": "My flow", "steps": PLAN * 2}
            (root / "my-flow.json").write_text(json.dumps(recipe))
            self.assertEqual(len(load_catalog(root)["recipes"][0]["steps"]), 2)
            (root / "bad.json").write_text(json.dumps(recipe | {"id": "bad", "steps": [{"strategy": "run_tcl"}]}))
            result = load_catalog(root)
            self.assertEqual(len(result["recipes"]), 1)
            self.assertEqual(result["errors"][0]["file"], "bad.json")

    def test_invalid_arguments_are_rejected_without_silent_substitution(self):
        invalid = [[], PLAN * 33, [{"strategy": "NO_OP"}], [{"strategy": []}],
                   [{"strategy": "PHYS_OPT", "args": {"directive": "typo"}}],
                   [{"strategy": "FANOUT", "args": {"top_n_nets": True}}],
                   [{"strategy": "FANOUT", "args": {"top_n_nets": 10 ** 500}}],
                   [{"strategy": "ROUTE_PRESERVE", "args": {"min_net_delay_ns": float("nan")}}],
                   [{"strategy": "PHYS_OPT", "args": {"command": "untrusted"}}]]
        for plan in invalid:
            with self.subTest(plan=str(plan)[:90]), self.assertRaises(ValueError):
                validate_plan(plan)
        self.assertEqual(validate_plan([{"strategy": "FANOUT"}])[0]["args"], {"top_n_nets": 5})


class PlaygroundApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "history" / "run"
        (self.run / "admission").mkdir(parents=True)
        self.events = [{"event": "baseline_measured", "wns_ns": -1, "clock_period_ns": 2}]
        for candidate, wns, parent in [("baseline", -1, None), ("better", -0.5, "baseline"), ("worse", -1.5, "baseline")]:
            path = self.run / "admission" / f"{candidate}.dcp"
            path.write_bytes(candidate.encode())
            self.events.append({"event": "candidate_admitted", "candidate_id": candidate,
                                "parent_id": parent, "metrics": {"wns": wns},
                                "checkpoint_path": path.relative_to(self.run).as_posix(),
                                "checkpoint_sha256": file_hash(path)})
        self.save_events()
        self.app = create_app(self.root / "jobs", [self.run])
        self.manager = self.app.state.manager
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.key = run_key(self.run)

    def save_events(self):
        for sequence, event in enumerate(self.events, 1):
            event.update(sequence=sequence, schema_version=1, run_id="original")
        (self.run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.events))

    def enqueue(self, candidate="baseline", **extra):
        return self.client.post(f"/api/runs/{self.key}/playground", headers=HEADERS,
                                json={"candidate_id": candidate, "steps": PLAN, "python": sys.executable, **extra})

    def test_theoretical_frequency_gain_is_local_to_each_candidate(self):
        data = self.client.get(f"/api/runs/{self.key}").json()
        nodes = {n["node_id"]: n for n in data["nodes"]}
        self.assertEqual(nodes["baseline"]["fmax_improvement_mhz"], 0)
        self.assertAlmostEqual(nodes["better"]["fmax_improvement_mhz"], 1000 / 2.5 - 1000 / 3)
        self.assertLess(nodes["worse"]["fmax_improvement_mhz"], 0)
        self.events[0].pop("clock_period_ns")
        self.save_events()
        self.assertIsNone(self.client.get(f"/api/runs/{self.key}").json()["nodes"][0]["fmax_improvement_mhz"])

    def test_branch_from_non_best_checkpoint_persists_exact_plan_and_lineage(self):
        checkpoints = self.client.get(f"/api/runs/{self.key}/checkpoints").json()["checkpoints"]
        self.assertTrue(all(c["available"] for c in checkpoints))
        with patch.object(self.manager, "ensure_scheduler") as scheduler:
            result = self.enqueue("worse", steps=PLAN * 2)
        self.assertEqual(result.status_code, 201, result.text)
        scheduler.assert_called_once()
        job = self.manager.get(result.json()["job_id"])
        self.assertEqual(job["config"]["mode"], "manual")
        self.assertEqual(job["config"]["parent_checkpoint"]["candidate_id"], "worse")
        directory = Path(job["directory"])
        plan = json.loads((directory / "manual-plan.json").read_text())
        self.assertEqual(plan["steps"], PLAN * 2)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertIn("--manual-plan", manifest["argv"])
        self.assertNotIn("--model", manifest["argv"])
        self.assertEqual(manifest["manual_plan_sha256"], file_hash(directory / "manual-plan.json"))
        self.assertEqual((self.run / "admission/worse.dcp").read_bytes(), b"worse")

    def test_graph_run_action_requires_a_local_saved_candidate(self):
        self.events.append({"event": "action_selected", "attempt_id": "attempt-only",
                            "seed_candidate_id": "baseline", "strategy": "FANOUT"})
        self.save_events()
        data = self.client.get(f"/api/runs/{self.key}").json()
        nodes = {n["node_id"]: n for n in data["nodes"]}
        self.assertTrue(nodes["worse"]["can_run_from"])
        self.assertFalse(nodes["attempt-only"]["can_run_from"])
        (self.run / "admission/worse.dcp").unlink()
        nodes = self.client.get(f"/api/runs/{self.key}").json()["nodes"]
        worse = next(n for n in nodes if n["node_id"] == "worse")
        self.assertFalse(worse["can_run_from"])
        self.assertIn("missing", worse["checkpoint_unavailable_reason"])
        (self.run / ".imported.json").write_text('{"snapshot":true}')
        self.assertFalse(any(n["can_run_from"] for n in self.client.get(f"/api/runs/{self.key}").json()["nodes"]))

    def test_missing_changed_imported_and_unsafe_checkpoints_cannot_enqueue(self):
        self.assertEqual(self.enqueue("attempt-id").status_code, 400)
        self.assertEqual(self.enqueue(steps=[{"strategy": "FANOUT", "args": {"top_n_nets": 0}}]).status_code, 400)
        (self.run / "admission/baseline.dcp").write_bytes(b"changed")
        self.assertEqual(self.enqueue().status_code, 400)
        self.events[-1]["checkpoint_path"] = "../../outside.dcp"
        self.save_events()
        self.assertEqual(self.enqueue("worse").status_code, 400)
        (self.run / ".imported.json").write_text('{"snapshot":true}')
        self.assertEqual(self.enqueue("better").status_code, 400)
        self.assertEqual(self.manager.list(), [])

    def test_legacy_checkpoint_is_located_by_hash_without_guessing_its_filename(self):
        self.events[1].pop("checkpoint_path")
        self.save_events()
        entries = self.client.get(f"/api/runs/{self.key}/checkpoints").json()["checkpoints"]
        baseline = next(c for c in entries if c["candidate_id"] == "baseline")
        self.assertTrue(baseline["available"])
        with patch.object(self.manager, "ensure_scheduler"):
            result = self.enqueue()
        self.assertEqual(result.status_code, 201, result.text)
        job = self.manager.get(result.json()["job_id"])
        self.assertEqual(Path(job["config"]["input_dcp"]), self.run / "admission/baseline.dcp")
        self.events[1]["checkpoint_sha256"] = "0" * 64
        self.save_events()
        self.assertEqual(self.enqueue().status_code, 400)

    def test_retimed_seed_carries_and_checks_original_golden(self):
        golden = self.run / "admission/golden.dcp"
        golden.write_bytes(b"original golden")
        self.events[2].update(equivalence_proof_ref={"sha256": "proof"},
                              golden_checkpoint_path="admission/golden.dcp",
                              golden_checkpoint_sha256=file_hash(golden))
        self.save_events()
        self.assertEqual(self.enqueue("better").status_code, 400)
        checker = self.root / "checker.json"
        checker.write_text('["checker"]')
        with patch.object(self.manager, "ensure_scheduler"):
            result = self.enqueue("better", advanced={"equivalence_command": str(checker)})
        self.assertEqual(result.status_code, 201, result.text)
        source = self.manager.get(result.json()["job_id"])["config"]["parent_checkpoint"]
        self.assertTrue(source["requires_equivalence"])
        self.assertEqual(source["golden_sha256"], file_hash(golden))
        golden.write_bytes(b"changed")
        self.assertEqual(self.enqueue("better", advanced={"equivalence_command": str(checker)}).status_code, 400)

    def test_worker_rejects_modified_plan_before_starting_fpga_tools(self):
        from framework.worker import run_job
        with patch.object(self.manager, "ensure_scheduler"):
            result = self.enqueue()
        job_id = result.json()["job_id"]
        directory = Path(self.manager.get(job_id)["directory"])
        (directory / "manual-plan.json").write_text("{}")
        with patch("framework.worker.check_environment") as probe:
            run_job(self.manager, job_id)
        probe.assert_not_called()
        self.assertEqual(self.manager.get(job_id)["status"], "failed")
        self.assertIn("Manual plan changed", self.manager.get(job_id)["error"])


class ManualControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from src.llm_optimizer import DCPOptimizer
        from src.policy import EligibleAction
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.optimizer = DCPOptimizer(api_key="test", run_dir=Path(self.temp.name), system_prompt="test")
        self.optimizer._trace = Mock()
        self.optimizer._initialize_search = AsyncMock()
        self.optimizer._baseline_candidate = SimpleNamespace(candidate_id="baseline")
        self.optimizer._restore_candidate_state = AsyncMock()
        self.optimizer._eligible_actions = Mock(return_value=[EligibleAction("PHYS_OPT", allowed_args={"directive": ["Explore"]})])
        self.optimizer._budget_stop_reason = Mock(return_value=None)
        self.optimizer._finish_search = Mock(return_value=True)

    async def test_neutral_and_worse_admitted_states_remain_sequence_parents(self):
        opt = self.optimizer
        parents = []
        async def attempt(parent, *args, **kwargs):
            parents.append(parent.candidate_id)
            opt.history.append({"implementation_passed": True})
            opt.search_candidates.append(SimpleNamespace(candidate_id=f"child-{len(parents)}"))
            return parent  # Automatic search treats a neutral action as seed retention.
        opt._attempt = AsyncMock(side_effect=attempt)
        self.assertTrue(await opt.run_manual_plan(Path("in.dcp"), Path("out.dcp"), PLAN * 2))
        self.assertEqual(parents, ["baseline", "child-1"])
        self.assertEqual(opt._attempt.call_args_list[0].kwargs["decision_context"]["source"], "manual_playground")

    async def test_rejected_step_stops_sequence_and_is_not_reported_as_success(self):
        opt = self.optimizer
        async def reject(parent, *args, **kwargs):
            opt.history.append({"implementation_passed": False, "error": "hold failed"})
            return parent
        opt._attempt = AsyncMock(side_effect=reject)
        self.assertFalse(await opt.run_manual_plan(Path("in.dcp"), Path("out.dcp"), PLAN * 2))
        self.assertEqual(opt._attempt.await_count, 1)
        self.assertIn("hold failed", opt._stop_reason)
        opt._finish_search.assert_called_once()

    async def test_error_after_admission_stops_the_remaining_steps(self):
        opt = self.optimizer
        async def reject(parent, *args, **kwargs):
            opt.history.append({"implementation_passed": True, "error": "evidence refresh failed"})
            return parent
        opt._attempt = AsyncMock(side_effect=reject)
        self.assertFalse(await opt.run_manual_plan(Path("in.dcp"), Path("out.dcp"), PLAN * 2))
        self.assertEqual(opt._attempt.await_count, 1)

    async def test_ineligible_action_and_cancellation_do_not_run_another_recipe(self):
        opt = self.optimizer
        opt._attempt = AsyncMock()
        opt._eligible_actions.return_value = []
        self.assertFalse(await opt.run_manual_plan(Path("in.dcp"), Path("out.dcp"), PLAN))
        opt._attempt.assert_not_awaited()
        opt._budget_stop_reason.return_value = "cancellation requested"
        self.assertFalse(await opt.run_manual_plan(Path("in.dcp"), Path("out.dcp"), PLAN))
        self.assertIn("cancellation requested", opt._stop_reason)

    async def test_saved_candidates_remain_addressable_after_cleanup(self):
        from src.run_logging import RunRecorder
        from src.scoring import ValidationStatus
        from tools.inspect_run import load_events
        opt = self.optimizer
        root = opt.run_dir
        with patch("src.run_logging._source_state", return_value={}):
            opt.run_recorder = RunRecorder(root, "manual", root / "input.dcp", root / "out.dcp")
        # Use the real event projection and checkpoint admission. Only FPGA
        # measurement/validation calls are substituted by fixed tool results.
        del opt._trace
        opt.clock_period = 2
        opt.initial_wns = -1
        opt._baseline_constraint_digest = "constraints"
        opt._initial_port_digest = "ports"
        opt._constraint_digest = AsyncMock(return_value="constraints")
        opt._port_digest = AsyncMock(return_value="ports")
        opt._validate_current_publishable_design = AsyncMock(return_value=ValidationStatus(
            par_routed=True, par_drc_clean=True, hold_passed=True, pulse_width_passed=True))
        opt._measure_current_metrics = AsyncMock(return_value={"wns": -1, "tns": -5, "failing_endpoints": 2})
        opt.v = AsyncMock()
        async def save(path):
            path.write_bytes(path.name.encode())
        opt._save_best_checkpoint = AsyncMock(side_effect=save)
        baseline = await opt._snapshot_candidate("baseline")
        neutral = await opt._snapshot_candidate("neutral", baseline)
        await opt.cleanup()
        events = load_events(root)
        for candidate, event in zip((baseline, neutral), events[1:]):
            self.assertEqual(root / event["checkpoint_path"], candidate.dcp_path)
            self.assertEqual(file_hash(candidate.dcp_path), event["checkpoint_sha256"])

    async def test_cli_manual_plan_needs_no_api_key_and_invokes_manual_runner(self):
        with patch("logging.basicConfig"):
            import dcp_optimizer
        root = self.optimizer.run_dir
        source = root / "source.dcp"
        source.write_bytes(b"checkpoint")
        plan = root / "plan.json"
        plan.write_text(json.dumps({"schema_version": 1, "steps": PLAN, "source": {"candidate_id": "selected"}}))
        runner = SimpleNamespace(_run_id="manual-cli", start_servers=AsyncMock(),
                                 run_manual_plan=AsyncMock(return_value=True), cleanup=AsyncMock())
        argv = ["dcp_optimizer.py", str(source), "--manual-plan", str(plan),
                "--run-dir", str(root / "cli-run"), "--output", str(root / "out.dcp")]
        with patch.object(sys, "argv", argv), patch.object(dcp_optimizer, "DCPOptimizer", return_value=runner), \
                patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), \
                patch("src.run_logging._source_state", return_value={}), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                await dcp_optimizer.main()
        self.assertEqual(result.exception.code, 0)
        runner.run_manual_plan.assert_awaited_once_with(source, root / "out.dcp", PLAN, {"candidate_id": "selected"})
        runner.cleanup.assert_awaited_once()

    async def test_retimed_resume_reproves_baseline_against_original_golden(self):
        from src.scoring import ValidationStatus
        opt = self.optimizer
        root = opt.run_dir
        source, golden = root / "retimed.dcp", root / "original.dcp"
        source.write_bytes(b"retimed")
        golden.write_bytes(b"original")
        opt._manual_source = {"requires_equivalence": True, "golden_path": str(golden), "golden_sha256": file_hash(golden)}
        opt.generation_config.equivalence_command = ("checker",)
        opt.generation_config.outcome_memory_path = None
        opt.clock_period, opt.initial_wns = 2, -0.5
        opt.perform_initial_analysis = AsyncMock(return_value="analysis")
        opt.v = AsyncMock(return_value="FPL26_VERSION=2025.1\nFPL26_PART=test-part")
        opt._constraint_digest = AsyncMock(return_value="constraints")
        opt._port_digest = AsyncMock(return_value="ports")
        opt._current_port_count = AsyncMock(return_value=2)
        opt._measure_current_metrics = AsyncMock(return_value={"wns": -0.5, "tns": -1, "failing_endpoints": 2})
        opt._validate_current_publishable_design = AsyncMock(return_value=ValidationStatus(
            par_routed=True, par_drc_clean=True, hold_passed=True, pulse_width_passed=True))
        async def save(path):
            path.write_bytes(source.read_bytes())
        opt._save_best_checkpoint = AsyncMock(side_effect=save)
        # Restore the real initializer for this integration check.
        del opt._initialize_search
        with patch("src.controller.prove_sequential_equivalence", new_callable=AsyncMock, return_value={"equivalent": True}) as prove:
            await opt._initialize_search(source, root / "result.dcp")
        self.assertEqual(opt._golden_dcp.read_bytes(), b"original")
        self.assertNotEqual(opt._golden_dcp.read_bytes(), source.read_bytes())
        self.assertEqual(prove.await_args.args[1], opt._golden_dcp)
        self.assertTrue(opt._baseline_candidate.equivalence_proof["equivalent"])


if __name__ == "__main__":
    unittest.main()
