"""Offline integration checks for links between decisions, attempts and tools."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from src.llm_optimizer import DCPOptimizer
from src.policy import BudgetState, EligibleAction
from src.run_logging import RunRecorder
from src.search import GenerationSearchConfig
from src.test_modes import run_test_mode
from tools.inspect_run import load_events, read_evidence, verify_run
from tools.export_run_tables import build_tables


class DeepRunLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.optimizer = DCPOptimizer(
            api_key="test-secret", run_dir=self.root,
            generation_config=GenerationSearchConfig(outcome_memory_path=None),
        )
        self.optimizer.run_recorder = RunRecorder(
            self.root, "generations", self.root / "input.dcp", self.root / "output.dcp",
            run_id=self.optimizer._run_id, secret_values=("test-secret",),
        )

    async def test_attempt_and_tool_share_ids_and_recall_payloads(self):
        optimizer = self.optimizer
        parent = SimpleNamespace(candidate_id="baseline", checkpoint_sha256="seed-hash")

        async def attempt_impl(*args, **kwargs):
            result = await optimizer.call_tool("rapidwright_probe", {"value": 4})
            self.assertEqual(result, '{"ok": true}')
            return parent

        optimizer._attempt_impl = attempt_impl
        optimizer._current_budget_state = Mock(return_value=BudgetState(1000, 1, 60))
        optimizer.rapidwright_session = SimpleNamespace(
            call_tool=AsyncMock(return_value=SimpleNamespace(
                content=[SimpleNamespace(text='{"ok": true}')], isError=False)))

        result = await optimizer._attempt(parent, "PHYS_OPT", {"directive": "Default"},
                                          decision_context={"decision_id": "decision-test",
                                                            "source": "ranked_policy"})
        self.assertIs(result, parent)
        events = load_events(self.root)
        selected = next(event for event in events if event["event"] == "action_selected")
        tool = next(event for event in events if event["event"] == "tool_call_finished")
        returned = next(event for event in events if event["event"] == "attempt_returned")
        self.assertEqual(selected["decision_id"], tool["decision_id"])
        self.assertEqual(selected["attempt_id"], tool["attempt_id"])
        self.assertEqual(returned["attempt_id"], tool["attempt_id"])
        self.assertEqual(read_evidence(self.root, tool["arguments_ref"]), {"value": 4})
        self.assertEqual(read_evidence(self.root, tool["result_ref"]), '{"ok": true}')
        optimizer.run_recorder.finish("completed", optimizer)
        self.assertTrue(verify_run(self.root)["ok"])

    async def test_planner_request_response_and_usage_are_recoverable(self):
        optimizer = self.optimizer
        optimizer._current_budget_state = Mock(return_value=BudgetState(1000, 1, 60))
        optimizer.openai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content='{"strategy":"PHYS_OPT","args":{"directive":"Default"}}'),
                    finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=9,
                                      total_tokens=29, cost=0.01),
            )))))
        action = await optimizer.choose_action_llm({"available_strategies": {"PHYS_OPT": {}}},
                                                    decision_id="decision-planner")
        self.assertEqual(action["strategy"], "PHYS_OPT")
        events = load_events(self.root)
        request = next(event for event in events if event["event"] == "llm_call_started")
        response = next(event for event in events if event["event"] == "llm_call_finished")
        self.assertEqual(request["call_id"], response["call_id"])
        self.assertEqual(response["usage"]["total_tokens"], 29)
        self.assertEqual(response["decision_id"], "decision-planner")
        self.assertIn("Decision input", read_evidence(self.root, request["request_ref"])["user"])
        self.assertEqual(json.loads(read_evidence(self.root, response["response_ref"])), action)

    async def test_aer_search_loop_exports_candidate_lineage_and_beam(self):
        optimizer = self.optimizer
        cfg = optimizer.generation_config
        cfg.deterministic_steps = 0
        cfg.max_generations = 1
        cfg.branch_factor = 1
        cfg.max_steps_per_branch = 1
        cfg.beam_width = 1
        cfg.max_llm_calls = 0
        root = SimpleNamespace(candidate_id="baseline", checkpoint_sha256="root-hash",
                               wns=-0.5, peak_wns=-0.5, steps_since_peak=0)
        child = SimpleNamespace(candidate_id="child", checkpoint_sha256="child-hash",
                                wns=-0.2, peak_wns=-0.2, steps_since_peak=0)
        optimizer._baseline_candidate = optimizer.best_candidate = root
        optimizer._restore_candidate_state = AsyncMock()
        optimizer._should_stop_for_budget = Mock(return_value=False)
        optimizer._candidate_sort_key = Mock(side_effect=lambda candidate: candidate.wns)
        optimizer._eligible_actions = Mock(return_value=(
            EligibleAction("PHYS_OPT", default_args={"directive": "Default"}),))
        optimizer._actions_for_candidate = Mock(return_value=(EligibleAction("NO_OP"),))
        optimizer.run_recorder.record("candidate_admitted", candidate_id="baseline", parent_id=None,
                                      metrics={"wns": -0.5}, generation=0)

        async def admit_child(*args, **kwargs):
            optimizer.run_recorder.record("candidate_admitted",
                                          decision_id=optimizer._active_decision_id,
                                          attempt_id=optimizer._active_attempt_id,
                                          candidate_id="child", parent_id="baseline",
                                          metrics={"wns": -0.2}, generation=1)
            return child

        optimizer._attempt_impl = admit_child
        await optimizer._search_portfolio("analysis", generations=True)
        events = load_events(self.root)
        action = next(event for event in events if event["event"] == "action_selected")
        admitted = next(event for event in events if event.get("candidate_id") == "child"
                        and event["event"] == "candidate_admitted")
        self.assertEqual(action["source"], "ranked_policy")
        self.assertEqual(action["attempt_id"], admitted["attempt_id"])
        self.assertEqual(action["decision_id"], admitted["decision_id"])
        self.assertTrue(any(event["event"] == "beam_selected" and
                            "child" in event["candidate_ids"] for event in events))
        self.assertEqual(build_tables([self.root])["tree_edges"][0]["source_id"], "baseline")

    async def test_unsupported_test_design_still_has_failed_run_summary(self):
        run_dir = self.root / "test-mode"
        recorder = RunRecorder(run_dir, "test", self.root / "custom.dcp",
                               self.root / "output.dcp")
        code = await run_test_mode(self.root / "custom.dcp", self.root / "output.dcp",
                                   run_dir=run_dir, recorder=recorder)
        self.assertEqual(code, 1)
        summary = json.loads((run_dir / "run_summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["error_type"], "UnsupportedDesign")
        self.assertTrue(verify_run(run_dir)["ok"])


if __name__ == "__main__":
    unittest.main()
