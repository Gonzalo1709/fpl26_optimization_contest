# Score-Aware Optimizer Portfolio Design

## Objective

Improve expected contest score across unknown FPGA benchmarks without sacrificing output validity. The optimizer must use the contest clock, `clk_fpl26contest`, as its only Fmax target; always retain the best legal checkpoint; and treat runtime, OpenRouter cost, routing, hold, pulse-width, and equivalence as first-class constraints.

## Evidence Baseline

The official test instance ran the full OpenRouter path successfully on `vexriscv_re-place_2025.1.dcp`: Vivado 2025.1, RapidWright, MCP servers, OpenRouter, checkpoint output, structural comparison, and a 1,000-vector functional simulation all worked. The fast profile selected PBLOCK, regressed WNS from `-1.654 ns` to `-2.388 ns`, and correctly restored the root candidate. That produced a valid DCP but `0.0 MHz` improvement and a `0.0` contest score after 470.77 seconds and $0.01339125 LLM cost.

The design therefore prioritizes correct diagnosis and action eligibility over broad recipe expansion.

## Contest Constraints

- The score is `delta_fmax_mhz * (1 - 0.1 * llm_cost_usd - 0.1 * runtime_hours)`, floored at zero.
- The output must be fully routed with zero routing errors, meet hold and pulse-width checks, and remain functionally equivalent.
- A run has one hour and an effective $1 OpenRouter budget per benchmark.
- `make setup` must work on a clean Ubuntu 22.04 / Vivado 2025.1 instance within 90 minutes.
- Only OpenRouter is allowed for remote LLM access.
- Never commit `.env`, private keys, DCPs, benchmark archives, generated logs, or remote result bundles.

## Architecture

The current `DCPOptimizer` remains the orchestrator. New small modules supply a `DesignSignature`, score calculation, and deterministic admissibility policy before the existing generation search asks the planner for a recipe. The planner may choose only from eligible recipes; it cannot bypass the policy.

```text
Vivado/RapidWright analysis
  -> DesignSignature (clock paths, spread, fanout, congestion, hard blocks)
  -> policy gates + projected-score estimates
  -> eligible existing recipes
  -> deterministic fallback or OpenRouter planner
  -> GenerationSearchConfig branch/beam controller
  -> timing/route/hold checks and incumbent promotion
  -> final structural and conditional functional validation
```

## Existing Functionality to Preserve and Reuse

- `src/base.py`: MCP lifecycle, target-clock WNS/Fmax helpers, high-fanout parsing, reporting.
- `src/llm_optimizer.py`: checkpoint persistence, candidate restoration, linear and generational search, wall-clock/cost controls, tool telemetry, and flows for `PBLOCK`, `FANOUT`, `CELL_RELOCATION`, `PHYS_OPT`, and `HARD_BLOCK`.
- `src/search.py`: `GenerationSearchConfig` and `SearchCandidate`; preserve branch factor, beam width, generations, patience, cost limit, and runtime limit semantics.
- `src/prompting.py`, `SYSTEM_PROMPT.TXT`, and `prompt_optimizer.py`: strict JSON planner contract plus offline prompt evaluation and DSPy/GEPA optimization.
- `RapidWrightMCP/rapidwright_tools.py`: fanout, LUT cone, cell placement, detour, pblock, and hard-block capabilities.
- `VivadoMCP/vivado_mcp_server.py`: timing, congestion, route status, pblock, phys-opt, and Tcl access.
- `validate_dcps.py`: structural and functional equivalence checks. The supported execution entrypoint is `make validate`; it derives `JAVA_HOME` from Vivado. Direct Python invocation needs the same environment explicitly.

## Recipe Policy

| Recipe | Position | Minimum gate |
| --- | --- | --- |
| `PHYS_OPT` | First wave | Always eligible at low effort; escalate only after measured ROI. |
| Critical-pin optimization | First wave | Target-clock critical LUT paths; no locked-pin conflict. |
| `FANOUT` | First/second wave | Critical non-clock high-fanout net shared by failing paths. |
| `CELL_RELOCATION` | Second wave | A small set of timing-path cells has exceptional detour or geometric spread. |
| Critical-net reroute / congestion spreading | Second wave | A local congestion or net-delay signature overlaps target-clock paths. |
| `HARD_BLOCK` | Specialist | A failing path touches DSP, BRAM, or URAM and a legal local move exists. |
| LUT cone merging | Specialist | Exact, local, provable logic-shape match. |
| Retiming | Specialist | Large remaining validation budget and an explicit sequential-path signature. |
| `PBLOCK` | Late fallback | Multiple spread-out critical paths meet the existing strong PBLOCK recommendation; enough time remains for replace/route. |

## Search and Budget Policy

- Run cheap target-clock analysis first; reserve 5-8 minutes.
- Prefer deterministic selection when no action clears its gate or remaining cost/runtime is low.
- Permit OpenRouter only to rank already-eligible actions. It may never request arbitrary Tcl or an ungated strategy.
- Use the existing generation tree to explore non-destructive alternatives from one saved root; rank candidates by contest score first, then target-clock timing metrics.
- Reserve at least 10-12 minutes for route status, target-clock timing, structural validation, and required simulation.
- Stop launching speculative transforms when remaining time is below the reserve, the last two medium-risk branches did not improve, or the next action requires a broad reroute while a positive legal incumbent exists.

## Prompt Optimization Policy

DSPy/GEPA is an offline policy-improvement tool, not an online replacement for deterministic control. `prompt_optimizer.py evaluate`, `gepa-lite`, and optionally `dspy-gepa` use planner decision examples without launching Vivado. Promote a candidate prompt only when it improves offline score and then improves or matches measured public-suite results under a fixed run budget. Store prompt hash, model, examples, metrics, and real-run comparison in experiment records.

## Verification Matrix

| Change type | Per-candidate check | Promotion gate | Final check |
| --- | --- | --- | --- |
| Vivado-only phys-opt/reroute | Target-clock Fmax, route status, hold/pulse-width | Higher projected score | Route status + target timing |
| Placement or hard-block move | Above plus structural sanity | Higher projected score and legal routing | Structural validation; simulation if time permits |
| Manual netlist/LUT/retiming edit | Above plus structural sanity | Higher projected score and structural pass | Full functional simulation |
| Prompt/policy change | Unit and offline prompt evaluation | Public-suite score is non-regressing | At least one full remote smoke benchmark |

## Git and Documentation

All implementation happens on `feat/score-aware-optimizer-portfolio`. Make small conventional commits after each independently verified ticket. Maintain `docs/experiments/`, `docs/strategy/`, and `docs/handoffs/`; push validated milestones to GitHub for morning review.
