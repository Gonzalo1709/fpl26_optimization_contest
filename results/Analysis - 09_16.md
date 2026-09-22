# Analysis of the 09-16 batch

## Update: successful VTR rerun

The replacement VTR console log records a separate run from **2026-09-17 04:00:49 to 04:33:35**, ending with **exit code 0 and Status PASS**. Its optimizer runtime is **1,963.97 seconds**, LLM cost **$0.0153**, and final reported Fmax **66.61 MHz**, up from **62.25 MHz**. This is approximately **7.00%** growth relative to the initial frequency. The CSV retains the established final-frequency denominator, giving **6.55%**.

The latest-result selection now has **10 passes and 2 failures**: CoreScore and ISPD16 remain failed. `Baseline - 09_16.csv` has been updated with the VTR rerun and a mean projected score of **32.920**, counting the two failed cases as zero. The CSV calculates gains from displayed initial/final values, yielding VTR +4.36 MHz and score 4.115; the log's independently rounded delta is +4.37 MHz.

The rerun published successive WNS improvements from -14.527 to -13.743, -13.535, and finally **-13.474 ns**. Its selected checkpoint is `targeted_replication-ecc4b0c1`. There are no ERROR or WARNING log entries in the replacement console. This demonstrates successful completion on retry, but does not establish the root cause or a permanent fix for the original artifact-loss failure.

**Provenance:** `09-16/summary.csv` still describes the original failed VTR attempt. It is retained unchanged as a historical batch record; the CSV's VTR row instead comes from the replacement console in `09-16/vtr_mcml_2025.1/console.log`. The VTR outcome database from the original inspection is no longer present. The original batch analysis below, including its nine-pass totals, timings, outcome counts, and VTR failure diagnosis, describes the first attempt and is retained as history. The updated CSV combines original results for 11 benchmarks with the VTR rerun; it is not one uninterrupted batch.

## Original batch analysis

The upgrades produce useful gains, especially through targeted replication, but this batch does not establish an overall improvement over the saved baseline. Reliability failures and additional execution time offset several better timing results.

## Scope and measurement

Inspected `09-16/summary.csv`, all 12 console logs, and 11 SQLite outcome databases in read-only mode. The batch ran from 2026-09-16 22:41:17 through 2026-09-17 03:42:26, in the logs' timezone: **5 hours, 1 minute, 9 seconds**.

The available comparison is `results/Baseline - 09_17.csv`. Its label does not establish chronology, so this report calls it the **saved reference**, not a controlled previous-version experiment. No implementation revision is recorded in the supplied batch summary. Different behavior cannot be attributed solely to individual code changes.

Reported configuration: `openai/gpt-5.6-terra`, fast profile, 3,600-second limit, one branch, beam width one, two generations, one step per branch, patience one, and minimum WNS improvement 0.020 ns. Additional deterministic/portfolio actions explain why total attempts exceed two.

**PASS means process success**, including recovery with an admitted output. It does not establish completed structural/simulation validation. Available outcome records have those validation fields unset. Optimized DCPs, published-artifact manifests, detailed Vivado reports, and token-usage JSON files referenced by the logs are absent from this supplied folder. Their content cannot be independently verified here.

## Results

Nine runs passed and all nine reported positive Fmax gains. Three failed. The nine successful runs consumed 16,633 seconds and reported $0.1385 in LLM cost. That cost is the sum of successful-run summaries, not a reconstructed exact total for failed runs.

Percentages below use the conventional `(final - initial) / initial` denominator and rounded console values. The saved reference CSV instead appears to use `(final - initial) / final`; its percentage column should not be compared directly.

