# Phys-opt portfolio policy

Vivado physical optimization is a set of independently measured portfolio
members, not a hidden multi-pass recipe. Each `PHYS_OPT` branch runs exactly one
mode, reports target-clock timing, and is saved by generation search as its own
candidate. A non-improving attempt reopens its baseline checkpoint immediately.

## Ordered modes and gates

| Order | Mode | Vivado arguments | Gate |
| ---: | --- | --- | --- |
| 1 | `RuntimeOptimized` | `-directive RuntimeOptimized` | Always eligible while transform budget remains. |
| 2 | `CriticalPin` | `-critical_pin_opt` | Prior measured gain, at least 5 minutes beyond validation reserve, and no known hold/pulse failure. |
| 3 | `PlacementRouting` | `-placement_opt -routing_opt` | Same as `CriticalPin`. |
| 4 | `Explore` | `-directive Explore` | Prior measured gain, at least 10 minutes beyond reserve, and no known hold/pulse failure. |
| 5 | `AggressiveExplore` | `-directive AggressiveExplore` | Prior measured gain, at least 15 minutes beyond reserve, and explicitly passing hold and pulse-width status. |

The planner receives only the modes that clear these gates. Sanitization and
forced branch diversity use the same allow-list. Invalid or premature escalation
falls back to `RuntimeOptimized`.

Task 8 will tighten `CriticalPin` with locked-pin evidence and add authoritative
route/hold/pulse collection. Until those fields are available,
`AggressiveExplore` remains disabled.

## Candidate and rollback contract

1. Save the current branch checkpoint as `phys_opt_baseline.dcp`.
2. Measure only `clk_fpl26contest` WNS/TNS/endpoints.
3. Run one mode.
4. Measure the same target-clock metrics.
5. If metrics improve, return the in-memory candidate so generation search can
   save and score it.
6. Otherwise reopen `phys_opt_baseline.dcp` and return the baseline report.

Generation search then compares projected contest score, target-clock metrics,
elapsed time, cost, and validation state. The phys-opt executor never writes the
final output path directly.

## Measurement and validation

- Record elapsed seconds and OpenRouter cost at each saved candidate.
- Do not infer hold or pulse-width success from setup WNS.
- A neutral attempt is a failed score experiment even when it is legal.
- Vivado-only phys-opt candidates require route status and target-clock timing
  before final promotion; the final output still receives the normal structural
  and simulation checks.
