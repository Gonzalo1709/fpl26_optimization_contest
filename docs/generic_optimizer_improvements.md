# Generic optimizer improvements

This earlier change set makes recipe selection depend on observable DCP evidence rather
than benchmark names or hard-coded design identities.  It does not add retiming
or other netlist-changing transforms: those require a separate equivalence and
legality proof before they are safe as generic actions.

## 1. Richer timing and topology classification

`DesignSignature` now includes two optional evidence records:

- `timing_anatomy`: the average logic and route portions of reported critical
  paths and a conservative route-dominated flag.
- `hard_block_topology`: the number of critical paths touching hard blocks,
  resource-boundary transitions, and same-family hard-block adjacencies.

Vivado timing anatomy is collected as an optional text report.  Parser failure
is represented as unavailable evidence, never guessed.  Hard-block relocation
is now gated on both spatial spread and an actual hard-block boundary in the
critical-path extraction.

## 2. Lane-local action memory

Action selection now receives the history of its own checkpoint lineage rather
than the global audit history.  Inert or failed actions are cooled down in that
lane.  For directive-based actions, only the exact inert directive is removed;
other directives remain eligible.  The global history remains intact for run
reporting.

## 3. Cost-aware global reimplementation

A global reimplementation is no longer automatic.  A conservative cost estimate
uses primitive-cell count plus congestion and route-delay evidence.  The action
is started only when it is placement-sensitive and enough time remains beyond
the validation reserve.  Measured reimplementation duration is retained for
future decisions in the run.

## 4. Independent candidate roots

The original routed DCP always becomes a `baseline` search root.  A successful
RQS/Explore reimplementation becomes a second root, rather than replacing the
baseline.  Branches restore their own root checkpoints sequentially through the
existing Vivado session, so the design does not require parallel Vivado licenses
or risk simultaneous writes to the submission output.

## 5. Topology-based hard-block gate

Presence of DSP, BRAM, or URAM cells alone no longer justifies relocation.  The
optimizer requires a target-clock path containing a resource boundary as well
as meaningful physical spread.  This avoids macro moves for designs where hard
blocks are present but are unrelated to the timing issue.

## Validation

`tests/test_generic_optimizer_policy.py` covers timing-anatomy parsing,
hard-block topology extraction, cost-aware reimplementation eligibility, and
directive-specific cooldown behavior.  Existing implementation, checkpoint,
route, hold, pulse-width, and DRC publish gates remain unchanged.

The later [adaptive optimizer upgrades](strategy/adaptive-optimizer-upgrades.md) add checkpoint admission, persistent outcomes, new bounded recipes and opt-in retiming. That document describes the current search and stopping behavior.
