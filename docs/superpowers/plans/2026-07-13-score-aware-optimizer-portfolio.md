# Score-Aware Optimizer Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a benchmark-general controller that reuses the current FPGA recipes and generation search while selecting, branching, measuring, and validating them by expected contest score.

**Architecture:** Add isolated analysis, scoring, and policy modules in front of `DCPOptimizer`. Keep `src/llm_optimizer.py` as the executor and candidate-state owner, and feed it only eligible actions plus a score-aware candidate ranking. Use `prompt_optimizer.py` with DSPy/GEPA offline before promoting planner prompts.

**Tech Stack:** Python 3.10+, asyncio, MCP, Vivado 2025.1 Tcl, RapidWright, OpenRouter, DSPy/GEPA optional dependencies, `unittest`, Bash, GitHub.

## Global Constraints

- Work only on `feat/score-aware-optimizer-portfolio`; use conventional commits and push every validated milestone.
- Target only `clk_fpl26contest`; calculate `Fmax = 1000 / (period_ns - wns_ns)`.
- Preserve the existing flows, `GenerationSearchConfig`, branch/beam search, wall-clock limits, checkpoint restoration, and prompt contract.
- Use `make setup`, `make run_optimizer`, and `make validate` on the contest instance; source `/tools/Xilinx/2025.1/Vivado/settings64.sh` first.
- Never stage secrets, DCPs, archives, logs, or generated result directories.
- Each accepted candidate must improve projected contest score and pass the check level required by its edit type.

---

## Read Order and Operating Procedure

1. Read `docs/superpowers/specs/2026-07-13-score-aware-optimizer-portfolio-design.md` for policy and architecture.
2. Execute this plan in task order; check each box only after its listed verification command passes.
3. Before a remote run, read `docs/handoffs/overnight-score-aware-optimizer-goal.md` and copy its environment-safe command pattern.
4. Log every remote experiment in `docs/experiments/<timestamp>-<benchmark>.md` using the template in Task 2.
5. At the morning handoff, update the handoff file with the branch, commits, experiment table, best scorecard, failures, and next action.

### Task 1: Make validation runtime configuration explicit

**Files:**
- Modify: `validate_dcps.py:69-126`
- Modify: `Makefile:20-42,283-326`
- Create: `tests/test_validation_environment.py`
- Create: `docs/strategy/validation-environment.md`

**Produces:** a reusable Java/Vivado environment builder used by direct validation and documented `make validate` behavior.

- [x] Write a failing `unittest` that verifies the validator subprocess environment contains `JAVA_HOME`, `RAPIDWRIGHT_PATH`, and a classpath rooted at the local `RapidWright` directory.
- [x] Extract environment construction from `src/mcp.py` or add a narrowly scoped helper so `DCPValidator.start_servers()` uses the same environment as `DCPOptimizerBase.start_servers()`.
- [x] Run `python -m unittest tests.test_validation_environment -v` and confirm it passes.
- [x] On the contest instance, run `make validate GOLDEN=<same-dcp> REVISED=<same-dcp> VECTORS=1000 VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado`; confirm structural and simulation phases pass.
- [x] Commit: `fix: configure Java runtime for direct validation`.

### Task 2: Add reproducible experiment records and score calculation

**Files:**
- Create: `src/scoring.py`
- Create: `tests/test_scoring.py`
- Modify: `src/llm_optimizer.py:2174-2395`
- Create: `docs/experiments/README.md`
- Create: `docs/experiments/TEMPLATE.md`

**Produces:** `ContestScoreInput`, `ContestScore`, and a JSON/Markdown record containing Fmax delta, runtime, LLM cost, validation status, and projected score.

- [x] Write failing tests for zero delta, the official 50 MHz / $0.25 / 1,200-second example, negative score clamping, and target-clock Fmax conversion.
- [x] Implement pure functions in `src/scoring.py`; do not call Vivado or OpenRouter from this module.
- [x] Extend the existing `token_usage.json` summary with `projected_contest_score` and required validation status fields.
- [x] Add the experiment template with command, commit SHA, prompt hash, profile/search controls, timing, cost, route/hold/pulse, structural/simulation, accepted/rejected reason, and artifact paths.
- [x] Run `python -m unittest tests.test_scoring -v` and inspect a real run report.
- [x] Commit: `feat: record target-clock experiment scorecards`.

### Task 3: Create the target-clock design signature

**Files:**
- Create: `src/analysis.py`
- Create: `tests/test_analysis.py`
- Modify: `src/llm_optimizer.py:443-575`
- Modify: `src/parsers.py`

