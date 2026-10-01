"""Launch with: python -m streamlit run gui/app.py"""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.inspect_run import expand_evidence
from framework import JobManager, RunService
from gui.graph import search_figure
from gui.workspace import batch_panel, compare_panel, config_panel, jobs_panel, load_draft

st.set_page_config(page_title="FPGA Optimizer", page_icon="🔬", layout="wide")
st.title("FPGA Optimizer")
st.caption("Launch experiments, monitor searches, and compare reproducible results.")

with st.sidebar:
    root_text = st.text_input("Run folder or parent folder", str(ROOT))
    refresh = st.checkbox("Refresh every 3 seconds", value=False)
    st.button("Refresh now")
    state_root = st.text_input("Framework workspace", str(ROOT / ".optimizer-framework"))
    st.caption("Jobs keep running independently of this browser session.")

service = RunService()
try:
    manager = JobManager(Path(state_root).expanduser(), ROOT)
except (OSError, ValueError, sqlite3.Error) as exc:
    st.error(f"Cannot open framework workspace: {exc}")
    st.stop()
page = st.radio("Workspace", ["Inspect", "Configure", "Jobs", "Compare", "Batch"], horizontal=True, key="workspace_page")

if page == "Configure":
    config_panel(manager)
    st.stop()
if page == "Jobs":
    jobs_panel(manager, refresh)
    st.stop()
if page == "Batch":
    batch_panel(manager)
    st.stop()
try:
    runs = sorted(set(service.discover(Path(root_text).expanduser().resolve()) + service.discover(manager.root)), key=str, reverse=True)
except OSError as exc:
    st.error(f"Cannot read run folder: {exc}")
    st.stop()
if page == "Compare":
    compare_panel(service, runs)
    st.stop()
if not runs:
    st.info("No runs found. Choose a folder containing events.jsonl, or its parent folder.")
    st.stop()

run = st.sidebar.selectbox("Run", runs, format_func=lambda path: path.name)


