# Overnight Goal: Score-Aware FPGA Optimizer Portfolio

## Read This First

1. Read the design: `docs/superpowers/specs/2026-07-13-score-aware-optimizer-portfolio-design.md`.
2. Read and execute the ordered checklist: `docs/superpowers/plans/2026-07-13-score-aware-optimizer-portfolio.md`.
3. Read the latest files in `docs/experiments/` before starting a new remote run. Do not repeat a rejected recipe/benchmark/profile combination without a new hypothesis.
4. Keep all code and docs on branch `feat/score-aware-optimizer-portfolio`; never commit from `main`.

## Copy/Paste Goal for an Overnight Agent

> Implement and evaluate the score-aware FPGA optimizer portfolio described in `docs/superpowers/specs/2026-07-13-score-aware-optimizer-portfolio-design.md` and `docs/superpowers/plans/2026-07-13-score-aware-optimizer-portfolio.md`.
>
> Work task-by-task, preserve the existing Vivado/RapidWright MCP recipes and generation-search controller, and add deterministic diagnosis, action gates, score-aware candidate ranking, and offline DSPy/GEPA prompt optimization. Do not replace the current optimizer with a prompt-only system.
>
> The goal is the best validated aggregate contest score on representative public benchmarks, not a benchmark-specific Fmax win. Always measure only `clk_fpl26contest`; include runtime and OpenRouter cost in projected score; retain the best legal incumbent checkpoint; and reserve time for validation.
>
> Use the official instance for real runs. Source `/tools/Xilinx/2025.1/Vivado/settings64.sh`; use `make setup`, `make run_optimizer`, and `make validate`; and keep credentials only in ignored `.env` files. Do not use `--test` as evidence that the full optimizer works. `make validate` is the supported validator entrypoint because it configures Java for RapidWright.
>
> Start from `feat/score-aware-optimizer-portfolio`. Make small conventional commits after each verified task, push them to GitHub, and record every experiment under `docs/experiments/`. At the end, update this file with the morning handoff table and leave the best validated DCP and reproducible commands available on the instance and/or downloaded safely outside Git.

## Required Existing Components

- Use `DCPOptimizer`, `DCPOptimizerBase`, `GenerationSearchConfig`, `SearchCandidate`, and checkpoint restore/promotion logic; do not bypass them.
- Reuse the existing `PBLOCK`, `FANOUT`, `CELL_RELOCATION`, `PHYS_OPT`, and `HARD_BLOCK` flows. Add gates and better ranking before adding new transforms.
- Keep the strict planner JSON contract in `src/prompting.py`. The LLM may rank eligible actions only.
- Use `prompt_optimizer.py evaluate`, `gepa-lite`, and optional `dspy-gepa` offline before a candidate prompt is promoted to real runs.
- Keep route status, target-clock timing, hold/pulse-width, structural equivalence, and simulation checks proportional to edit risk.

## Remote Run Pattern

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
make setup VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
make run_optimizer DCP=<benchmark.dcp> RUN_CWD=<artifact-directory> OPT_ARGS="<fixed profile and search controls>"
make validate GOLDEN=<benchmark.dcp> REVISED=<output.dcp> VECTORS=1000 VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

Use the same model, prompt hash, budget profile, branch factor, beam width, generations, and runtime/cost caps for an A/B comparison. Store the command in the corresponding experiment record.

## Measurement and Promotion

| Metric | Required rule |
| --- | --- |
| Fmax | Derive from target-clock WNS and period only. |
| Score | `delta_fmax_mhz * (1 - 0.1 * llm_cost_usd - 0.1 * runtime_hours)`, floored at zero. |
| Incumbent | Replace only if projected score improves and the required legality checks pass. |
| Route | `report_route_status` must report zero errors. |
| Timing | Hold and pulse width must remain valid. |
| Logic edits | Structural validation before promotion; full simulation for final or higher-risk candidates. |
| Stop | Stop speculative work with less than 10-12 minutes remaining or after two medium-risk non-improving branches. |

## Morning Handoff Template

