# Experiment: Task 6 phys-opt portfolio A/B

## Provenance

- UTC window: 2026-07-13 08:01-08:10
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `e4bda43`; Task 6 working tree was deployed on top
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Prompt SHA256-16: `613a5713481610e5`
- Model: `~openai/gpt-latest`
- Profile: `fast`, branch/beam 1, 2 generations, 1 step/branch
- Limits per benchmark: 20 minutes and $0.10

## Reproduction

Both benchmarks used:

```bash
make run_optimizer \
  DCP=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/<benchmark>.dcp \
  RUN_CWD=/home/ubuntu/fpl26_full/experiments/task6-phys-opt-portfolio/<benchmark> \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
  OPT_ARGS="--budget-profile fast --max-runtime-minutes 20 --max-cost 0.10"
```

## A/B summary

| Run | Retained action | Follow-up | Delta Fmax | Runtime | Cost | Projected score |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Task 5 Vex single-directive baseline | `CELL_RELOCATE` | neutral `AggressiveExplore` | +50.706851 MHz | 172.355 s | $0.0366725 | 50.278130 |
| Task 6 Vex portfolio | `CELL_RELOCATE` | neutral `PlacementRouting` | +50.706851 MHz | 167.275 s | $0.0387825 | 50.274587 |
| Task 6 LogicNets portfolio | root | rejected `PBLOCK` | 0 MHz | 245.544 s | $0.019935 | 0 |

The Task 6 Vex score is 0.003543 below Task 5 because its second LLM response
cost slightly more despite saving about five seconds. This is not a score win.
It does prove the new follow-up is isolated and rolled back rather than folded
into a multi-pass mutation. Task 7 should stop after the strong first gain when
the next attempt has insufficient expected score upside.

## Candidate details

Vex:

| Candidate | WNS | Elapsed | Cost | Frozen projected score |
| --- | ---: | ---: | ---: | ---: |
| root | -1.654 ns | 21.514 s | $0 | 0 |
| `CELL_RELOCATE` | -1.201 ns | 92.558 s | $0.01965875 | 50.476798 |
| `PlacementRouting` | -1.201 ns | 167.273 s | $0.0387825 | 50.274589 |

LogicNets:

- Root WNS/Fmax: -0.978 ns / 403.551251 MHz.
- PBLOCK candidate WNS: -2.164 ns; the executor restored the root.
- Strong path spread made PBLOCK eligible, but the chosen region/flow was not
  beneficial. Task 9 must treat this rejected run as evidence for stronger
  specialist gates, not as a reason to retain a regressed checkpoint.

## Validation

The Task 6 Vex output passed structural checks 4/4 and 1,000 simulation vectors
with zero mismatches in 64.9 seconds. Route/DRC/hold/pulse fields remain unknown,
so validated contest score is not claimed.

## Artifacts

- Vex run: `/home/ubuntu/fpl26_full/experiments/task6-phys-opt-portfolio/vex/dcp_optimizer_run-20260713_080115`
- Vex output: `/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1_optimized-20260713_080115.dcp`
- Vex validation: `/home/ubuntu/fpl26_full/dcp_validation_midl_sch/validation_report.json`
- LogicNets run: `/home/ubuntu/fpl26_full/experiments/task6-phys-opt-portfolio/logicnets/dcp_optimizer_run-20260713_080404`
