# PACT: implementation summary and comparison with our optimizer

Source review dated 2026-09-16. PACT revision: `40810620b70bfa073da6b292d37683b34f764fbf`. Our revision: `d68e44d14fe42bd193eea678b3b983f6acba7f95`. This is a source inspection, not a benchmark run. No optimization or validation workloads were executed.

PACT's most useful contributions for us are a richer set of targeted edits, evidence-bound action selection, explicit retention of useful intermediate candidates, and strict final submission validation. We already share much of its basic architecture: bounded actions, Vivado/RapidWright integration, checkpoint branching, fresh measurement, and budget-aware decisions.

## 1. General strategy

PACT means **Post-route Agentic Checkpoint Tuning**. Its README describes this artifact as a **top-five** FPL'26 submission; it should not be confused with the RouteAgents repository previously discussed.

The core loop is:

1. Inspect a checkpoint and identify its physical or logical bottleneck.
2. Construct actions whose prerequisites and targets are supported by that checkpoint's evidence.
3. Let the decision stage choose among bounded actions and candidate seeds.
4. Execute the selected skill through Vivado or RapidWright.
5. Reopen the emitted checkpoint and measure it centrally.
6. Update the candidate graph, action history, and remaining budget.
7. In submission mode, validate the selected output against the original input before publishing it.

The LLM primarily interprets evidence and chooses actions. The implementation controls what may execute and whether its result is eligible. This is broadly aligned with our design, but PACT has more detailed action prerequisites and physical/semantic operands.

Sources: [README](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/README.md), [agent](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/agent.py), [action contracts](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/action_contracts.py).

## 2. Main implemented features

### Targeted physical and logical actions

The public registry contains **25 skills**, including physical optimization, fanout replication, per-net unroute, critical-net reroute, selective branch reroute, LUT pin swapping, LUT merging, endpoint BEL moves, hard-macro moves, path-local LUT reflow, structure relocation, floorplanning, fresh placement/routing, and implementation recipes.

This goes beyond trying alternative global directives. For example, a route-dominated path can motivate work on a particular net or branch, while a placement bottleneck can motivate movement of an endpoint or a related structure.

The registry also includes operator rewriting, equivalent-source remapping, and semantic replay. These have specialized extraction, eligibility, backend, and proof requirements. Their presence does not mean every input supports them or that every run executes them. Semantic replay can introduce additional source/tool requirements.

Our action library already includes scoped physical optimization, targeted replication, partial and full replacement, floorplanning, and local/macro relocation. The main gap is the granularity and breadth of PACT's surgical and semantic transformations, not the mere availability of placement or replication.

Sources: [skill registry](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/skills/__init__.py), [operator dispatcher](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/skills/operator_rewrite.py).

### Evidence-bound planning

PACT has separate Report, Knowledge, and Decision stage implementations. Report analysis can retrieve bounded excerpts from immutable report snapshots and cite report lines. Action contracts describe required facts, parameter policies, resource estimates, destructive scope, and readiness requirements.

The important mechanism is binding an action to the current seed and verified targets. A plausible diagnosis alone is insufficient to authorize an edit. Changing the seed may require fresh profiling or target certification.

**Released defaults matter:** staged reasoning is enabled, but the Knowledge stage is disabled. Historical case and skills-guide paths point to empty corpora, with zero historical cases in the prompt. Generic taxonomy support remains available. Therefore, describing the default optimizer as repeatedly retrieving successful historical benchmark recipes would be inaccurate.

Our planner already receives a fresh design signature and a bounded eligible-action list. PACT adds more explicit links between the report evidence, exact operand, parameter derivation, and executor readiness.

Sources: [stages](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/stages.py), [configuration](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/config.yaml).

### Candidate graph, diversity, and enabling moves

PACT maintains immutable candidate identities and parent-child relationships. Its beam uses Pareto fronts over measured Fmax and cumulative lineage runtime, with physical-signature diversity used in selection.

It also has a separate **enabling-candidate pool**: a bounded way to retain a legal move that does not immediately improve timing but creates a supported follow-up opportunity. Defaults include beam width 3, enabling-pool capacity 4, and composition depth 2.

