"""The run record must remain readable after normal and failed runs."""

import json
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.run_logging import RunRecorder, new_run_dir
from tools.export_run_tables import build_tables, write_tables
from tools.inspect_run import expand_evidence, read_evidence, verify_run
from tools.export_search_tree import build_dot, build_mermaid, build_svg


class FakeOptimizer:
    initial_wns = -0.5
    best_wns = float("-inf")
    clock_period = 2.5
    llm_call_count = 0
    total_cost = 0.0
    tool_call_details = []

    @staticmethod
    def calculate_fmax(wns, period):
        return 1000 / (period - wns) if wns is not None and period is not None else None


class RunLoggingTests(unittest.TestCase):
    def test_search_tree_exports_candidates_failed_attempts_and_beam(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_dir = new_run_dir(root)
            recorder = RunRecorder(run_dir, "generations", root / "input.dcp", root / "output.dcp")
            recorder.record("candidate_admitted", candidate_id="root", parent_id=None,
                            metrics={"wns": -0.5}, generation=0)
            recorder.record("action_selected", decision_id="d1", attempt_id="a1",
                            seed_candidate_id="root", strategy="PHYS_OPT", source="llm_planner",
                            generation=0, branch=0, step=0, args={"directive": "Default"})
            recorder.record("candidate_admitted", candidate_id="child", parent_id="root",
                            decision_id="d1", attempt_id="a1", metrics={"wns": -0.2},
                            generation=1, summary='a | "quoted" <name>')
            recorder.record("recipe_attempt", decision_id="d1", attempt_id="a1",
                            status="measured", delta_wns_ns=0.3, recipe_seconds=2.5)
            recorder.record("evidence_refreshed", candidate_id="child", unavailable=["congestion"],
                            evidence_ref=recorder.capture({"path_spread": {"avg_distance": 12}}))
            recorder.record("action_selected", decision_id="d2", attempt_id="a2",
                            seed_candidate_id="root", strategy="RETIME", source="ranked_policy")
            recorder.record("attempt_aborted", decision_id="d2", attempt_id="a2",
                            error_type="TimeoutError")
            recorder.record("beam_selected", stage="generation_end", generation=0,
                            considered_candidate_ids=["root", "child"], candidate_ids=["child"])
            tables = build_tables([run_dir])
            self.assertEqual({row["node_id"] for row in tables["tree_nodes"]},
                             {"root", "child", "a2"})
            self.assertEqual({(row["source_id"], row["target_id"])
                              for row in tables["tree_edges"]}, {("root", "child"), ("root", "a2")})
            self.assertEqual(next(row for row in tables["tree_nodes"] if row["node_id"] == "child")
                             ["strategy"], "PHYS_OPT")
            self.assertEqual([row["selected"] for row in tables["beam_memberships"]
                              if row["candidate_id"] == "child"], [True])
            self.assertIn('root', build_dot(run_dir))
            svg = build_svg(run_dir)
            ET.fromstring(svg)
            self.assertIn('<svg', svg)
            self.assertIn('PHYS_OPT +0.300 ns', svg)
            self.assertIn('attempt without candidate', svg)
            mermaid = build_mermaid(run_dir)
            self.assertIn('flowchart LR', mermaid)
            self.assertIn('n0 -->|PHYS_OPT +0.300 ns| n1', mermaid)
            self.assertIn('wns_ns: -0.2', mermaid)
            self.assertIn('summary: a #124; #quot;quoted#quot; #60;name#62;', mermaid)
            self.assertIn('action_args: {#quot;directive#quot;: #quot;Default#quot;}', mermaid)
            self.assertIn('design_evidence_ref:', mermaid)
            self.assertIn('class n1 beam;', mermaid)

    def test_unique_directories_and_failed_run_are_machine_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = new_run_dir(root)
            second = new_run_dir(root)
            self.assertNotEqual(first, second)
            input_dcp = root / "input.dcp"
            input_dcp.write_bytes(b"checkpoint")
            recorder = RunRecorder(first, "generations", input_dcp, root / "output.dcp",
                                   {"model": "example"}, run_id="shared-id")
            recorder.record("baseline_measured", wns_ns=-0.5)
            recorder.finish("failed", FakeOptimizer(), "ToolExecutionError")
            recorder.finish("completed", FakeOptimizer())

            events = [json.loads(line) for line in (first / "events.jsonl").read_text().splitlines()]
            summary = json.loads((first / "run_summary.json").read_text())
            self.assertEqual([event["sequence"] for event in events], [1, 2, 3])
            self.assertEqual([event["event"] for event in events],
                             ["run_started", "baseline_measured", "run_finished"])
            self.assertTrue(all(event["run_id"] == summary["run_id"] == "shared-id" for event in events))
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["output_exists"])
            self.assertIsNone(summary["metrics"]["final_wns_ns"])
            self.assertIsNone(summary["metrics"]["final_fmax_mhz"])
            self.assertEqual(summary["event_count"], 3)
            self.assertTrue(math.isfinite(summary["runtime_seconds"]))

    def test_evidence_can_be_recalled_verified_and_exported_without_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_dir = new_run_dir(root)
            recorder = RunRecorder(run_dir, "generations", root / "input.dcp",
                                   root / "output.dcp",
                                   config={"command": "Bearer sk-very-secret"},
                                   secret_values=("sk-very-secret",))
            ref = recorder.capture({"api_key": "sk-very-secret",
                                    "request": "Bearer sk-very-secret",
                                    "decision": {"strategy": "PHYS_OPT"}})
            self.assertEqual(ref, recorder.capture({"api_key": "sk-very-secret",
                                                    "request": "Bearer sk-very-secret",
                                                    "decision": {"strategy": "PHYS_OPT"}}))
            recorder.record("action_selected", decision_id="decision-1", attempt_id="attempt-1",
                            strategy="PHYS_OPT", decision_input_ref=ref,
                            note="key=sk-very-secret")
            recorder.finish("interrupted")

            recovered = read_evidence(run_dir, ref)
            self.assertEqual(recovered["api_key"], "[REDACTED]")
            self.assertEqual(recovered["request"], "Bearer [REDACTED]")
            self.assertEqual(recovered["decision"]["strategy"], "PHYS_OPT")
            self.assertTrue(verify_run(run_dir)["ok"])
            self.assertNotIn("sk-very-secret", (run_dir / "events.jsonl").read_text())
            self.assertNotIn("sk-very-secret", (run_dir / "run_summary.json").read_text())
            selected = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()][1]
            self.assertEqual(expand_evidence(run_dir, selected)["decision_input_ref"]["content"], recovered)
            tables = build_tables([run_dir])
            self.assertEqual(tables["decisions"][0]["decision_id"], "decision-1")
            self.assertEqual(tables["runs"][0]["status"], "interrupted")
            write_tables(tables, root / "analysis")
            self.assertIn("decision-1", (root / "analysis" / "decisions.csv").read_text())

            (run_dir / ref["path"]).write_bytes(b"tampered")
            self.assertFalse(verify_run(run_dir)["ok"])


if __name__ == "__main__":
    unittest.main()
