# Manual recipe workshop

The Web Workspace includes **Workshop**, a side panel beside the tree. Click a
node to select its saved checkpoint, add recipes, edit their parameters, reorder
the steps with drag and drop or the arrow buttons, and choose **Run sequence**. Each sequence creates a
separate managed run; its configuration records the source run, candidate and
checkpoint checksum. The original run and published output are preserved.

The selected node is the Workshop's only checkpoint context; there is no separate
checkpoint selector or play button. Switching nodes, closing the panel or visiting
another tab preserves the recipe draft. The **Workshop** toolbar button toggles
the panel, while **Node details** exposes evidence on demand. Attempts without a
saved candidate, missing DCPs and imported analysis snapshots cannot start runs.

The main tree-node value is theoretical Fmax in MHz: `1000 / (period - node WNS)`.
Its secondary label reports the percentage higher or lower than its parent by default.
The WNS remains visible in smaller muted text. Regressions are labelled as lower
frequency instead of a negative improvement; unavailable timing remains unavailable.
This is an estimate from target-clock timing, independent of final validation.

**Compare** switches between the parent, original baseline, best measured sibling
(Alternative), and best checkpoint in the displayed tree. Missing measurements or
siblings remain unavailable. **Order** ranks nodes vertically within each tree
column by Fmax or the chosen comparison; parent-child connections remain intact.
**Trace path** highlights the ancestry of the selected node while keeping the
other routes visible. **Node list** opens a selectable table grouped by recorded
generation, decision recipe, or ancestry depth. Generations from manual sequences
are labelled separately; missing generation data is not inferred from depth.

**Best** is recalculated whenever an admitted measurement arrives, including an
intermediate result of a manual sequence that is still running. Exactly one
checkpoint carries the badge; equal measurements retain the existing first result.
Queued work and attempts without admitted measurements do not compete. The header
shows the best observed Fmax separately from the original run's recorded output;
these comparisons do not republish or rewrite that output.

## Saved checkpoints

The existing controller retains its baseline, golden input, and every admitted
candidate under `run/admission/`, including neutral and worse candidates. Each
`candidate_admitted` event now records the relative checkpoint path, SHA-256,
clock period and original golden identity. These files remain after cleanup,
failed steps, cancellation, or exclusion from the beam. Failed admission may
leave diagnostic bytes, but does not make a checkpoint selectable.

Workshop verifies the selected checkpoint checksum before queuing. The
worker verifies it again before execution, together with the saved plan checksum.
Manual steps retain implementation, constraint and equivalence admission, tool
capability checks, cancellation and runtime limits. They bypass learned ranking
and automatic state cooldowns. An unavailable or failed step stops the sequence
with an error; the best admitted output and intermediate checkpoints survive.
Each successful step continues from that step's admitted checkpoint, including a
neutral or worse one. Publication still selects the best admitted result.

Retimed seeds retain the original golden identity and must be re-proven with an
`equivalence_command` file configured in Advanced settings. New retiming steps
also require `enable_retiming: true`, as in normal optimizer runs.

For legacy logs that recorded hashes but no paths, execution locates the exact
matching DCP in `run/admission/` on demand. Discovery never guesses from candidate
names or timing, and enqueue re-verifies the selected bytes. Missing hashes or
matching files leave the run unavailable. Imported analysis ZIPs intentionally
exclude DCPs and remain analysis-only. Run Workshop on the host containing
the saved checkpoints.

Queuing a sequence preserves the source tree and the editor. A blue dashed
branch labelled **Manual** appears directly under its source node. Before a
checkpoint is admitted, it shows the actual queued/running/failed/cancelled job
state. Admitted checkpoints replace that placeholder and extend the manual path;
the repeated initialization baseline is folded into the source node. **Show branch**
selects this path without leaving the tree. Selecting any admitted manual result
makes it the source for another manual experiment. Desktop uses the existing side column; narrow screens retain
the tree above the editor. Graph resizing fits the tree to the available canvas
without changing the viewport on ordinary metric updates.

The tree projection resolves provenance using the source run path, local
candidate identity and recorded checkpoint hash. Independent runs use distinct
graph IDs; their original logs, evidence and outputs remain independent. Node
inspection and recipe execution resolve back to the selected node's real run.
Initial comparisons across automatic and manual branches use the original
displayed tree baseline. Parent comparisons use each node's actual ancestry. Local
managed-job manifests restore the branches after restart. Cancelling an experiment
keeps its already admitted checkpoints available. Analysis-only imports remain
read-only; the live manual projection uses the local managed-job workspace.

## Recipe files

Each built-in recipe has its own JSON file in `recipes/`. Copy a new JSON file
into that folder to add a recipe, or compose several existing operations:

```json
{
  "schema_version": 1,
  "id": "explore-then-route",
  "name": "Explore then route",
  "description": "Physical optimization followed by a reroute.",
  "steps": [
    {"strategy": "PHYS_OPT", "args": {"directive": "Explore"}},
    {"strategy": "PHYS_OPT_REROUTE", "args": {"directive": "Explore"}}
  ]
}
```

