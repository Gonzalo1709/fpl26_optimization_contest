"""Transfer optimizer analysis from a cloud run to the local web workspace.

python -m tools.run_bundle export /path/to/run --out analysis.zip
python -m tools.run_bundle export /path/to/run-a /path/to/run-b --out batch.zip
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools.inspect_run import evidence_refs, load_events

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 4096
ANALYSIS_FILES = {
    "events.jsonl", "run_summary.json", "recipe_outcomes.jsonl", "token_usage.json",
    "published_artifact.json", "policy_decisions.json", "enabling_moves.json",
    "tool_timeline.jsonl", "manifest.json",
}
EVIDENCE_PATH = re.compile(r"evidence/[a-f0-9]{64}\.(json|text)\.gz\Z")


def validate_run(run: Path):
    """Check causal IDs and bounded evidence without importing any FPGA packages."""
    events = load_events(run)
    if not events or any(not isinstance(e, dict) or e.get("schema_version", 1) != 1
                         or not isinstance(e.get("event"), str) for e in events):
        raise ValueError("Expected a nonempty schema-v1 events.jsonl from the optimizer")
    if [e.get("sequence") for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("Event sequence has gaps or duplicates")
    if len({e.get("run_id") for e in events}) != 1 or not events[0].get("run_id"):
        raise ValueError("Expected one run_id per run folder")
    for filename in ANALYSIS_FILES - {"events.jsonl", "recipe_outcomes.jsonl", "tool_timeline.jsonl"}:
        path = run / filename
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if filename == "run_summary.json" and (not isinstance(value, dict)
                    or value.get("run_id") != events[0]["run_id"] or value.get("event_count") != len(events)):
                raise ValueError("Summary and event log do not match; export again after the run finishes")
    refs = {json.dumps(ref, sort_keys=True): ref for ref in evidence_refs(events)}
    expanded = 0
    for ref in refs.values():
        relative = str(ref["path"])
        if not EVIDENCE_PATH.fullmatch(relative):
            raise ValueError("Evidence must reference a content-addressed file inside evidence/")
        target = (run / relative).resolve()
        if not target.is_relative_to(run.resolve()):
            raise ValueError("Evidence points outside the run folder")
        if not target.is_file():
            raise ValueError("Missing evidence file; export the complete run folder, not events.jsonl alone")
        with gzip.open(target, "rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
        expanded += len(data)
        if len(data) > MAX_EVIDENCE_BYTES or expanded > MAX_EXTRACTED_BYTES:
            raise ValueError("Evidence exceeds the analysis import size limit")
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("Evidence hash or length mismatch")
        if ref["kind"] == "json":
            json.loads(data)
        elif ref["kind"] != "text":
            raise ValueError("Unknown evidence format")
    return events, refs


def export_bundle(runs: list[Path], destination: Path):
    """One top-level folder per run. Original paths/files are never modified."""
    if not runs:
        raise ValueError("Choose at least one run folder")
    entries = []
    names = set()
    for source in runs:
        source = Path(source).expanduser().resolve()
        if not (source / "events.jsonl").is_file():
            raise ValueError(f"No events.jsonl in {source}; use a run folder printed by the optimizer")
        _, refs = validate_run(source)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", source.name)
        if name in {"", ".", ".."} or name in names:
            raise ValueError("Each run must have a distinct portable folder name")
        names.add(name)
        files = [(source / filename, f"{name}/{filename}") for filename in sorted(ANALYSIS_FILES)
                 if (source / filename).is_file()]
        if not (source / "manifest.json").is_file() and (source.parent / "manifest.json").is_file():
            files.append((source.parent / "manifest.json", f"{name}/manifest.json"))
        files.extend((source / relative, f"{name}/{relative}") for relative in sorted({ref["path"] for ref in refs.values()}))
        if any(path.is_symlink() for path, _ in files):
            raise ValueError("Analysis exports cannot include symbolic links")
        entries.extend(files)
    if len(entries) > MAX_ENTRIES or any(p.stat().st_size > MAX_FILE_BYTES for p, _ in entries) or sum(p.stat().st_size for p, _ in entries) > MAX_EXTRACTED_BYTES:
        raise ValueError("Analysis is too large for one bundle; export fewer runs")
    destination = Path(destination).expanduser().resolve()
    # Exclusive creation refuses to replace a previous export or any source file.
    with destination.open("xb") as handle:
        try:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, archive_name in entries:
                    archive.write(path, archive_name)
            if handle.tell() > MAX_ARCHIVE_BYTES:
                raise ValueError("ZIP exceeds 64 MiB; export fewer runs")
        except BaseException:
            handle.close()
            destination.unlink(missing_ok=True)
            raise
    return {"archive": str(destination), "runs": len(names), "bytes": destination.stat().st_size}


def import_bundle(archive_path: Path, imports_root: Path, filename: str):
    """Validate into a disposable directory; publish only complete valid imports."""
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP exceeds the 64 MiB upload limit")
    imports_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=imports_root) as pending:
        pending = Path(pending)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            root_layout = any(info.filename == "events.jsonl" for info in infos)
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_EXTRACTED_BYTES:
                raise ValueError("ZIP exceeds the analysis import size limit")
            paths = set()
            for info in infos:
                raw = info.filename
                parts = PurePosixPath(raw).parts
                if (not parts or raw.startswith("/") or "\\" in raw or ":" in raw or ".." in parts
                        or any(part.endswith((".", " ")) for part in parts)
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise ValueError("ZIP contains an unsafe or encrypted entry")
                normalized = "/".join(parts).casefold()
                if normalized in paths:
                    raise ValueError("ZIP contains duplicate file names")
                paths.add(normalized)
                if info.is_dir():
                    continue
                # Generated bundles use run-name/files. A ZIP of a single run's
                # contents is accepted too, but arbitrary nested paths are not.
                relative = raw if root_layout else "/".join(parts[1:])
                if relative not in ANALYSIS_FILES and not EVIDENCE_PATH.fullmatch(relative):
                    raise ValueError("ZIP must contain optimizer analysis files only; use tools.run_bundle export")
                if info.file_size > MAX_FILE_BYTES:
                    raise ValueError("ZIP contains a file larger than 64 MiB")
                target = pending.joinpath(*parts)
                if not target.resolve().is_relative_to(pending.resolve()):
                    raise ValueError("ZIP path escapes the import directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as out:
                    shutil.copyfileobj(source, out)
        runs = [p.parent for p in pending.glob("*/events.jsonl")]
        if (pending / "events.jsonl").is_file():
            if runs:
                raise ValueError("ZIP mixes root files and nested run folders")
            root_run = pending / "imported-run"
            root_run.mkdir()
            for item in list(pending.iterdir()):
                if item != root_run:
                    item.rename(root_run / item.name)
            runs = [root_run]
        if not runs:
            raise ValueError("No events.jsonl found in the ZIP")
        metadata = {"source_archive": filename[:200], "imported_at_utc": datetime.now(timezone.utc).isoformat(), "snapshot": True}
        for run in runs:
            validate_run(run)
            (run / ".imported.json").write_text(json.dumps(metadata), encoding="utf-8")
        batch = imports_root / uuid.uuid4().hex
        pending.rename(batch)
        return [batch / run.name for run in sorted(runs)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Create an uploadable analysis ZIP (no FPGA dependencies)")
    export.add_argument("runs", nargs="+", type=Path)
    export.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(export_bundle(args.runs, args.out), indent=2))
    except (OSError, ValueError, EOFError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"Cannot export analysis: {exc}\n")


if __name__ == "__main__":
    main()
