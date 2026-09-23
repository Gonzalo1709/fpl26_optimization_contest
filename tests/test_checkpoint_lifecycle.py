"""Regressions for readable EDIF snapshots and interrupted search publication."""

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.admission import sha256_file
from src.base import DCPOptimizerBase
from src.llm_optimizer import DCPOptimizer
from src.scoring import ValidationStatus
from src.search import GenerationSearchConfig, SearchCandidate


class CheckpointSidecarTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_exports_matching_edif_before_returning(self):
        with tempfile.TemporaryDirectory() as directory:
            dcp = Path(directory) / "snapshot.dcp"
            optimizer = object.__new__(DCPOptimizer)
            calls = []

            async def tool(name, args):
                calls.append(name)
                if name == "write_checkpoint":
                    Path(args["dcp_path"]).write_bytes(b"new checkpoint")
                else:
                    self.assertTrue(dcp.is_file())
                    self.assertEqual(Path(args["edif_path"]), dcp.with_suffix(".edf"))
                    Path(args["edif_path"]).write_text("(edif matching_netlist)")
                return "Written successfully"

            optimizer.v = tool
            self.assertTrue(await optimizer._save_vivado_checkpoint(dcp))
            self.assertEqual(calls, ["write_checkpoint", "write_edif"])

    async def test_missing_edif_rejects_snapshot_and_removes_stale_netlist(self):
        with tempfile.TemporaryDirectory() as directory:
            dcp = Path(directory) / "snapshot.dcp"
            edif = dcp.with_suffix(".edf")
            edif.write_text("stale netlist")
            optimizer = object.__new__(DCPOptimizer)

            async def tool(name, args):
                if name == "write_checkpoint":
                    dcp.write_bytes(b"new checkpoint")
                return "Written successfully"

            optimizer.v = tool
            with self.assertRaisesRegex(RuntimeError, "EDIF sidecar"):
                await optimizer._save_best_checkpoint(dcp)
            self.assertFalse(edif.exists())

    async def test_checkpoint_failure_does_not_export_edif(self):
        with tempfile.TemporaryDirectory() as directory:
            optimizer = object.__new__(DCPOptimizer)
            optimizer.v = AsyncMock(side_effect=RuntimeError("checkpoint failed"))
            with self.assertRaisesRegex(RuntimeError, "checkpoint failed"):
                await optimizer._save_vivado_checkpoint(Path(directory) / "snapshot.dcp")
            optimizer.v.assert_awaited_once()


class ControllerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.optimizer = DCPOptimizer(
            api_key="test", run_dir=self.root,
            generation_config=GenerationSearchConfig(outcome_memory_path=None),
        )
        opt = self.optimizer
        opt.start_time = time.time()
        opt.clock_period = 1.57
        opt.initial_wns = -1.686
        opt._golden_dcp = self.root / "golden.dcp"
        opt._golden_dcp.write_bytes(b"original")
        opt._input_sha256 = sha256_file(opt._golden_dcp)
        opt.output_dcp = self.root / "output.dcp"
        opt._baseline_constraint_digest = "constraints"
        opt._print_optimization_summary = Mock()
        opt._candidate_score_metadata = Mock(return_value={})
        opt._is_candidate_improvement = lambda candidate, best: candidate.wns > best.wns
        opt._baseline_candidate = self.candidate("baseline", -1.686)
        opt._publish_admitted(opt._baseline_candidate)
        self.improved = self.candidate("improved", -1.094)
        opt._initialize_search = AsyncMock(return_value="analysis")
        opt._current_budget_state = Mock(return_value=SimpleNamespace(remaining_runtime_seconds=600.03))
        opt.cleanup = AsyncMock()

    def candidate(self, name, wns):
        path = self.root / (name + ".dcp")
        path.write_bytes(name.encode())
        return SearchCandidate(
            candidate_id=name, dcp_path=path, wns=wns, tns=-1, failing_endpoints=1,
            peak_wns=wns, generation=0, parent_id=None, branch_index=0,
            steps_taken=0, steps_since_peak=0, summary=name,
            validation=ValidationStatus(par_routed=True, par_drc_clean=True,
                                        hold_passed=True, pulse_width_passed=True),
            checkpoint_sha256=sha256_file(path), constraint_sha256="constraints",
        )

    def manifest(self):
        return json.loads((self.root / "published_artifact.json").read_text())

    async def test_search_deadline_finalizes_best_in_session_owner_task(self):
        opt = self.optimizer
        owner = asyncio.current_task()

        async def search(*args, **kwargs):
            opt._publish_admitted(self.improved)
            await asyncio.Event().wait()

        async def cleanup():
            self.assertIs(asyncio.current_task(), owner)

        async def validate(*args):
            opt.cleanup.assert_awaited_once()
            self.assertIs(asyncio.current_task(), owner)
            self.assertEqual(self.manifest()["run_status"], "validating")
            return {"structural_passed": True, "simulation_passed": True}

        opt._search_portfolio = search
        opt.cleanup.side_effect = cleanup
        with patch("src.controller.validate_submission", side_effect=validate):
            self.assertTrue(await opt.optimize(opt._golden_dcp, opt.output_dcp))
        self.assertEqual(opt.output_dcp.read_bytes(), b"improved")
        self.assertEqual(self.manifest()["run_status"], "completed")
        self.assertTrue(self.manifest()["validation"]["simulation_passed"])

    async def test_search_error_is_not_success_with_valid_fallback(self):
        opt = self.optimizer
        opt._initialize_search.side_effect = RuntimeError("RapidWright failed")
        self.assertFalse(await opt.optimize(opt._golden_dcp, opt.output_dcp))
        self.assertEqual(opt.output_dcp.read_bytes(), b"original")
        self.assertEqual(self.manifest()["run_status"], "failed")
        self.assertIn("RapidWright failed", self.manifest()["stop_reason"])

    async def test_cancelled_search_records_both_output_and_best_candidate(self):
        opt = self.optimizer
        started = asyncio.Event()
        opt._current_budget_state.return_value.remaining_runtime_seconds = 3600

        async def search(*args, **kwargs):
            opt._publish_admitted(self.improved)
            started.set()
            await asyncio.Event().wait()

        opt._search_portfolio = search
        task = asyncio.create_task(opt.optimize(opt._golden_dcp, opt.output_dcp))
        await started.wait()
        # The candidate must be recoverable even before graceful interruption.
        self.assertEqual(self.manifest()["search_best_candidate"]["sha256"], self.improved.checkpoint_sha256)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        manifest = self.manifest()
        self.assertEqual(manifest["run_status"], "interrupted")
        self.assertEqual(manifest["sha256"], opt._input_sha256)
        self.assertEqual(manifest["search_best_candidate"]["dcp_path"], str(self.improved.dcp_path))
        self.assertIsNone(manifest["final_validation"])

    async def test_validation_failure_keeps_original_and_recoverable_candidate(self):
        opt = self.optimizer
        opt._publish_admitted(self.improved)
        opt._search_portfolio = AsyncMock()
        with patch("src.controller.validate_submission", side_effect=ValueError("simulation failed")):
            self.assertFalse(await opt.optimize(opt._golden_dcp, opt.output_dcp))
        self.assertEqual(opt.output_dcp.read_bytes(), b"original")
        self.assertEqual(self.manifest()["run_status"], "failed")
        self.assertEqual(self.manifest()["search_best_candidate_id"], "improved")

    async def test_cancelled_validation_never_publishes_unvalidated_candidate(self):
        opt = self.optimizer
        opt._publish_admitted(self.improved)
        opt._search_portfolio = AsyncMock()
        validating = asyncio.Event()

        async def validate(*args):
            validating.set()
            await asyncio.Event().wait()

        with patch("src.controller.validate_submission", side_effect=validate):
            task = asyncio.create_task(opt.optimize(opt._golden_dcp, opt.output_dcp))
            await validating.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(opt.output_dcp.read_bytes(), b"original")
        self.assertEqual(self.manifest()["run_status"], "interrupted")

    async def test_blocked_mcp_process_is_closed_before_deadline_validation(self):
        opt = self.optimizer
        script = self.root / "blocking_server.py"
        marker = self.root / "request_started"
        script.write_text("""
import asyncio
import sys
import time
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("blocking-regression")
@server.list_tools()
async def list_tools():
    return [Tool(name="read_checkpoint", inputSchema={"type": "object"})]
@server.call_tool()
async def call_tool(name, arguments):
    Path(sys.argv[1]).touch()
    time.sleep(60)
    return [TextContent(type="text", text="done")]
async def main():
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())
asyncio.run(main())
""")
        opt._rw_log_file = (self.root / "server.log").open("w")
        opt.cleanup = DCPOptimizerBase.cleanup.__get__(opt)
        try:
            reader, writer = await opt.exit_stack.enter_async_context(stdio_client(
                StdioServerParameters(command=sys.executable, args=[str(script), str(marker)]),
                errlog=opt._rw_log_file,
            ))
            opt.rapidwright_session = await opt.exit_stack.enter_async_context(ClientSession(reader, writer))
            await opt.rapidwright_session.initialize()
            opt._current_budget_state.return_value.remaining_runtime_seconds = 600.3

            async def search(*args, **kwargs):
                opt._publish_admitted(self.improved)
                await opt.rw("read_checkpoint", {"dcp_path": str(self.improved.dcp_path)})

            async def validate(*args):
                self.assertIsNone(opt.rapidwright_session)
                self.assertTrue(marker.exists())
                return {"structural_passed": True, "simulation_passed": True}

            opt._search_portfolio = search
            with patch("src.controller.validate_submission", side_effect=validate):
                self.assertTrue(await opt.optimize(opt._golden_dcp, opt.output_dcp))
            self.assertTrue(opt._tool_session_poisoned)
            self.assertEqual(opt.output_dcp.read_bytes(), b"improved")
        finally:
            await opt.cleanup()
