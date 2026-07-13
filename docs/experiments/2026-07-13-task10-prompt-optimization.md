# Task 10: Prompt Optimization and Final Portfolio Selection

## Scope

This experiment used the existing generation-search controller, deterministic
action gates, checkpoint rollback, and score ranking. `gepa-lite` and DSPy GEPA
were used only to generate planner candidates; all real comparisons were full
non-test Vivado/RapidWright runs on the official instance.

## Offline corpus

- Corpus: 7 sanitized planner decisions
- Examples hash: `62211c207941ac8b`
- Planner/evaluator: `~openai/gpt-latest`
- Planner temperature: `0`
- Optional optimizer: DSPy 3.2.1 / GEPA 0.0.27 on remote Python 3.10

| Prompt | Prompt hash | Offline mean | Decision |
| --- | --- | ---: | --- |
| Original Task 9 production prompt | `19e86a3230fcac60` | 0.871 | Control |
| GEPA-lite candidate | `a64f4db8cd511483` | 0.907 | Real A/B required |
| DSPy GEPA candidate | `6aecee74188e7a78` | 1.000 | Real A/B required |

The DSPy command completed with OpenRouter model
`openrouter/openai/gpt-5` for both the planner and reflection LM. The generated
prompt was then scored independently with `~openai/gpt-latest`; DSPy's internal
training score was not used as promotion evidence.

## Fixed real prompt comparisons

All rows used `fast`, one branch, beam width one, two generations, one step per
branch, 30-minute runtime cap, and $0.10 LLM cap.

| Benchmark / prompt | Best action | WNS (ns) | Delta Fmax (MHz) | Projected score | Cost (USD) | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Vex / Task 9 control | `PHYS_OPT RuntimeOptimized` | -0.886 | 96.992 | 96.620 | 0.01310 | Incumbent |
| Vex / GEPA-lite | `PHYS_OPT RuntimeOptimized` | -0.886 | 96.992 | 96.607 | 0.01451 | Timing tie, lower score |
| LogicNets / Task 9 control | PBLOCK trial, rollback | -0.978 | 0.000 | 0.000 | 0.01689 | Rejected |
| LogicNets / GEPA-lite | PBLOCK trial, rollback | -0.978 | 0.000 | 0.000 | 0.01727 | Rejected |
| Vex / pre-final production | HARD_BLOCK trial, rollback | -1.654 | 0.000 | 0.000 | 0.01398 | Exposed false-positive gate |
| Vex / DSPy | HARD_BLOCK trial, rollback | -1.654 | 0.000 | 0.000 | 0.01652 | No prompt advantage |
| LogicNets / production | `FANOUT top_n_nets=3` | -0.891 | 14.684 | 14.590 | 0.01744 | Incumbent |
| LogicNets / DSPy | `FANOUT top_n_nets=3` | -0.905 | 12.249 | 12.162 | 0.02208 | Timing and score regression |
| Vex / final tightened production | `PHYS_OPT RuntimeOptimized` | -0.886 | 96.992 | 96.626 | 0.01209 | Incumbent |

DSPy was not promoted despite its perfect offline score. It regressed the real
LogicNets result and added token cost. GEPA-lite tied Vex timing but also cost
more and did not improve LogicNets. The shorter production prompt remains the
general default.

The validated two-benchmark projected score is **111.216** (96.626 Vex plus
14.590 LogicNets). Rosetta specialist trials remained neutral and were rolled
back, so no unvalidated gain is included.

## Final validation

| Benchmark | Structure | Simulation | Routing / DRC | Hold | Pulse width |
| --- | --- | --- | --- | ---: | --- |
| LogicNets | 4/4 pass | 1,000 vectors, 0 mismatch | 27,963/27,963 routable nets; 0 route errors; 0 error DRCs | +0.077 ns | No violators |
| Vex | 4/4 pass | 1,000 vectors, 0 mismatch | 2,938/2,938 routable nets; 0 route errors; 0 error DRCs | +0.042 ns | No violators |

Validation reports:

- LogicNets: `/home/ubuntu/fpl26_full/dcp_validation_a9wmsu08/validation_report.json`
- Vex: `/home/ubuntu/fpl26_full/dcp_validation_mcypqtbz/validation_report.json`
- Vivado legality logs:
  `/home/ubuntu/fpl26_full/experiments/final-production-vex/logic-legality.log`
  and `final-legality.log`

## Gate corrections from real evidence

Two deterministic gates were narrowed after full rollback-protected runs:

- PBLOCK now requires average spread at least 120 tiles and maximum spread at
  least 150 over at least five sampled target-clock paths. Severe congestion no
  longer lowers the spread floor. This excludes the measured LogicNets
  111.86/198-tile shape, where PBLOCK produced WNS -2.164 before rollback.
- HARD_BLOCK now requires critical DSP/BRAM/URAM incidence and average path
  spread at least 80 tiles. Severe congestion alone no longer admits it. This
  excludes Vex's 53.5-tile average BRAM shape, where no legal improving move was
  found.

These corrections retain Rosetta's URAM/extreme-spread signature while keeping
Vex on the proven `RuntimeOptimized` path and LogicNets on geography-aware
FANOUT.

## Artifact locations

- GEPA prompt A/B: `/home/ubuntu/fpl26_full/experiments/task10-prompt-ab/`
- DSPy prompt A/B: `/home/ubuntu/fpl26_full/experiments/task10-dspy-ab/`
- Best LogicNets DCP:
  `/home/ubuntu/fpl26_full/experiments/task10-dspy-ab/base-logic/dcp_optimizer_run-20260713_093558/generation_search/g01_pdc76e9f0_b01_step01.dcp`
- Final production Vex run: `/home/ubuntu/fpl26_full/experiments/final-production-vex/`

Generated JSON reports and candidate prompts were summarized here and left out
of Git. DCPs, keys, `.env`, and remote logs must never be committed.