**Produces:** a serializable `DesignSignature` with target-clock timing, path spread, high-fanout candidates, congestion/hard-block flags, and analysis duration.

- [x] Write fixture-driven parser tests for target clock, fanout rows, spread recommendation, and missing reports.
- [x] Implement a bounded `collect_design_signature()` that reuses `get_clock_period`, `get_wns_for_target_clock`, `get_critical_high_fanout_nets`, `extract_critical_path_cells`, and RapidWright spread analysis.
- [x] Add optional, timeout-bounded congestion and QoR report collection through existing Vivado Tcl access; record an unavailable value rather than failing the run.
- [x] Include the signature in the existing `initial_analysis` summary and token report.
- [x] Run unit tests, then collect signatures on VexRiscv, LogicNets, one Rosetta benchmark, and one large benchmark; record analysis seconds.
- [x] Commit: `feat: collect target-clock design signatures`.

### Task 4: Add deterministic recipe admissibility gates

**Files:**
- Create: `src/policy.py`
- Create: `tests/test_policy.py`
- Modify: `src/llm_optimizer.py:576-806,1380-1419`
- Modify: `src/prompting.py`

**Produces:** `EligibleAction`, `gate_actions(signature, budget, history)`, and an explicit no-op fallback.

- [x] Write failing tests proving: PBLOCK is rejected for a one-path/local-detour signature; FANOUT is rejected without a critical non-clock high-fanout net; HARD_BLOCK is rejected without critical hard-block incidence; PHYS_OPT remains eligible on ambiguous inputs.
- [x] Implement gates for existing `PBLOCK`, `FANOUT`, `CELL_RELOCATION`, `PHYS_OPT`, and `HARD_BLOCK` actions without changing their executors.
- [x] Pass only eligible actions to `_build_decision_input()` and update the planner contract so it returns only one allowed action.
- [x] Make `_fallback_action_candidates()` choose a deterministic eligible action when LLM output is invalid, over budget, or unavailable.
- [x] Run `python -m unittest tests.test_policy -v` and offline prompt evaluation.
- [x] Commit: `feat: gate recipes by design signature`.

### Task 5: Rank generation-search candidates by score-aware metrics

**Files:**
- Modify: `src/search.py:9-44`
- Modify: `src/llm_optimizer.py:825-879,1488-1537,1803-2173`
- Create: `tests/test_search_ranking.py`

**Produces:** candidate metadata for elapsed time, LLM cost, validation state, projected score, and a score-first pruning key.

- [x] Write failing tests where a smaller Fmax improvement with a much lower runtime wins projected score, and where an unvalidated candidate cannot replace a validated incumbent.
- [x] Extend `SearchCandidate` with explicit score/validation fields while retaining WNS, TNS, endpoints, branch, and checkpoint fields.
- [x] Replace the current WNS-only branch ranking with projected-score-first ranking and target-clock metrics as deterministic tie breakers.
- [x] Keep root checkpoint restoration; no branch may overwrite output until it wins the promotion gate.
- [x] Run search-ranking tests and one full remote VexRiscv smoke run with `--budget-profile fast`.
- [x] Commit: `feat: rank search candidates by projected score`.

### Task 6: Turn existing phys-opt support into a measured portfolio

**Files:**
- Modify: `src/llm_optimizer.py:1173-1215`
- Modify: `src/policy.py`
- Create: `tests/test_phys_opt_portfolio.py`
- Create: `docs/strategy/phys-opt-portfolio.md`

**Produces:** a guarded sequence: `RuntimeOptimized`, targeted critical-pin/routing/placement options, `Explore`, and `AggressiveExplore` only when budget and prior results justify it.

- [x] Write tests for directive ordering, skip conditions, and rollback after negative target-clock delta.
- [x] Implement portfolio attempts as separate saved candidates so existing generation branching can compare them instead of mutating one state.
- [x] Gate escalation on remaining runtime, previous gain, and hold/pulse status.
- [x] Run a fixed-budget public-suite A/B against the current single-directive behavior and fill experiment records.
- [x] Commit: `feat: add score-aware phys-opt portfolio`.

### Task 7: Improve existing fanout and cell-relocation flows

**Files:**
- Modify: `src/llm_optimizer.py:1020-1172`
- Modify: `RapidWrightMCP/rapidwright_tools.py:740-846,2833-3015`
- Create: `tests/test_fanout_selection.py`
- Create: `docs/strategy/local-eco-recipes.md`