For example, a relocation could make a later routing improvement possible without improving the first measurement. This is an illustration of the mechanism, not a measured result from the reviewed artifact.

Our branches can traverse temporary regressions, but we do not explicitly maintain this separate enabling pool or use physical diversity to preserve different search directions. That distinction matters: ordinary beam search can retain several nearly identical candidates and discard useful intermediate ones.

PACT's lineage-runtime objective is a search heuristic. It is not the total incurred contest runtime, and we should preserve our existing same-incurred-cost comparison when choosing the published incumbent.

Sources: [candidate graph](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/candidate_graph.py), [enabling planner](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/enabling_planner.py).

### Central measurement and strict submission

Skills emit checkpoint artifacts and evidence; central measurement reopens the actual checkpoint rather than accepting the skill's reported improvement. It checks target-clock timing, routing, placement completeness, hold, pulse width, and original timing-constraint identity.

In `--submission` mode, the finalizer stages the original and selected checkpoint, verifies their hashes, and requires affirmative structural and randomized-simulation results from a subprocess validator. Skipped simulation and infrastructure failure do not count as passes. Failed finalization restores the original input as the output. The standard `make run_optimizer` entrypoint enables submission mode; other invocation modes must not be assumed to provide the same final gate.

Our normal admission already reopens and hashes candidates, preserves timing constraints and port identity, requires route/DRC/hold/pulse checks, and publishes atomically. However, normal publication does not automatically require the standalone structural-and-simulation validator. Our retiming path separately requires an external sequential-equivalence checker and rechecks descendants against the original.

Randomized simulation is useful validation, but it is not a universal formal-equivalence proof. PACT's specialized local proof machinery must also be distinguished from its general final validator.

Sources: [measurement](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/measurement.py), [submission finalizer](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/submission.py), our [controller](../../src/controller.py), [score validation states](../../src/scoring.py).

### Memory and economics

PACT saves run state, candidate lineage, executed action fingerprints, failures, and evidence. This supports resuming and avoiding repeated attempts against the same state. It also contains configurable historical knowledge and optional registry mechanisms, but the default configuration does not provide an automatically learned cross-run outcome database equivalent to ours.

Our SQLite outcome memory already transfers measured success, neutral outcomes, failures, runtime, and cost between sufficiently similar design signatures, constrained by tool/device/action compatibility. Negative outcomes reduce expected benefit and retain their cost; within-state history also prevents unproductive repetition. This is a capability to preserve.

Both implementations consider limited execution time and LLM cost. PACT additionally has per-stage retrieval/turn bounds, reserve windows, and saturation controls. Its Bayesian-optimization module is disabled by default and configured for shadow use; it should not be presented as the main optimizer.

Sources: [memory](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/memory.py), [configuration](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/config.yaml), our [outcome memory](../../src/outcome_memory.py), [economics](../../src/economics.py).

## 3. Direct comparison

| Area | PACT | Our current implementation | Practical implication |
|---|---|---|---|
| Action selection | Staged analysis and decision, exact-seed action contracts | Deterministic opening actions, then bounded JSON recipe planning | Adopt stronger evidence-to-target binding before adding more stages |
| Physical edits | Broad library including net branches, LUT pins, endpoint BELs, related structures | Scoped optimization, replication, placement/routing and relocation recipes | Add a few targeted primitives with measurable applicability |
| Logic changes | Specialized operator rewrite/remap and proof infrastructure | Opt-in retiming with an external proof adapter | Substantial engineering gap; do not port as a simple flag |
| Search retention | Pareto beam, physical diversity, separate enabling pool | Timing-oriented beam and branch patience | Explicitly retain physically different and useful intermediate states |
| General memory | Run history and configurable knowledge; historical corpus empty by default | Persistent feature-based SQLite outcome estimates | Keep our cross-run learning and improve the evidence it records |
| Repeated failures | Action fingerprints and execution history | State-specific cooldown/history plus failed-outcome forecasts | Shared objective; PACT's exact operand identity can refine ours |
| Candidate measurement | Reopens artifacts; measures centrally; checks constraints and implementation legality | Same central admission principle, including explicit DRC and port checks | Largely shared foundation |
| Final submission | Strict structural + randomized simulation in submission mode | Implementation admission; separate proof requirement for retiming | Add a reserved final validation phase |
| Budget handling | Stage/action bounds, reserves, saturation, score scheduling | Expected gain versus runtime/cost, persistent forecasts, reserved time | Combine selective evidence collection with existing economics |

