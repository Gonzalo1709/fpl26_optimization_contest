# Experiment: Task 8 critical-pin and preserved-reroute actions

## Provenance

- UTC window: 2026-07-13 08:46-08:53
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `bb25a0b`; Task 8 working tree was deployed on top
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Search: one branch, one generation, one step
- Limit: 20 minutes and $0.05 per run
- Execution: full `make run_optimizer`; no `--test` mode
- Model calls: zero because the actions were forced for controlled A/B runs

An initial 12-minute control matrix is intentionally excluded from the Task 8
action comparison. Startup analysis consumed part of the validation reserve, so
the deterministic gate rejected both forced actions and correctly fell back to
`PHYS_OPT RuntimeOptimized`. That control unexpectedly produced a useful Vex
result (+96.992427 MHz projected Fmax), but it is existing-recipe evidence, not
critical-pin or preserved-reroute evidence.

## Corrected critical-pin matrix

The corrected 20-minute matrix admitted `CRITICAL_PIN {}` and the tool logs
show exactly one `vivado_phys_opt_design` call with
`{"critical_pin_opt": true}`.

| Benchmark | Root WNS | Best WNS | Delta Fmax | Runtime | Projected score | Retained |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| VexRiscv | -1.654 ns | -1.557 ns | +9.621634 MHz | 77.971 s | 9.600795 | yes |
| LogicNets | -0.978 ns | -0.957 ns | +3.449156 MHz | 107.711 s | 3.438836 | yes |
| Rosetta digit recognition | -1.025 ns | -1.025 ns | 0 MHz | 128.291 s | 0 | no, root retained |

Critical-pin is therefore a legitimate low-cost optional branch on Vex and
LogicNets, but it should not replace `RuntimeOptimized`: the 12-minute control's
existing default was substantially stronger on Vex.

Artifacts:

- Vex: `/home/ubuntu/fpl26_full/experiments/task8-critical-route-v2/vex-critical-pin/dcp_optimizer_run-20260713_084648`
- LogicNets: `/home/ubuntu/fpl26_full/experiments/task8-critical-route-v2/logic-critical-pin/dcp_optimizer_run-20260713_084808`
- Rosetta: `/home/ubuntu/fpl26_full/experiments/task8-critical-route-v2/rosetta-critical-pin/dcp_optimizer_run-20260713_084958`
- Existing `RuntimeOptimized` control: `/home/ubuntu/fpl26_full/experiments/task8-critical-route/vex-critical-pin/dcp_optimizer_run-20260713_083846`

## Vex preserved-reroute ablation

The corrected run admitted `ROUTE_PRESERVE` and exercised the complete bounded
flow:

- one `extract_critical_route_nets` call;
- four unlocked target-clock nets selected at the 0.20 ns threshold;
- one selected-net `route_design -auto_delay` call;
- one `route_design -preserve` call.

WNS remained -1.654 ns, so the executor reopened
`route_preserve_baseline.dcp`, retained `root`, and reported zero score after
83.463 seconds. This proves the safe interface and rollback behavior but is not
a score win.

- Run: `/home/ubuntu/fpl26_full/experiments/task8-critical-route-v2/vex-route-preserve/dcp_optimizer_run-20260713_085208`

## Validation

All three promoted candidates passed the official two-phase validator:

| Candidate | Structural | Simulation | Runtime | Report |
| --- | --- | --- | ---: | --- |
| Vex critical-pin | 4/4 | 1,000 vectors, 0 mismatch | 64.855 s | `/home/ubuntu/fpl26_full/dcp_validation_16e9e0xn/validation_report.json` |
| LogicNets critical-pin | 4/4 | 1,000 vectors, 0 mismatch | 126.959 s | `/home/ubuntu/fpl26_full/dcp_validation__apay77p/validation_report.json` |
| Vex `RuntimeOptimized` control | 4/4 | 1,000 vectors, 0 mismatch | 65.446 s | `/home/ubuntu/fpl26_full/dcp_validation_bkyhxdn3/validation_report.json` |

Route/DRC, hold, and pulse-width remain separate mandatory promotion checks;
unknown values are not treated as passes.
