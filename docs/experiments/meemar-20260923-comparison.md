# Meemar batch comparison: September 23–24

**Update after the PACT upload:** A separate PACT run is now available: see the [PACT comparison](pact-20260923-comparison.md). It reports 5/12 PASS and approximately 119.683 aggregate points, versus Meemar's 7/12 and 215.625. Statements below about no supplied PACT-only batch describe the evidence available when this report was first written; they are superseded by that comparison. Exact causal isolation remains unavailable.

## Conclusion

The integrated configuration is **not ready to replace the September 16 configuration**. Across the 12 original benchmarks, it delivered seven validated improvements and five failed runs. Its reconstructed aggregate score is **215.625**, versus **395.039** in the September 16 CSV and **378.564** on September 8. That is a 45.4% decline versus September 16.

The density action works and is particularly promising on LogicNets. However, final-validation failures discard major gains, some placement trials add runtime without improving the incumbent, and two benchmarks still cannot enter search because of baseline DRC admission.

This is an analysis of uploaded artifacts, not a new optimizer or validation run. No source code or result CSV was changed.

## Coverage and comparison limits

- Sources: [new batch summary](../../meemar/summary.csv), benchmark `published_artifact.json`, `token_usage.json`, `recipe_outcomes.jsonl`, validation logs and console logs; historical [September 16 CSV](../../results/Baseline%20-%2009_16.csv) and [September 8 CSV](../../results/Baseline%20-%2009_08.csv).
- The new summary contains **13 rows**, including an already-optimized AMD input named `amd_mini-isp_2025.1_optimized-20260923_195145.dcp`. That extra row is excluded: it is not an independent original benchmark, and its detailed folder is absent from the upload. The comparison uses the 12 original benchmark folders, not the raw 8/13 PASS count.
- New scores use full-precision values from token summaries and the actually delivered artifact. Three final-validation fallbacks have zero improvement; the two pre-search failures contribute zero to the 12-benchmark aggregate. This is a reconstructed score, not an organizer scorecard.
- Historical CSV PASS labels do not establish the same structural/simulation validation standard as this new run. The new batch includes both PACT and Meemar behavior; no PACT-only batch was supplied for causal isolation.
- Initial frequencies agree with the historical CSV to its displayed precision, but matching input hashes across all historical runs could not be established from those CSVs.
- Historical CSV percentage columns use gain divided by final frequency, rather than the conventional gain divided by initial frequency. This report uses MHz deltas and does not reuse those percentages.

## Delivered outcomes

Frequencies are MHz. “Input fallback” means the optimized candidate was rejected and the original input was retained. “Admission failure” means no candidate entered search; a copied input does not establish validated legality.

| Benchmark | Sep 8 best | Sep 16 best | Meemar delivered | Change vs Sep 16 | Meemar result |
|---|---:|---:|---:|---:|---|
| AMD mini-ISP | 404.20 | 404.20 | 397.61 | -6.59 | PASS |
| BOOM | 51.68 | 50.74 | 48.24 | -2.50 | FAIL; input fallback |
| CoreScore | 344.23 | — | — | — | FAIL; baseline admission |
| FINN RadioML | 284.90 | 296.30 | 302.02 | +5.72 | PASS |
| ISPD16 | 121.57 | — | — | — | FAIL; baseline admission |
| LogicNets | 473.04 | 480.08 | 499.00 | +18.92 | PASS |
| 3D rendering | 270.93 | 276.78 | 276.78 | 0.00 | PASS |
| Digit recognition | 414.08 | 419.11 | 366.97 | -52.14 | FAIL; input fallback |
| Optical flow | 325.31 | 325.31 | 325.31 | 0.00 | PASS |
| Spam filter | 447.63 | 454.34 | 449.24 | -5.10 | PASS |
| VexRiscv | 455.37 | 455.37 | 310.17 | -145.20 | FAIL; input fallback |
| VTR MCML | 62.25 | 66.61 | 66.82 | +0.21 | PASS |

