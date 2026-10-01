# Optimizer dashboard

The local Streamlit dashboard inspects existing optimization runs without
loading Vivado, RapidWright, MCP, or the LLM client.

From the repository root:

```bash
python -m pip install -r requirements-gui.txt
python -m streamlit run gui/app.py --server.address 127.0.0.1
```

Select a parent folder containing run directories, or a run folder containing
`events.jsonl`. Custom run directory names are supported. Enable periodic
refresh to monitor files written by an optimizer launched separately through
the CLI. The first version supports inspection only; run launching and process
control are future work.

The Timing tab charts admitted candidate WNS against event sequence. The
Search explorer shows candidate ancestry and unsuccessful attempts, with the
latest beam and final best candidate highlighted. Select a node to inspect its
fields. Events can be filtered by type and their evidence expanded with the
existing hash and length verification. Summary & output shows the recorded
run summary and checkpoint publication metadata.

Live reads ignore an incomplete trailing JSONL write, while complete malformed
records remain errors. Missing summaries are explicitly marked; they are not
used to infer that a process is running. Unknown metrics remain missing rather
than displaying zero. Published outputs can be unchanged baselines, and timing
improvement does not establish a validated contest score.

Run folders are read from the machine hosting the dashboard. Keep it bound to
localhost for local use: its folder picker and evidence viewer expose local
research artifacts. No authentication or remote access layer is included.
