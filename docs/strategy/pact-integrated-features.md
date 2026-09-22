# PACT-inspired integration: changes and justifications

Implemented on `test/pact`, 2026-09-22, against local base commit `7c1d9f42edbb8cecdb99d7f181c8e044b64a6166`.

This document covers the new PACT-inspired changes. The earlier [ESCA and RouteAgents integration](esca-routeagents-integrated-features.md) remains a separate document. Source context and the original recommendations are in the [PACT comparison](pact-comparison-2026-09-16.md), which reviewed PACT revision `40810620b70bfa073da6b292d37683b34f764fbf`.

The strategy is to make the existing optimizer more selective about **where it edits**, more deliberate about **which intermediate states it retains**, and stricter about **which final artifact it delivers**. This is an adaptation to our controller, not a full port of PACT or evidence of a measured performance gain.

## Changes at a glance

| Change | Previous behavior | Implemented behavior | Justification |
|---|---|---|---|
| Targeted physical actions | Existing global/scoped recipes and relocation actions | Three additional recipes select current critical-path terminal nets, sink branches, or terminal cells | Explore smaller physical edits when routing or placement evidence supports them |
| Seed-bound action contracts | Planner received design evidence and eligible actions | Prompt includes seed hash, reason, and bounded arguments; executor restores the seed and rechecks eligibility | Avoid executing a decision against stale checkpoint evidence |
| Operand evidence | Outcomes primarily described recipe and timing | New recipes record exact selected objects before mutation; outcomes also record physical before/after features | Make successes and failures traceable to their actual targets |
| Physical beam diversity | Ranked candidates principally by timing/score | Preserve the best candidate, then favor physically different candidates in a bounded quality shortlist | Avoid spending multiple branches on nearly identical physical states |
| Enabling candidates | Neutral moves usually returned to their parent | Separate bounded pool retains neutral or slightly regressive states with measurable physical improvement | Allow a placement or replication move to prepare a useful reroute |
| Final validation | Normal publication required implementation admission | Optimized output additionally requires structural checks and randomized simulation against the original input | A timing improvement alone does not establish functional correctness |

## 1. Three targeted recipes

Implemented in [pact_actions.py](../../src/pact_actions.py), exposed through the existing planner, single-method interface, and controller.

| Strategy | Current-seed targets and operation | Default scope | Eligibility |
|---|---|---|---|
| `CRITICAL_NET_REROUTE` | Nets attached to terminals of the top 50 target-clock timing paths; unroute, timing-driven reroute, then preserve routing | 4 nets; hard limit 8 | Route-dominated evidence and at least 360 seconds beyond the reserve |
| `CRITICAL_BRANCH_REROUTE` | Input endpoint pins on those paths; unroute/reroute selected sink branches, then preserve routing | 4 pins; hard limit 8 | Same routing evidence and runtime gate |
| `PATH_LOCAL_REPLACE` | Movable LUT/FD cells at those path terminals; temporarily fix other placed primitives, unplace selected cells, place with `Quick`, restore original lock flags, route with `Explore` | 20 cells; hard limit 50 | At least 3 analyzed paths, mean spread at least 30, and 900 seconds beyond the reserve |

Selection excludes clock, protected, or fixed nets for routing actions, and protected or location/BEL-fixed cells for replacement. Empty target sets fail the action. The executor selects targets from Vivado after restoring the checkpoint; the LLM does not supply object names. Exact targets are recorded before mutation.

These are deliberately limited implementations. Net selection covers **path-terminal nets**, not every internal net along each path. Replacement covers **terminal cells**, not a complete path-local LUT reflow. Final route completion can touch routing beyond the initial target set. These recipes do not implement PACT's full skill library.

The Tcl uses documented [route_design options](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/route_design) and [timing-path properties](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/get_timing_paths). Compatibility and physical effects still require a run with our installed Vivado version.

## 2. Evidence and execution contracts

The planner payload now includes `action_contracts`: the seed SHA-256, eligibility reason, and bounded default arguments. Immediately before execution, the controller restores and hash-checks the parent, recomputes eligibility, and checks enumerated parameters. The new actions apply their own count limits and extract targets from that live design.

`recipe_outcomes.jsonl` and the existing SQLite outcome payload now include the action contract, selected operands for new recipes, and physical before/after summaries. Existing persistent forecasting still uses its original compatible-design/action features; it does **not yet learn target-specific success probabilities** from the new fields.

This adapts PACT's [action-contract idea](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/action_contracts.py). It does not add PACT's staged report retrieval or report-line citation machinery.

## 3. Physically diverse beam

[pact_search.py](../../src/pact_search.py) compares mean path spread, maximum congestion level, routing-delay percentage, and maximum reported high fanout. Distances normalize these features by fixed scales of 100, 5, 100, and 500. At least two shared measurements are required; missing evidence earns no diversity credit.

Selection keeps the highest-ranked implementation-valid candidate first. Remaining slots favor maximum distance from the selected candidates within the top `3 × beam_width` candidates. Hash-identical checkpoints are deduplicated. Existing ranking breaks distance ties and continues to govern the published incumbent.

This is simpler than PACT's Pareto selection over frequency and lineage runtime. We preserve our existing incurred-cost economics. With beam width 1, diversity has no effect; this matters for the fast profile.

## 4. Intermediate moves: retained for a specific follow-up

A candidate can enter the enabling pool only after normal implementation admission, when its immediate WNS improvement is no greater than the configured meaningful-gain threshold and it satisfies all of these conditions:

