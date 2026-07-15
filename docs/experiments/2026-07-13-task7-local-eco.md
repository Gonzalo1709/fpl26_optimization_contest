# Experiment: Task 7 local ECO recipes

## Provenance

- UTC run window: 2026-07-13 08:18-08:24
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `b797e2a`; Task 7 working tree was deployed on top
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Budget profile: `fast`
- Search: branch factor 1, beam width 1, 2 generations, 1 step/branch
- Limits: 20 minutes and $0.10 per run
- Execution: full `make run_optimizer`; no `--test` mode

## VexRiscv bounded relocation

The normal planner chose `CELL_RELOCATE`, passed `max_move_distance=30` to
RapidWright, rerouted the candidate in Vivado, and then tried an independent
phys-opt branch. The phys-opt branch was neutral and did not replace the
relocation result.

| Metric | Root | Best relocation | Delta |
| --- | ---: | ---: | ---: |
| Target-clock WNS | -1.654 ns | -1.201 ns | +0.453 ns |
| Target-clock Fmax | 310.173697 MHz | 360.880549 MHz | +50.706851 MHz |
| Runtime | 0 s | 163.721 s | +163.721 s |
| OpenRouter cost | $0 | $0.0359475 | +$0.0359475 |
| Frozen projected score | 0 | 50.293967 | +50.293967 |

- Best candidate: `g01_pdc76e9f0_b01_s01`
- Token report: `/home/ubuntu/fpl26_full/experiments/task7-local-eco/vex/dcp_optimizer_run-20260713_081800/token_usage.json`
- Candidate DCP: `/home/ubuntu/fpl26_full/experiments/task7-local-eco/vex/dcp_optimizer_run-20260713_081800/generation_search/g01_pdc76e9f0_b01_step01.dcp`
- Structural validation: 4/4 checks passed.
- Functional validation: 1,000 vectors, 0 mismatches.
- Validation runtime: 44.7 seconds.
- Validation report: `/home/ubuntu/fpl26_full/dcp_validation_6ymudu87/validation_report.json`

## Rosetta digit-recognition fanout ablation

The forced deterministic `FANOUT` action exercised the new
`rapidwright_analyze_fanout_geography` tool, optimized five eligible nets,
wrote a candidate DCP, and rerouted it in Vivado. The target-clock result was
neutral, so score-first selection retained `root`.

| Metric | Root | Fanout branch | Promoted |
| --- | ---: | ---: | --- |
| Target-clock WNS | -1.025 ns | -1.025 ns | no |
| Target-clock Fmax | 366.972477 MHz | 366.972477 MHz | no |
| Runtime | 0 s | 224.195 s | no |
| OpenRouter cost | $0 | $0 | n/a (forced action) |
| Frozen projected score | 0 | 0 | no |

Tool evidence includes one geography analysis, one RapidWright fanout edit,
one RapidWright checkpoint write, and one Vivado reroute. Because the edited
branch was rejected and the emitted result remained the original root, it was
not represented as a validated optimization.

- Token report: `/home/ubuntu/fpl26_full/experiments/task7-local-eco/rosetta-fanout/dcp_optimizer_run-20260713_082045/token_usage.json`
- Rejected branch DCP: `/home/ubuntu/fpl26_full/experiments/task7-local-eco/rosetta-fanout/dcp_optimizer_run-20260713_082045/generation_search/g01_pdc76e9f0_b01_step01.dcp`

## Conclusion

Geography/path evidence now participates in fanout selection and was exercised
end to end, but it produced no Rosetta gain in this bounded trial. The local
radius preserved the repeatable Vex relocation improvement while adding a
pre-mutation safety check and immediate baseline rollback. Route/DRC, hold, and
pulse-width promotion fields remain unknown until the authoritative checks in
the next task are wired into candidate validation.
