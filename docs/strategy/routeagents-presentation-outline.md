# RouteAgents: implementation and optimization strategy

Eight slides for an audience familiar with the contest and FPGA optimization. Suggested duration: 8–10 minutes. Copy **Slide text** into the slides and use **Speaker notes** for technical explanation.

Source reviewed: public commit `4a929b490dad048198e746d15c475a8c19dc5017`. The [implementation guide](routeagents-implementation-guide.md) contains detailed explanations and commit-pinned source links.

---

## Slide 1 — A feature-selected portfolio drives the search

### Slide text

- Start with deterministic recipes selected from measured features.
- Give the LLM an ordered plan, exclusions, and concrete targeting tools.
- Explore alternative placements when local optimization stalls.
- Retain measured improvements and price the next experiment.

**The strategy combines planned first moves with adaptive exploration.**

### Speaker notes

RouteAgents organizes the search around physical situations. Different designs receive different starting sequences. The model and later search stages explore beyond those sequences.

The controller coordinates broad operations, focused changes, and multi-step chains. Its contribution is deciding which moves to try, in what order, and under what conditions. The advertised 42 plays include directive variants and controller stages, rather than 42 independent physical algorithms.

### Visual

Use four blocks: feature routing, deterministic recipes, model-guided exploration, and placement/routing polish. Show the retained best checkpoint below the search stages.

Code: `recipe_router.py`, `recipe_passes.py`, `polish_ladder.py`, `finalization.py`.

---

## Slide 2 — The router selects sequences and blocks poor choices

### Slide text

| Evidence | Strategy family |
|---|---|
| Deep failure with many failing endpoints | Broad retiming or route-first work |
| Dispersed critical paths and sufficient budget | Re-placement or a placement-preserving sweep |
| Small residual timing gap | Scoped physical optimization and polish |
| Missing evidence or insufficient time | Restricted fallback plan |

Output: **ordered actions + blocked actions + rationale**.

### Speaker notes

`PhaseOneFeatures` includes WNS, frequency ratio, failing-endpoint count, path spread, size, utilization, and remaining time. `decide_recipe_path()` returns a structured `RecipePlan`.

The rules combine features. This table summarizes strategy families, not one-feature dispatch rules. Path spread alone does not automatically justify re-placement.

Exclusions matter. A small endpoint scope may be ineffective against an enormous failing population. A promising global operation may still cost more time than remains. The public router uses physical features as selection keys, while its thresholds reflect the authors' prior experiments.

### Visual

Place the table beside a schematic plan with two recommended actions and one blocked operation.

Code: `recipe_router.py`.

---

## Slide 3 — The recipe layer exposes targeted transformations

### Slide text

| Implementation | What it adds |
|---|---|
| Granular phys-opt sweep | Per-flag measurement and rollback after regressions |
| Endpoint-scoped phys-opt | Focused optimization of a bounded path group |
| High-fanout replication | Explicit targeting of critical nets and drivers |
| Cell relocation | Moves targeting excessive routing detours |
| LUT-cone optimization and retiming | Changes to logic or register structure |

### Speaker notes

Macros package tool operations and measurements into reusable procedures. The model does not have to reconstruct every sequence.

The granular sweep can stop after its first useful subpass and checks remaining time before another layer. Scoped optimization concentrates work on selected endpoints. Replication targets measured critical nets rather than duplicating drivers indiscriminately.

The LUT-cone macro extracts critical-path pins, applies RapidWright transformations, then reopens the checkpoint in Vivado for routing and measurement. Retiming also requires rerouting and fresh timing.

Logical transformations need stronger correctness evidence. The public macros do not themselves establish exhaustive formal sequential equivalence.

### Visual

Use the table as the main content. A small global-versus-selected-path sketch can illustrate the scope difference.

Code: `recipe_passes.py`.

---

## Slide 4 — Diversification changes both scope and starting point

### Slide text

**From the retained state**

- Partial replacement of critical-path fabric cells.
- Full replacement with alternative directives.
- Routing-only and incremental routing variants.

**From the original checkpoint**

- Independent replacement candidates.
- Additional restart attempts when budget permits.

Rejected attempts restore the retained best result.

### Speaker notes

`ils_polish.py` implements iterated local search: perturb, rebuild, measure, and accept or restore. Its directive rotation explores different physical choices.

Partial replacement defaults to 200 critical paths, not 200 cells. It selects associated fabric primitives and unplaces them before rebuilding. The implementation skips this move when spread is unavailable or below 30 tiles.

`deep_replace_sibling.py` explores alternatives from the original input. The restart wrapper adds exploration across attempts. These mechanisms avoid forcing every experiment to inherit the current solution's placement choices. Rejected candidates still consume runtime, but they need not erase an earlier gain.

### Visual

Draw branches from “original input” and “current retained state,” labeled by replacement and routing variants. Highlight the selected checkpoint without inventing performance values.

Code: `ils_polish.py`, `deep_replace_sibling.py`, `scripts/multi_restart_optimize.py`.

---

## Slide 5 — The LLM targets operands; memory supplies experience

### Slide text

| Component | Implemented role |
|---|---|
| LLM tool loop | Interpret reports and select recipes, parameters, cells, or nets |
| Persistent memory | Retrieve similar runs using LUT count and path spread |
| Negative memory | Surface regressions and wasted-budget episodes as advice |
| Tail controller | Rank moves by gain per second and reconsider them after state changes |

### Speaker notes

The model receives the router's brief, prior outcomes, and recent tool results. Its useful freedom includes selecting exact operands within a design.

