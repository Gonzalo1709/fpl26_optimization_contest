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
| amd_mini-isp | spread 56.88/80 tiles; 4 critical fanout nets; BRAM; severe congestion | `FANOUT top_n_nets=4` regressed to -1.756; root restored | -1.686 ns | -1.686 ns | 0 MHz | 178.788 s | $0.0122025 | 0 | Not required for rolled-back candidate | Rejected FANOUT; legal root retained |
| boom_soc | spread 302.52/343 tiles; 6 critical fanout nets; severe congestion; no critical hard-block type | `PBLOCK` candidate retained | -19.162 ns | -16.952 ns | +5.755825 MHz | 1802.897 s | $0.0130725 | 5.460046 | Passed structural 4/4, 1,000 vectors/0 mismatches, and Vivado legality | Promoted validated PBLOCK incumbent |
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

Validated positive subtotal before this screening was **111.216**. BOOM raises
the current validated subtotal to **116.676046**.

## Execution State

The inaccessible instance was explicitly authorized for termination. Fresh
instance `i-00322722584e0ce88` was launched at `54.90.157.179` with 20.66
instance-hours remaining. Deployment used SCP as the expected transport: a Git
bundle containing only the feature branch and the ignored `.env` were copied
to the VM separately; generated token reports are copied back to `C:/tmp` by
SCP and never committed. Remote setup passed, the full unit suite passed 57/57,
and same-DCP validation passed structural 4/4 plus 1,000 vectors with zero
mismatches using Vivado's bundled JRE.

BOOM exposed two validator-environment gaps without producing a functional
mismatch: its clock port is named `clock_uncore_clock`, and its 147 MB generated
netlist needs more than the former 300-second elaboration limit. Clock-token
recognition and a tool-specific bounded timeout map (`xvlog=300`, `xelab=900`,
`xsim=600`) were added under tests and deployed by SCP. The final BOOM run
passed in 678.222 seconds. Evidence was retrieved outside Git to
`C:/tmp/boom-soc-validation_report.json`, `C:/tmp/boom-soc-simulation.log`,
`C:/tmp/boom-soc-equivalence-final.log`, and `C:/tmp/boom-soc-legality.log`.

## Cross-Design Findings

Two of nine new control rows are complete. No policy change is justified from
this incomplete matrix, although PBLOCK now has one validated positive on an
extreme multi-path-spread signature and remains correctly gated.