@st.fragment(run_every="3s" if refresh else None)
def render_run():
    try:
        snapshot = service.snapshot(run)
        tables = snapshot["tables"]
        summary = snapshot["summary"]
        artifact = snapshot["artifact"]
        monitor = service.monitor(snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"Cannot read this run: {exc}. Refresh after the current write finishes.")
        return
    events = tables["events"]
    metrics = summary.get("metrics", {})
    status = summary.get("status", "No final summary")
    st.subheader(run.name)
    demo = summary.get("config", {}).get("demo", False)
    if demo:
        st.warning("Demonstration data: these measurements are synthetic; no FPGA tools were run.")
    st.caption(f"Status: {status} · {len(events)} recorded events")
    if snapshot["manifest"].get("job_id"):
        managed = next((job for job in manager.list() if job["id"] == snapshot["manifest"]["job_id"]), None)
        if managed:
            st.caption(f"Managed job: {managed['status']} · Exit code: {managed['exit_code']}")
    if not summary:
        st.info("A missing summary does not prove the run is still active. The event log remains inspectable.")
    columns = st.columns(3)
    def number(value, decimals=3):
        return "—" if value is None else f"{value:.{decimals}f}"
    columns[0].metric("Initial WNS (ns)", number(monitor["initial_wns_ns"]))
    columns[1].metric("Final WNS (ns)", number(metrics.get("final_wns_ns")), number(metrics["delta_wns_ns"]) if metrics.get("delta_wns_ns") is not None else None)
    columns[2].metric("Final Fmax (MHz)", number(metrics.get("final_fmax_mhz"), 1))
    live_columns = st.columns(4)
    live_columns[0].metric("Best observed WNS (ns)", number(monitor["best_wns_ns"]))
    live_columns[1].metric("Recorded elapsed (seconds)", number(monitor["elapsed_seconds"], 1))
    live_columns[2].metric("LLM cost (USD)", number(monitor["cost_usd"], 4))
    live_columns[3].metric("LLM calls", monitor["llm_calls"])
    st.caption(f"Latest strategy: {monitor['current_action'].get('strategy', '—')} · Generation: {monitor['current_action'].get('generation', '—')} · Cost verified: {monitor['cost_verified']}")
    with st.expander("Search budgets and latest beam"):
        st.json({"budget": monitor["budget"], "beam": monitor["latest_beam"]})
    overview, search, timeline, output = st.tabs(["Timing", "Search explorer", "Events & evidence", "Summary & output"])
    with overview:
        nodes = tables["tree_nodes"]
        measured = [node for node in nodes if node.get("wns_ns") is not None]
        if measured:
            curve = pd.DataFrame(monitor["timing"])
            st.line_chart(curve.set_index("sequence")[["candidate_wns_ns", "best_wns_ns"]], x_label="Event sequence", y_label="WNS (ns)")
            st.caption("Each point is an admitted candidate; candidate timing can worsen along explored branches.")
        else:
            st.info("No admitted candidate timing recorded yet.")
        st.dataframe(pd.DataFrame(tables["attempts"]), hide_index=True, width="stretch")
    with search:
        if tables["tree_nodes"]:
            strategy = st.multiselect("Search strategies", sorted({node["strategy"] for node in tables["tree_nodes"] if node.get("strategy")}))
            selection = st.plotly_chart(search_figure(tables, summary.get("best_candidate_id")), on_select="rerun", selection_mode="points", key=f"graph-{run}")
            st.caption("Click a node to inspect it. Green: final best. Orange border: latest beam. Cross: unsuccessful attempt. Edges run from parent to child toward increasing depth.")
            available = [node for node in tables["tree_nodes"] if not strategy or node.get("strategy") in strategy]
            selected_ids = [point.get("customdata") for point in selection.selection.points if point.get("curve_number") == 1]
            index = next((i for i, node in enumerate(available) if node["node_id"] in selected_ids), 0)
            if not available:
                st.info("No nodes match the selected strategies")
                return
            node = st.selectbox("Candidate or attempt", available, index=index, format_func=lambda item: item["node_id"])
            st.json(node)
            linked = service.linked_events(snapshot, node)
            st.write("Linked decisions, policy gates, tool results, and publication events")
            st.dataframe(pd.DataFrame(linked), hide_index=True, width="stretch")
            if linked and st.checkbox("Expand node decision and tool evidence"):
                try:
                    st.json([service.evidence(run, event) for event in linked])
                except (OSError, ValueError, KeyError, EOFError) as exc:
                    st.error(f"Evidence could not be verified: {exc}")
        else:
            st.info("This run has no candidate ancestry records.")
    with timeline:
        kinds = sorted({event["event"] for event in events})
        selected = st.multiselect("Event types", kinds)
        filtered = [event for event in events if not selected or event["event"] in selected]
        st.dataframe(pd.DataFrame(filtered), hide_index=True, width="stretch")
        if filtered:
            event = st.selectbox("Inspect event", filtered,
                                 format_func=lambda item: f"{item['sequence']} · {item['event']}")
            st.json(event)
            if st.checkbox("Expand linked evidence"):
                try:
                    st.json(expand_evidence(run, event))
                except (OSError, ValueError, KeyError, EOFError) as exc:
                    st.error(f"Evidence could not be verified: {exc}")
    with output:
        st.write("Run summary")
        st.json(summary)
        st.write("Published checkpoint")
        st.json(artifact)
        st.write("Projected and validated contest scores")
        st.json({"projected_score": monitor["projected_score"], "validated_score": monitor["validated_score"], "output_validated": summary.get("output_validated")})
        st.caption("An output checkpoint may still be the baseline. Timing gain and validated contest score are separate measurements.")
        st.download_button("Download summary JSON", json.dumps(summary, indent=2),
                           file_name=f"{run.name}-summary.json", mime="application/json")
        st.download_button("Download experiment report", service.report(run), file_name=f"{run.name}-report.html", mime="text/html")
        st.download_button("Download analysis tables", service.export_tables([run]), file_name=f"{run.name}-tables.zip", mime="application/zip")
        try:
            if demo:
                raise ValueError("Synthetic demonstrations cannot be rerun as FPGA experiments")
            configuration = service.configuration(snapshot).to_dict()
            st.button("Use configuration for a new run", on_click=load_draft, args=(configuration,))
            st.download_button("Download reproducible configuration", json.dumps(configuration, indent=2), file_name="configuration.json")
            if not snapshot["manifest"]:
                st.caption("Legacy logs may omit settings. Review the reconstructed configuration before launching.")
        except (TypeError, ValueError) as exc:
            st.info(f"Configuration cannot be reconstructed: {exc}")


render_run()
