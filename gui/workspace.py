"""Framework control panels. UI functions delegate execution to services."""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from framework.config import METHODS, PROFILES, RunConfig, check_environment, expand_sweep
from framework.jobs import TERMINAL


def load_draft(payload):
    st.session_state["draft_config"] = payload
    st.session_state["checkpoint_picker"] = ""
    st.session_state["workspace_page"] = "Configure"


def config_panel(manager):
    st.subheader("Configure an optimization")
    imported = st.file_uploader("Import configuration JSON", type=["json"])
    if imported:
        try:
            imported_config = RunConfig.from_dict(json.loads(imported.getvalue()))
            st.button("Load imported configuration", on_click=load_draft, args=(imported_config.to_dict(),))
        except (ValueError, TypeError) as exc:
            st.error(f"Invalid configuration: {exc}")
    presets = manager.presets()
    if presets:
        name = st.selectbox("Saved configuration", list(presets))
        st.button("Load configuration", on_click=load_draft, args=(presets[name].to_dict(),))
    draft = RunConfig.from_dict(st.session_state.get("draft_config", RunConfig("").to_dict()))
    folder = st.text_input("Checkpoint folder", str(manager.repository / "fpl26_contest_benchmarks"))
    paths = sorted(Path(folder).expanduser().glob("*.dcp"))
    selected = st.selectbox("Checkpoint picker", [""] + [str(path.resolve()) for path in paths], key="checkpoint_picker")
    with st.form("run_config"):
        source = st.text_input("Input DCP path", selected or draft.input_dcp)
        python = st.text_input("Optimizer Python executable", draft.python)
        left, right = st.columns(2)
        mode = left.selectbox("Run mode", ["deterministic", "llm", "test", "single"], index=["deterministic", "llm", "test", "single"].index(draft.mode))
        profile = right.selectbox("Budget profile", PROFILES, index=PROFILES.index(draft.profile))
        model = st.text_input("Model (required for LLM mode)", draft.model)
        method = st.selectbox("Single optimization method", METHODS, index=METHODS.index(draft.method))
        runtime = st.number_input("Runtime limit (minutes)", min_value=1.0, value=float(draft.max_runtime_minutes))
        cost = st.number_input("LLM cost limit (USD; 0 means no cost cap)", min_value=0.0, value=float(draft.max_cost or 0))
        advanced = st.text_area("Advanced settings (JSON)", json.dumps(draft.advanced, indent=2),
                                help='Example: {"branches": 2, "beam_width": 2, "generations": 3, "stop_when_timing_met": true}')
        preset_name = st.text_input("Preset name")
        preview = st.form_submit_button("Validate and preview")
        save = st.form_submit_button("Save configuration")
        launch = st.form_submit_button("Queue run")
    if preview or save or launch:
        try:
            config = RunConfig(source, python, mode, profile, model, runtime, cost or None, method, json.loads(advanced)).validate(check_files=not save)
            st.session_state["draft_config"] = config.to_dict()
            if save:
                manager.save_config(preset_name, config)
                st.success("Configuration saved")
            else:
                argv = config.argv(manager.repository, manager.root / "preview" / "optimized.dcp")
                st.code(subprocess.list2cmdline(argv) if sys.platform == "win32" else __import__("shlex").join(argv), language="bash")
                if launch:
                    ids = manager.enqueue([config])
                    st.success(f"Queued job {ids[0]}")
        except (OSError, ValueError, TypeError) as exc:
            st.error(str(exc))
    if st.button("Check tool availability"):
        try:
            st.json(check_environment(python, manager.repository))
            st.caption("Presence checks do not establish tool compatibility or license availability. The selected runtime must also satisfy requirements.txt.")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            st.error(str(exc))


def jobs_panel(manager, refresh):
    st.subheader("Persistent job queue")
    concurrency = st.number_input("Concurrent optimizer jobs", min_value=1, max_value=16, value=manager.concurrency())
    if st.button("Apply concurrency"):
        manager.set_concurrency(concurrency)
    st.button("Start or recover scheduler", on_click=manager.ensure_scheduler)

    @st.fragment(run_every="3s" if refresh else None)
    def jobs():
        rows = manager.list()
        if not rows:
            st.info("No jobs queued yet")
            return
        st.dataframe(pd.DataFrame([{key: row[key] for key in ("id", "status", "batch_id", "started", "finished", "exit_code", "error")} for row in rows]), hide_index=True, width="stretch")
        job = st.selectbox("Job", rows, format_func=lambda item: f"{item['id'][:10]} · {item['status']}")
        st.json(job["config"])
        st.caption(f"Artifacts: {job['directory']}")
        st.code(manager.log_tail(job["id"]) or "No console output yet", language="text")
        if job["status"] not in TERMINAL:
            if st.button("Request cancellation", key=f"cancel-{job['id']}"):
                manager.cancel(job["id"])
                st.success("Stop requested. The optimizer stops at a safe search boundary; a stuck process is interrupted after 120 seconds and terminated after a further 15 seconds. Existing published checkpoints are retained.")
        st.button("Use this configuration for a new run", on_click=load_draft, args=(job["config"],))
        manifest_path = Path(job["directory"]) / "manifest.json"
        if manifest_path.exists():
            st.download_button("Download job manifest", manifest_path.read_bytes(), file_name=f"{job['id']}-manifest.json")
    jobs()


