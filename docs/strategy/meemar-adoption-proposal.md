# Meemar: proposed transfers and justifications

Source review: 2026-09-22. Meemar revision: [`509a4c10ffa1586f5078fe63754e9fd3471db221`](https://github.com/randomuzbek/meemar-fpl26-optimizer/tree/509a4c10ffa1586f5078fe63754e9fd3471db221). Local comparison: `test/pact`, commit `ca2622038ceb52ee4eb47d87545648ea41bf9eba`, including the PACT integration. The downloaded optimizer's MD5 is `64475899a43e372f4dcf441a254eec9d`, matching the repository's reported scored artifact.

**Status: proposal only.** No optimizer implementation was changed and no tests or FPGA workloads were run for this review. Recommendations below are engineering judgments based on source inspection, not demonstrated improvements to our model.

## Main conclusion

The strongest new optimization idea is a **device-centered, whole-design pblock density search**. It differs substantially from our existing critical-cell pblock flow. The strongest operational ideas are **automatic deterministic fallback when credentials are missing**, **preserving the input before tool startup**, and **better attribution of tool timeouts and synchronization delays**.

Meemar reinforces several things we already do: deterministic opening actions, bounded recipes, checkpoint rollback, score-aware stopping, and retaining the best candidate. Those are shared foundations, not new transfers. Its evidence does not justify replacing our planner or switching to its default model.

## 1. What the implementation actually does

The shipped optimizer is one large Python file. Its general sequence is a baseline fallback, deterministic physical optimization and placement experiments, optional LLM exploration, and bounded polishing. Exact paths depend on size, measured gain, environment switches, and several benchmark fingerprints.

| Mechanism | Source behavior | Difference from ours |
|---|---|---|
| Density search | Derives central SLICE boxes from device geometry and occupied SLICE count; defaults to densities 0.50, 0.42, 0.58 | Our `PBLOCK` targets at most 160 critical-path cells and chooses a fabric region for that subset |
| Size-adaptive candidate count | Density list is limited to one at ≥120,000 cells, two at ≥40,000, otherwise all three | We have action/runtime gates, but no equivalent whole-design density portfolio |
| Placement rescue | Default box attempts precede `Explore` boxes; Explore is skipped once the entry floor improves, unless explicitly forced | A useful conditional ordering policy to evaluate within our existing economics |
| Free replacement | Reopens the original input and runs fresh placement, physical optimization, and routing; generic gate includes weak gain and moderate design size | We already have reimplementation and full-placement actions; the novelty is conditional scheduling and seed choice |
| Surgical replacement | Attempts to release cells associated with worst setup paths while fixing other primitives | Our PACT replacement selects path-terminal LUT/FD cells; broader path coverage is a possible extension |
| LLM resilience | Missing credentials select deterministic execution; unavailable-model errors can trigger a configured fallback | Our CLI supports explicit `--no-llm`, but missing credentials otherwise terminate before optimization |
| Best-output persistence | Saves improving routed candidates during the run | Our strict PACT mode keeps improvements internal until final functional validation |

Source: [shipped optimizer](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py), especially `_deterministic_pblock_shrink`, `_derive_pblock_range`, `_free_replace_rescue`, `_surgical_replace`, and `_resolve_api_key_or_deterministic`.

### Defaults that matter

- Whole-design pblock search is enabled, with a 600,000-cell cap and an 1,800-second loop budget. The time check occurs between candidates; this is not a hard per-candidate deadline. The cell probe uses hierarchical cells, so these thresholds are not directly comparable with our primitive-cell gates.
- The derived-box SLICEM skip is **off** by default (`DCP_PBLOCK_SLICEM_SKIP=0`). Its presence is not evidence that the shipped density policy accounts for scarce SLICEM capacity.
- Additional budget-filling placement search is **off** (`DCP_GAMMA_FILL=0`). Comments describe a local improvement that failed to transfer when the real LLM stage had already raised the incumbent.
- Fingerprinted fast paths and a literal box exist alongside the generic policy. They must be separated when assessing generalization.
- `_design_is_legal` allows saving after a failed or empty route probe and some incomplete parses. Its runtime gate is weaker than the README's broad safety language implies. Reported successful external validation is a separate fact.
- The fallback chain specifically recognizes unavailable-model errors. It is not a general recovery mechanism for authentication, rate-limit, or arbitrary API failures.

These observations come from the executable branches and defaults in the [source file](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py), rather than treating all documented features as active.

## 2. Transfers to prioritize

### Priority 1 — preserve an input artifact before tool startup

**Take:** the placement of `_preseed_output_dcp` before server initialization.

**Why:** our CLI starts servers before `optimize()`, and our initial output publication follows successful analysis and baseline admission. A startup failure or baseline-admission failure can therefore occur before any fallback is published. Meemar addresses this earlier failure window.

**Adaptation:** atomically copy and hash-check the original to a distinct output path before tool startup. Record it explicitly as `unchanged_input`, with validation status unknown until checked. Keep startup failure visible in the return status and manifest.

**Important distinction:** an input copy is not proof that the input is legal. This helps preserve an artifact when analysis fails; it does not repair the DRC problem previously discussed. Separately, investigate allowing a defective input to enter a repair search while retaining strict acceptance of new candidates. Do not achieve that by making candidate checks permissive.

Local targets: [CLI startup](../../dcp_optimizer.py), [initialization and publication](../../src/controller.py). Meemar reference: `_preseed_output_dcp` in the [optimizer](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py#L4689).

### Priority 1 — automatic no-key fallback

**Take:** automatically use the deterministic portfolio when no API key is available.

**Why:** deterministic work is already supported locally, so aborting solely because credentials are absent loses useful work unnecessarily. This is a small integration gap, not a new search algorithm.

**Adaptation:** resolve missing credentials to the existing no-LLM mode, issue a clear log entry, and make zero network calls. Preserve an explicit option to require an LLM for controlled experiments. Consider a separately configured model fallback list for unavailable-model errors, with accurate per-model cost accounting; do not silently change models on arbitrary failures.

Local targets: [credential handling](../../dcp_optimizer.py), [planner](../../src/llm_optimizer.py). Meemar references: `_resolve_api_key_or_deterministic`, `_model_fallback_chain`, `_is_model_unavailable_error` in the [optimizer](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py).

### Priority 1 — timeout-aware measurement

**Take:** analyze whether a long call includes unfinished work from a previous command before using its duration to rank recipes.

**Why:** erroneous timing attribution can teach our persistent memory that a cheap report is expensive or that an expensive transformation was cheap. Meemar's notes describe precisely that failure with the harness's pending-command synchronization.

**Current overlap:** our tool wrapper already rejects MCP/text errors and marks timed-out sessions unusable. Therefore, do not assume its silent-success bug is still present in ours. Our server nevertheless contains pending-command synchronization, and historical logs may come from older behavior.

**Adaptation:** record command ID, requested timeout, completion state, synchronization wait, execution time, and total observed time separately. Mark unresolved attribution as uncertain. Keep total recipe wall time in economic accounting, but exclude uncertain per-command estimates from clean runtime models. Add a timeline view for historical runs.

Do not directly copy Meemar's 299.5–301-second timeout detector or its under-30-second drainage heuristic as proof of completion. Those are log-analysis heuristics for a particular harness. Prefer explicit server events and configured timeouts.

Sources: [measurement notes](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/docs/measurement-notes.md), [timeline parser](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/tools/harness_timeline.py). Local targets: [tool wrapper](../../src/llm_optimizer.py), [Vivado server](../../VivadoMCP/vivado_mcp_server.py), [outcome memory](../../src/outcome_memory.py).

### Priority 2 — add a distinct whole-design density action

**Take:** derive several compact placement regions from device geometry and actual occupied sites, then compare their routed outcomes.

**Why:** our local pblock can improve a critical cluster while leaving the global placement arrangement intact. A whole-design density experiment can explore a different arrangement and shorter interconnect across the design. This is the clearest genuinely different physical search direction in Meemar.

**Adaptation:** introduce a separate action, such as `DENSITY_REIMPLEMENTATION`, instead of changing the meaning of `PBLOCK`. Start with the three source densities as experimental candidates, not universal optima. Each trial should reopen the same immutable parent, use fresh capacity measurements, and pass our existing admission and final validation.

Before implementation, require:

- Resource-aware feasibility for SLICEL/SLICEM, LUTRAM/SRL, BRAM, DSP, and applicable clock-region restrictions.
- Actual device resource boundaries rather than blindly assuming a uniform rectangular clock-region grid.
- Preservation of user floorplanning and fixed-placement constraints; remove only constraints owned by the experimental action. Meemar deletes all pblocks in this flow, which we should not copy indiscriminately.
- A predicted complete trial cost, including routing, measurement, and final-validation reserve. The source's 600,000-cell threshold is not a portable runtime guarantee.
- Deduplication by resolved region, directive, and seed hash: different densities may map to the same box.

Cache immutable device geometry by part/tool identity, but recompute occupied-site counts after checkpoint changes. This combines Meemar's useful caching with our seed-bound evidence.

Sources: `_deterministic_pblock_shrink` and `_derive_pblock_range` in the [optimizer](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py#L1452). Local comparison: [current pblock flow](../../src/llm_optimizer.py#L1306), [policy](../../src/policy.py), [admission controller](../../src/controller.py).

### Priority 2 — condition expensive rescue work on the incumbent

**Take:** use a cheaper/default attempt first, then try more expensive placement variants only when there is a supported reason to expect incremental benefit.

**Why:** the relevant gain is improvement over the current best candidate. A recipe that beats the original input can still be useless after another action has already produced a better design.

**Adaptation:** extend our existing forecasts with action order and seed context: gain already banked, physical evidence, previous directive outcomes, and runtime. Evaluate fresh-input replacement against both the original input and the current incumbent. Skip stages that a later original-input restart would discard only when repeatable evidence supports that ordering.

Our [economics](../../src/economics.py) already accounts for incumbent deficit and runtime plus dollar cost. Keep that formula; Meemar's `alpha × seconds / 32400` approximation is not an upgrade. Avoid copying benchmark fingerprints or fixed MHz thresholds as general rules.

### Priority 3 — broader critical-path replacement and ancestor polishing

**Take:** investigate releasing a bounded set of cells along critical paths, and polishing an earlier strong candidate when a later branch has changed the placement landscape.

**Why:** our PACT action currently covers terminal cells. Internal path cells may be responsible for placement problems. Also, a lower-ranked ancestor may respond better to a particular polish sequence than the current winner.

**Adaptation:** verify supported path-to-cell extraction in our Vivado version; keep exact operand evidence, count limits, macro exclusions, and original lock restoration. Use our existing beam and enabling pool to schedule ancestor trials rather than introducing another independent search loop. Require remaining-budget and expected-benefit checks.

Meemar's surgical code attempts path-cell collection through `get_cells -of_objects` timing paths and resets primitive location locks broadly afterward. Treat this as an idea to validate, not drop-in Tcl. Its final polish also revisits a pre-LLM snapshot when the LLM improved the incumbent. Sources: `_surgical_replace` and `_final_polish` in the [optimizer](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/submission/dcp_optimizer.py).

## 3. What to preserve or avoid

| Item | Recommendation | Reason |
|---|---|---|
| Strict candidate and functional validation | Preserve ours | Meemar permits some failed probes; its clean scorecard does not make that policy fail-closed |
| Persistent positive/negative outcome memory | Preserve ours | Meemar's fixed ladder and fingerprints do not replace adaptive cross-run evidence |
| Exact score-aware economics | Preserve ours | Already handles runtime, dollars, and the current incumbent |
| Benchmark fingerprints and literal coordinates | Do not transfer | They encode known instances; matching counts does not establish general applicability |
| SLICEM-aware gating | Develop as an extension and measure | The source recognizes the risk but ships its skip disabled |
| Budget-filling placement and remap roundtrip | Defer | Both are experimental/off by default; source comments report inconsistent benefit |
| Retiming polish | Keep our existing proof requirement | External reported simulation results do not replace our sequential-equivalence policy |
| Immediate publication of each improvement | Do not weaken final validation | Consider periodic fully validated banking only if hard-deadline losses justify its extra cost |
| Single-file packaging | Do not copy the architecture | Instead verify that our package contains all required modules and pinned dependencies |

## 4. Evidence and experiment plan

The repository's [results file](https://github.com/randomuzbek/meemar-fpl26-optimizer/blob/509a4c10ffa1586f5078fe63754e9fd3471db221/RESULTS.md) reports a 318.254 total score, seven clean benchmarks, and $0.3482 LLM spend. These are repository-reported organizer results, not independently reproduced here. Different benchmark revisions and input frequencies prevent a direct numerical comparison with our September runs. The scorecard also does not isolate how much each mechanism contributed.

For implementation, start with startup fallback, credential fallback, and trustworthy runtime telemetry. Then evaluate the new density action independently before combining it with rescue scheduling or broader critical-path replacement.

Use identical input hashes, tool/device versions, thread counts, runtime limits, and validation settings. Alternate A/B order or control cache state. Measure the configuration intended for deployment, including the LLM stage and final validator. Record delivered Fmax and score, legal/validated completion, fallback reason, time to first validated improvement, total action cost, and incremental gain over the incumbent. Repeat comparisons where placement or model variance could determine the winner.

This plan tests whether Meemar's physical search directions improve our existing optimizer without confusing a better intermediate timing report with a better delivered result.
