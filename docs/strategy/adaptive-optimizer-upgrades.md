# Adaptive optimizer upgrades

Implementation of the five recommendations from the RouteAgents comparison.
Both generation and linear search now use `src/controller.py`; individual
Vivado/RapidWright recipes remain in `src/llm_optimizer.py` and `src/recipes.py`.

This change was reviewed at source level only. No tests, FPGA runs, or performance
experiments were executed for these changes, as requested. The command examples
below are for the configured FPGA environment, not evidence of completed runs.

## 1. Correct artifact ranking and admission

Equally validated candidates rank by target-clock WNS (equivalently Fmax at the
unchanged clock period), then TNS and failing endpoints. Historical candidate
costs remain diagnostic fields. They cannot make an older, slower checkpoint win
after the run has already incurred the later cost.

A candidate is saved to a private DCP, reloaded, measured on
`clk_fpl26contest`, and admitted only with affirmative routing, hold, pulse-width
and DRC evidence. Missing measurements remain unknown. A full routed-net count
equal to the routable-net count plus zero routing errors supplies route evidence;
missing zero-valued subcategories alone do not invalidate that full coverage.

The controller also checks exported timing-XDC identity and port names/directions.
It verifies the private DCP's SHA-256, copies those same bytes to a temporary file,
checks the copy and atomically replaces the output. Only then can `best_candidate`
and `best_wns` change. A rejected speculative result cannot become the reported
winner. Finalization checks the output hash against the admitted candidate.

`published_artifact.json` records the delivered hash, input hash, clock, Fmax,
validation state, configuration, tool/device identification, cost, time and stop
reason. Structural/simulation fields remain pending unless actually established;
implementation admission is not mislabeled as complete functional validation.

## 2. Add bounded transformations

| Recipe | Implementation | Admission |
|---|---|---|
| `GRANULAR_PHYS_OPT` | One of critical-pin, placement, routing or equivalent-driver optimization, then routing | Admitted input and sufficient runtime; each flag has a separate outcome |
| `SCOPED_PHYS_OPT` | Temporary group for measured critical endpoints, placement optimization, restore default grouping, route | Known failing population of 1–2000, with at most 100 paths selected |
| `PARTIAL_REPLACE` | Select movable LUT/FF cells on critical paths; temporarily fix other placed primitives, unplace the selected subset, place, restore original fixed flags and route | At least three sampled paths and average spread of at least 30 tiles; default 50 paths/200 cells |
| `TARGETED_REPLICATION` | Select measured non-clock critical high-fanout nets and invoke Vivado replication | Critical fanout evidence; default at most three nets |
| `RETIME` | Independent unrouted candidate, supported retiming directive, route and sequential-equivalence admission | Explicit opt-in, logic-heavy timing evidence, sufficient runtime, supported directive and checker |

Existing pblock and hard-block gates are retained. Original and RQS/Explore
reimplementation candidates remain separate search roots. The default three
deterministic steps use the same gates and outcome tracking as LLM-selected work.
Thresholds are initial policy assumptions to calibrate on the FPGA environment;
they are not claimed to be measured wins in this project.

All changed candidates pass the same transaction, including older recipes.
Neutral or failed attempts restore the parent. Legal temporary regressions may
continue in a branch, while the best published artifact remains intact.

## 3. Isolate retiming and require sequential equivalence

Retiming is disabled by default. The running Vivado help must advertise the
directive before the policy can expose it. The experiment uses `AddRetime` or
`AlternateFlowWithRetiming` and never accepts a model's assertion of equivalence.

Configure a JSON argv array for your sequential-equivalence adapter, for example:

```json
["/opt/equivalence/bin/dcp-sequential-check"]
```

The controller appends three positional arguments: the immutable copy of the
original DCP, the revised DCP, and a fresh result-JSON path. No shell is involved.
The adapter must invoke the actual checker and exit successfully only after
producing its report. The required report shape is:

```json
{
  "schema_version": 1,
  "equivalent": true,
  "method": "sequential_equivalence",
  "cycle_accurate": true,
  "reset_and_initial_state_preserved": true,
  "golden_sha256": "actual original DCP SHA-256",
  "revised_sha256": "actual revised DCP SHA-256",
  "tool": "actual checker name",
  "tool_version": "actual checker version"
}
```

