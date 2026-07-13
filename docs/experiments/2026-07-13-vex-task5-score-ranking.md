# Experiment: VexRiscv Task 5 score-aware ranking

## Provenance

- UTC timestamp: 2026-07-13 07:47:32
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `c2cd8a2`; Task 5 working tree was deployed on top
- Benchmark: `vexriscv_re-place_2025.1.dcp`
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Prompt SHA256-16: `613a5713481610e5`
- Model: `~openai/gpt-latest`
- Budget profile: `fast`
- Search: branch factor 1, beam width 1, 2 generations, 1 step/branch
- Limits: 20 minutes and $0.10

## Reproduction

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
make run_optimizer \
  DCP=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  RUN_CWD=/home/ubuntu/fpl26_full/experiments/task5-score-ranked-vex \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
  OPT_ARGS="--budget-profile fast --max-runtime-minutes 20 --max-cost 0.10"
```

Validation:

```bash
make validate \
  GOLDEN=fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  REVISED=fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_074732.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

## Candidate scorecard

| Candidate | Action | WNS | Fmax | Elapsed | Cost | Frozen projected score | Promoted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `root` | no-op baseline | -1.654 ns | 310.173697 MHz | 21.112 s | $0 | 0 | initially |
| `g01...s01` | `CELL_RELOCATE`, 3 cells | -1.201 ns | 360.880549 MHz | 91.529 s | $0.0188325 | 50.482437 | yes |
| `g02...s01` | `PHYS_OPT AggressiveExplore` | -1.201 ns | 360.880549 MHz | 172.354 s | $0.0366725 | 50.278133 | no |

Final-run score inputs:

| Metric | Value |
| --- | ---: |
| Delta Fmax | +50.706851 MHz |
| Total runtime | 172.354995 s |
| OpenRouter cost | $0.0366725 |
| Penalty multiplier | 0.9915451113 |
| Projected contest score | 50.278130 |
| Structural validation | 4/4 passed |
| Simulation | 1,000 vectors, 0 mismatches |
| Validated contest score | unknown |

`validated_contest_score` remains unknown because route/DRC/hold/pulse-width
status is not yet populated by the optimizer. The external equivalence validator
passed, but that must not be represented as complete contest validation.

## Decision

- The gate omitted PBLOCK and FANOUT. The planner selected `CELL_RELOCATE` and
  moved three detour-heavy cells, including the known Vex outlier from
  `SLICE_X115Y2` to `SLICE_X111Y17`.
- The first candidate gained 0.453 ns WNS and 50.706851 MHz Fmax.
- The second `AggressiveExplore` branch produced identical timing while adding
  about 80.8 seconds and $0.01784, so score-aware promotion retained the first
  candidate.
- This is a positive result worth preserving for later portfolio A/B runs. Task
  8 must add authoritative route, DRC, hold, and pulse-width promotion fields.

## Artifacts

- Run directory: `/home/ubuntu/fpl26_full/experiments/task5-score-ranked-vex/dcp_optimizer_run-20260713_074732`
- Token report: `<run directory>/token_usage.json`
- Retained output: `/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_074732.dcp`
- Validation report: `/home/ubuntu/fpl26_full/dcp_validation_siah7av2/validation_report.json`
