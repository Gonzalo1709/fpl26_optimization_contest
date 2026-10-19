"""Cloud-to-local analysis transfer; standard library only."""

import json
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.create_gui_demo import create_demo
from tools.run_bundle import export_bundle, import_bundle, validate_run


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.history = create_demo(self.root / "history")
        self.run = self.history / "demo-run-1"

    def tearDown(self):
        self.temp.cleanup()

    def test_cloud_cli_to_import_preserves_evidence_without_checkpoints(self):
        (self.run / "large.dcp").write_bytes(b"not for transfer")
        (self.run / ".env").write_text("not for transfer")
        bundle = self.root / "cloud.zip"
        command = subprocess.run([sys.executable, "-m", "tools.run_bundle", "export", str(self.run),
                                  str(self.history / "demo-run-2"), "--out", str(bundle)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(json.loads(command.stdout)["runs"], 2)
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
        self.assertIn("demo-run-1/events.jsonl", names)
        self.assertTrue(any(name.startswith("demo-run-1/evidence/") for name in names))
        self.assertFalse(any(name.endswith((".dcp", ".env")) for name in names))
        runs = import_bundle(bundle, self.root / "imports", "cloud.zip")
        self.assertEqual(len(runs), 2)
        self.assertEqual((runs[0] / "events.jsonl").read_bytes(), (self.run / "events.jsonl").read_bytes())
        self.assertTrue(json.loads((runs[0] / ".imported.json").read_text())["snapshot"])
        self.assertEqual(validate_run(runs[0])[0], validate_run(self.run)[0])
        with self.assertRaises(FileExistsError):
            export_bundle([self.run], bundle)

    def test_rejects_unsafe_paths_duplicates_and_unrelated_files(self):
        for name in ["../escape.txt", "/absolute.txt", "run/../../escape", "run\\events.jsonl", "C:/events.jsonl", "run/design.dcp", "run/.env"]:
            with self.subTest(name=name):
                archive = self.root / "unsafe.zip"
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr(name, "bad")
                with self.assertRaises(ValueError):
                    import_bundle(archive, self.root / "imports", "unsafe.zip")
                self.assertEqual(list((self.root / "imports").iterdir()), [])
        archive = self.root / "symlink.zip"
        info = zipfile.ZipInfo("run/events.jsonl")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(info, "../../escape")
        with self.assertRaises(ValueError):
            import_bundle(archive, self.root / "imports", "symlink.zip")

    def test_missing_or_corrupt_evidence_is_an_error_and_import_is_atomic(self):
        good = self.root / "good.zip"
        export_bundle([self.run], good)
        for missing in (True, False):
            with self.subTest(missing=missing):
                bad = self.root / "bad.zip"
                with zipfile.ZipFile(good) as original, zipfile.ZipFile(bad, "w") as archive:
                    for entry in original.infolist():
                        if "evidence/" in entry.filename:
                            if not missing:
                                archive.writestr(entry.filename, b"invalid gzip")
                        else:
                            archive.writestr(entry.filename, original.read(entry))
                with self.assertRaises((ValueError, OSError)):
                    import_bundle(bad, self.root / "imports", "bad.zip")
                self.assertEqual(list((self.root / "imports").iterdir()), [])

    def test_single_run_zip_contents_and_partial_logs(self):
        bundle = self.root / "flat.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for source in self.run.rglob("*"):
                if source.is_file():
                    archive.write(source, source.relative_to(self.run).as_posix())
        runs = import_bundle(bundle, self.root / "imports", "flat.zip")
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(validate_run(runs[0])[0]), 16)
        with (self.run / "events.jsonl").open("a") as handle:
            handle.write('{"unfinished":')
        with self.assertRaises(ValueError):
            export_bundle([self.run], self.root / "partial.zip")

    def test_archive_limits_are_checked_before_publication(self):
        bundle = self.root / "cloud.zip"
        export_bundle([self.run], bundle)
        with patch("tools.run_bundle.MAX_EXTRACTED_BYTES", 10):
            with self.assertRaises(ValueError):
                import_bundle(bundle, self.root / "imports", "cloud.zip")
        self.assertEqual(list((self.root / "imports").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
