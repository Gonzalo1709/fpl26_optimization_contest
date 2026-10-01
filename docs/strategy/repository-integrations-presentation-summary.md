# Repository-inspired optimizer changes

Presentation content for an audience familiar with the contest. These are adaptations to our optimizer, not complete ports of the upstream repositories. Implementation attribution follows the integration documents; performance claims follow the recorded batch analysis.

## Slide 1 — How the optimization strategy evolved

| Reference | Main contribution | Reason for adoption |
|---|---|---|
| ESCA | Deterministic reimplementation and recovery of the best checkpoint | Explore a substantially different placement when local improvements stall |
| RouteAgents | Bounded actions, persistent outcome memory, and cost-aware continuation | Choose experiments using measured physical evidence and previous outcomes |
| PACT | Targeted edits, intermediate states, and final functional validation | Explore useful action sequences and validate the candidate before delivery |
| Meemar | Density-controlled placement, selective rescue, and execution telemetry | Add a new physical search dimension and improve operational reliability |

**Speaker note:** Most changes are in the search controller, action library, and validation infrastructure. They do not retrain the language model; they give it better choices, evidence, and execution boundaries.

## Slide 2 — ESCA: add a deterministic global alternative

- Added a reimplementation flow: reset placement/routing, optimize, place, optionally run physical optimization, route, and compare timing.
- Added QoR-suggestion preparation, with an Explore fallback when the suggested strategy is unavailable.
- Made optional stages budget-aware so an experiment leaves enough time to complete routing and preserve a usable checkpoint.
- Added placement-preserving physical optimization/rerouting and bounded placement alternatives.
- Retain the best accepted state and restore it after a regression or failed experiment.

**Why:** Local changes can be limited by the current placement. A deterministic global attempt can find a different starting point without asking the LLM to choose every command.

**Speaker note:** ESCA supplied the earlier incumbent-retention pattern. Later changes strengthened artifact checks, and PACT changed final publication: an improved search candidate is now withheld until final validation passes. We did not import ESCA's concurrent two-process scheduler or register-surgery implementation.

Source: [ESCA and RouteAgents integration](esca-routeagents-integrated-features.md).

## Slide 3 — RouteAgents: choose actions from evidence and experience

- Expanded the bounded action library: granular and scoped physical optimization, partial replacement, targeted high-fanout replication, and optional retiming.
- Added persistent SQLite memory of action parameters, design features, timing gain, runtime, cost, and failures; retrieve compatible outcomes from similar designs.
- Use failed and neutral attempts as negative evidence: they retain their cost but contribute no usable positive gain.
- Prevent repeated ineffective actions on the same checkpoint; refresh physical evidence after an accepted design change.
- Start with three deterministic moves, then use model-guided selection and expected benefit versus additional time/cost to decide whether to continue.

**Why:** Action selection should reflect the design's physical bottleneck and the cost of previous experiments. Memory also allows lessons to survive beyond a single run when the database is reused.

**Speaker note:** Candidate ranking was corrected to compare candidates at the same incurred run cost. Artifact checks were strengthened with save/reopen, hashes, port/constraint identity, and implementation checks. Retiming remains opt-in and requires an external sequential-equivalence proof. Scoped and partial-replacement recipes have recorded execution defects; their presence is not evidence of successful optimization. Cross-run memory benefit has not been isolated experimentally.

Source: [ESCA and RouteAgents integration](esca-routeagents-integrated-features.md).

## Slide 4 — PACT: explore targeted edits and useful intermediate states

- Added critical-net rerouting, critical-branch rerouting, and path-local replacement with bounded target counts.
- Bind each proposed action to its seed checkpoint; recheck eligibility and record the exact live Vivado objects selected before modification.
- Added physical diversity to beam selection so retained candidates can represent different congestion, spread, routing-delay, or fanout conditions.
- Added a small enabling pool for legal neutral or slightly regressive states that improve physical conditions; give them a bounded rerouting follow-up.

**Why:** An action may improve placement or congestion before improving timing. Keeping a few promising intermediate states allows a second action to exploit that change.

**Speaker example — illustrative, not a measured result:** A placement change reduces path spread but worsens WNS by 0.005 ns. It can remain in the enabling pool for a reroute attempt. If the follow-up improves the best timing and passes the required checks, it can advance; otherwise the previous best is retained.

**Speaker note:** The allowed WNS regression is capped at 0.010 ns, with bounded pool size, lifetime, depth, and follow-up budget. This is a restricted producer-then-reroute mechanism, not arbitrary action composition. Beam diversity requires beam width greater than one. The latest batch used width one and recorded no enabling-pool events, so neither mechanism has demonstrated a benefit there.