Persistent memory uses a normalized distance over LUT count and path spread. It retrieves sequences and hints. Negative-memory warnings are advisory, rather than hard tool gates. This is retrieval of recorded experience, not model-weight training.

Within a run, the tail controller retires unproductive moves. An accepted transformation re-enables other moves because their earlier results may no longer describe the changed state.

Attribution remains imperfect: associating a gain with the most recent transformation cannot isolate that transformation's contribution within a chain. Our outcome records should retain complete recipe context.

### Visual

Show persistent memory feeding the model's brief and current-run measurements feeding the tail controller. Keep the two feedback paths distinct.

Code: `tool_dispatch.py`, `llm_runtime.py`, `strategy_memory.py`, `tail_controller.py`.

---

## Slide 6 — The controller prices exploration and preserves results

### Slide text

| Controller | Decision |
|---|---|
| Wall economics | Does recent progress justify more runtime? |
| Route and restart gates | Can the proposed operation fit the budget? |
| Logic-floor heuristic | Is little recoverable headroom likely to remain? |
| Candidate finalization | Which checked candidate should become the output? |

Artifact selection and the decision to keep searching are separate.

### Speaker notes

The economic controller compares observed progress with the penalty of further runtime. Insufficient history leaves exploration eligible. Budget gates separately assess whether an expensive operation can finish.

The logic-floor mechanism uses path composition, calibrated delay assumptions, and repeated timing measurements. It is a stopping heuristic, not a universal physical bound.

Speculative candidates can register for final comparison without immediately replacing the retained result. Finalization rechecks the selected candidate, and the wrapper preserves winners across attempts.

Two public implementation limitations matter when borrowing this design: missing constraint fingerprints allow continuation with an `UNVERIFIED` result, and the atomic-copy helper has a direct-copy fallback. Our publication path can enforce stricter behavior.

### Visual

Show separate decisions before and after an experiment: “Run another operation?” and “Publish this candidate?”

Code: `wall_economics.py`, `route_gate.py`, `logic_floor.py`, `finalization.py`, `finalize_mux.py`.

---

## Slide 7 — Five mechanisms informed our implemented upgrades

### Slide text

| Our implementation | Intended improvement |
|---|---|
| Common-cost ranking and admitted-result reporting | Align reported best with the delivered checkpoint |
| Granular, scoped, replication, and partial-placement recipes | Broaden the physical moves available |
| Opt-in retiming with an external equivalence gate | Control register-structure experiments |
| Persistent outcomes and refreshed evidence | Use current state and prior results for decisions |
| Score-aware stopping | Evaluate the value of further work |

**Implemented in source. Performance gains remain unmeasured.**

### Speaker notes

These are mechanisms adapted to our controller, rather than a reproduction of the entire RouteAgents portfolio. Our retiming path requires an external sequential-equivalence checker, and no checker is bundled. LUT-cone optimization is not part of the five completed upgrades.

The ranking correction addresses a specific accounting issue: compare earlier and later candidates at the same incurred run cost. Future cost belongs in the decision to launch another operation.

### Visual

Use the table with the implementation-status statement clearly visible below it.

Our code: `src/controller.py`, `src/recipes.py`, `src/equivalence.py`, `src/outcome_memory.py`, `src/economics.py`.

Source: [our upgrade guide](adaptive-optimizer-upgrades.md).

---

## Slide 8 — Evaluation should isolate which mechanisms earn their cost

### Slide text

- Verify the deployed revision and effective configuration first.
- Evaluate controller fixes, added recipes, memory, and stopping policy separately.
- Start with the four zero-gain designs and established regression anchors.
- Track delivered frequency, validation, runtime, cost, and failed attempts.

The supplied 09-17 logs still show the older search behavior.

### Speaker notes

The supplied logs include one-step patience and early stopping after a positive projected score. They do not demonstrate the new controller running, so we cannot attribute their results to the upgrades.

CoreScore, FINN RadioML, Rosetta 3D rendering, and VTR MCML are the immediate zero-gain targets. VexRiscv and LogicNets provide regression anchors.

Use matched input hashes, tool versions, machines, and budgets. Preserve output identity and the deployed revision. Repeat runs where implementation variance could explain a result.

The purpose is to identify mechanisms that deliver repeatable gains worth their runtime. RouteAgents supplies useful candidates and a search architecture. Its fitted thresholds still need evaluation in our environment.

### Visual

Show proposed comparisons for the corrected controller, added recipes, memory, and economic stopping. Label this as an evaluation plan, not completed results.

Source: [09-17 log analysis](../../results/Analysis%20-%2009_17.md).

---

## Backup notes for questions

**Why keep an original-input branch?** Later experiments can inherit poor choices. An independent branch tests another trajectory while preserving the current winner.

**Why refresh evidence?** Placement, replication, and routing can change critical paths. Original measurements may describe a bottleneck that no longer limits the current design.

**Why distinguish physical checks from equivalence?** Physical checks establish implementation properties. Structural checks and simulation have limited functional coverage. Retiming needs an appropriate sequential-equivalence procedure.

**What are the evidence limits?** The public branch differs from the scored submission and omits its measured seed-memory file. The review does not establish component-level causal gains or reproduce contest performance.

## References

- [Detailed implementation guide and source links](routeagents-implementation-guide.md)
- [RouteAgents at the reviewed commit](https://github.com/Geochatz3/routeagents-fpl26/tree/4a929b490dad048198e746d15c475a8c19dc5017)
- [Our implementation upgrades](adaptive-optimizer-upgrades.md)
- [Our supplied-log analysis](../../results/Analysis%20-%2009_17.md)

For a RouteAgents-only presentation, use slides 1–6. Slides 7–8 connect its mechanisms to our implementation and evaluation.