**Produces:** geography-aware fanout ranking and bounded, path-anchored cell relocation with required checkpoint rollback.

- [x] Write tests that prefer target-clock-critical, shared-endpoint non-clock fanout over merely large fanout, and reject relocation beyond the configured local radius.
- [x] Reuse the current RapidWright fanout and detour APIs; add only metadata needed for sink geography and path association.
- [x] Preserve the existing write/open/reroute/measure loop and reject a branch on timing/score or local-radius failure; Task 8 owns authoritative route/DRC/hold/pulse promotion fields.
- [x] Validate accepted manual netlist changes structurally; run simulation for final manual-edit candidates.
- [x] Commit: `feat: target local fanout and relocation recipes`.

### Task 8: Add low-cost critical-pin and route-preserve recipes

**Files:**
- Modify: `VivadoMCP/vivado_mcp_server.py`
- Modify: `src/llm_optimizer.py:1173-1363`
- Modify: `src/policy.py`
- Create: `tests/test_recipe_gates.py`

**Produces:** a first-wave critical-pin phys-opt action and a small-set critical-net reroute action, both measured through the existing Vivado MCP interface.

- [ ] Add tests that reject locked-pin candidates and reroute sets above a small configured limit.
- [ ] Expose only the required Vivado Tcl arguments for `phys_opt_design -critical_pin_opt` and `route_design -nets ... -auto_delay/-preserve`; do not add arbitrary Tcl access to the planner.
- [ ] Add action gates from target-clock path membership and net-delay/congestion evidence.
- [ ] Run remote A/B experiments on at least VexRiscv, LogicNets, and one Rosetta benchmark.
- [ ] Commit: `feat: add critical-pin and preserved-reroute actions`.

### Task 9: Gate specialist transforms instead of broadening defaults

**Files:**
- Modify: `src/llm_optimizer.py:922-1019,1216-1333`
- Modify: `RapidWrightMCP/rapidwright_tools.py`
- Modify: `SYSTEM_PROMPT.TXT`
- Create: `docs/strategy/specialist-recipe-gates.md`

**Produces:** late-stage gates for PBLOCK, hard-block relocation, LUT cone merging, retiming, and congestion-aware spreading.

- [ ] Document exact evidence thresholds and required validation for every specialist recipe.
- [ ] Keep PBLOCK eligible only for multiple strongly spread target-clock paths and sufficient remaining place/route budget.
- [ ] Keep hard-block relocation eligible only for DSP/BRAM/URAM-critical paths and a legal local candidate.
- [ ] Keep LUT merge and retiming disabled by default until a local proof/validation gate exists.
- [ ] Run focused benchmarks where each signature applies; record skipped cases as successful gate behavior.
- [ ] Commit: `feat: gate specialist optimization recipes`.

### Task 10: Optimize planner prompts with DSPy/GEPA and close the loop

**Files:**
- Modify: `prompt_optimizer.py`
- Modify: `prompt_eval_examples/planner_examples.jsonl`
- Modify: `requirements-prompt-opt.txt`
- Create: `docs/strategy/prompt-optimization.md`
- Create: `docs/handoffs/overnight-score-aware-optimizer-goal.md`

**Produces:** reproducible offline DSPy/GEPA evaluation, prompt provenance, and a morning-ready handoff.

- [ ] Add real decision examples from rejected PBLOCK and accepted/rejected recipe runs, without secrets or raw DCP contents.
- [ ] Run `python3 prompt_optimizer.py evaluate`, `gepa-lite`, and, after installing optional dependencies, `dspy-gepa`; capture prompt hash, examples hash, model, and offline score.
- [ ] Promote only candidate prompts that outperform the baseline offline and do not regress a fixed remote benchmark subset under identical budget/search controls.
- [ ] Update the handoff goal with committed SHA, branch, commands, scorecard table, failures, artifact locations, remaining instance budget, and next recommended ticket.
- [ ] Commit: `feat: add offline planner prompt optimization` and `docs: add optimizer portfolio handoff`.

## Plan Self-Review

- Existing optimizer recipes, generation branching, checkpoint restoration, budget controls, prompt contract, MCP servers, and validator are explicit dependencies in this plan.
- Every recipe has a target-clock metric, rollback rule, and validation level.
- The plan separates deterministic control, existing recipe improvement, specialist recipes, and offline DSPy/GEPA work so no one task requires an all-at-once rewrite.
- The plan intentionally avoids adding unrestricted planner Tcl execution or ungated global place-and-route branches.