| Benchmark | Initial MHz | Final MHz | Gain | Runtime, min | Final versus reference, MHz | Outcome |
|---|---:|---:|---:|---:|---:|---|
| mini-ISP | 307.13 | 404.20 | 31.61% | 13.87 | 0.00 | PASS |
| BOOM | 48.24 | 50.74 | 5.18% | 60.00 | -0.94 | PASS; timed out, retained incumbent |
| CoreScore | 344.23* | unavailable | unavailable | 2.82** | unavailable | FAIL before baseline admission |
| FINN RadioML | 284.90 | 296.30 | 4.00% | 32.32 | +11.40 | PASS |
| ISPD16 example2 | 107.64* | unavailable | unavailable | 5.33** | unavailable | FAIL before baseline admission |
| LogicNets | 403.55 | 480.08 | 18.96% | 30.53 | -19.17 | PASS |
| 3D rendering | 270.93 | 276.78 | 2.16% | 33.17 | +5.85 | PASS |
| Digit recognition | 366.97 | 419.11 | 14.21% | 36.21 | +5.03 | PASS |
| Optical flow | 324.89 | 325.31 | 0.13% | 17.59 | 0.00 | PASS |
| Spam filter | 437.45 | 454.34 | 3.86% | 32.90 | +6.71 | PASS |
| VexRiscv | 310.17 | 455.37 | 46.81% | 20.62 | 0.00 | PASS |
| VTR MCML | 62.25 | unavailable | unavailable | 15.40** | unavailable | FAIL during checkpoint restore/finalization |

*Initial values also recorded in the saved reference; failed runs do not have final optimization summaries. **For failed runs, runtime is the batch start/end interval. Successful rows use optimizer runtime.

On the nine common completed benchmarks: **four better, three equal, two worse** than the reference. Runtime was **2.11 times** the reference runtime, and LLM cost **3.58 times** the reference cost for those same nine designs. Their geometric-mean Fmax gain over their own initial checkpoints was 13.19%; this excludes failed designs and is not a full-suite result.

Using the current score calculation and rounded console delta/runtime/cost, the nine-run mean projected score is approximately **43.438**, versus **43.315** for the same reference rows. That is effectively flat at this level of evidence. If the three failed runs are assigned zero for a conservative 12-run operational comparison, the mean is approximately **32.579**, versus the reference's **33.583**, about **3.0% lower**. These are projected comparisons, not validated contest scores. In particular, VTR had logged publications before failing, so zero is an explicit failure-handling assumption rather than proof that no output exists.

## What worked

### Targeted replication provides useful additional capability

The available databases contain 17 completed targeted-replication attempts: nine with positive parent-relative Fmax gain and eight with zero gain. No recorded targeted-replication attempt failed implementation admission. This is a small, selected sample rather than a general success-rate estimate.

- **FINN:** successive improvements of approximately +7.93 and +3.47 MHz produced its 296.30 MHz final result. The saved reference had no improvement.
- **BOOM:** three successive gains of +1.31, +1.13, and +0.07 MHz produced the retained result. The last gain was expensive relative to its size.
- **Spam filter:** reimplementation, targeted replication, and fanout optimization formed the winning chain. Their parent-relative gains were approximately +10.18, +1.41, and +5.30 MHz.
- **VTR:** the first replication produced +3.19 MHz before the later infrastructure failure. This is useful search evidence, not a verified final result.

### Existing reimplementation remains important

Mini-ISP and VexRiscv finished at the same Fmax as the reference. Both selected reimplementation checkpoints. Digit recognition gained approximately +47.11 MHz through reimplementation and another +5.03 MHz through physical optimization. LogicNets gained approximately +69.49 MHz through reimplementation and +7.04 MHz through fanout from that state, but still finished below the reference.

The additional physical-optimization improvement on digit recognition and the +5.85 MHz result on 3D rendering are useful. These actions also show that success is not limited to the new replication recipe.

### Small granular improvements are possible

Optical flow's `critical_pin_opt` attempt produced approximately +0.423 MHz. Other tried granular flags did not improve it. The result matches the reference final Fmax, but this run took approximately 3.11 times as long.

## Failures and defects

### Baseline admission blocks CoreScore and ISPD16