Source: [PACT integration](pact-integrated-features.md).

## Slide 5 — PACT: separate search success from publishable output

- Preserve the original input as the golden reference and keep the search-best candidate internal until final validation.
- Reserve time for structural checking and randomized simulation before publishing an optimized DCP.
- Require affirmative validation results tied to the candidate's hash; skipped checks and validation infrastructure failures do not count as success.
- If final validation fails or times out, retain the original input and report the optimization run as failed.

**Why:** Better timing and clean implementation checks alone do not establish preserved functionality.

**Speaker note:** Defaults reserve 600 seconds, allow 480 seconds for final validation, and use 1,000 random vectors. Randomized simulation is not formal equivalence; retiming retains its separate proof requirement. The strict baseline DRC admission rule already existed and was not introduced by PACT.

Source: [PACT integration](pact-integrated-features.md).

## Slide 6 — Meemar: search placement density and spend rescue time selectively

- Added density-controlled reimplementation: try central placement regions for target densities 0.50, 0.42, and 0.58, each from the same immutable baseline.
- Check region capacity for fabric and hard resources, preserve protected constraints, and skip trials that do not fit size or remaining-time limits.
- Detect trials resolving to an already-tested region to avoid repeating placement.
- Move the automatic original-input reimplementation rescue after the opening and density phases; run it only if those phases produced no meaningful gain.
- Added broader critical-path cluster replacement, targeting internal datapath LUT/FF cells after cheaper actions stall.

**Why:** Region size changes placement compactness and routing pressure. Testing a few densities adds a physical search variable, while selective rescue reduces unnecessary global rebuilds.

**Speaker note:** Density is gated to designs with at most 50,000 primitives and sufficient runtime. It is a generic capacity-checked strategy, not a collection of benchmark-specific boxes. Path-cluster replacement was implemented but did not execute in the latest batch.

Source: [Meemar integration](meemar-integrated-features.md).

## Slide 7 — Meemar: improve startup recovery and cost measurements

- Copy and hash-check the input into the output location before tool-server startup, preserving a fallback even after an early startup failure.
- Fall back to the existing deterministic mode when no API key is available; retain an explicit option to require LLM access.
- Separate client call duration from server execution and synchronization time in telemetry.
- Record completion, pending, and timeout states explicitly; keep uncertain records for diagnosis and exclude them from completed-cost forecasts.

**Why:** Startup errors should not leave the output missing, and search decisions need measured action costs rather than ambiguous timeout durations.

**Speaker note:** A copied input is only a recovery artifact. It does not repair baseline DRC violations or establish that the input passed validation. Meemar preserved the existing final-validation and memory safeguards.

Source: [Meemar integration](meemar-integrated-features.md).

## Slide 8 — What the results support, and what comes next

- **Strongest direct evidence: density search on LogicNets.** Early replication reached 413.22 MHz; density 0.50 reached 494.81 MHz; later replication delivered a validated 499.00 MHz, versus 480.08 MHz on September 16.
- **Meemar improves on PACT, but both trail September 16.** PASS counts are 10/12 for September 16, 5/12 for PACT, and 7/12 for Meemar; aggregate reported/reconstructed scores are 395.039, approximately 119.683, and 215.625, respectively.
- **The separate PACT run clarifies attribution.** FINN and VTR already match Meemar's final frequencies. PACT preserves AMD's 404.20 MHz reimplementation result, above Meemar's 397.61 MHz. Meemar delivers LogicNets and spam filter improvements where PACT falls back after final-validation rejection.
- **Three new failures occurred during final validation:** BOOM timed out; digit recognition and VexRiscv failed simulation elaboration. These logs do not demonstrate behavioral mismatches.
- **Two existing failures still block search:** CoreScore and ISPD16 fail baseline DRC admission. Repair-oriented input admission remains unresolved.
- **Priorities:** repair validator elaboration and timeout handling; distinguish repairable inputs from publishable outputs; reduce costly neutral placement trials; then measure memory, beam diversity, and enabling moves with controlled comparisons.

**Speaker note:** A separate PACT run is now available, but it contains only console logs and is not a controlled ablation. Its five final-validation fallbacks are BOOM, LogicNets, digit recognition, spam filter, and VexRiscv. BOOM reports a timeout; the other four require the missing validator logs for diagnosis. Historical PASS labels do not establish the same validation standard. Even hypothetically accepting all three rejected Meemar search-best candidates would yield about 376.89 points, still below September 16, so validation repairs alone would not recover all previous performance.

Sources: [Meemar batch comparison](../experiments/meemar-20260923-comparison.md), [PACT batch comparison](../experiments/pact-20260923-comparison.md).
