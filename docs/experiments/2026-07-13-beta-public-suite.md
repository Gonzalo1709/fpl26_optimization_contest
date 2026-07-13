# Beta Public-Suite Production Screening

## Control

- Branch: `feat/score-aware-optimizer-portfolio`
- Initial screening commit: `990c019`
- RapidWright submodule commit: `35da0b4ea46ecccb6e09207573ca13531eb02d6c`
- Production prompt SHA256-16: `ee3acce412f63417`
- Model: `~openai/gpt-latest`
- Profile: `fast`
- Search: one branch, beam width one, two generations, one step per branch
- Limits: 30 minutes and $0.10 per benchmark
- Mode: full optimizer; `--test` is prohibited as evidence
- Local preflight: `.venv/Scripts/python.exe -m unittest discover -s tests -v` passed 53 tests on 2026-07-13

The suite control remains frozen until all nine rows have a real result. Policy
or prompt changes made later require a fixed A/B against affected signature
classes; they do not replace these control rows.

## Results

| Benchmark | Signature | Action | Initial WNS | Final WNS | Delta Fmax | Runtime | LLM cost | Projected score | Validation | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| amd_mini-isp | pending | pending | | | | | | | pending | pending |
| boom_soc | pending | pending | | | | | | | pending | pending |
| corescore_500_mod | pending | pending | | | | | | | pending | pending |
| finn_radioml | pending | pending | | | | | | | pending | pending |
| ispd16_example2 | pending | pending | | | | | | | pending | pending |
| rosetta_3d-rendering | pending | pending | | | | | | | pending | pending |
| rosetta_optical-flow | pending | pending | | | | | | | pending | pending |
| rosetta_spam-filter | pending | pending | | | | | | | pending | pending |
| vtr_mcml | pending | pending | | | | | | | pending | pending |

## Previously Characterized Controls

| Benchmark | Action | Initial WNS | Final WNS | Delta Fmax | Projected score | Validation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| vexriscv_re-place | `PHYS_OPT RuntimeOptimized` | -1.654 ns | -0.886 ns | +96.992 MHz | 96.626 | Passed all required gates |
| logicnets_jscl | `FANOUT top_n_nets=3` | -0.978 ns | -0.891 ns | +14.684 MHz | 14.590 | Passed all required gates |
| rosetta_digit-recognition | Specialist trials rolled back | recorded in Task 10 | unchanged root | 0 MHz | 0 | Neutral root retained |

Validated positive subtotal before this screening is **111.216**.

## Execution State

The official account reported 20.86 instance-hours remaining and instance
`i-0058deec95f879b31` running at `100.31.235.29`. Screening has not started:
the locally available contest SSH key was overwritten by the HTTP 409 response
from a rejected duplicate start request, and the separate personal SSH key is
not authorized on this instance. No restart or termination has been performed
because that would delete the existing remote artifacts. Resume by recovering
authorized SSH access or, with explicit approval to discard the current VM,
terminating and launching a fresh instance.

## Cross-Design Findings

Pending completion of the nine control rows. No policy change is justified from
this incomplete matrix.
