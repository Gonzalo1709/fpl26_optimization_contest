# Experiment: VexRiscv Task 2 scorecard smoke

## Provenance

- UTC timestamp: 2026-07-13 07:05:52
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `f7d707a`; Task 2 working tree was deployed on top
- Benchmark: `vexriscv_re-place_2025.1.dcp`
- Input SHA256: `8baf6451f9b20b8a82f035d14187c7350529a6ea0330e02d93c7100b19753149`
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Prompt SHA256-16: `f8fdc8fb69556f6a`
- Model: `~openai/gpt-latest`
- Budget profile: `fast`
- Search: branch factor 1, beam width 1, 2 generations, 1 step/branch
- Limits: 20 minutes, $0.10; controller wall clock 3,600 seconds

## Reproduction

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
make run_optimizer \
  DCP=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  RUN_CWD=/home/ubuntu/fpl26_full/experiments/task2-vex-scorecard \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
  OPT_ARGS="--budget-profile fast --max-runtime-minutes 20 --max-cost 0.10"
```

Validation:

```bash
make validate \
  GOLDEN=fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  REVISED=fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_070552.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

## Scorecard

| Metric | Baseline/root | PBLOCK candidate | Retained output |
| --- | ---: | ---: | ---: |
| `clk_fpl26contest` period | 1.570 ns | 1.570 ns | 1.570 ns |
| `clk_fpl26contest` WNS | -1.654 ns | -2.388 ns | -1.654 ns |
| Fmax | 310.173697 MHz | 252.653 MHz | 310.173697 MHz |
| Runtime | n/a | n/a | 164.901906 s |
| OpenRouter cost | n/a | n/a | $0.01339125 |
| Score multiplier | n/a | n/a | 0.9940802665 |
| Projected score | n/a | negative delta | 0.0 |
| Structural validation | n/a | not promoted | 4/4 passed |
| Simulation | n/a | not promoted | 1,000 vectors, 0 mismatches |

Route, DRC, hold, and pulse-width fields remain unknown in `token_usage.json`;
the equivalence validator does not authoritatively produce those checks. They
must not be inferred from structural/simulation success.

## Decision

- OpenRouter selected `PBLOCK` with no arguments.
- Evidence before the action: 50 target-clock paths, maximum spread 93 tiles,
  average spread 53.5 tiles, and no critical high-fanout nets.
- The PBLOCK branch regressed WNS by 0.734 ns and was rejected.
- The generation controller correctly restored and emitted the root checkpoint.
- This repeated failure is direct evidence for Task 4: PBLOCK must be gated out
  for a moderate-spread/local-path signature instead of spending 114 seconds on
  place/route.

## Artifacts

- Run directory: `/home/ubuntu/fpl26_full/experiments/task2-vex-scorecard/dcp_optimizer_run-20260713_070552`
- Token report: `<run directory>/token_usage.json`
- Retained output: `/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_070552.dcp`
- Validation report: `/home/ubuntu/fpl26_full/dcp_validation_c12sk31u/validation_report.json`
