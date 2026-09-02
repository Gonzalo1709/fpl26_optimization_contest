"""Tests for bounded, outcome-oriented LLM planner context."""

import json
import sys
import tempfile
import types
import unittest

# These tests exercise context compaction only; installing the live OpenRouter
# client is not required for that deterministic behavior.
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub
if "mcp" not in sys.modules:
    mcp_stub = types.ModuleType("mcp")
    client_stub = types.ModuleType("mcp.client")
    session_stub = types.ModuleType("mcp.client.session")
    stdio_stub = types.ModuleType("mcp.client.stdio")
    session_stub.ClientSession = object
    stdio_stub.StdioServerParameters = object
    stdio_stub.stdio_client = object
    sys.modules.update(
        {
            "mcp": mcp_stub,
            "mcp.client": client_stub,
            "mcp.client.session": session_stub,
            "mcp.client.stdio": stdio_stub,
        }
    )

from src.llm_optimizer import DCPOptimizer, PLANNER_CONTEXT_MAX_CHARS


class PlannerContextTests(unittest.TestCase):
    def test_compact_history_preserves_measured_outcomes_without_raw_error(self):
        optimizer = DCPOptimizer.__new__(DCPOptimizer)
        history = optimizer._compact_history(
            [
                {
                    "iteration": 4,
                    "strategy": "FANOUT",
                    "args": {"top_n_nets": 2},
                    "delta_wns": 0.12549,
                    "delta_tns": 42.6,
                    "delta_failing_endpoints": -9,
                    "elapsed_seconds": 221.44,
                    "roi_accepted": True,
                },
                {
                    "iteration": 5,
                    "strategy": "PBLOCK",
                    "error": "Pblock resource validation failed after a verbose tool report",
                },
            ]
        )

        self.assertEqual(history[0]["outcome"], "improved")
        self.assertEqual(history[0]["seconds"], 221.4)
        self.assertEqual(history[0]["roi"], "accepted")
        self.assertEqual(history[1]["outcome"], "failed")
        self.assertEqual(history[1]["failure_kind"], "resource")
        self.assertNotIn("error", history[1])

    def test_context_fitting_keeps_valid_json_below_input_budget(self):
        payload = {
            "branch_context": "x" * 5000,
            "recent_candidates": "x" * 5000,
            "history": [{"strategy": "PBLOCK", "args": {"raw": "x" * 5000}}],
            "fanout_blacklist": {"examples": ["x" * 5000]},
            "available_strategies": {"PBLOCK": {"args": {}, "evidence": "x" * 5000}},
            "evidence": {"fanout": ["x" * 5000], "physical": {"path_spread": "x" * 5000}},
        }

        fitted = DCPOptimizer._fit_planner_context(payload)
        encoded = json.dumps(fitted, separators=(",", ":"), ensure_ascii=True)

        self.assertLessEqual(len(encoded), PLANNER_CONTEXT_MAX_CHARS)
        self.assertEqual(fitted["history"], [{"strategy": "PBLOCK"}])

    def test_new_recipe_arguments_are_bounded(self):
        optimizer = DCPOptimizer.__new__(DCPOptimizer)
        self.assertEqual(
            optimizer._sanitize_action_shape(
                {"strategy": "PHYS_OPT_REROUTE", "args": {"directive": "not-a-directive"}}
            ),
            ("PHYS_OPT_REROUTE", {"directive": "RuntimeOptimized"}),
        )
        self.assertEqual(
            optimizer._sanitize_action_shape(
                {"strategy": "PLACEMENT_SHOT", "args": {"directive": "ExtraTimingOpt"}}
            ),
            ("PLACEMENT_SHOT", {"directive": "ExtraTimingOpt"}),
        )


class RQSPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rqs_preparation_only_enables_rqs_on_explicit_success_marker(self):
        optimizer = DCPOptimizer.__new__(DCPOptimizer)
        with tempfile.TemporaryDirectory() as temporary_directory:
            optimizer.temp_dir = temporary_directory
            calls = []

            async def fake_v(name, args):
                calls.append((name, args))
                return "report output\nFPL26_RQS_READY=1\n"

            optimizer.v = fake_v
            self.assertTrue(await optimizer._prepare_rqs_strategy())

        self.assertEqual(calls[0][0], "run_tcl")
        self.assertIn("write_qor_suggestions", calls[0][1]["command"])
        self.assertIn("read_qor_suggestions", calls[0][1]["command"])


if __name__ == "__main__":
    unittest.main()
