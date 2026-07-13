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
| Branch / latest commit | |
| Remote instance / remaining budget | |
| Best aggregate scorecard | |
| Best per-benchmark results | |
| Validation status | |
| DSPy/GEPA candidate prompt and hash | |
| Rejected hypotheses and evidence | |
| Exact next command | |
| Recommended next plan task | |

## Git Discipline

Use only conventional commits, for example `fix: configure Java runtime for direct validation`, `feat: gate recipes by design signature`, `feat: rank search candidates by projected score`, and `docs: record remote benchmark experiment`. Stage only intended source, test, and Markdown files. Never stage `.env`, keys, DCPs, tarballs, output directories, remote logs, or instance artifacts.
