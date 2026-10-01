"""Launch with: python -m streamlit run gui/app.py"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.data import discover_runs, read_optional_json, search_dot
from tools.export_run_tables import build_tables
from tools.inspect_run import expand_evidence

st.set_page_config(page_title="FPGA Optimizer", page_icon="🔬", layout="wide")
st.title("FPGA Optimizer")
st.caption("Inspect optimization runs, candidate timing, and decision evidence.")

with st.sidebar:
    root_text = st.text_input("Run folder or parent folder", str(ROOT))
    refresh = st.checkbox("Refresh every 3 seconds", value=False)
    st.button("Refresh now")
    st.caption("This viewer reads run files. Start optimization through the existing CLI.")

try:
    runs = discover_runs(Path(root_text).expanduser().resolve())
except OSError as exc:
    st.error(f"Cannot read run folder: {exc}")
    st.stop()
if not runs:
    st.info("No runs found. Choose a folder containing events.jsonl, or its parent folder.")
    st.stop()

run = st.sidebar.selectbox("Run", runs, format_func=lambda path: path.name)


@st.fragment(run_every="3s" if refresh else None)
def render_run():
    try:
        tables = build_tables([run], live=True)
        summary = read_optional_json(run / "run_summary.json")
        artifact = read_optional_json(run / "published_artifact.json")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"Cannot read this run: {exc}. Refresh after the current write finishes.")
        return
    events = tables["events"]
    metrics = summary.get("metrics", {})
    status = summary.get("status", "No final summary")
    st.subheader(run.name)
    st.caption(f"Status: {status} · {len(events)} recorded events")
    if not summary:
        st.info("A missing summary does not prove the run is still active. The event log remains inspectable.")
    columns = st.columns(3)
    columns[0].metric("Initial WNS (ns)", metrics.get("initial_wns_ns", "—"))
    columns[1].metric("Final WNS (ns)", metrics.get("final_wns_ns", "—"), metrics.get("delta_wns_ns"))
    columns[2].metric("Final Fmax (MHz)", metrics.get("final_fmax_mhz", "—"))
    overview, search, timeline, output = st.tabs(["Timing", "Search explorer", "Events & evidence", "Summary & output"])
    with overview:
        nodes = tables["tree_nodes"]
        measured = [node for node in nodes if node.get("wns_ns") is not None]
        if measured:
            frame = pd.DataFrame(measured)
            st.line_chart(frame.set_index("sequence")[["wns_ns"]], x_label="Event sequence", y_label="WNS (ns)")
            st.caption("Each point is an admitted candidate; candidate timing can worsen along explored branches.")
        else:
            st.info("No admitted candidate timing recorded yet.")
        st.dataframe(pd.DataFrame(tables["attempts"]), hide_index=True, width="stretch")
    with search:
        if tables["tree_nodes"]:
            st.graphviz_chart(search_dot(tables, summary.get("best_candidate_id")))
            st.caption("Green: final best candidate. Orange border: latest beam. Dashed: attempt without an admitted candidate.")
            node = st.selectbox("Candidate or attempt", tables["tree_nodes"], format_func=lambda item: item["node_id"])
            st.json(node)
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
        st.caption("An output checkpoint may still be the baseline. Timing gain and validated contest score are separate measurements.")
        st.download_button("Download summary JSON", json.dumps(summary, indent=2),
                           file_name=f"{run.name}-summary.json", mime="application/json")


render_run()
