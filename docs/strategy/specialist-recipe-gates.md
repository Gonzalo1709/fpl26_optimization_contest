# Specialist Recipe Gates

Specialist recipes are opt-in branches behind deterministic evidence and budget
checks. The planner receives only the actions that pass this table. Every branch
starts from the existing generation checkpoint and restores it on a neutral or
negative target-clock result.

| Recipe | Eligibility evidence | Runtime reserve | Promotion check | Required validation |
| --- | --- | ---: | --- | --- |
| PBLOCK | At least 5 sampled target-clock paths, avg spread >=120, and max spread >=150 tiles | 180 s beyond validation reserve | Higher score after place/route; reject any WNS/TNS/endpoint regression | Fully placed/routed, DRC, hold, pulse width, structural; simulation for final candidate |
| Hard-block relocation | DSP/BRAM/URAM occurs on sampled target-clock paths and avg spread >=80 | 300 s beyond validation reserve | RapidWright legal local candidate, Vivado open/unplaced/route sanity, then higher score after reroute | Fully placed/routed, DRC, hold, pulse width, structural and 1,000-vector simulation |
| LUT cone merge | Disabled: no proven bounded cone-selection and equivalence gate | n/a | n/a | Would require structural and functional equivalence before eligibility |
| Register retiming | Disabled: changes sequential boundaries and has no state-correspondence proof | n/a | n/a | Would require sequential/formal equivalence plus simulation before eligibility |
| Congestion-aware spreading | No independent global action; severe congestion may corroborate bounded route-preserve evidence but does not admit PBLOCK by itself | n/a | Existing branch rollback | Same as the underlying recipe |

## Evidence from public benchmarks

- LogicNets had max/average spread 198/111.86 tiles but no congestion report.
  The older broad PBLOCK gate admitted it and WNS regressed from -0.978 to
  -2.164 ns before rollback. The tightened gate now skips this case.
- A later full run collected severe congestion for the same LogicNets shape and
  again spent 249.78 s on a non-improving PBLOCK branch. Severe congestion is
  therefore insufficient below the 120-tile average-spread floor.
- Rosetta digit recognition has max/average spread 283/131.38 tiles and URAM on
  sampled target-clock paths. PBLOCK and hard-block analysis remain eligible
  when runtime permits, but a candidate is retained only after legal-local and
  Vivado checks.
- VexRiscv has moderate spread (93/53.5) and severe congestion level 5. It does
  not meet the PBLOCK or hard-block locality floor; bounded route or cell
  relocation may still be considered and must beat the strong
  `RuntimeOptimized` incumbent.

Skipped specialist cases are successful gate behavior, not failed optimizer
runs. They preserve runtime for the default physical-optimization portfolio and
final validation.
