# RouteAgents comparison and improvement plan

Reviewed 2026-09-14. Our source commit: `56b3880c60ebf3329a9d28afb8e4e952a8c1711d`. RouteAgents main: `4a929b490dad048198e746d15c475a8c19dc5017`. Source checkout: `.comparison/routeagents-fpl26`. This is a source review and analysis of existing results, not a Vivado reproduction or a change to optimization behavior.

## Evidence and ranking

The linked repository describes a **top-five** result, not first place. Its author reports an official seven-design score of 369.9, seven improvements, and no validation failures. An independent first-place ranking was not established here.

[Provenance](https://github.com/Geochatz3/routeagents-fpl26/blob/main/docs/PROVENANCE.md) identifies the scored commit as `d8ae7bd8f1f8e4f434d21c751fd853f73be7ed96`, tag `fpl26-final-submission`. Main has subsequent fixes and omits the submission's measured seed memory. Main is therefore useful for learning mechanisms but is not a byte-exact reproduction of the evaluated system. Its priors were developed on 19 public designs, from which the seven evaluated inputs were selected. This does not establish generalization to unseen design families.

## What the approach actually is

RouteAgents combines a deterministic optimizer portfolio with an LLM that chooses and parameterizes additional transformations. There is no evidence here that training different model weights is the principal source of improvement.

1. Measure target-clock timing, failing endpoints, path geometry and available structural evidence.
2. Select an ordered recipe plan from features, with explicit exclusions and runtime gates.
3. Execute deterministic recipes before paying for exploratory model calls.
4. Let the model inspect fresh reports and select cells, nets, endpoints and recipe macros.
5. On stagnation, explore alternate placements, partial re-placement and routing/physical-optimization polish.
6. Retain measured, routed, acceptable checkpoints and finalize the best deliverable.

The advertised 42 plays include directive variants, sequence variants and wrapper stages; they are not 42 independent physical algorithms. The meaningful extension is a broader, empirically gated repertoire. See [playbook](https://github.com/Geochatz3/routeagents-fpl26/blob/main/docs/PLAYBOOK.md) and [methods](https://github.com/Geochatz3/routeagents-fpl26/blob/main/docs/METHODS.md).

Examples verified against the source:

- `optimizer/recipe_router.py` selects plans using slack, achieved/target frequency ratio, endpoint count, spread and remaining time. Very large failing populations can lead to full-scope retiming; smaller populations can justify focused work.
- `optimizer/recipe_passes.py` exposes retiming, LUT-cone optimization, granular phys-opt, endpoint-scoped phys-opt and targeted replication macros.
- `optimizer/ils_polish.py` rotates placement and routing moves. Partial ruin unplaces cells on critical paths rather than the whole design. It is skipped when average spread is unknown or below 30 tiles. A concluding playbook sentence reverses this inequality; the implementation and lead table agree on the skip condition.
- `optimizer/strategy_memory.py` retrieves prior outcomes by structural fingerprint. Offline successes and failures guide future selection; this is separate from per-run patience.
- `optimizer/wall_economics.py` relates observed gain to the score penalty of additional runtime. `logic_floor.py` adds a heuristic headroom certificate with repeated timing measurements. Its per-hop assumptions should be calibrated, not treated as a universal physical bound.

## Comparison with our implementation

| Mechanism | What we already have | Transfer opportunity |
|---|---|---|
| Feature-based selection | `src/analysis.py`, `src/policy.py`: timing anatomy, congestion, path spread, fanout and hard-block topology | Learn ordered recipe preferences and exclusions from measured outcomes; enrich failing-population and logic-depth distinctions |
| Checkpoint exploration | Baseline and reimplementation roots; branch/generation search; placement shots | Add partial re-placement and selected independent restart families, rather than simply increasing branch count |
| Local transformations | Phys-opt portfolio, critical-pin optimization, fanout, preserved reroute, cell relocation and macro relocation | Add scoped phys-opt and granular flags first; evaluate retiming and LUT merging separately |
| LLM role | Bounded JSON recipe planner; controller selects operands | Allow bounded selection among freshly measured operand candidates where useful; retain the structured contract |
| Memory | Lane-local cooldowns and prompt optimization workflow | Persist state/action/runtime/gain/validation records across runs; retrieve by features |
| Budget | Runtime/cost caps, reserve, WNS/minute threshold, fast-profile stopping | Use expected incremental contest score and measured action durations |
| Artifact publication | Atomic replacement and route/DRC/hold/pulse checks already exist | Bind measured state, candidate validity, reported best and output checksum together |
| Constraint integrity | No corresponding fingerprint found in the inspected optimizer | Fingerprint timing constraints before/after transformations and reject unexpected changes |

Our prompt explicitly prohibits retiming and LUT merging as default strategies. Some underlying MCP capabilities already exist; the missing work is recipe orchestration, admissibility, validation and experiments, not necessarily a new tool server. Our existing prompt optimization should learn from real design outcomes, rather than only agreement with hand-labelled recipe choices.

## Concrete local correctness concerns

1. **Scores use different historical costs.** `_candidate_score_metadata` captures elapsed time and cost when a candidate is created; `_candidate_sort_key` later compares these stored scores. Once time and money have been spent, every possible final artifact shares that run-level cost. For example, 100 MHz gained at penalty 0.99 has stored score 99; a later 101 MHz at 0.97 has score 97.97. At finalization the first is actually worth 97, so the later artifact is better. Rank equally valid artifacts with the current common penalty or by achieved frequency; use expected score separately to decide whether to launch another action.
2. **Reported best precedes admission.** `_run_generation_branch` assigns `best_candidate` before awaiting `_publish_current_candidate`. A rejected candidate can remain the search best; finalization reports its WNS while retaining an older published artifact. Separate exploratory state from an admitted incumbent and derive delivered metrics from that incumbent. The existing publication gates prevent directly equating this with an unchecked artifact overwrite.
3. **Missing measurements can appear successful.** The hold query maps no returned path to 999 ns; route admission tolerates some missing counters; pulse/DRC checks rely on absence of matching violation text. Represent unavailable measurements explicitly and require affirmative evidence for required gates.
4. **Timing met is not necessarily optimal Fmax.** `GenerationSearchConfig.stop_when_timing_met` defaults true. Evaluate the existing `--continue-after-timing-met` option with score-based stopping; do not assume zero WNS exhausts the contest objective.
5. **Physical evidence is initially frozen.** `SYSTEM_PROMPT.TXT` explicitly says so. Refresh relevant topology after accepted changes; allow previously neutral actions to be reconsidered after a material state change rather than cooling them down for the whole lineage.

## What the available results suggest

Our `run-20260908_180929/optimizer_results.csv` contains 12 designs: eight positive gains and four zero gains. Formula-derived aggregate projected score is approximately 378.57. This is not comparable to their seven-design 369.9, and it is not a validated score. `run_all_dcps.sh` labels exit code zero as PASS; this does not prove equivalence.

| Design family | Our Sept 8 delta MHz | RouteAgents reported delta MHz | Interpretation |
|---|---:|---:|---|
| Mini-ISP | 97.08 | 125.2 | Their name explicitly includes v2; compare matched input hashes first |
| FINN RadioML | 0.00 | 65.2 | Strong target for missing-transformation experiments |
| Rosetta 3D | 0.00 | 48.7 | Their v2 input prevents direct attribution |
| Rosetta digit | 47.11 | 92.4 | Test structured diversification after our initial gain |
| VTR MCML | 0.00 | 5.1 | Test whether scoped/cheap moves can earn a modest gain |

These are family-level pointers, not measured head-to-head gaps. Hardware, input hashes, settings, execution time and validation differ or are unavailable. Our local VexRiscv gain of 145.20 MHz and LogicNets gain of 69.49 MHz are useful regression anchors. The CSV cannot establish which transformation caused a plateau.

## Recommended sequence

**P0: Make comparison and delivery trustworthy.** Correct common-cost candidate ranking and admitted-best reporting. Strengthen unknown-state admission. Record output hash, measured target-clock Fmax, validation results, tool versions, configuration and total wall/cost. Add meaningful regression cases for each corrected behavior.

**P1: Extend affordable transformations.** Add granular phys-opt flags, focused endpoint groups, targeted Vivado replication and partial re-placement. Execute a small feature-selected deterministic portfolio with before/after measurements and rollback. Keep our existing pblock and hard-block gates until experiments justify alternatives.

**P2: Add retiming as an explicit experimental recipe.** Use independent checkpoints, device/directive compatibility checks, unchanged timing constraints and suitable functional validation. FF counts and randomized simulation alone are not proof of sequential equivalence. Establish the acceptable equivalence procedure before enabling this by default. Evaluate LUT merging afterward as a separate ablation.

**P3: Improve policy from data.** Persist outcome records, including failures and neutral runs; fit recipe success/gain/runtime estimates by features. Refresh evidence after accepted changes. Distinguish costly action chains from isolated moves when assigning credit. RouteAgents itself discloses recency-based attribution, which cannot prove the last move caused the entire gain.

**P4: Price exploration.** Let A be banked delta-Fmax and P the current score multiplier. For an action with additional penalty d = 0.1*(additional dollars + additional seconds/3600), continuing beats stopping only when expected additional gain g satisfies `g > A*d/(P-d)`, assuming P>d and costs are fixed for that comparison. With A=100 MHz, P=0.98 and a ten-minute, zero-LLM-cost action, the break-even gain is about 1.73 MHz. Apply confidence and feasibility gates to the forecast; elapsed time already spent is sunk.

Run staged ablations on identical input hashes, machines, Vivado versions and budgets. Start with the four zero-gain designs plus VexRiscv and LogicNets, then test the full suite. Use multiple independent runs where placement variance matters. Report validated score, gain, time, cost, failure count and delivered artifact identity. Learn thresholds on a training subset and evaluate by held-out design family. Do not import all 42 plays or their fitted thresholds simultaneously.

## Limits on borrowing

RouteAgents has useful mechanisms, but its constraint fingerprint explicitly reports UNVERIFIED and continues when capture fails; do not copy that as proof of integrity. Its published admission tolerances and fitted thresholds should not replace our stricter validation without evidence. The public release omits measured seed priors, and offline tests do not establish FPGA performance. Preserve Apache-2.0 notices and attribution if source is copied. No competitor code was integrated by this review.