| Field | Value |
| --- | --- |
| Branch / implementation commit | `feat/score-aware-optimizer-portfolio` / `af65de5` (`feat: add offline planner prompt optimization`) |
| Remote instance / remaining budget | `100.31.235.29`, instance `i-0058deec95f879b31`, running with 27.77 h remaining at 2026-07-13 04:56 America/Lima |
| Best aggregate scorecard | 111.216 projected across validated Vex and LogicNets incumbents; neutral Rosetta trials contribute zero |
| Best per-benchmark results | Vex: WNS -1.654 -> -0.886, +96.992 MHz, score 96.626. LogicNets: WNS -0.978 -> -0.891, +14.684 MHz, score 14.590. |
| Validation status | Both: structural 4/4, 1,000 vectors with 0 mismatches, all routable nets routed, 0 route errors, 0 error DRCs, positive hold slack, no pulse-width violators |
| DSPy/GEPA candidate prompt and hash | DSPy `6aecee74188e7a78`, offline 1.000, rejected after LogicNets score 12.162 < 14.590. GEPA-lite `a64f4db8cd511483`, offline 0.907, rejected after a Vex timing tie with higher cost and neutral LogicNets. Corpus hash `62211c207941ac8b`. |
| Rejected hypotheses and evidence | LogicNets PBLOCK reached -2.164 before rollback; Vex BRAM HARD_BLOCK found no gain; Vex critical-pin +9.622 and relocation +50.707 were below RuntimeOptimized; Vex route preserve and Rosetta FANOUT/hard-block trials were neutral; generated prompts failed the real promotion gate. |
| Exact next command | Run the final production policy on `rosetta_3d-rendering_2025.1.dcp` using the command below, then validate any positive-score incumbent. |
| Recommended next plan task | Add a bounded multi-seed FANOUT/routing portfolio and evaluate it across the remaining public DCPs; LogicNets showed the same three-net action varying from WNS -0.891 to -0.905. |

## Completed Implementation

Tasks 1-10 in the linked plan are complete. The final implementation preserves
the existing recipes and branching system while adding target-clock signatures,
deterministic recipe gates, projected-score ranking, a low-to-high-risk phys-opt
portfolio, bounded local/route recipes, offline prompt optimization, and final
legality checks. See
`docs/experiments/2026-07-13-task10-prompt-optimization.md` for the final A/B and
validation evidence.

The production prompt hash is `ee3acce412f63417`. It intentionally remains
shorter than the DSPy candidate because the candidate regressed the measured
LogicNets result despite its perfect offline score.

## Exact Next Command

```bash
cd /home/ubuntu/fpl26_full
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a; source .env; set +a
make run_optimizer \
  DCP="$PWD/fpl26_contest_benchmarks/rosetta_3d-rendering_2025.1.dcp" \
  RUN_CWD="$PWD/experiments/next-rosetta-3d-production" \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
  OPT_ARGS="--system-prompt $PWD/SYSTEM_PROMPT.TXT --budget-profile fast --branches 1 --beam-width 1 --generations 2 --steps-per-branch 1 --max-runtime-minutes 30 --max-cost 0.10"
```

Do not use `--test`. If the run produces positive projected score, run
`make validate` with 1,000 vectors and `scripts/check_dcp_legality.tcl` before
recording it as validated.

## Java Recovery Reminder

`make validate` first resolves the JRE bundled with Vivado; that path worked on
this instance. If RapidWright later reports that Java or `libjvm.so` is missing
and neither bundled Java nor `JAVA_HOME` works, use:

```bash
sudo apt update
sudo apt install default-jre
java -version
make validate GOLDEN=golden.dcp REVISED=revised.dcp VECTORS=1000
```

The fallback is documented in `docs/strategy/validation-environment.md` and
`docs/strategy/prompt-optimization.md` so the same issue is not rediscovered.

## Git Discipline

Use only conventional commits, for example `fix: configure Java runtime for direct validation`, `feat: gate recipes by design signature`, `feat: rank search candidates by projected score`, and `docs: record remote benchmark experiment`. Stage only intended source, test, and Markdown files. Never stage `.env`, keys, DCPs, tarballs, output directories, remote logs, or instance artifacts.
