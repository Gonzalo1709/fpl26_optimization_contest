"""Exercise the actual dashboard with Streamlit's application test runtime."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from src.run_logging import RunRecorder


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Install requirements-gui.txt")
class DashboardTests(unittest.TestCase):
    def test_empty_folder_then_run_and_evidence(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "gui" / "app.py"))
            app.run(timeout=30)
            app.text_input[0].set_value(str(root)).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertIn("No runs found", app.info[0].value)
            run = root / "fixture-run"
            recorder = RunRecorder(run, "generations", root / "input.dcp", root / "output.dcp")
            recorder.record("candidate_admitted", candidate_id="baseline", parent_id=None,
                            metrics={"wns": -0.5}, evidence_ref=recorder.capture({"test": "evidence"}))
            recorder.record("candidate_admitted", candidate_id="child", parent_id="baseline",
                            metrics={"wns": -0.2})
            recorder.record("beam_selected", candidate_ids=["child"])
            app.run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 4)
            self.assertEqual(len(app.metric), 3)
            # Filter to candidates and select the event with a verified evidence blob.
            app.multiselect[0].set_value(["candidate_admitted"]).run(timeout=30)
            app.checkbox[1].check().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            app.checkbox[0].check().run(timeout=30)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
