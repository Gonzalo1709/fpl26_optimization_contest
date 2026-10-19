"""Local web workspace: python -m framework.web --help."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

from framework import JobManager, RunConfig, RunService
from framework.config import METHODS, PROFILES, check_environment
from framework.jobs import ACTIVE, TERMINAL
from framework.runs import read_json
from tools.run_bundle import MAX_ARCHIVE_BYTES, export_bundle, import_bundle


class OpenRun(BaseModel):
    path: str


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_dcp: str
    python: str = sys.executable
    mode: str = "deterministic"
    profile: str = "fast"
    model: str = ""
    max_runtime_minutes: float = 60
    max_cost: float | None = None
    method: str = "PHYS_OPT"
    advanced: dict = {}

    def config(self):
        return RunConfig.from_dict(self.model_dump())


def run_key(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]


def present_snapshot(service, run, job=None):
    """Project existing evidence into UI state without changing recorded facts."""
    snapshot = service.snapshot(run)
    imported = read_json(run / ".imported.json") or None
    if (run / "manifest.json").is_file():
        snapshot["manifest"] = read_json(run / "manifest.json")
    events, summary = snapshot["events"], snapshot["summary"]
    status = job["status"] if job else summary.get("status", "unknown")
    beams = snapshot["tables"]["beams"]
    beam = set(json.loads(beams[-1].get("candidate_ids", "[]"))) if beams else set()
    best = summary.get("best_candidate_id")
    if not best:
        publications = [e for e in events if e["event"] in {"incumbent_selected", "artifact_published"}]
        if publications:
            best = publications[-1].get("candidate_id")
    finished = {e.get("attempt_id"): e for e in events
                if e["event"] in {"recipe_attempt", "attempt_aborted", "attempt_returned"}}
    nodes = []
    for item in snapshot["tables"]["tree_nodes"]:
        node = dict(item)
        if node["node_type"] == "candidate":
            state = "candidate"
        elif node.get("attempt_id") in finished:
            outcome = finished[node["attempt_id"]]
            state = "failed" if outcome["event"] == "attempt_aborted" or outcome.get("status") == "error" else "no_candidate"
        elif status in ACTIVE:
            state = "running"
        elif status in TERMINAL:
            state = "interrupted"
        else:
            state = "unknown"
        nodes.append(node | {"state": state, "in_beam": node["node_id"] in beam,
                             "is_best": node["node_id"] == best})
    # Start/finish pairs also expose the current tool or planner without a candidate yet.
    open_calls = {}
    for event in events:
        if event["event"] in {"tool_call_started", "llm_call_started"}:
            open_calls[event.get("call_id")] = event
        elif event["event"] in {"tool_call_finished", "llm_call_finished"}:
            open_calls.pop(event.get("call_id"), None)
    activity = list(open_calls.values()) if status not in TERMINAL else []
    return {"id": run_key(run), "name": run.name, "path": str(run), "status": status,
            "job": job, "summary": summary, "artifact": snapshot["artifact"],
            "manifest": snapshot["manifest"], "monitor": service.monitor(snapshot),
            "events": events, "nodes": nodes, "edges": snapshot["tables"]["tree_edges"],
            "activity": activity, "sequence": events[-1]["sequence"] if events else 0,
            "imported": imported,
            "demo": summary.get("config", {}).get("demo", events[0].get("config", {}).get("demo", False) if events else False)}


def create_app(workspace=None, run_roots=None, repository=None, static_dir=None):
    repository = Path(repository or Path(__file__).resolve().parents[1]).resolve()
    manager = JobManager(Path(workspace or repository / ".optimizer-framework"), repository)
    service = RunService()
    roots = [Path(p).expanduser().resolve() for p in (run_roots or [repository])]
    imports_root = manager.root / "imports"
    registered = {}
    app = FastAPI(title="FPGA Optimizer Workspace", docs_url=None, redoc_url=None)
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        # No CORS: arbitrary websites must not control this local process launcher.
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin access is disabled"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-optimizer-client") != "web":
                return JSONResponse({"detail": "Missing workspace client header"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    def invalid_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(OSError)
    @app.exception_handler(EOFError)
    @app.exception_handler(zipfile.BadZipFile)
    def unreadable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def discover():
        found = set(registered.values())
        for root in [*roots, manager.root, *(p for p in imports_root.glob("*") if p.is_dir() and not p.name.startswith("."))]:
            if root.is_dir():
                found.update(service.discover(root))
        registered.update({run_key(path): path for path in found})
        return found

    def resolve_run(key):
        if key not in registered:
            discover()
        if key not in registered:
            raise HTTPException(404, "Run not found")
        return registered[key]

    def job_for(run):
        return next((job for job in manager.list() if (Path(job["directory"]) / "run").resolve() == run.resolve()), None)

    def snapshot(key):
        run = resolve_run(key)
        return present_snapshot(service, run, job_for(run))

    @app.get("/api/settings")
    def settings():
        return {"workspace": str(manager.root), "roots": [str(r) for r in roots],
                "defaults": RunConfig("").to_dict(), "profiles": PROFILES, "methods": METHODS}

    @app.get("/api/runs")
    def runs():
        jobs = {(Path(j["directory"]) / "run").resolve(): j for j in manager.list()}
        return [{"id": run_key(path), "name": path.name, "path": str(path),
                 "source": "imported" if (path / ".imported.json").is_file() else "managed" if path in jobs else "folder",
                 "job_id": jobs[path]["id"] if path in jobs else None} for path in sorted(discover(), key=str, reverse=True)]

    @app.post("/api/runs/open")
    def open_run(body: OpenRun):
        path = Path(body.path).expanduser().resolve()
        if path.name == "events.jsonl" and path.is_file():
            path = path.parent
        found = service.discover(path)
        if not found:
            raise ValueError("No events.jsonl found in that run folder or its immediate run subfolders")
        if path not in roots:
            roots.append(path)
        registered.update({run_key(run): run for run in found})
        return {"id": run_key(found[-1]), "count": len(found)}

    @app.post("/api/runs/import", status_code=201)
    async def upload(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/zip":
            raise HTTPException(415, "Upload an analysis ZIP generated with tools.run_bundle export")
        filename = unquote(request.headers.get("x-optimizer-filename", "analysis.zip"))
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        # Raw ZIP request body avoids multipart dependencies and caps bytes while receiving.
        with tempfile.TemporaryDirectory(dir=manager.root) as incoming:
            archive_path = Path(incoming) / "upload.zip"
            with archive_path.open("wb") as temporary:
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise HTTPException(413, "ZIP exceeds the 64 MiB upload limit")
                    temporary.write(chunk)
            paths = await asyncio.to_thread(import_bundle, archive_path, imports_root, filename)
        registered.update({run_key(run): run for run in paths})
        return {"id": run_key(paths[0]), "count": len(paths), "runs": [{"id": run_key(p), "name": p.name} for p in paths]}

    @app.get("/api/runs/{key}/bundle")
    def download_bundle(key: str):
        with tempfile.TemporaryDirectory(dir=manager.root) as temporary:
            output = Path(temporary) / "analysis.zip"
            export_bundle([resolve_run(key)], output)
            return Response(output.read_bytes(), media_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="run-analysis.zip"'})

    @app.get("/api/runs/{key}")
    def run_snapshot(key: str):
        return snapshot(key)

    @app.get("/api/runs/{key}/events/{sequence}/evidence")
    def evidence(key: str, sequence: int):
        run = resolve_run(key)
        event = next((event for event in service.snapshot(run)["events"] if event["sequence"] == sequence), None)
        if event is None:
            raise HTTPException(404, "Event not found")
        return service.evidence(run, event)

    @app.get("/api/runs/{key}/configuration")
    def configuration(key: str):
        run = resolve_run(key)
        if (run / ".imported.json").is_file():
            raise ValueError("Imported snapshots are for analysis; create a new experiment with a local input checkpoint")
        data = service.snapshot(run)
        if data["summary"].get("config", {}).get("demo"):
            raise ValueError("Synthetic demo configurations cannot launch real experiments")
        return service.configuration(data).to_dict()

    @app.get("/api/runs/{key}/report")
    def report(key: str):
        return Response(service.report(resolve_run(key)), media_type="text/html",
                        headers={"Content-Disposition": 'attachment; filename="run-report.html"'})

    async def stream(key, request):
        # Every connection starts with a complete snapshot, including missed events.
        # EventSource Last-Event-ID is therefore reconciled without append duplicates.
        previous = None
        ticks = 0
        while not await request.is_disconnected():
            try:
                run = resolve_run(key)
                signature = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                                  for p in [run / "events.jsonl", run / "run_summary.json",
                                            run / "published_artifact.json", manager.db])
                if signature != previous:
                    data = await asyncio.to_thread(snapshot, key)
                    yield f"id: {data['sequence']}\nevent: snapshot\ndata: {json.dumps(data, allow_nan=False)}\n\n"
                    previous = signature
                elif ticks % 15 == 0:
                    yield ": keep-alive\n\n"
            except (OSError, ValueError, KeyError, TypeError) as exc:
                yield f"event: read_error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            ticks += 1
            await asyncio.sleep(1)

    app.state.stream = stream

    @app.get("/api/runs/{key}/stream")
    async def run_stream(key: str, request: Request):
        resolve_run(key)
        return StreamingResponse(stream(key, request), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.get("/api/jobs")
    def jobs():
        return {"jobs": manager.list(), "concurrency": manager.concurrency()}

    @app.get("/api/jobs/{job_id}/console")
    def console(job_id: str):
        return {"text": manager.log_tail(job_id)}

    @app.post("/api/configuration/preview")
    def preview(body: Configuration):
        config = body.config().validate()
        return {"argv": config.argv(repository, manager.root / "preview" / "optimized.dcp")}

    @app.post("/api/configuration/check")
    def probe(body: Configuration):
        return check_environment(body.config().python, repository)

    @app.post("/api/jobs", status_code=201)
    def enqueue(body: Configuration):
        return {"job_id": manager.enqueue([body.config()])[0]}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        manager.cancel(job_id)
        return manager.get(job_id)

    static_dir = Path(static_dir or repository / "web" / "dist")
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(static_dir / "index.html")
    else:
        @app.get("/")
        def build_needed():
            return JSONResponse({"detail": "Build the frontend first: cd web && npm ci && npm run build"}, status_code=503)
    return app


def main():
    parser = argparse.ArgumentParser(description="Serve the local FPGA optimizer web workspace")
    parser.add_argument("--workspace", type=Path, default=Path(".optimizer-framework"))
    parser.add_argument("--runs", type=Path, action="append", help="Run directory or parent; repeat for multiple roots")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(args.workspace, args.runs), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
