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
Its secondary label reports the percentage higher or lower than the initial Fmax.
The WNS remains visible in smaller muted text. Regressions are labelled as lower
frequency instead of a negative improvement; unavailable timing remains unavailable.
This is an estimate from target-clock timing, independent of final validation.

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

Queuing a sequence preserves the source tree and the editor. **Run created**
provides an **Open run** action; the operator chooses when to switch to the
new execution. Desktop uses the existing side column; narrow screens retain
the tree above the editor. Graph resizing fits the tree to the available canvas
without changing the viewport on ordinary metric updates.

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
  queuing, an explicit switch to the created run, frequency/gain/loss labels,
  desktop geometry and mobile tree fitting. Backend contracts are unchanged.
- The broader `test_phys_opt_portfolio` suite has five pre-existing errors: four
  reference the removed `_run_generation_branch` method and one expects the old
  planner schema. The same five errors were independently reproduced from a clean
  archive of `07e5a96`; those tests and the unrelated legacy behavior are unchanged.

The sandbox blocks Windows asyncio's local socket pair. Backend/browser checks
therefore ran with the approved local-process permission. Test supervisors and
browser servers are disposable; no persistent application server was started.
