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
            app.session_state["run_folder"] = str(root)
            app.session_state["state_folder"] = str(root / "framework")
            app.run(timeout=30)
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
            self.assertEqual(len(app.metric), 7)
            # Filter to candidates and select the event with a verified evidence blob.
            app.multiselect[1].set_value(["candidate_admitted"]).run(timeout=30)
            next(widget for widget in app.checkbox if widget.label == "Expand linked evidence").check().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            app.checkbox[0].check().run(timeout=30)
            self.assertFalse(app.exception)

    def test_control_panels_and_saved_configuration(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.dcp"
            source.write_bytes(b"checkpoint")
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "gui" / "app.py"))
            app.run(timeout=30)
            app.session_state["run_folder"] = str(root)
            app.session_state["state_folder"] = str(root / "jobs")
            app.run(timeout=30)
            app.radio[0].set_value("Configure").run(timeout=30)
            self.assertFalse(app.exception)
            next(widget for widget in app.text_input if widget.label == "Input DCP path").set_value(str(source))
            next(widget for widget in app.text_input if widget.label == "Preset name").set_value("test-preset")
            next(widget for widget in app.button if widget.label == "Save configuration").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue((root / "jobs" / "presets" / "test-preset.json").exists())
            from unittest.mock import patch
            app.run(timeout=30)
            with patch("framework.jobs.JobManager.enqueue", return_value=["test-job"]) as enqueue:
                next(widget for widget in app.button if widget.label == "Queue run").click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(enqueue.call_args.args[0][0].input_dcp, str(source))
            for page in ["Jobs", "Compare", "Batch"]:
                app.radio[0].set_value(page).run(timeout=30)
                self.assertFalse(app.exception)
            next(widget for widget in app.text_area if widget.label == "Additional DCP paths (one per line)").set_value(str(source))
            app.run(timeout=30)
            with patch("framework.jobs.JobManager.enqueue", return_value=["job-1", "job-2"]) as enqueue:
                next(widget for widget in app.button if widget.label == "Queue batch").click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(len(enqueue.call_args.args[0]), 2)

    def test_comparison_panel_on_recorded_runs(self):
        from streamlit.testing.v1 import AppTest
        from tools.create_gui_demo import create_demo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            create_demo(root / "demo")
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "gui" / "app.py"))
            app.run(timeout=30)
            app.session_state["run_folder"] = str(root / "demo")
            app.session_state["state_folder"] = str(root / "jobs")
            app.run(timeout=30)
            app.radio[0].set_value("Compare").run(timeout=30)
            app.multiselect[0].set_value([root / "demo" / "demo-run-1", root / "demo" / "demo-run-2"]).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe), 1)
            self.assertTrue(app.warning)


if __name__ == "__main__":
    unittest.main()