- WNS regression relative to its parent is at most **0.010 ns**.
- A fresh measurement shows at least **5% less path spread**, **10% less reported high fanout**, or **10% less congestion**.
- Its producer is `PATH_LOCAL_REPLACE`, `PARTIAL_REPLACE`, `TARGETED_REPLICATION`, `CELL_RELOCATE`, or `PBLOCK`.
- The pool and composition-depth limits permit retention.

Example: a relocation reduces average spread from 60 to 54 while WNS changes from -1.000 to -1.005 ns. It may be retained for a subsequent `CRITICAL_NET_REROUTE`. An equally slow candidate with no measured physical improvement is discarded from this pool. This is illustrative, not a benchmark result.

Defaults are capacity **4**, depth cap **2**, lifetime **600 seconds**, and a total follow-up allowance of **600 seconds per run**. At generation boundaries, each selected state gets at most one prescribed reroute attempt, subject to fresh eligibility and remaining time. The current prescribed reroute is not itself an enabling producer, so this is principally a producer→reroute pair, not a general multi-step composition planner. `enabling_moves.json` records retention, selection, expiry, and capacity retirement. Selection does not guarantee execution if the budget or eligibility check prevents it.

Retaining an intermediate state does not bypass publication ranking or any admission check. A state with worse timing cannot replace a better incumbent merely because its physical signature improved. Evidence collection now also runs for neutral candidates when time permits; this adds runtime cost.

Inspiration: PACT's [enabling planner](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/enabling_planner.py).

## 5. Strict final publication

[submission.py](../../src/submission.py) and [submission_worker.py](../../src/submission_worker.py) wrap the existing two-phase [validator](../../validate_dcps.py) in an isolated subprocess.

1. Preserve a byte-identical golden input and publish that fallback after baseline admission.
2. Keep improved candidates internally during search; do not publish them yet.
3. Bound the search phase by the remaining runtime minus the validation reserve, then close search servers.
4. Validate the selected checkpoint against the original with structural checks and randomized simulation.
5. Require explicit boolean passes for both phases, no simulation skip, no infrastructure failure, a successful subprocess exit, and matching artifact hashes.
6. Atomically publish the validated candidate. On validation failure, restore the unchanged input and report an unsuccessful run.

The default final validator timeout is **480 seconds**, inside the existing **600-second reserve**, with **1,000 simulation vectors**. Timeout or cancellation terminates the validator process tree. Search-server cleanup runs in the original task because its MCP/AnyIO contexts require task-local unwinding; that cleanup has no separate hard deadline and can reduce the time available for validation. Reports and logs are preserved; `published_artifact.json` records the delivered artifact and final-validation evidence. A run that selects the unchanged input uses byte identity as its equivalence basis; it does not execute or claim to have executed simulation for that case.

Randomized simulation is not formal equivalence. The existing external sequential-equivalence requirement for retiming remains. Encrypted-IP simulation skips now reject an optimized final candidate rather than counting as success. This may increase fallback frequency and consume more runtime; these are deliberate tradeoffs to measure.

Inspiration: PACT's [submission finalizer](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/submission.py).

## 6. Controls and files

The four features are enabled by default. CLI ablations are `--no-targeted-actions`, `--no-physical-diversity`, `--no-enabling-moves`, and `--no-final-validation`. The last switch allows implementation-admitted publication without the new functional gate and is intended for diagnostic comparisons. Validator controls are `--final-validation-timeout-seconds` and `--final-validation-vectors`; `--validation-reserve-seconds` still controls reserved time. Pool limits are configurable through `GenerationSearchConfig`.

| Files | Responsibility |
|---|---|
| [controller.py](../../src/controller.py) | Eligibility, action transactions, evidence refresh, beam/pool integration, deadlines, publication and fallback |
| [pact_actions.py](../../src/pact_actions.py) | Target extraction, bounded Tcl actions, operand evidence |
| [pact_search.py](../../src/pact_search.py) | Physical distance, diverse selection, enabling pool |
| [submission.py](../../src/submission.py), [submission_worker.py](../../src/submission_worker.py) | Isolated strict validator, hashes, deadlines and reports |
| [search.py](../../src/search.py), [dcp_optimizer.py](../../dcp_optimizer.py) | Defaults and CLI controls |
| [llm_optimizer.py](../../src/llm_optimizer.py), [prompting.py](../../src/prompting.py), [SYSTEM_PROMPT.TXT](../../SYSTEM_PROMPT.TXT) | Planner contracts, normalization and dispatch |
| [test_pact_search.py](../../tests/test_pact_search.py), [test_submission.py](../../tests/test_submission.py) | Offline policy and mocked report-validation regressions, authored but not executed |

## 7. Scope and verification limits

No operator rewriting, semantic replay, equivalent-source remapping, LUT merging/pin-swap library, PACT historical knowledge stage, or Bayesian optimization was added. Existing ESCA/RouteAgents features, persistent memory, and economic forecasts remain in place.

The pre-existing strict **baseline DRC admission** rule remains: a broken input can still be rejected before optimization starts. This integration does not solve that earlier failure mode. Separating permissive input diagnosis from strict candidate/output admission is a distinct controller change.

Verification for this integration is static only: Python syntax parsing and patch whitespace checks. Offline regression tests were authored but not run. No Vivado, RapidWright, simulation, optimization, or benchmark workload was executed. Runtime compatibility, cancellation behavior across the MCP processes, and Fmax/contest-score benefit remain unverified.

The next experimental comparison should hold benchmark inputs, tool version, runtime, and LLM budget constant, then compare the full integration against each ablation. Track delivered Fmax and score, validator fallback rate, targeted-action success/runtime, and how often an enabling move produces a better descendant. Reporting only the best pre-validation timing would overstate delivered results.