The recipe selector loads the catalog when opening Workshop. Reload recipes to
pick up file changes. Invalid files are listed under Advanced while other recipes
remain usable. Files declare compositions of the existing supported strategies;
arbitrary Python, Tcl, shell commands and constraint changes are not plugins.
The parameter contract in `src/recipe_catalog.py` supplies defaults and bounds to
both the generic UI editor and manual execution. Plans contain at most 32 steps
and are saved with resolved values, so later catalog edits cannot change queued
work. A new execution primitive requires a controller handler and a reviewed
parameter contract; a new combination only requires a JSON file.

## CLI

Save the same steps in a plan file with a version:

```json
{"schema_version": 1, "steps": [{"strategy": "PHYS_OPT", "args": {"directive": "Explore"}}]}
```

```sh
python dcp_optimizer.py input.dcp --manual-plan plan.json --run-dir runs/manual-01 --output manual-01.dcp
```

Manual mode does not request LLM decisions or require an API key. Vivado,
RapidWright and the optimizer's Python dependencies are still required to execute.

## Implementation and verification scope

Work is based on `feat/web-workspace` at `07e5a96`, incorporating Rodrigo's latest
GUI removal and the current `origin/main`. The older thesis experiment branches
are independent. The main checkout's unrelated untracked files are preserved.

Validation covers catalog loading, exact step arguments, saved checkpoint paths
and checksums, source lineage, neutral/worse-state continuation, stopped failures,
retimed ancestry, worker plan integrity, API boundaries and the browser workflow.
FPGA execution is mocked at the tool boundary for local checks; a real Vivado run
is a separate environment-dependent validation.

Verified locally on 2026-11-11:

- 62 related backend tests passed (`test_playground`, `test_web`, `test_framework`,
  `test_live_log_ingestion`, `test_run_logging`, `test_run_bundle`, `test_drc_policy`,
  `test_deep_run_logging`, `test_generic_optimizer_policy`, `test_recipe_gates`).
- `npm run build` and `npm run lint` passed. The existing large-bundle warning
  remains; no dependency changes were made.
- Three Playwright workflows passed in Edge, including manual editing, arrow and
  drag-and-drop reordering, draft retention across tabs, queueing, mobile overflow,
  live reconnect, cancellation and cloud-import compatibility. Desktop and mobile
  captures are under ignored `web/test-results/`.
- The direct-node follow-up passed 29 affected backend tests and the three
  browser workflows. It also verifies exact intermediate-node selection, retained
  recipe drafts, legacy hash-based DCP lookup and the selected checkpoint context.
- The Workshop sidebar passed build, lint and the three browser workflows.
  Coverage includes direct node selection, implicit source identity, persistence
  across closing/reopening and tab changes, visible tree while editing and
  queuing, frequency/gain/loss labels,
  desktop geometry and mobile tree fitting. Backend contracts are unchanged.
- Manual-tree validation covers queued/running/results, cancellation and failure,
  source checksum isolation, child-log SSE updates, restart persistence, nested
  manual forks, the original root baseline reference and unchanged source logs.
  Browser coverage verifies blue dashed edges, scoped evidence and continuing
  from an admitted manual result without leaving the original tree.
  The synthetic **Workshop example** starts with a three-checkpoint automatic
  chain; branching manually from **middle** preserves the original continuation
  and shows the alternative route next to it. This fixture never launches FPGA
  tools or LLM calls.
  The affected backend gate passed 36 tests and all three browser workflows
  passed, including the three-node chain with two continuations from its middle.
- The broader `test_phys_opt_portfolio` suite has five pre-existing errors: four
  reference the removed `_run_generation_branch` method and one expects the old
  planner schema. The same five errors were independently reproduced from a clean
  archive of `07e5a96`; those tests and the unrelated legacy behavior are unchanged.
- Exploration analysis passed build, lint, 38 affected backend tests and nine
  Playwright checks. Coverage includes live best promotion before job completion,
  restart, all comparison references, alternative exclusion, ordering, grouping,
  path highlighting, list selection, left alignment and mobile overflow. Zoom,
  zoom-out and fit-view work in both themes; rendered icon contrast exceeds 4.5:1.
  Controls and minimap use the workspace theme, including hover and mask colors.
  Explicit initial card dimensions keep minimap nodes visible in the controlled
  graph; minimap rendering and navigation use the same 110 by 70 pixel geometry.
  The tab underline stays inside its header, preventing a spurious vertical
  scrollbar beside Workshop. Native controls and scrollbars follow the theme.

The sandbox blocks Windows asyncio's local socket pair. Backend/browser checks
therefore ran with the approved local-process permission. Test supervisors and
browser servers are disposable. The user-requested Chrome demo is a separate
synthetic fixture with optimizer scheduling disabled.
