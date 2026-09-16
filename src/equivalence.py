"""Bounded adapter to a configured sequential-equivalence tool.

The checker receives golden/revised DCP paths and a result-file path as three
argv arguments. An exit status alone, FF counts, or random simulation cannot
admit retiming. The report must attest cycle-accurate sequential equivalence,
including initial/reset behavior, and bind it to both input hashes.
"""

import asyncio
import json
import os
import signal
from pathlib import Path

from src.admission import sha256_file


async def prove_sequential_equivalence(command: tuple[str, ...], golden: Path,
                                      revised: Path, report_path: Path,
                                      timeout_seconds: float) -> dict:
    if not command or timeout_seconds <= 0:
        raise ValueError("Sequential equivalence checker or its budget is unavailable")
    golden_hash, revised_hash = sha256_file(golden), sha256_file(revised)
    if report_path.exists():
        raise ValueError("Equivalence result path must be fresh")
    log_path = report_path.with_suffix(".log")
    options = {"start_new_session": True} if os.name != "nt" else {}
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *command, str(golden.resolve()), str(revised.resolve()), str(report_path.resolve()),
            stdout=log, stderr=asyncio.subprocess.STDOUT, **options,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout_seconds)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    # Kill the checker tree, including any solver child.
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill", "/PID", str(process.pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                await process.wait()
            raise
    if process.returncode != 0 or not report_path.is_file():
        raise ValueError(f"Equivalence checker failed; see {log_path}")
    if report_path.stat().st_size > 1024 * 1024:
        raise ValueError("Equivalence report exceeds the bounded JSON contract")
    proof = json.loads(report_path.read_text(encoding="utf-8"))
    required = {
        "schema_version": 1, "equivalent": True, "method": "sequential_equivalence",
        "cycle_accurate": True, "reset_and_initial_state_preserved": True,
        "golden_sha256": golden_hash, "revised_sha256": revised_hash,
    }
    if not isinstance(proof, dict) or any(type(proof.get(key)) is not type(value) or proof[key] != value
                                          for key, value in required.items()):
        raise ValueError("Equivalence report does not attest the required behavior and artifact hashes")
    if any(not isinstance(proof.get(key), str) or not proof[key].strip()
           for key in ("tool", "tool_version")):
        raise ValueError("Equivalence proof must identify the checker and version")
    if sha256_file(golden) != golden_hash or sha256_file(revised) != revised_hash:
        raise ValueError("Equivalence checker modified an input artifact")
    return {**proof, "report_path": str(report_path.resolve()), "report_sha256": sha256_file(report_path)}
