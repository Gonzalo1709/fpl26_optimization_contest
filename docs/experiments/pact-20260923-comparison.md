# PACT batch comparison: September 23-24

The newly supplied PACT batch reports **5 PASS and 7 FAIL**, compared with **7 PASS and 5 FAIL for Meemar** and **10 PASS and 2 FAIL on September 16**. Meemar improves delivery relative to this PACT run, principally by successfully validating LogicNets and spam filter. Neither configuration matches September 16's aggregate result.

## Evidence and limits

The upload contains twelve [console logs](../../pact/), one per original benchmark. It does not contain the referenced token-usage JSON, candidate manifests, recipe-outcome files, enabling-pool events, or detailed final-validation logs. Frequencies and costs below use rounded console summaries. PASS is the console's reported result; the underlying validation reports cannot be independently inspected from this upload.

This supplies a separate PACT configuration run, replacing the earlier absence of a PACT comparison. It is still not a controlled ablation: historical input hashes, exact executed commits, memory contents, and equivalent validation conditions are not established across all batches. Run timestamps span September 23-24 even though the folder is simply named `pact`.

## Delivered results

All frequencies are MHz. Fallback values are the original input, not the rejected search-best candidate.

| Benchmark | Sep 16 | PACT delivered | Meemar delivered | PACT outcome |
|---|---:|---:|---:|---|
| AMD mini-ISP | 404.20 | 404.20 | 397.61 | PASS |
| BOOM | 50.74 | 48.24 | 48.24 | FAIL; final-validation timeout, input fallback |
| CoreScore | — | — | — | FAIL; baseline DRC admission |
| FINN RadioML | 296.30 | 302.02 | 302.02 | PASS |
| ISPD16 | — | — | — | FAIL; baseline DRC admission |
| LogicNets | 480.08 | 403.55 | 499.00 | FAIL; final-validation rejection, input fallback |
| 3D rendering | 276.78 | 276.78 | 276.78 | PASS |
| Digit recognition | 419.11 | 366.97 | 366.97 | FAIL; final-validation rejection, input fallback |
| Optical flow | 325.31 | 325.31 | 325.31 | PASS |
| Spam filter | 454.34 | 437.45 | 449.24 | FAIL; final-validation rejection, input fallback |
| VexRiscv | 455.37 | 310.17 | 310.17 | FAIL; final-validation rejection, input fallback |
| VTR MCML | 66.61 | 66.82 | 66.82 | PASS |

| Aggregate | Sep 16 | PACT | Meemar |
|---|---:|---:|---:|
| PASS / original benchmarks | 10/12 | 5/12 | 7/12 |
| Reported/reconstructed score sum | 395.039 | approximately 119.683 | 215.625 |
| Mean score across 12 | 32.920 | approximately 9.974 | 17.969 |
| Recorded LLM cost | $0.1538 | approximately $0.1690 | $0.11053 |
| Runtime total | 19,086 s | approximately 20,209 s | approximately 17,632 s |

PACT scores are estimates from console `Delta Fmax`, cost, and optimizer runtime using `max(0, gain * (1 - 0.1 * cost - runtime / 36000))`; failures contribute zero. Console rounding means these are not full-precision manifest-derived scores. Runtime uses the ten optimizer summaries plus Started/Ended elapsed time for the two admission failures. Unreported early-failure LLM costs are excluded. These are local comparisons, not an organizer scorecard.

## What failed

- **CoreScore and ISPD16:** the baseline has `par_drc_clean=False`, while routing, hold, and pulse checks pass. They stop before search. This is the same admission issue seen previously.
- **BOOM:** the final-validation call raises `asyncio.exceptions.TimeoutError` and restores the original input. The PACT upload does not establish which internal validator phase timed out; Meemar's detailed logs separately placed its timeout in elaboration.
- **LogicNets, digit recognition, spam filter, and VexRiscv:** each reports `Strict final validation failed` and restores the original input. Their console logs refer to missing `validation-*.log` files. These logs alone cannot distinguish a structural failure, elaboration error, simulation mismatch, or another validation failure. Do not transfer Meemar's digit/VexRiscv elaboration diagnosis to PACT as a confirmed fact.

Useful next evidence is the referenced final-validation logs and JSON reports, especially LogicNets and spam filter, which pass in Meemar but fail here. No optimization or validation workloads were rerun for this analysis.

## What the new comparison says about the implementations

1. **Final-validation delivery failures also occur in the PACT configuration.** Meemar is not required to reproduce the general problem: PACT has five final-validation fallbacks, versus three for Meemar. This is evidence about the integrated configurations, not proof that the validation rule is incorrect or that every rejected design is functionally wrong.
2. **Meemar's clearest advantage is LogicNets.** It delivers 499.00 MHz where PACT falls back to 403.55 MHz. Meemar's detailed trajectory directly shows density contributing to that result. However, the full delivered difference combines search quality and validation outcome; it is not a pure density speedup.
3. **AMD favors the earlier reimplementation path.** PACT delivers 404.20 MHz and identifies a reimplementation candidate as best; Meemar delivers 397.61 MHz. Retain or test that lane when refining Meemar's rescue scheduling.
4. **FINN and VTR gains are already present in PACT.** Their delivered frequencies match Meemar at displayed precision. They therefore cannot be credited as new Meemar gains; Meemar's density action did not run on either design.
5. **PACT's distinctive search features remain unproven by this upload.** Beam width is one, so diverse-beam retention is inactive. No enabling-pool event files were supplied; console silence does not establish that the pool was empty. Critical-net reroute attempts on optical flow and digit recognition were rejected for missing operand evidence. No successful benefit from those attempts is shown.
6. **Existing recipe defects persist.** Scoped physical optimization is rejected for changing timing constraints on AMD, LogicNets, and VexRiscv. These should be repaired before attributing failed exploration to the high-level search strategy.

## Presentation conclusions

- ESCA-style reimplementation remains useful: it supplies PACT's delivered AMD result.
- PACT introduces stronger output acceptance, but this run loses five optimized outputs at that final gate; detailed failure reports are required before deciding whether search or validation needs repair in each case.
- Meemar improves the PACT configuration's delivered score and pass count, especially on LogicNets and spam filter, while reducing recorded runtime and LLM cost in these runs.
- September 16 remains ahead on aggregate score, subject to the different validation standards. Prioritize validator diagnosis, repair-oriented input admission, and targeted search-policy comparisons over adding more recipes.

Related sources: [PACT integration](../strategy/pact-integrated-features.md), [Meemar comparison](meemar-20260923-comparison.md), [September 16 CSV](../../results/Baseline%20-%2009_16.csv).
