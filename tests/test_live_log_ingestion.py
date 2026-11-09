"""Live log ingestion must tolerate trailing writes without hiding corruption."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.export_run_tables import build_tables
from tools.inspect_run import load_events


class LiveLogIngestionTests(unittest.TestCase):
    def test_partial_trailing_write_and_completed_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            event = {"run_id": "r1", "sequence": 1, "event": "candidate_admitted",
                     "candidate_id": "baseline", "metrics": {"wns": -0.5}}
            path = run / "events.jsonl"
            path.write_text(json.dumps(event) + '\n{"sequence":', encoding="utf-8")
            self.assertEqual(load_events(run, live=True), [event])
            self.assertEqual(len(build_tables([run], live=True)["tree_nodes"]), 1)
            with self.assertRaises(json.JSONDecodeError):
                load_events(run)
            path.write_text(json.dumps(event) + '\n{"event": "run_finished", "sequence": 2, "run_id": "r1"}\n', encoding="utf-8")
            self.assertEqual(len(load_events(run, live=True)), 2)

    def test_corrupt_complete_or_middle_line_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            for contents in ['{"broken":\n', '{"broken":\n{}']:
                (run / "events.jsonl").write_text(contents, encoding="utf-8")
                with self.assertRaises(json.JSONDecodeError):
                    load_events(run, live=True)


if __name__ == "__main__":
    unittest.main()