| Aggregate | Sep 8 | Sep 16 | Meemar |
|---|---:|---:|---:|
| Batch PASS / original benchmarks | 12/12 | 10/12 | 7/12 |
| Sum of reported/reconstructed scores | 378.564 | 395.039 | 215.625 |
| Mean score across 12 | 31.547 | 32.920 | 17.969 |
| Recorded LLM cost | $0.0467 | $0.1538 | $0.11053 |
| Runtime total | 10,795 s | 19,086 s | approximately 17,632 s |

The new runtime combines optimizer durations for the ten completed summaries with batch durations for the two early failures. The batch-level elapsed durations for all 12 sum to 17,651 seconds. Historical durations follow their CSV definitions; treat runtime comparisons as approximate rather than a controlled machine-speed measurement.

Among the **same seven benchmarks that pass now**, score rises from **203.857 to 215.625**, about **5.8%**. This shows useful gains survive on part of the suite, but excludes the three new failures and must not replace the full-suite comparison.

The older [September 2 CSV](../../results/Baseline%20-%2009_02.csv) totals 576.165, including BOOM's TIMEOUT row. It is dominated by unusually large ISPD16 and digit-recognition gains. Those old outputs have not been revalidated here; that historical total is not evidence of a better validated configuration.

## Why the five runs failed

### CoreScore and ISPD16: the existing admission problem persists

Both stopped before optimization with `par_routed=True`, `par_drc_clean=False`, and passing hold/pulse-width checks. Their structural and simulation checks remained unknown. The immediate cause is strict baseline admission; it is not a failed density experiment.

Evidence: [CoreScore console](../../meemar/corescore_500_mod_2025.1/console.log), [ISPD16 console](../../meemar/ispd16_example2_2025.1/console.log). The same two benchmarks failed in the September 16 comparison.

The startup fallback preserves input bytes but cannot resolve the policy mismatch: allowing a defective input to enter a repair search is different from accepting a defective output.

### BOOM: final validator exceeded 480 seconds

Search produced an admitted candidate at **50.74 MHz**, essentially the September 16 result. The search deadline stopped a later pblock attempt and preserved the validation reserve. Final validation then ran from about 21:12:52 to 21:20:52 and raised `asyncio.TimeoutError`.

The validator log reaches `Elaborating with xelab...` at 21:15:33 and has no successful completion report before termination. There is no demonstrated functional mismatch. The controller restored the **48.24 MHz** input.

Evidence: [BOOM console](../../meemar/boom_soc_2025.1/console.log) and its `validation-*.log`. The empty error string in the manifest is a reporting defect caused by stringifying the timeout exception; the traceback supplies the missing diagnosis.

### Digit recognition and VexRiscv: XSIM elaboration errors

Their best admitted search candidates reached **403.88 MHz** and **437.25 MHz**, respectively. Structural validation passed. Simulation could not complete because XSIM reported `VRFC 10-3180` missing ports in `revised_sim_renamed.v`, followed by failed static elaboration. The controller therefore restored **366.97 MHz** and **310.17 MHz** inputs.

These are not observed simulation mismatches and do not yet prove that the optimized hardware is functionally wrong. The validator's module-renaming code is a strong investigation target: it renames general word-form module declarations but only selected `layer...` and `myreg...` instance patterns, rather than handling arbitrary module references and escaped identifiers. Confirming the exact cause requires inspecting the generated golden/revised netlists and the elaborator's bound modules.

