# Features adapted from ESCA and RouteAgents

Reviewed September 22, 2026, against framework commit `7c1d9f42edbb8cecdb99d7f181c8e044b64a6166` and the current working tree. This document lists implemented adaptations, explains their purpose, and distinguishes them from unimplemented upstream capabilities and known defects. No optimizer code was changed and no tests or FPGA workloads were run for this review.

The main progression is **ESCA-style deterministic reimplementation and incumbent publication**, followed by **RouteAgents-inspired recipe expansion, persistent learning, and economic search control**. These are adaptations within our existing MCP and generation-search framework, not complete imports of either optimizer.

## Evidence and attribution

- **ESCA:** [jun311k/fpl26_optimization_contest](https://github.com/jun311k/fpl26_optimization_contest), branch `esca-submission`, particularly [SUBMISSION.md](https://github.com/jun311k/fpl26_optimization_contest/blob/esca-submission/SUBMISSION.md) and [dcp_optimizer.py](https://github.com/jun311k/fpl26_optimization_contest/blob/esca-submission/dcp_optimizer.py), inspected on this review date. The [official results page](https://xilinx.github.io/fpl26_optimization_contest/results.html) identifies this repository as ESCA's. These branch links are mutable; the exact upstream revision originally used for the transfer is not recorded locally.
- **RouteAgents:** [Geochatz3/routeagents-fpl26](https://github.com/Geochatz3/routeagents-fpl26), reviewed previously at `4a929b490dad048198e746d15c475a8c19dc5017`. The local [comparison](routeagents-comparison-2026-09-14.md), [implementation guide](routeagents-implementation-guide.md), and [upgrade record](adaptive-optimizer-upgrades.md) document the source-to-implementation mapping. Pinned upstream pages could not be refetched during this review, so that mapping relies on those retained reviews plus current local code and history.
- **Local history:** `3320918` introduced the Slot-A transfer; `cce9c56` added RQS preparation, physical optimization followed by rerouting, and alternative placement shots; `f2455cf` added full-place-route and richer physical classification; `5ff4607` introduced the documented RouteAgents-inspired upgrades; `d68e44d` repaired multiline Tcl execution.

The user identifies ESCA as the earlier reference. Local history calls that work “Slot-A transfer” without naming ESCA. Its implemented sequence and publication mechanism match the ESCA source. This supports attribution at the mechanism level; it does not establish line-for-line copying. Features that already existed in the contest framework, such as MCP integration and general fanout/placement tools, are not counted as newly imported algorithms.

## 1. ESCA-derived features

ESCA uses an aggressive reimplementation slot and a placement-preserving safety slot, with a shared atomic publication gate. Its strategy slot tries Vivado's RQS suggestions and otherwise uses Explore directives. Our transfer brings those implementation and output-retention ideas into a sequential controller. We do not reproduce its two concurrent Vivado processes. Sources: ESCA's submission description and optimizer linked above.

### 1.1 Deterministic global reimplementation

**Implemented:** `run_reimplementation_flow()` measures a baseline, removes routing and placement, runs optimization, placement, optional physical optimization, and routing, then compares the result. A non-improving result or exception restores the baseline. This started as the Explore-based Slot-A transfer in `3320918`.

**Why:** local repairs can remain trapped in a poor global placement. Rebuilding the implementation offers a substantially different candidate without spending model calls deciding every tool command.

**Adaptation:** it is a bounded recipe in our existing controller, rather than a separate upstream optimizer process. The present controller retains the original root and may add the successful reimplementation as another root. This preserves the opportunity for local optimization of the original.

**Evidence:** [executor](../../src/llm_optimizer.py), `run_reimplementation_flow`; [controller](../../src/controller.py), `_search_portfolio`; [earlier design explanation](../generic_optimizer_improvements.md).

### 1.2 RQS suggestions with Explore fallback

**Implemented:** `_prepare_rqs_strategy()` generates QoR reports and tries to load a generated `.rqs` file before unplacing the design. A successful preparation selects RQS directives; unavailable suggestions leave the Explore path usable. Added in `cce9c56`.

**Why:** use tool-generated guidance where available without making optimization depend on that optional capability. A missing suggestion file should not eliminate a viable deterministic recipe.

**Evidence:** [executor](../../src/llm_optimizer.py), `_prepare_rqs_strategy` and `run_reimplementation_flow`.

### 1.3 Budget-dependent physical optimization

**Implemented:** reimplementation checks remaining time against the reserve and an initial minimum. After placement, it estimates routing and physical-optimization time from measured placement duration. It can omit physical optimization or abandon the candidate when the remaining budget is insufficient.

**Why:** an unfinished implementation is not a usable timing result. Reserving time for routing and admission is more valuable than launching another expensive pass with no chance of completing.

**Difference from ESCA:** our recipe can roll back before routing when its estimate does not fit. This is a local adaptation, not a reproduction of upstream scheduling. The estimates are heuristics and do not guarantee deadline compliance.

**Evidence:** [executor](../../src/llm_optimizer.py), `run_reimplementation_flow`; [policy](../../src/policy.py), `should_attempt_reimplementation`.

### 1.4 Publish an incumbent throughout the run

**Implemented originally:** the Slot-A transfer introduced an on-disk incumbent, implementation checks before replacement, and temporary-file publication followed by atomic rename. A later failure need not erase an earlier accepted output.

**Why:** the useful result is the file delivered at termination, not an improvement held only in process memory. This is especially important when a later experiment times out.

**Current evolution:** the RouteAgents-inspired controller now binds this publication to reopened checkpoint bytes, hashes, and measured metrics. ESCA inspired the publication pattern; the later identity and admission corrections are a separate local upgrade.

**Evidence:** introduction in `3320918`; current [controller](../../src/controller.py), `_snapshot_candidate`, `_publish_admitted`, `_finish_search`; [artifact helpers](../../src/admission.py).

### 1.5 Placement-preserving and alternative-placement recipes

**Implemented:** `PHYS_OPT_REROUTE` and `PLACEMENT_SHOT` were added in `cce9c56`. The former combines physical optimization with routing; the latter explores bounded alternative placement directives. Policy filters attempted variants and checks remaining budget.

**Why:** retaining an existing placement can be cheaper than rebuilding it, while a different placement directive may find a result unavailable to the first implementation path. Keeping both choices reduces dependence on a single global recipe.

**Attribution limit:** these correspond to ESCA's safety/alternative-placement mechanisms, but the local commit does not explicitly label each recipe as an ESCA import. They are documented here as adaptations consistent with the Slot-A transfer, not proven copied source.

**Evidence:** [executor](../../src/llm_optimizer.py), `run_placement_shot_flow` and `PHYS_OPT_REROUTE` dispatch; [policy](../../src/policy.py).

### What we did not import from ESCA

We did not import its two-process scheduler, standard-library-only batch-Tcl execution architecture, custom latency-preserving register-surgery toolchain, or one-call veto-only model policy. Our MCP backends and bounded recipe planner remain. Our later optional RETIME adapter is not ESCA's retiming implementation.

## 2. RouteAgents-derived features

The [adaptive upgrade record](adaptive-optimizer-upgrades.md) explicitly identifies five recommendation groups implemented in `5ff4607`. The following breakdown separates physical actions from controller changes so each justification is clear.

### 2.1 Five bounded transformation choices

| Feature | What our implementation does | Why it was added | Current qualification |
|---|---|---|---|
| `GRANULAR_PHYS_OPT` | Executes one allowed critical-pin, placement, routing, or equivalent-driver flag, then routes | Attribute results to a specific sub-operation and avoid always running a broad directive | Implemented; critical-pin optimization produced a small gain in optical flow |
| `SCOPED_PHYS_OPT` | Selects measured critical endpoints and applies placement optimization through a temporary path group | Concentrate effort on a bounded failing population | Implemented but rejected for changed timing constraints in three 09-16 runs |
| `PARTIAL_REPLACE` | Selects movable critical-path LUT/FF cells, temporarily fixes other primitives, replaces the selected subset, and restores fixed flags | Escape local placement problems without rebuilding the entire design | Implemented but FINN failed on the requested `timing_path.POINTS` property |
| `TARGETED_REPLICATION` | Selects measured critical high-fanout non-clock nets and requests Vivado driver replication | Reduce load and routing pressure around critical control signals | Implemented and produced gains, including FINN and BOOM |
| `RETIME` | Runs a supported retiming directive on an isolated unrouted candidate, then routes and invokes a proof adapter | Explore logic-delay improvements beyond placement/routing changes | Disabled by default; external sequential-equivalence checker required |

All use bounded arguments and policy-selected eligibility. The full upstream playbook was not imported. Existing RapidWright FANOUT, pblock, relocation, and other earlier recipes must not be relabeled as newly added RouteAgents actions.

**Evidence:** [recipes](../../src/recipes.py), `NEW_STRATEGIES`, `normalize_recipe`, `execute_recipe`; [policy](../../src/policy.py); [RouteAgents recipe explanation](routeagents-implementation-guide.md).

### 2.2 Stronger artifact admission and correct incumbent ranking

**Implemented:** save a private candidate, reopen it, measure target-clock timing, compare timing constraints and port identity, require affirmative implementation evidence, verify hashes, and publish those exact bytes atomically. Unknown required measurements do not count as passes. The publication manifest identifies the delivered artifact.

Candidate selection no longer rewards an older checkpoint for having been created when less runtime or money had been spent. At publication, the run has incurred the same total cost regardless of which checkpoint is selected. Equally validated candidates are therefore compared by target timing, with secondary timing metrics.

**Why:** prevent speculative or stale measurements from becoming the reported winner and prevent historical accounting from preferring a slower output.

**Qualification:** these are local correctness improvements prompted by the comparison, extending the earlier ESCA-style publication mechanism. They are not a claim that every detail was copied from RouteAgents. General structural/simulation validation remains separate from normal implementation admission.

**Evidence:** [controller](../../src/controller.py), [admission](../../src/admission.py), [scoring](../../src/scoring.py), and the correctness findings in the [original comparison](routeagents-comparison-2026-09-14.md).

### 2.3 Sequential proof requirement for retiming

**Implemented:** a configured external checker receives the original and revised DCPs and must return a successful, hash-bound report attesting cycle accuracy and preservation of reset/initial-state behavior. Changed descendants of a retimed candidate are checked again against the original.

**Why:** improved timing does not establish unchanged behavior. Moving registers can alter externally visible latency or state semantics.

**Qualification:** no proof engine is bundled, and no successful retiming experiment is established by the reviewed logs. This is an experimental capability with an explicit acceptance contract.

**Evidence:** [equivalence adapter](../../src/equivalence.py), `_snapshot_candidate` in [controller](../../src/controller.py), defaults in [search configuration](../../src/search.py).

### 2.4 Persistent positive and negative outcome memory

**Implemented:** SQLite stores complete recipe outcomes, parameters, checkpoint identity, physical features, runtime, cost, and validation/failure information. Retrieval matches action arguments, tool version, device, and similar design features. Nearby records supply gain estimates, uncertainty, and a conservative runtime estimate.

**Why:** successful runs teach where an action helps; failed and neutral runs teach where spending is unlikely to pay off. Attributing cost to the complete attempt includes measurement and checkpoint overhead rather than only the transformation command.

**Qualification:** this adapts the strategy/negative-memory idea to our own SQLite schema. Failed or invalid outcomes contribute no usable positive gain while retaining their costs. Cross-run benefit depends on actually reusing the database; the supplied 09-16 database snapshots alone did not establish successful transfer across runs.

**Evidence:** [outcome memory](../../src/outcome_memory.py), `OutcomeMemory`, `forecast`; outcome recording in [controller](../../src/controller.py).

### 2.5 State-specific repetition control and refreshed evidence

**Implemented:** action history is associated with checkpoint state and arguments. Neutral attempts restore the parent state so a newly written file cannot automatically evade its cooldown. Changed admitted states receive refreshed fanout, geometry, congestion, and timing-anatomy evidence; missing evidence is not silently inherited.

**Why:** avoid paying for the same failed experiment repeatedly while allowing a formerly unhelpful recipe to become useful after a meaningful design change. Refreshed evidence keeps the planner's targets relevant.

**Evidence:** [controller](../../src/controller.py), `_attempt`, `_restore_candidate_state` and evidence refresh; [policy](../../src/policy.py), `apply_action_cooldowns`.

### 2.6 Deterministic opening moves and economic continuation

**Implemented:** a default three deterministic moves precede model-guided exploration. They share the same policy, validation, and outcome tracking. Further action selection compares expected additional benefit with runtime/cost penalties, and default stopping no longer treats reaching zero WNS as the end of useful optimization.

With banked gain `A`, current score multiplier `P`, and proposed additional penalty `d`, the added gain must exceed `A*d/(P-d)` to beat stopping, assuming `P > d`. A weaker branch must also recover its deficit to the incumbent. The implementation requires at least three compatible samples before an optimistic gain estimate can exclude an action economically.

**Why:** reserve model calls for choices where they can help, and spend execution time only when potential improvement justifies it. A positive setup slack does not imply maximum achievable Fmax.

**Qualification:** sparse history still permits exploration. The 09-16 runs show this has not eliminated expensive neutral continuation; implementation presence is not proof of effective calibration.

**Evidence:** [economics](../../src/economics.py), [controller](../../src/controller.py), [search defaults](../../src/search.py).

## 3. Related local work and current limitations

The timing-anatomy classifier, hard-block boundary gate, size-aware full reimplementation gate, independent roots, and `FULL_PLACE_ROUTE` belong to the intervening local generalization work documented in [generic optimizer improvements](../generic_optimizer_improvements.md). They support the transferred mechanisms but should not all be presented as direct upstream imports. Likewise, `d68e44d`'s temporary-script handling fixes our MCP multiline Tcl transport; it is supporting infrastructure, not an imported optimization strategy.

Three issues remain visible in current source and recorded runs:

1. **Baseline admission is too restrictive for repair-oriented search.** `_initialize_search()` sends the baseline through the same implementation gate as a candidate. CoreScore and ISPD16 therefore stopped on DRC failure before optimization. Separating an input usable for search from an output accepted for publication has been discussed but is not implemented.
2. **Scoped and partial replacement need repair.** The scoped recipe still resets endpoints to the default group rather than demonstrating restoration of the original constraint identity. Partial replacement still requests `POINTS`. Their observed failures must not be presented as successful deployments.
3. **Output acceptance is not complete equivalence validation.** Normal route/DRC/hold/pulse checks and unchanged ports/constraints are valuable, but they do not establish full functional equivalence. Retiming has a separate mandatory proof adapter.

## 4. What the observed results justify

The [09-16 analysis](../../results/Analysis%20-%2009_16.md) records useful gains from targeted replication, physical optimization, and combinations following reimplementation. It also records long neutral attempts, recipe defects, and the two baseline admission failures. VTR's successful rerun supersedes its original operational failure in the updated result selection.

These observations support retaining the deterministic reimplementation and targeted-action capabilities while repairing their execution and stopping policies. They do not isolate the causal benefit of persistent memory, retiming, or every upstream-inspired change: a controlled ablation under equal inputs, tools, budgets, and validation requirements has not been established here.

The practical distinction is: **ESCA supplied the earlier reimplementation and incumbent-retention pattern; RouteAgents motivated the later action expansion and learning/economic controller.** Their value depends on correct local execution, measurable gains, and preserving an acceptable delivered checkpoint.