Both failed with `par_routed=True`, `hold_passed=True`, `pulse_width_passed=True`, and **`par_drc_clean=False`** before any output was admitted. This is not evidence that an optimization made those designs worse: search had not started.

The logged DRC query counts both `Error` and `Critical Warning` severities. The supplied console logs do not include violation names, counts, or the full DRC report, so they cannot establish which rule triggered rejection or whether the check matches the intended contest acceptance criteria.

Next action: capture rule IDs, severity, affected objects, and baseline/candidate differences. Review the check against the actual required validation policy. Do not bypass all DRC failures merely to restore a green process status.

Evidence: [CoreScore console](../09-16/corescore_500_mod_2025.1/console.log), [ISPD16 console](../09-16/ispd16_example2_2025.1/console.log).

### Scoped optimization changes the constraint identity

`SCOPED_PHYS_OPT` was rejected on mini-ISP, LogicNets, and VexRiscv with **“Candidate changed timing constraints.”** Admission protected the incumbent in each case.

The current recipe creates a named path group and later assigns its endpoints to the default group. That is a concrete suspect for why exported timing constraints differ: assigning the default group is not demonstrated to restore the original path-group definitions. Exact attribution requires the pre/post XDC files, which are absent.

Next action: restore exact original timing constraints after the temporary scoped operation, inspect the XDC difference, and measure again before admission. Until corrected, this recipe repeatedly spends time producing rejected candidates.

Evidence: [mini-ISP console](../09-16/amd_mini-isp_2025.1/console.log), [recipe source](../src/recipes.py).

### Partial replacement cannot execute its timing-path extraction

FINN's `PARTIAL_REPLACE` attempt failed with **“The object 'timing_path' does not have a property 'POINTS'.”** The current recipe directly requests that property. This is a tool-interface defect; it says nothing about whether partial replacement would improve FINN.

Next action: use a timing-path extraction supported by the installed Vivado version and preflight the required interface before selecting the recipe.

Evidence: [FINN console](../09-16/finn_radioml_2025.1/console.log), [recipe source](../src/recipes.py).

### VTR loses access to checkpoint and run artifacts

VTR logged publication at WNS -13.535 ns, corresponding to approximately **66.34 MHz** at its 1.538 ns clock, before failing. This value is an intermediate logged publication, not a recovered final output.

The failure sequence was:

1. Reopening a physical-optimization checkpoint could not find `mcml.nnlns`.
2. Restoring the parent failed because the parent's DCP was missing.
3. Appending recipe history and writing the publication manifest failed because their run-directory paths were missing.

This indicates an artifact-availability/lifecycle problem beyond a bad routing choice. The logs do not establish who removed or moved the files, whether checkpoint extraction failed, or whether the published output outside the run directory survived. Do not attribute it to cleanup code without more evidence.

Next action: inspect filesystem/cleanup activity on the execution machine, preserve the run directory until all workers finish, and make failure reporting tolerate missing run artifacts while retaining a verifiable output.

Evidence: [VTR console](../09-16/vtr_mcml_2025.1/console.log).

### BOOM exhausts the wall-clock budget

BOOM's final `CELL_RELOCATE` attempt reached the wall-clock limit during routing. The optimizer retained its admitted replication result and returned PASS. This is successful fallback behavior, but the final attempt consumed approximately 771 seconds without delivering a measured candidate.

The preceding replication attempt also consumed approximately 803 seconds for only +0.069 MHz. For a modest already-banked gain, its added runtime penalty can exceed the gain's score benefit. Runtime estimates need to include repair routing, checkpoint admission, and restoration, not only the mutation itself.

Evidence: [BOOM console](../09-16/boom_soc_2025.1/console.log), its outcome database.

## Where the extra time goes

The 11 supplied databases contain **56 outcome rows**. Mini-ISP's database is absent, the two baseline failures have empty databases, and VTR's final attempt was not recorded because history writing failed. These counts therefore do not cover every action in the batch.