Evidence: [digit console](../../meemar/rosetta_digit-recognition_2025.1/console.log), [VexRiscv console](../../meemar/vexriscv_re-place_2025.1/console.log), their validation logs, and [validator renaming implementation](../../validate_dcps.py#L644).

The wrapper reports `infrastructure_failure=False` in these failed validation JSONs because the existing validator returns a failed simulation phase for elaboration errors. That field does not turn these failures into behavioral mismatches.

Even if all three rejected candidates had validated, using their search-best frequency and the observed total runtime/cost would produce approximately **376.89 points**, still below September 16's 395.04. This is a hypothetical diagnostic, not a valid achieved score. Validator repairs alone would not recover all prior performance.

## What the Meemar mechanisms accomplished

### Density search: real benefit, uneven return

There were **18 density attempts across six benchmarks**. Nine ran placement successfully; nine mapped to an already-attempted region and were rejected before another placement. Duplicate-region attempts still consumed **151.5 seconds** in total. All density attempts together cost approximately **3,250 seconds** across the batch.

- **LogicNets:** baseline 403.55 → 413.22 after early replication → **494.81** with density 0.50 → **499.00** after later replication. Density 0.42 regressed to 388.20; 0.58 reached 494.32 and did not beat 0.50. The final candidate passed structural and simulation checks. This is the strongest direct evidence for keeping the density action.
- **AMD mini-ISP:** density improved the run to 397.61 MHz, but the prior configurations reached 404.20. The action helps relative to this run's earlier state without establishing a new best across runs.
- **Spam filter:** density supplied the useful gain to 449.24 MHz. It beats September 8 but falls short of September 16's 454.34.
- **3D rendering:** two unique density placements consumed about **919 seconds**, both producing worse timing. The retained 276.78 MHz came from earlier physical optimization. Including the duplicate trial, the density phase cost about 937 seconds without a delivered improvement.
- **Digit and VexRiscv:** density created improved intermediate candidates, then full-placement actions improved them further. Final functional validation was unavailable because elaboration failed.

Density did not run on FINN, optical flow, VTR, or BOOM. Their initial sizes exceeded the **50,000-primitive** limit (about 157k, 84k, 78k, and 377k–379k, respectively). FINN and VTR's gains therefore came from the existing replication/physical-optimization actions, not density search.

### Other search findings

- Seven `FULL_PLACE_ROUTE` attempts occurred. Four were WNS-neutral: AMD, LogicNets, spam filter, and the second digit attempt. Together they consumed roughly **24 minutes** across the batch. This is a larger optimization opportunity than eliminating duplicate-density overhead alone.
- All ten available enabling-pool event files are empty. No enabling-move benefit is demonstrated by this batch.
- Beam width is **1**, so the physical-diversity selector cannot preserve multiple different candidates. The batch does not evaluate that PACT feature's intended benefit.
- `PATH_CLUSTER_REPLACE` and `REIMPLEMENTATION` did not execute in the recorded recipe outcomes. Broader path rescue is therefore untested here. The changed scheduling also differs from earlier runs that used the independent reimplementation lane.
- Two scoped physical-optimization attempts were rejected for changing timing constraints, on LogicNets and VexRiscv. This is an existing recipe problem, not evidence that the new density flow violated constraints.
- The optical-flow critical-net reroute failed because no eligible terminal nets were selected. The outer message says “no operand evidence,” but the Vivado log gives the more specific no-eligible-net reason.

## Recommended next work

1. **Repair and classify final-validation failures first.** Investigate complete module/instance renaming and escaped identifiers for digit/VexRiscv. Distinguish compilation/elaboration errors from simulation mismatches. Give BOOM a measured, size-aware validation allowance and preserve explicit timeout diagnostics. Keep strict publication checks.
2. **Resolve baseline admission versus repair eligibility.** CoreScore and ISPD16 cannot benefit from any new search action while rejected before search. Record baseline defects, define what repairs are permitted, and require accepted outputs to meet the intended final rules.
3. **Run targeted policy ablations.** Compare old reimplementation scheduling with Meemar scheduling on AMD, spam, digit, and VexRiscv. Keep the LogicNets density lane. Deduplicate resolved regions before a recorded execution attempt, and gate density/full-placement retries on measured incremental benefit and runtime.

Do not attribute aggregate changes to Meemar alone until a matched PACT-only control is available. Preserve the current passing output artifacts and rerun validation on the rejected candidates before spending another full search hour on each affected design.
