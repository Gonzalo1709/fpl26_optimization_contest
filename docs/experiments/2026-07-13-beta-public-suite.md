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
| corescore_500_mod | spread 232.36/448 tiles; no critical fanout nets; critical BRAM; severe congestion | `PBLOCK` produced no gain; root restored | -1.238 ns | -1.238 ns | 0 MHz | 771.041 s | $0.010335 | 0 | Not required for neutral rolled-back candidate | Rejected PBLOCK; legal root retained |
| finn_radioml | spread 255.08/408 tiles; 4 critical fanout nets; no critical hard block; severe congestion | `PBLOCK` produced no gain; root restored | -1.910 ns | -1.910 ns | 0 MHz | 529.904 s | $0.01301 | 0 | Not required for neutral rolled-back candidate | Rejected PBLOCK; legal root retained |
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

Four of nine new control rows are complete. No policy change is justified from
this incomplete matrix, although PBLOCK now has one validated positive on an
extreme multi-path-spread signature and two neutral results on others; it
remains correctly gated and cannot yet be promoted more broadly.

## Beta Preview Candidate A Result

Candidate A at `75cf2498f0bb9a0d0b34c9e405d4f9086e900ba3`
(`feat: stop low-value fast search expansion`) was submitted as archive
`C:/tmp/fpl26_beta_candidate_a.zip`. The 1,525,735-byte archive has 468 entries,
SHA256 `337d9c4381c21cd99dce340b104d15faaa4e4e7027a92eeb6d61f80b5ae9b141`,
and MD5/server MD5 `94daa68fdd1794430b5edbb2b194f57c`.

Attempt #3 (`v_520de46a2c58`) was confirmed at `2026-07-14T01:25:04Z` and
completed at `2026-07-14T01:47:24Z` with score **10.616**, completed global
status, and no global failure.

| Benchmark | Input Fmax | Output Fmax | Delta Fmax | Runtime | Cost | Score | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | 403.551251 MHz | 414.250 MHz | +10.699 MHz | 210.633 s | $0.0195 | 10.616 | Routed, DRC, hold, pulse-width, and simulation gates all passed |
| `vexriscv_re-place_v2` | 397.456280 MHz | 397.456 MHz | 0 MHz | 100.498 s | $0.0098 | 0 | All gates passed; `no_improvement` |

The official preview supplied the full non-test run with metering. A manual SSH
non-test run was not possible because the instance environment had no injected
OpenRouter key and credentials were not transferred. Artifacts are retained at
`C:/tmp/beta-preview-attempt3/{scorecard.json,logs.zip,dcp_results.zip}`.

Candidate A improved the former beta incumbent by 3.077 points in attempt #3
and remained protected through the extended candidate window. Candidate B was
authorized and evaluated, then rejected after tying rather than exceeding A.
Candidate C had no justified single-variable change, and Candidate D was
skipped by its three-hour reserve gate.

Candidate A's archive, attempt #3 result, MD5, and hashes remain protected.
Every worse, equal, failed, or unproven candidate triggers automatic restoration
of `C:/tmp/fpl26_beta_candidate_a.zip` and confirmation of server MD5
`94daa68fdd1794430b5edbb2b194f57c`. The former incumbent archive remains
immutable at `C:/tmp/fpl26_beta_submission_runtime_v2.zip` for historical
rollback only; final freeze verification remains outstanding.

## Beta Preview Candidate B Result

Candidate B at commits `ef62cd5` and `416e4aa` added one fail-safe CriticalPin
attempt only after a neutral RuntimeOptimized result on an eligible
fanout-absent signature. Archive `C:/tmp/fpl26_beta_candidate_b.zip` was
1,526,812 bytes with 468 entries, SHA256
`53d75b9d1205a83edd0db15c8d8c320f5bb2ac5433327f40f2247e44ee7a9684`,
and MD5/server MD5 `29a9c8e2161bd8daa85c0319f8302991`. Organizer SCP
transferred it to `i-010122f97d9e8d2fd`; exact extracted `make setup` passed
with Vivado 2025.1 and its bundled Java 11, without installing `default-jre`.

Attempt #4 (`v_da0b3a97b453`) completed at `2026-07-14T07:25:16Z`:

| Benchmark | Input Fmax | Output Fmax | Delta Fmax | Runtime | Cost | Score | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | 403.551251 MHz | 414.250 MHz | +10.699 MHz | 210.602 s | $0.0192 | 10.616 | All official gates passed |
| `vexriscv_re-place_v2` | 397.456280 MHz | 397.456 MHz | 0 MHz | 148.383 s | $0.0098 | 0 | All gates passed; bounded fallback neutral; `no_improvement` |

The total **10.616** tied Candidate A rather than strictly improving it. The
fallback added about 47.9 seconds to the neutral Vex row and no Fmax. Candidate
B was therefore rejected. All attempt #4 artifacts were downloaded with
`--all` under
`C:/tmp/beta-preview-attempt4/results/beta/preview/attempt-4/`.

Candidate A was resubmitted at `2026-07-14T07:57:27Z`; its protected MD5 was
confirmed. Preview attempt #5 (`v_a6e8e4d1915a`) completed at
`2026-07-14T08:19:13Z` with score **10.788**: LogicNets reached 414.422 MHz
(+10.871 MHz) in 207.683 seconds at $0.0183, while Vex remained legal and
neutral in 99.892 seconds. Every official gate passed. Complete artifacts are
under `C:/tmp/beta-preview-attempt5/results/beta/preview/attempt-5/`.

Candidate C had no justified single-variable change. Candidate D became
ineligible at 07:30Z because fewer than three hours remained before freeze while
B was nonterminal. The validation instance was stopped after SCP/setup work
with 13h52m remaining. The final local suite passed 72/72 plus `compileall` and
`git diff --check` in `.venv`.

## Pre-Freeze Readiness

At `2026-07-14T02:49:29Z`, the live service still showed Candidate A MD5
`94daa68fdd1794430b5edbb2b194f57c` as the beta submission and attempt #3 as the
latest completed preview at **10.616**. There was no running instance or newer
preview attempt, and 14h52m of instance budget remained. A fresh organizer
`--all` download under `C:/tmp/fpl26-beta-freeze-final/` reproduced the existing
scorecard, logs, and DCP-result SHA256 hashes. The local suite passed 63/63 plus
`compileall`. The existing PID `38892` watcher at 08:30Z is read-only pre-freeze
evidence, not the new hard freeze. Under the `2026-07-14` authorization, no new
candidate may start after 09:45Z and the hard experimental freeze is 10:30Z.

## Final Beta Freeze Result

The 09:45Z candidate cutoff and 10:30Z hard freeze passed without any newer
candidate or upload. An interactive freeze audit at 10:31Z confirmed Candidate
A MD5 `94daa68fdd1794430b5edbb2b194f57c` as the latest beta submission and
attempt #5 / `v_a6e8e4d1915a` as completed/non-stale at **10.788**, with no
newer pending attempt. No validation instance was running and 13h52m remained.

The final `--all` download under
`C:/tmp/fpl26-beta-freeze-final-1030-interactive/` exactly reproduced the
recorded scorecard, log, and DCP-result hashes. Both benchmark rows were scored
and all official legality, routing, DRC, hold, pulse-width, and simulation gates
were true. The final `.venv` suite passed 72/72 plus `compileall` and `git diff
--check`.