def compare_panel(service, runs):
    st.subheader("Compare experiments")
    selected = st.multiselect("Runs to compare", runs, format_func=lambda path: str(path))
    if not selected:
        st.info("Select runs to compare timing, validated score, cost, and configuration.")
        return
    try:
        comparison = service.compare(selected)
        for warning in comparison["warnings"]:
            st.warning(warning)
        frame = pd.DataFrame(comparison["rows"])
        st.dataframe(frame, hide_index=True, width="stretch")
        st.download_button("Download comparison CSV", frame.to_csv(index=False), file_name="comparison.csv", mime="text/csv")
        st.download_button("Download all analysis tables", service.export_tables(selected), file_name="experiment-tables.zip", mime="application/zip")
        st.write("Configuration differences")
        configurations = comparison["configurations"]
        baseline = next(iter(configurations.values()))
        differences = {name: {key: value for key, value in config.items() if baseline.get(key) != value}
                       for name, config in configurations.items()}
        st.json(differences)
        st.write("Full configurations")
        st.json(configurations)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"Cannot compare selected runs: {exc}")


def batch_panel(manager):
    st.subheader("Benchmark batches and parameter sweeps")
    base = RunConfig.from_dict(st.session_state.get("draft_config", RunConfig("").to_dict()))
    st.caption("Uses the configuration from Configure. Each combination receives its own job, output, and manifest.")
    folder = st.text_input("Benchmark folder", str(manager.repository / "fpl26_contest_benchmarks"))
    designs = st.multiselect("Benchmarks", [str(path.resolve()) for path in sorted(Path(folder).expanduser().glob("*.dcp"))])
    extra = st.text_area("Additional DCP paths (one per line)")
    axes = st.text_area("Sweep axes (JSON lists)", '{"profile": ["fast", "quality"]}')
    configs = None
    try:
        chosen = list(dict.fromkeys(designs + [line.strip() for line in extra.splitlines() if line.strip()]))
        if chosen:
            configs = expand_sweep(base, chosen, json.loads(axes))
            st.write(f"{len(configs)} jobs · concurrency {manager.concurrency()}")
            st.dataframe(pd.DataFrame([config.to_dict() for config in configs]), hide_index=True, width="stretch")
    except (OSError, ValueError, TypeError) as exc:
        st.error(str(exc))
    if st.button("Queue batch", disabled=not configs):
        import uuid
        batch_id = uuid.uuid4().hex
        try:
            ids = manager.enqueue(configs, batch_id=batch_id)
            st.success(f"Queued {len(ids)} jobs in batch {batch_id}")
        except (OSError, ValueError, TypeError) as exc:
            st.error(str(exc))
    rows = manager.list()
    batches = sorted({row["batch_id"] for row in rows if row["batch_id"]})
    if batches:
        batch = st.selectbox("Batch results", batches)
        members = [row for row in rows if row["batch_id"] == batch]
        st.dataframe(pd.DataFrame([{"job": row["id"], "design": row["config"]["input_dcp"], "profile": row["config"]["profile"], "status": row["status"], "exit_code": row["exit_code"]} for row in members]), hide_index=True, width="stretch")
        from framework import RunService
        service = RunService()
        recorded = [Path(row["directory"]) / "run" for row in members if (Path(row["directory"]) / "run" / "events.jsonl").exists()]
        if recorded:
            try:
                comparison = service.compare(recorded)
                for warning in comparison["warnings"]:
                    st.warning(warning)
                results = pd.DataFrame(comparison["rows"])
                st.write("Recorded batch metrics")
                st.dataframe(results, hide_index=True, width="stretch")
                st.download_button("Download batch results CSV", results.to_csv(index=False), file_name=f"{batch}-results.csv", mime="text/csv")
                # Group repeated trials by design and profile, never across designs.
                profiles = {str(Path(row["directory"]) / "run"): row["config"]["profile"] for row in members}
                results["profile"] = results["run"].map(profiles)
                st.write("Aggregate results by checkpoint and profile")
                for column in ("final_fmax_mhz", "cost_usd", "runtime_seconds"):
                    results[column] = pd.to_numeric(results[column], errors="coerce")
                results["checkpoint_group"] = results["input_sha256"].where(results["input_sha256"].notna(), results["run"])
                aggregate = results.groupby(["checkpoint_group", "profile"], dropna=False).agg(
                    runs=("run", "count"), measured_fmax=("final_fmax_mhz", "count"),
                    mean_fmax_mhz=("final_fmax_mhz", "mean"), mean_runtime_seconds=("runtime_seconds", "mean"),
                    mean_cost_usd=("cost_usd", "mean"))
                st.dataframe(aggregate, width="stretch")
                st.caption("Means use recorded measurements only; missing metrics are excluded. Review tool and validation differences before comparing trials.")
            except (OSError, ValueError, TypeError, KeyError) as exc:
                st.error(f"Cannot read batch results: {exc}")
        if st.button("Cancel unfinished jobs in batch"):
            for row in members:
                if row["status"] not in TERMINAL:
                    manager.cancel(row["id"])
            st.success("Batch stop requested")
