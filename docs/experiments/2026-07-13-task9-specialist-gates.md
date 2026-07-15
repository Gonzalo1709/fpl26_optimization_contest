# Experiment: Task 9 specialist recipe gates

## Provenance

- UTC window: 2026-07-13 09:04-09:08
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `e615389`; Task 9 working tree was deployed on top
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Search: one branch, one generation, one step
- Limit: 20 minutes and $0.05 per run
- Execution: full `make run_optimizer`; no `--test` mode
- Model calls: zero; specialist recipes were forced only after deterministic admission

## Focused hard-block searches

| Benchmark | Admitted type | Root WNS | Result | Runtime | Retained |
| --- | --- | ---: | --- | ---: | --- |
| Rosetta digit recognition | URAM | -1.025 ns | no improving legal local move | 124.502 s | root |
| VexRiscv | BRAM | -1.654 ns | no improving legal local move | 98.455 s | root |

Each run called `hard_block_column_cascade_relocation` exactly once with only
the hard-block type observed on sampled `clk_fpl26contest` paths. RapidWright
returned `no_improvement`, so the executor reopened `hard_block_baseline.dcp`;
neither run wrote a specialist placement into the incumbent.

Artifacts:

- Rosetta: `/home/ubuntu/fpl26_full/experiments/task9-specialist-gates/rosetta-hard-block/dcp_optimizer_run-20260713_090415`
- Vex: `/home/ubuntu/fpl26_full/experiments/task9-specialist-gates/vex-hard-block/dcp_optimizer_run-20260713_090622`

## PBLOCK gate correction

The earlier LogicNets run admitted PBLOCK from max/average spread 198/111.86
tiles and regressed WNS from -0.978 to -2.164 ns before rollback. The new policy
requires average spread at least 120 and maximum at least 150, unless severe
congestion corroborates average spread at least 70 and maximum at least 120.
LogicNets without congestion evidence is now skipped; Rosetta's 283/131.38 and
CoreScore-class spread remain eligible when budget permits.

## Disabled specialists

LUT cone merge, register retiming, and an independent global congestion-spread
action are absent from the allow-list in all policy tests. This is deliberate:
there is not yet a bounded proof/equivalence gate strong enough to make them a
general hidden-benchmark default.

## Conclusion

The focused runs found no hard-block score gain, but they confirmed type
narrowing, legal-local no-op behavior, and checkpoint restoration. Tightening
PBLOCK and retaining the other high-risk transformations as disabled saves
runtime for the proven `RuntimeOptimized`, bounded relocation, and optional
critical-pin portfolio.
