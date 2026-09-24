# Run data for analysis

Every `dcp_optimizer.py` invocation that reaches a run mode creates a unique
`dcp_optimizer_run-*` directory. The runner writes these files during the run:

| File | Grain | Use |
| --- | --- | --- |
| `events.jsonl` | One ordered event | Full causal timeline with decision, policy, attempt, candidate, and tool IDs |
| `evidence/*.json.gz`, `evidence/*.text.gz` | One unique payload | Exact redacted planner input and response, policy evidence, recipe outcome, tool arguments and result |
| `run_summary.json` | One run | Join key, mode, configuration, status, runtime, headline metrics and usage |
| `recipe_outcomes.jsonl` | One recipe attempt in the adaptive controller | Strategy, seed and candidate hashes, validation, physical features and measured gain |
| `token_usage.json` | One adaptive run, with per-call details | LLM and tool cost analysis, candidate scores |
| `published_artifact.json` | Current published checkpoint state | Identify the admitted output and its validation status |

`run_id` joins `events.jsonl`, `run_summary.json`, and the adaptive controller's
`recipe_outcomes.jsonl` and `published_artifact.json`. `decision_id` joins a
planner request and selected action; `attempt_id` joins its tool calls, admitted
candidate, and measured recipe outcome. `policy_eval_id` groups each evaluated
action variant and final allow-list. `call_id` pairs tool events with their
argument and result evidence. Timestamps are UTC and
durations are seconds. Metric names include units (`wns_ns`, `fmax_mhz`,
`cost_usd`). Missing measurements are JSON `null`, never zero. AER publishes
admitted candidates during the search, including the baseline. An existing
output can therefore still be the baseline; compare the candidate IDs and
metrics before treating it as an optimization gain. `output_validated` reflects
the available validation status and must not be read as a separate final
simulation gate. Test mode records its measured baseline and final WNS in
`test_metrics` but does not use the adaptive controller's recipe outcome file.

The recorder stores the exact planner request and response and raw text returned
by each MCP tool as compressed, content-addressed evidence. It recursively
redacts API-key fields, configured API-key values, and Bearer headers before
writing. It does not copy the environment or DCP binaries. Source DCPs and
checkpoint paths remain in the run directory and manifest. **Treat complete run
directories as private research artifacts:** design names, reports, and prompts
can still be sensitive despite credential redaction. Evidence references include
SHA-256 and uncompressed byte length so corruption can be detected.

Recorded decision points include policy variants and their forecast/admission
reason, the eligible action set and physical evidence, deterministic or LLM
selection source, every recipe attempt and tool result, candidate admission,
beam selection, publication decisions, budget stops, and the
terminal run status. Some external process failures can still interrupt before
Python writes its final summary; the flushed event stream and prior evidence
remain readable in that case.

Inspect a run without FPGA dependencies:

```bash
python tools/inspect_run.py dcp_optimizer_run-... --verify
python tools/inspect_run.py dcp_optimizer_run-... --decision decision-...
python tools/inspect_run.py dcp_optimizer_run-... --attempt attempt-...
python tools/inspect_run.py dcp_optimizer_run-... --decision decision-... --expand
python tools/inspect_run.py dcp_optimizer_run-... --evidence <sha256>
```

Export selected event types as CSV for plotting:

```bash
python -m tools.export_run_tables --out analysis_tables dcp_optimizer_run-...
```

This writes `runs.csv`, `events.csv`, `decisions.csv`, `attempts.csv`,
`tools.csv`, `llm_calls.csv`, `policy_variants.csv`, `candidates.csv`, and
`beams.csv` when those event types exist. It also writes `tree_nodes.csv`,
`tree_edges.csv`, and `beam_memberships.csv`. Candidate nodes contain parent IDs,
generation, timing metrics, strategy, and linked attempt IDs. Attempts that did
not admit a candidate become dashed terminal nodes, so failed explorations are
visible too. `beam_memberships.csv` marks candidates considered and retained at
each beam selection. A node is a **search candidate or attempt**, not an FPGA
cell or net. Nested values remain JSON strings in CSV cells. Retain the original
JSONL and evidence files as the authoritative record; CSV is a derived analysis
view.

For a quick debug graph, generate a standalone SVG and open it in a browser:

```bash
python -m tools.export_search_tree dcp_optimizer_run-... --out search_tree.svg
```

The graph shows candidate ancestry, unsuccessful attempt leaves, edge strategies
and WNS changes. Green marks the final best candidate; an orange border marks
membership in the last selected beam. Hover over a node for its recorded fields.
For later styling with Graphviz, export the same graph with `--out search_tree.dot`.

To inspect all exported fields inside square Mermaid nodes, use:

```bash
python -m tools.export_search_tree dcp_optimizer_run-... --out search_tree.mmd
```

Open the `.mmd` file in a Mermaid viewer or paste it into a Mermaid code block.
Arrows show parent-to-candidate and parent-to-unsuccessful-attempt relationships,
with strategy and WNS change on each edge. Node labels include every non-null
field from `tree_nodes.csv` except the duplicated `node_id` and `run_dir`,
including IDs, timing, score, validation, hashes, and evidence references.
Full tool responses and planner payloads stay in the
referenced evidence blobs; use `inspect_run.py --attempt ... --expand` to inspect
those without making the graph unreadably large.

Example to load the two tabular sources with pandas:

```python
import json
import pandas as pd
from pathlib import Path

run_dir = Path("dcp_optimizer_run-...")
summary = json.loads((run_dir / "run_summary.json").read_text())
events = pd.read_json(run_dir / "events.jsonl", lines=True)
attempts_path = run_dir / "recipe_outcomes.jsonl"
attempts = pd.read_json(attempts_path, lines=True) if attempts_path.exists() else pd.DataFrame()

print(summary["status"], summary["metrics"])
print(events.loc[events["event"] == "recipe_attempt", ["elapsed_seconds", "strategy", "wns_ns"]])
```

The summary's `final_fmax_mhz` is derived from the reported clock period and
WNS. Contest score and publication details remain in `token_usage.json` and
`published_artifact.json`; WNS improvement by itself is not a validated score.
