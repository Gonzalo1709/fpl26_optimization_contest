"""SQLite-backed queue. Detached workers own processes, never browser sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import threading
import uuid
from pathlib import Path
from contextlib import contextmanager

from framework.config import RunConfig, file_hash

ACTIVE = {"starting", "running", "cancelling", "orphaned"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class JobManager:
    def __init__(self, root: Path, repository: Path | None = None):
        self.root = Path(root).resolve()
        self.repository = (repository or Path(__file__).resolve().parents[1]).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "jobs.sqlite3"
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported job database schema")
            connection.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, status TEXT, config TEXT, directory TEXT, worker_pid INTEGER, worker_created REAL, child_pid INTEGER, child_created REAL, started REAL, finished REAL, exit_code INTEGER, cancel_requested REAL, error TEXT, batch_id TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT OR IGNORE INTO settings VALUES ('concurrency', '1')")
            connection.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self):
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created DESC").fetchall()
        return [dict(row) | {"config": json.loads(row["config"])} for row in rows]

    def get(self, job_id):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown job")
        return dict(row) | {"config": json.loads(row["config"])}

    def update(self, job_id, **values):
        allowed = {"status", "worker_pid", "worker_created", "child_pid", "child_created",
                   "started", "finished", "exit_code", "cancel_requested", "error"}
        if not values or not values.keys() <= allowed:
            raise ValueError("Unsupported job update")
        with self.connect() as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(key + '=?' for key in values)} WHERE id=?",
                               [*values.values(), job_id])

    def enqueue(self, configs: list[RunConfig], *, batch_id=None, start=True):
        """Validate all configurations first, then commit the batch atomically."""
        for config in configs:
            config.validate()
        prepared = []
        for config in configs:
            config.validate()
            payload = config.to_dict()
            payload["input_dcp"] = str(Path(config.input_dcp).expanduser().resolve())
            for name in ("system_prompt", "equivalence_command", "outcome_memory"):
                if name in payload["advanced"]:
                    payload["advanced"][name] = str(Path(payload["advanced"][name]).expanduser().resolve())
            executable = Path(config.python).expanduser()
            if executable.is_file():
                payload["python"] = str(executable.resolve())
            config = RunConfig.from_dict(payload)
            job_id = uuid.uuid4().hex
            directory = self.root / job_id
            directory.mkdir()
            argv = config.argv(self.repository, directory / "optimized.dcp")
            manifest = {"schema_version": 1, "job_id": job_id, "config": payload,
                        "input_sha256": file_hash(Path(config.input_dcp)), "argv": argv,
                        "repository": str(self.repository), "created": time.time()}
            (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            prepared.append((job_id, time.time(), "queued", json.dumps(payload), str(directory), batch_id))
        with self.connect() as connection:
            connection.executemany("INSERT INTO jobs (id,created,status,config,directory,batch_id) VALUES (?,?,?,?,?,?)", prepared)
        if start and prepared:
            self.ensure_scheduler()
        return [row[0] for row in prepared]

    def cancel(self, job_id):
        with self.connect() as connection:
            row = connection.execute("SELECT status,directory FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown job")
            if row["status"] in TERMINAL:
                return
            if row["status"] == "queued":
                connection.execute("UPDATE jobs SET status='cancelled',finished=?,cancel_requested=? WHERE id=?",
                                   (time.time(), time.time(), job_id))
            else:
                connection.execute("UPDATE jobs SET cancel_requested=?,status='cancelling' WHERE id=?", (time.time(), job_id))
                (Path(row["directory"]) / "cancel.request").touch()

    def set_concurrency(self, value):
        if type(value) is not int or not 1 <= value <= 16:
            raise ValueError("Concurrency must be between 1 and 16")
        with self.connect() as connection:
            connection.execute("UPDATE settings SET value=? WHERE key='concurrency'", (str(value),))

    def concurrency(self):
        with self.connect() as connection:
            return int(connection.execute("SELECT value FROM settings WHERE key='concurrency'").fetchone()[0])

    def ensure_scheduler(self):
        """An OS file lock in the scheduler makes concurrent launches harmless."""
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        with (self.root / "scheduler.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "framework.worker", "scheduler", str(self.root), str(self.repository)],
                                       cwd=self.repository, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        # Reap detached launchers without tying their lifetime to the UI thread.
        threading.Thread(target=process.wait, daemon=True).start()

    def log_tail(self, job_id, size=32000):
        path = Path(self.get(job_id)["directory"]) / "console.log"
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - size))
            return handle.read().decode("utf-8", errors="replace")

    def save_config(self, name, config):
        if not name or len(name) > 80 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in name):
            raise ValueError("Use a preset name containing letters, numbers, hyphens, or underscores")
        config.validate(check_files=False)
        folder = self.root / "presets"
        folder.mkdir(exist_ok=True)
        temporary = folder / f"{name}-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        temporary.replace(folder / f"{name}.json")

    def presets(self):
        folder = self.root / "presets"
        return {path.stem: RunConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
                for path in folder.glob("*.json")} if folder.exists() else {}
