# Experiment: VexRiscv Task 4 gated policy

## Provenance

- UTC timestamp: 2026-07-13 07:36:04
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `f26bbac`; Task 4 working tree was deployed on top
- Benchmark: `vexriscv_re-place_2025.1.dcp`
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Prompt SHA256-16: `613a5713481610e5`
- Model: `~openai/gpt-latest`
- Budget profile: `fast`
- Search: branch factor 1, beam width 1, 2 generations, 1 step/branch
- Limits: 20 minutes and $0.10
- Offline prompt evaluation: mean score 1.000 on 3 examples

## Reproduction

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
make run_optimizer \
  DCP=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  RUN_CWD=/home/ubuntu/fpl26_full/experiments/task4-gated-vex \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
  OPT_ARGS="--budget-profile fast --max-runtime-minutes 20 --max-cost 0.10"
```

Validation:

```bash
make validate \
  GOLDEN=fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  REVISED=fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_073604.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

## Task 2 versus Task 4

| Metric | Task 2 ungated PBLOCK | Task 4 gated CELL_RELOCATE | Task 4 retained output |
| --- | ---: | ---: | ---: |
| `clk_fpl26contest` WNS | -2.388 ns | -1.755 ns | -1.654 ns |
| Fmax | 252.653 MHz | 300.752 MHz | 310.173697 MHz |
| Runtime | 164.902 s | 93.332 s total run | 93.332 s total run |
| OpenRouter cost | $0.01339125 | $0.01829250 | $0.01829250 |
| Projected score | 0 | 0 | 0 |
| Structural validation | not promoted | not promoted | 4/4 passed |
| Simulation | not promoted | not promoted | 1,000 vectors, 0 mismatches |

Route, DRC, hold, and pulse-width fields remain unknown in `token_usage.json`;
structural and simulation success are not substitutes for those authoritative
checks.

## Decision

- Signature: no critical high-fanout nets, 50 paths, maximum/average spread
  93/53.5 tiles, BRAM incidence, and severe congestion.
- The gate omitted PBLOCK for this moderate-spread signature. The planner chose
  `CELL_RELOCATE` with 20 paths, detour threshold 1.5, and 5 cells.
- The candidate regressed WNS by 0.101 ns. Generation search rejected it,
  restored the root, and emitted the legal incumbent.
- The gate avoided the prior 0.734 ns PBLOCK regression and reduced total run
  time by about 71.6 seconds, but it did not produce positive score on Vex.
- Task 5 should rank branches by projected score while retaining this incumbent
  restoration behavior.

## Environment and deployment notes

- A partial source deployment initially failed because the updated optimizer
  imported the newer Task 3 analysis API. Deploy `src/*.py` as one coherent
  runtime unit when testing uncommitted milestones.
- With `RUN_CWD`, use an absolute DCP path; relative paths resolve from the run
  directory and fail before Vivado starts.
- Validation automatically used `JAVA_HOME`, `PATH`, or Vivado's bundled JRE.
  If none is available, follow `docs/strategy/validation-environment.md` and
  install `default-jre` as the documented Ubuntu fallback.

## Artifacts

- Run directory: `/home/ubuntu/fpl26_full/experiments/task4-gated-vex/dcp_optimizer_run-20260713_073604`
- Token report: `<run directory>/token_usage.json`
- Retained output: `/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_073604.dcp`
- Validation report: `/home/ubuntu/fpl26_full/dcp_validation_pja5_rhj/validation_report.json`
