"""Offline strict-validator report regressions; subprocesses are mocked."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.admission import sha256_file
from src.submission import validate_submission


class SubmissionReportTests(unittest.IsolatedAsyncioTestCase):
    async def validate_report(self, overrides=None, mutate=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            golden, revised = root / "golden.dcp", root / "revised.dcp"
            golden.write_bytes(b"original")
            revised.write_bytes(b"candidate")

            async def spawn(*argv, **kwargs):
                report = {"schema_version": 1, "golden_sha256": sha256_file(golden),
                          "revised_sha256": sha256_file(revised), "structural_passed": True,
                          "simulation_passed": True, "simulation_skipped": False,
                          "infrastructure_failure": False}
                report.update(overrides or {})
                Path(argv[5]).write_text(json.dumps(report), encoding="utf-8")
                if mutate:
                    revised.write_bytes(b"changed after validation")
                return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))

            with patch("src.submission.asyncio.create_subprocess_exec", side_effect=spawn):
                return await validate_submission(golden, revised, root, 10)

    async def test_affirmative_report_is_accepted(self):
        evidence = await self.validate_report()
        self.assertTrue(evidence["simulation_passed"])
        self.assertIn("report_sha256", evidence)

    async def test_skipped_simulation_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.validate_report({"simulation_skipped": True})

    async def test_wrong_hash_and_non_boolean_pass_are_rejected(self):
        for overrides in ({"revised_sha256": "wrong"}, {"structural_passed": 1}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                await self.validate_report(overrides)

    async def test_changed_artifact_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.validate_report(mutate=True)