Among those 56 rows, **31 had zero parent-relative Fmax gain**, consuming approximately **6,033 seconds**, or **40.5% of the recorded attempt time**. Zero gain is not proof of an identical physical state, but there is no demonstrated later benefit from these neutral attempts in this evidence.

| Strategy | Recorded attempts | Positive gain | Zero gain | Failed | Recorded time, min |
|---|---:|---:|---:|---:|---:|
| TARGETED_REPLICATION | 17 | 9 | 8 | 0 | 78.8 |
| REIMPLEMENTATION | 5 | 4 | 1 | 0 | 58.4 |
| PBLOCK | 5 | 0 | 5 | 0 | 28.9 |
| PHYS_OPT | 13 | 3 | 10 | 0 | 22.8 |
| GRANULAR_PHYS_OPT | 5 | 1 | 4 | 0 | 13.1 |
| FANOUT | 3 | 2 | 1 | 0 | 12.4 |

Positive here means improvement over that action's parent, not necessarily improvement over the global incumbent. Branch gains must not be summed as if they all occurred in one winning chain.

Five PBLOCK attempts, on FINN and digit recognition, consumed nearly 29 minutes without timing gain. Some use different parent states, so this is not evidence of a broken exact-state duplicate filter. It does show that changing checkpoint identity alone should not erase all evidence that an action is unlikely to help.

The detailed tool summaries also show substantial checkpoint-loading overhead: approximately 20–41% of measured tool time across successful runs was in `vivado_open_checkpoint` and `rapidwright_read_checkpoint`. Some reopens are essential to verify exact artifacts. Optimize redundant loads and lazy RapidWright synchronization while preserving admission checks.

Examples of stopping opportunities, visible retrospectively:

- Mini-ISP reached its final best at 22:46:15, then continued for almost nine minutes.
- VexRiscv reached its final best at 03:13:53, then continued for approximately thirteen minutes.
- FINN reached its final best at 00:08:20, then continued for approximately twenty-two minutes.
- Optical flow reached its final best at 02:24:21, then continued for approximately nine minutes.

These timestamps identify wasted time in hindsight; they do not imply the optimizer could know the future. They motivate better runtime/gain estimates and limits on repeated low-yield action families.

## Memory and intermediate moves

Each nonempty database contains only one run ID. The copied files demonstrate outcome recording but do not demonstrate cross-run transfer. Confirm whether batch execution uses one durable shared memory database or creates/moves a separate database per benchmark. Local per-run records alone cannot establish that persistent memory improved this batch.

The economics code requires at least three comparable samples before an expected-gain estimate can exclude an action. Sparse, parameter-specific or isolated histories may therefore leave many unproductive actions eligible. This is an explanation consistent with the implementation, not a logged proof of the planner's rationale for each choice.

This batch also does **not** demonstrate the PACT-style intermediate-move advantage discussed earlier. The recorded successful chains improve timing at each useful step; no recorded outcome has a negative parent-relative gain. We have evidence for composing beneficial moves, especially reimplementation, replication and fanout. We do not yet have evidence that retaining a deliberately worse intermediate checkpoint would have improved these results.

## Recommended order of work

1. **Recover reliability:** inspect baseline DRC details, fix scoped-constraint restoration and partial-replacement extraction, and diagnose VTR's missing artifacts.
2. **Reduce low-yield continuation:** improve full-attempt runtime estimates, protect the finalization reserve, and limit repeated neutral PBLOCK/physical-optimization attempts using compatible physical evidence.
3. **Verify memory persistence:** preserve a shared, version/device-aware history and log retrieved sample counts and economic admission reasons.
4. **Then evaluate richer search:** compare enabling moves or physical diversity under the same total budget, after broken recipes no longer consume the comparison.

No optimizer code was changed and no Vivado, RapidWright, optimization, or validation workload was run for this analysis.
