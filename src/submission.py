"""Hash-bound, deadline-bounded final structural and simulation validation."""

import asyncio
import json
import os
import signal
import sys
import uuid
from pathlib import Path

from src.admission import sha256_file


async def validate_submission(golden, revised, directory, timeout, vectors=1000):
    if timeout <= 0:
        raise TimeoutError("No final-validation budget remains")
    identity = {"golden_sha256": sha256_file(golden), "revised_sha256": sha256_file(revised)}
    report = directory / f"validation-{uuid.uuid4().hex}.json"
    log = report.with_suffix(".log")
    # Inherit the same Vivado/Java environment as the optimizer and Makefile.
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "src.submission_worker", str(golden), str(revised),
            str(report), str(vectors), cwd=str(Path(__file__).resolve().parent.parent),
            stdout=output, stderr=output, start_new_session=os.name != "nt")
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except BaseException:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                                                             stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            await process.wait()
            raise
    if process.returncode != 0 or not report.is_file() or report.stat().st_size > 1024*1024:
        raise ValueError(f"Strict final validation failed; see {log}")
    evidence = json.loads(report.read_text(encoding="utf-8"))
    required = {"schema_version": 1, **identity, "structural_passed": True,
                "simulation_passed": True, "simulation_skipped": False, "infrastructure_failure": False}
    if not isinstance(evidence, dict) or any(type(evidence.get(k)) is not type(v) or evidence[k] != v for k, v in required.items()):
        raise ValueError("Final validator did not affirm both phases for these exact artifacts")
    if sha256_file(golden) != identity["golden_sha256"] or sha256_file(revised) != identity["revised_sha256"]:
        raise ValueError("Artifacts changed during final validation")
    return {**evidence, "report_path": str(report), "report_sha256": sha256_file(report)}
