"""Append-only run events with content-addressed, compressed evidence blobs."""

import gzip
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path


SENSITIVE_KEYS = {"api_key", "access_token", "authorization", "password", "secret", "private_key"}
TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+|OPENROUTER_API_KEY\s*[=:]\s*)([^\s\"']+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_run_dir(root: Path = None) -> Path:
    root = root or Path.cwd()
    while True:
        name = f"dcp_optimizer_run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:6]}"
        path = root / name
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _file_identity(path: Path):
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}
    except OSError:
        return {"sha256": None, "bytes": None}


def _source_state():
    root = Path(__file__).resolve().parent.parent

    def git(*args):
        try:
            result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}",
                                     "-C", str(root), *args], capture_output=True,
                                    text=True, timeout=3, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    changes = git("status", "--porcelain", "--untracked-files=no")
    return {"git_commit": git("rev-parse", "HEAD"),
            "git_branch": git("branch", "--show-current"),
            "tracked_worktree_dirty": bool(changes) if changes is not None else None,
            "python_version": platform.python_version(), "platform": platform.platform(),
            "cpu_count": os.cpu_count()}


class RunRecorder:
    """Flush every event so a failed or interrupted run remains analyzable."""

    def __init__(self, run_dir: Path, mode: str, input_dcp: Path, output_dcp: Path,
                 config=None, run_id=None, secret_values=()):
        initialization_started = time.monotonic()
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or run_dir.name
        self.mode = mode
        self.started_at = utc_now()
        self.started_monotonic = time.monotonic()
        self.input_dcp = str(input_dcp.resolve())
        self.output_dcp = str(output_dcp.resolve())
        self.input_identity = _file_identity(input_dcp)
        self.source_state = _source_state()
        self.config = config or {}
        self.secret_values = tuple(
            value for value in (*secret_values, os.environ.get("OPENROUTER_API_KEY"))
            if isinstance(value, str) and len(value) >= 8
        )
        self.event_count = 0
        self.logging_seconds = time.monotonic() - initialization_started
        self.finished = False
        self.record("run_started", input_dcp=self.input_dcp,
                    output_dcp=self.output_dcp, input_identity=self.input_identity,
                    source_state=self.source_state, config=self.config)

    def _redact(self, value):
        if isinstance(value, dict):
            return {str(key): ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else self._redact(item))
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        if isinstance(value, Path):
            return self._redact(str(value))
        if isinstance(value, str):
            for secret in self.secret_values:
                value = value.replace(secret, "[REDACTED]")
            return TOKEN_PATTERN.sub(lambda match: match.group(1) + "[REDACTED]", value)
        return _json_safe(value)

    @staticmethod
    def new_id(kind: str) -> str:
        return f"{kind}-{uuid.uuid4().hex}"

    def capture(self, value, kind: str = "json") -> dict:
        """Persist complete text/JSON evidence and return its verified lookup key."""
        started = time.monotonic()
        if kind not in {"json", "text"}:
            raise ValueError("Evidence kind must be json or text")
        safe = self._redact(value)
        data = (safe if kind == "text" else json.dumps(safe, sort_keys=True, allow_nan=False,
                                                      ensure_ascii=False)).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        evidence_dir = self.run_dir / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        path = evidence_dir / f"{digest}.{kind}.gz"
        if not path.exists():
            temporary = evidence_dir / f".{digest}.{uuid.uuid4().hex}.tmp"
            try:
                with gzip.open(temporary, "wb", compresslevel=6) as handle:
                    handle.write(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        self.logging_seconds += time.monotonic() - started
        return {"sha256": digest, "path": str(path.relative_to(self.run_dir)).replace("\\", "/"),
                "kind": kind, "bytes": len(data)}

    def record(self, event: str, **fields):
        started = time.monotonic()
        sequence = self.event_count + 1
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "sequence": sequence,
            "timestamp_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "mode": self.mode,
            "event": event,
            **fields,
        }
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._redact(payload), allow_nan=False, ensure_ascii=False) + "\n")
        self.event_count = sequence
        self.logging_seconds += time.monotonic() - started
        return sequence

    def finish(self, status: str, optimizer=None, error_type=None):
        if self.finished:
            return
        initial_wns = getattr(optimizer, "initial_wns", None)
        final_wns = getattr(optimizer, "final_wns", None)
        if final_wns is None:
            final_wns = getattr(optimizer, "best_wns", None)
        clock_period = getattr(optimizer, "clock_period", None)
        calculate_fmax = getattr(optimizer, "calculate_fmax", None)
        initial_fmax = calculate_fmax(initial_wns, clock_period) if calculate_fmax and initial_wns is not None else None
        final_fmax = calculate_fmax(final_wns, clock_period) if calculate_fmax and final_wns is not None and math.isfinite(final_wns) else None
        best_candidate = getattr(optimizer, "best_candidate", None)
        validation = getattr(optimizer, "validation_status", None)
        validation_details = asdict(validation) if is_dataclass(validation) else None
        summary = {
            "schema_version": 1,
            "run_id": self.run_id,
            "mode": self.mode,
            "status": status,
            "error_type": error_type,
            "started_at_utc": self.started_at,
            "ended_at_utc": utc_now(),
            "runtime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "logging_overhead_seconds": round(self.logging_seconds, 3),
            "input_dcp": self.input_dcp,
            "output_dcp": self.output_dcp,
            "output_exists": Path(self.output_dcp).is_file(),
            "output_validated": getattr(getattr(optimizer, "validation_status", None), "passed", None),
            "validation": validation_details,
            "input_sha256": getattr(optimizer, "_input_sha256", None) or self.input_identity["sha256"],
            "input_bytes": self.input_identity["bytes"],
            "source_state": self.source_state,
            "best_candidate_id": getattr(best_candidate, "candidate_id", None),
            "best_candidate_sha256": getattr(best_candidate, "checkpoint_sha256", None),
            "stop_reason": getattr(optimizer, "_stop_reason", None),
            "tool_version": getattr(optimizer, "_tool_version", None),
            "part": getattr(optimizer, "_part", None),
            "config": self.config,
            "metrics": {
                "clock_period_ns": clock_period,
                "initial_wns_ns": initial_wns,
                "final_wns_ns": final_wns,
                "delta_wns_ns": final_wns - initial_wns if initial_wns is not None
                and final_wns is not None and math.isfinite(final_wns) else None,
                "initial_tns_ns": getattr(optimizer, "initial_tns", None),
                "final_tns_ns": getattr(best_candidate, "tns", None),
                "initial_failing_endpoints": getattr(optimizer, "initial_failing_endpoints", None),
                "final_failing_endpoints": getattr(best_candidate, "failing_endpoints", None),
                "initial_fmax_mhz": initial_fmax,
                "final_fmax_mhz": final_fmax,
                "delta_fmax_mhz": final_fmax - initial_fmax if initial_fmax is not None
                and final_fmax is not None else None,
                "projected_score": getattr(best_candidate, "projected_score", None),
                "validated_score": getattr(best_candidate, "validated_score", None),
            },
            "usage": {
                "llm_calls": getattr(optimizer, "llm_call_count", 0),
                "prompt_tokens": getattr(optimizer, "total_prompt_tokens", 0),
                "completion_tokens": getattr(optimizer, "total_completion_tokens", 0),
                "total_tokens": getattr(optimizer, "total_tokens", 0),
                "cost_usd": getattr(optimizer, "total_cost", None),
                "cost_verified": not getattr(optimizer, "_llm_cost_unknown", False),
                "tool_calls": len(getattr(optimizer, "tool_call_details", [])),
            },
            "event_count": self.event_count + 1,
            "evidence_blob_count": len(list((self.run_dir / "evidence").glob("*.gz")))
            if (self.run_dir / "evidence").exists() else 0,
        }
        self.record("run_finished", status=status, error_type=error_type)
        target = self.run_dir / "run_summary.json"
        temporary = self.run_dir / f".{target.name}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(self._redact(summary), indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
        self.finished = True
