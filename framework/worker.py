"""Detached queue scheduler and per-job supervisors. No Streamlit imports."""

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from framework.config import file_hash, check_environment
from framework.jobs import ACTIVE, JobManager
from framework.processes import ProcessTree


def process_identity(pid, created):
    if pid is None or created is None:
        return None
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - created) < 0.01 and process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
            return process
    except psutil.Error:
        pass
    return None


@contextmanager
def scheduler_lock(root):
    """The OS releases the lock on crash, allowing a safe scheduler restart."""
    handle = (root / "scheduler.lock").open("a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        yield False
        return
    try:
        yield True
    finally:
        handle.close()


def cleanup_processes(processes):
    """Only terminate handles whose creation identity still matches."""
    alive = []
    for process in reversed(processes):
        try:
            if process.is_running():
                process.terminate()
                alive.append(process)
        except psutil.Error:
            pass
    _, remaining = psutil.wait_procs(alive, timeout=3)
    for process in remaining:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(remaining, timeout=3)


def scheduler(manager):
    with scheduler_lock(manager.root) as acquired:
        if not acquired:
            return
        process = psutil.Process()
        (manager.root / "scheduler.json").write_text(json.dumps({"pid": process.pid, "created": process.create_time()}), encoding="utf-8")
        workers = []
        while True:
            workers = [worker for worker in workers if worker.poll() is None]
            jobs = manager.list()
            now = time.time()
            for job in jobs:
                if job["status"] not in ACTIVE:
                    continue
                worker = process_identity(job["worker_pid"], job["worker_created"])
                child = process_identity(job["child_pid"], job["child_created"])
                if worker:
                    continue
                # Cover the brief spawn-to-registration handoff.
                if job["status"] == "starting" and now - (job["started"] or now) < 10:
                    continue
                if child:
                    manager.update(job["id"], status="orphaned", error="Supervisor exited; optimizer process still exists")
                    if job["cancel_requested"]:
                        (Path(job["directory"]) / "cancel.request").touch()
                        if now - job["cancel_requested"] > 120:
                            cleanup_processes([child, *child.children(recursive=True)])
                    continue
                manager.update(job["id"], status="cancelled" if job["cancel_requested"] else "interrupted",
                               finished=now, error="Supervisor handle is gone; job was not automatically rerun")
            jobs = manager.list()
            active = sum(job["status"] in ACTIVE for job in jobs)
            queued = sorted((job for job in jobs if job["status"] == "queued"), key=lambda job: job["created"])
            for job in queued[:max(0, manager.concurrency() - active)]:
                with manager.connect() as connection:
                    claimed = connection.execute("UPDATE jobs SET status='starting',started=? WHERE id=? AND status='queued'", (time.time(), job["id"])).rowcount
                if not claimed:
                    continue
                options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
                try:
                    with (Path(job["directory"]) / "worker.log").open("ab") as log:
                        process = subprocess.Popen([sys.executable, "-m", "framework.worker", "job", str(manager.root), str(manager.repository), job["id"]],
                                                   cwd=manager.repository, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
                    workers.append(process)
                    try:
                        created = psutil.Process(process.pid).create_time()
                        with manager.connect() as connection:
                            connection.execute("UPDATE jobs SET worker_pid=?,worker_created=? WHERE id=? AND worker_pid IS NULL AND status='starting'", (process.pid, created, job["id"]))
                    except psutil.NoSuchProcess:
                        pass
                except (OSError, psutil.Error) as exc:
                    manager.update(job["id"], status="failed", finished=time.time(), error=str(exc))
            # Staying alive while idle avoids an enqueue-versus-shutdown race.
            time.sleep(0.25 if queued or active else 1.0)


def run_job(manager, job_id, *, cancellation_grace=120, interrupt_grace=15):
    own_process = psutil.Process()
    manager.update(job_id, worker_pid=own_process.pid, worker_created=own_process.create_time())
    directory = Path(manager.get(job_id)["directory"])
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    child = None
    descendants = {}
    tree = None
    result = {"status": "failed", "error": "Worker exited before recording its result"}
    try:
        if manager.get(job_id)["cancel_requested"]:
            result = {"status": "cancelled", "error": None}
            return
        if file_hash(Path(manifest["config"]["input_dcp"])) != manifest["input_sha256"]:
            raise ValueError("Input checkpoint changed after enqueue; create a new job")
        manifest["environment"] = check_environment(manifest["config"]["python"], manager.repository)
        try:
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=manager.repository, capture_output=True, text=True, timeout=5)
            manifest["source_commit"] = revision.stdout.strip() if revision.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            manifest["source_commit"] = None
        temporary = directory / "manifest.tmp"
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(directory / "manifest.json")
        env = os.environ.copy()
        env["OPTIMIZER_CANCEL_FILE"] = str(directory / "cancel.request")
        tree = ProcessTree()
        with (directory / "console.log").open("ab") as log:
            child = tree.launch(manifest["argv"], cwd=manager.repository, env=env,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            process = psutil.Process(child.pid)
            with manager.connect() as connection:
                connection.execute("UPDATE jobs SET child_pid=?,child_created=?,status=CASE WHEN cancel_requested IS NULL THEN 'running' ELSE 'cancelling' END WHERE id=?", (child.pid, process.create_time(), job_id))
            interrupted_at = None
            while child.poll() is None:
                try:
                    for descendant in process.children(recursive=True):
                        descendants[(descendant.pid, descendant.create_time())] = descendant
                except psutil.Error:
                    pass
                job = manager.get(job_id)
                if job["cancel_requested"]:
                    (directory / "cancel.request").touch()
                    # Prefer the optimizer's next safe boundary, preserving publication.
                    if time.time() - job["cancel_requested"] > cancellation_grace and interrupted_at is None:
                        try:
                            child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                        except OSError:
                            pass
                        interrupted_at = time.time()
                    if interrupted_at and time.time() - interrupted_at > interrupt_grace:
                        cleanup_processes([process, *descendants.values()])
                time.sleep(0.2)
            code = child.wait()
        cancelled = bool(manager.get(job_id)["cancel_requested"])
        result = {"status": "cancelled" if cancelled else "completed" if code == 0 else "failed", "exit_code": code, "error": None}
    except Exception as exc:
        result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        processes = list(descendants.values())
        if child and child.poll() is None:
            try:
                processes.insert(0, psutil.Process(child.pid))
            except psutil.Error:
                pass
        cleanup_processes(processes)
        if tree:
            tree.close()
        manager.update(job_id, finished=time.time(), **result)


if __name__ == "__main__":
    manager = JobManager(Path(sys.argv[2]), Path(sys.argv[3]))
    scheduler(manager) if sys.argv[1] == "scheduler" else run_job(manager, sys.argv[4])
