# Optimizer Experiment Records

Every official-instance optimizer or validation run gets one Markdown record in
this directory. Copy `TEMPLATE.md`, use a UTC timestamp plus benchmark in the
filename, and fill results from `token_usage.json`, Vivado reports, and
`validation_report.json`. Do not infer missing checks: record them as unknown.

The projected per-benchmark score is:

```text
delta_fmax_mhz * (1 - 0.1 * llm_cost_usd - 0.1 * runtime_hours)
```

It is clamped at zero. Fmax must be computed only from `clk_fpl26contest` as
`1000 / (period_ns - wns_ns)`. A projected score is not a validated score until
routing, DRC, hold, pulse-width, structural, and required simulation checks have
all passed.

## Promotion rule

Promote a recipe, policy, search setting, or prompt only when a fixed benchmark
subset shows a non-regressing aggregate validated score under identical budget
controls. Preserve the previous legal incumbent and record negative or skipped
experiments because they are evidence for later gates.

Generated DCPs, logs, token reports, benchmark archives, and credentials stay
outside Git. Records may point to their remote or safely downloaded locations.