This is a contract, not a sample proof to reuse. No sequential-equivalence engine
is bundled. Random simulation, matching FF counts, an absent report, a nonzero
exit status, an expired timeout or mismatched hashes cannot satisfy the gate.
Every changed descendant of a retimed candidate is checked again against the
original. Proof identity is stored with the candidate and published manifest.

```bash
python dcp_optimizer.py input.dcp --single-method RETIME \
  --enable-retiming --equivalence-command checker-argv.json \
  --phys-opt-directive AddRetime
```

## 4. Persistent outcomes and refreshed evidence

`optimizer_outcomes.sqlite3` stores versioned records transactionally. Each record
contains the state hash, features, recipe/arguments, full-attempt runtime, LLM
cost, measured gain, admission outcome, and any failure. `recipe_outcomes.jsonl`
also retains the current run's records if persistent storage is unavailable.

Retrieval uses size, failing-population, spatial spread, route fraction, achieved
frequency ratio and fanout. It does not use benchmark names. Tool-version and
device matches prevent importing estimates from a different implementation
environment. Up to 20 nearby records supply success rate, mean gain, gain
uncertainty and a conservative measured runtime quantile. Invalid and failed
attempts contribute zero usable gain, retaining their time/cost penalties.

Credit belongs to the complete recipe transaction, not the last Tcl command.
Cooldowns are attached to the exact checkpoint state and arguments. Re-entering
that same state cannot repeat an already attempted variant; a changed state can
reconsider it. Physical evidence is refreshed after a changed admitted checkpoint,
and the planner receives its checkpoint ID as `evidence_epoch`. Missing refreshed
features are cleared rather than inherited from stale topology.

The target failing-population query is capped at 2001 paths. Reaching the cap
means the exact count and TNS are unavailable, rather than reporting a partial
sum as a full measurement. This is sufficient to exclude an overly broad
population from the scoped recipe.

## 5. Price the next action separately from artifact selection

With banked delta-Fmax A, current score multiplier P and an additional penalty
`d = 0.1 * (additional dollars + additional seconds / 3600)`, the next action
must earn more than `A*d/(P-d)` additional MHz to beat stopping now. A branch
behind the bank must first recover that frequency deficit too.

The controller requires at least three comparable samples before excluding an
action for insufficient expected gain. It uses an optimistic uncertainty bound
to avoid treating a noisy average as conclusive. Unknown evidence allows
exploration; runtime/cost caps and the validation reserve still apply. Economic
exclusions remove the exact flag/directive from the planner schema, not just its
default. `policy_decisions.json` records forecasts and exclusion reasons.

An unavailable provider cost or timed-out model request is recorded as unverified
spend, stops further search, and suppresses final score claims. Model requests
have bounded timeouts and no invisible SDK retries.

Zero WNS and the first positive fast-profile score no longer stop the default
search. Fixed patience applies only with the economic policy disabled. Generation,
branch, step and wall/cost bounds remain hard limits on the experiment.

## Controls for subsequent environment evaluation

```bash
# Generic portfolio without model calls; use --search-mode linear if desired.
python dcp_optimizer.py input.dcp --no-llm

# Isolate individual new physical recipes.
python dcp_optimizer.py input.dcp --single-method PARTIAL_REPLACE
python dcp_optimizer.py input.dcp --single-method SCOPED_PHYS_OPT

# Change one policy component for an ablation.
python dcp_optimizer.py input.dcp --deterministic-steps 0
python dcp_optimizer.py input.dcp --no-outcome-memory
python dcp_optimizer.py input.dcp --no-score-aware-stopping
python dcp_optimizer.py input.dcp --stop-when-timing-met
```

Use `--outcome-memory PATH` to separate training, holdout and production stores.
`--no-outcome-memory` retains learning within the current run but neither reads nor
writes cross-run memory. `--no-refresh-evidence` clears physical evidence on
changed checkpoints for an ablation; it does not pretend old evidence is current.

For later performance evaluation, match input hashes, tool versions, hardware,
budgets and validator settings. Start with the four zero-gain designs plus
VexRiscv and LogicNets as regression anchors. None of those experiments is claimed
as completed by this implementation change.

Vendor command references used during implementation: [group_path](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/group_path?contentId=RcPR5sPUfBS1EMBMRrvqPA),
[unplace_cell](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/unplace_cell),
and [timing-XDC export](https://docs.amd.com/r/2022.1-English/ug903-vivado-using-constraints/Constraints-Processing-Order-and-Invalid-Constraints?contentId=n4o3QdeewxgT4n91rvVQxQ).