## 4. What the reported results actually establish

The manuscript reports geometric-mean Fmax improvements of **22.30% for PACT**, **15.14% for DATuner**, and **9.78% for its Codex Agent baseline** over 35 designs. That Codex baseline is not our repository.

The more useful comparison is its ablation:

| Method | Development: 27 designs | Held-out: 8 designs | All 35 |
|---|---:|---:|---:|
| PACT | +27.70% | +5.70% | +22.30% |
| Same action/gate framework without the LLM | +16.78% | +5.54% | +14.11% |
| Pure physical-optimization directive sweep | +3.53% | +1.12% | +2.98% |

These are authors' reported results, not measurements reproduced here. Their held-out comparison suggests that the structured actions and execution framework account for much of the generalization benefit. It does not support assuming that more LLM calls will improve our optimizer. Their small cross-design evidence experiment also reports little additional benefit from retrieved cases beyond the existing recipe selection.

The README explicitly says the complete 35-design reproduction package is absent. The released configuration also selects a different model from the paper's GPT-5.5 experiments. Consequently, neither the headline improvement nor paper cost numbers can be assigned to our workload or to a run of the current defaults without evaluation.

Sources: [manuscript, ablation and generalization section](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/journals/fpt-2026.tex), [artifact limitations](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/README.md).

## 5. Recommended adoption order

1. **Complete final validation.** Reserve time to run structural and randomized-simulation validation against the original input, bind evidence to exact output hashes, and retain an explicitly validated fallback. Preserve stronger sequential proof requirements for retiming.
2. **Add a small targeted action set.** Start with critical-net/branch rerouting and endpoint or path-local placement edits. Require fresh evidence that identifies the bottleneck, affected operands, legality requirements, and bounded repair cost.
3. **Preserve useful intermediate candidates.** Add physical diversity and a small enabling pool with explicit follow-up actions, expiry, depth limits, and runtime limits. Keep publication ranking separate from exploration ranking.
4. **Record action-level evidence.** Extend our existing persistent memory with target characteristics and physical changes, so two executions of the same recipe can be distinguished by what they actually changed.
5. **Evaluate richer semantic rewrites later.** Begin with a narrowly defined transformation and independent proof boundary. PACT's large semantic infrastructure should not be copied wholesale without validating prerequisites and assumptions.

For the supplied mini-ISP signature, route delay accounts for approximately 85% of critical-path delay, with severe congestion, high-fanout control signals, and BRAM involvement. That makes targeted routing, replication, and placement the first hypotheses to investigate. It does not by itself establish that retiming or arithmetic rewriting would help. The reported run stopped during port-digest initialization, so it provides no evidence that an optimization action succeeded or failed.

One implementation detail deserves care before borrowing clock-pressure recipes: PACT has fresh-place logic that restores original timing constraints, while its separate legacy `clock_tighten` skill describes emitting a modified-clock checkpoint. Central measurement rejects changed constraint identities. Copy the restore-and-remeasure discipline, not a converted WNS value as a substitute for measuring under the original constraints. Sources: [fresh placement](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/skills/fresh_place_route.py), [clock skill](https://github.com/FudanLLMEDA/PACT/blob/40810620b70bfa073da6b292d37683b34f764fbf/FDAgents/skills/clock_tighten.py).

The next evaluation should compare one addition at a time against our unchanged baseline under the same checkpoints, tool version, total runtime, model/cost policy, and validation requirements. Measure validated Fmax, cost, failed attempts, and time spent on analysis versus execution. No performance improvement from these proposed changes is established by this review.
