# Critical-Pin and Preserved-Reroute Recipes

These are low-cost Vivado-only recipes. Both use the existing generation
checkpoint/rollback machinery and are measured only on `clk_fpl26contest`.

## Critical-pin optimization

`CRITICAL_PIN` exposes exactly `phys_opt_design -critical_pin_opt`; the planner
cannot add other Tcl options. It is eligible when the target clock has negative
setup slack and at least two minutes remain beyond the ten-minute validation
reserve. The executor saves the parent checkpoint and target-clock timing,
runs the pin swap pass, and immediately restores the parent when WNS/TNS/failing
endpoints do not improve.

AMD documents `-critical_pin_opt` as pin-swapping optimization on timing-critical
nets. Supplying a specific `phys_opt_design` option disables unrelated default
optimizations, which keeps this ablation attributable:

- <https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/phys_opt_design>

## Bounded route preservation

`ROUTE_PRESERVE` is eligible only when all of the following hold:

- `clk_fpl26contest` has negative setup slack;
- the deterministic design signature reports severe congestion (`max_level >= 5`);
- at least four minutes remain beyond the validation reserve.

Vivado extracts up to 20 target-clock paths and ranks their reported net rows by
incremental net delay, then shared critical-path count. A candidate must have at
least 0.20 ns net delay, occur on a sampled target-clock path, and have
`IS_ROUTE_FIXED == 0`. The controller selects at most four nets. Both the
controller and MCP boundary enforce an absolute limit of eight and reject Tcl
metacharacters.

The MCP interface permits only this sequence:

```tcl
route_design -nets [get_nets <bounded-explicit-list>] -auto_delay
route_design -preserve
```

It performs a second fixed-route preflight immediately before execution. A
directive cannot be combined with selected-net arguments, `-auto_delay` cannot
run without an explicit list, and the selected-net and preserve phases are
separate calls. This follows AMD's documented iterative-routing pattern:

- <https://docs.amd.com/r/2025.1-English/ug904-vivado-implementation/Routing-Example-Script-3>

The branch is promoted only if target-clock timing improves; otherwise the
saved parent checkpoint is reopened. Route/DRC, hold, pulse-width, structural,
and simulation checks remain mandatory before a projected score is called
validated.
