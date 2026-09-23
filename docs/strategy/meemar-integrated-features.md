# Meemar-inspired changes implemented on test/meemar

Date: 2026-09-23. The working tree was already on `test/meemar`, separate from `test/pact`, and clean before these changes. This implements the main transfers from the [adoption proposal](meemar-adoption-proposal.md) on top of the PACT work. It is an adaptation, not a copy of Meemar's optimizer.

## Changes and justifications

| Change | Implementation | Why it was added |
|---|---|---|
| Startup fallback | Atomically copy and hash-check the input before MCP startup | Preserve an artifact even if server startup or initial analysis fails |
| Automatic deterministic mode | Missing API credentials select the existing no-LLM portfolio | Useful optimization should not require a working API key |
| Density search | New `DENSITY_REIMPLEMENTATION` action tries central clock-region rectangles at densities 0.50, 0.42, 0.58 | Explore a global fabric placement arrangement beyond our local critical-cell pblock |
| Resource feasibility | Count actual SLICE/SLICEM, DSP, RAMB/FIFO, and URAM sites by clock region | Avoid deriving a box from total SLICE area alone |
| Conditional reimplementation | Run the automatic independent reimplementation lane after opening work, only if no meaningful gain has been banked | Avoid immediately paying for a full replacement before cheaper opportunities are tried |
| Broader path rescue | New `PATH_CLUSTER_REPLACE` uses cells along critical paths after neutral cheap physical optimization | Internal path placement can matter even when moving terminal cells is insufficient |
| Explicit runtime telemetry | Client call events and server command events distinguish observed time, synchronization wait, execution, timeout, and cancellation | Prevent misleading per-call timing conclusions |
| Memory handling | Preserve uncertain outcomes for audit but exclude them from completed-runtime forecasts | A timed-out recipe's elapsed time is not its completed cost |

## 1. Startup and missing credentials

[preseed_output](../../src/meemar.py) copies the original to a temporary sibling, verifies its SHA-256, and atomically replaces the output. Input and output must be different paths. This happens before server startup in the CLI, including test and single-method entrypoints.

`<output>.startup.json` records the original input hash and explicitly marks validation as **unknown**. It is a historical startup snapshot, not the final output manifest. Normal final publication still uses `published_artifact.json` in the run directory.

This does not claim that an input DCP is legal. A broken input remains broken in this fallback. Startup and admission errors still fail the run. The existing strict baseline DRC admission rule has not been changed into a repair-mode policy.

Without credentials, ordinary CLI execution now sets the existing no-LLM mode, with zero planner calls. `--require-llm` restores failure on missing credentials. Combining it with `--no-llm` is rejected. The installed Python dependencies are still required; this change only removes the credential requirement for deterministic execution.

## 2. Resource-aware density reimplementation

The action is separate from `PBLOCK`, whose critical-cell behavior remains intact. `DENSITY_REIMPLEMENTATION` is eligible only on the admitted baseline, with affirmative implementation status, at most **50,000 primitives**, and at least **1,500 seconds beyond the validation reserve**. If measured recipe runtime is available, the gate also requires 1.2 times that runtime. These conservative limits are configuration fields, not Meemar's much larger benchmark-derived thresholds.

Each attempted density:

1. Restores the same immutable baseline.
2. Rejects existing pblocks and protected/location-fixed/BEL-fixed fabric targets.
3. Measures capacity and occupied sites per actual clock region and site type.
4. Enumerates central rectangular sets of clock regions with a complete coordinate grid. It prefers fewer regions, then taller regions, with deterministic tie-breaking.
5. Requires SLICE capacity at the requested density, separate capacity for each site type, and 20% headroom for hard resources. Combined BRAM/FIFO demand is also checked against conservative shared capacity.
6. Records the region, demand, capacity, seed hash, and exact target cells before mutation.
7. Creates its own pblock, unplaces the selected fabric cells, places, routes, and returns to normal admission.

The selected targets are the cells occupying SLICE, DSP, RAMB/FIFO, or URAM resources. This is a whole-fabric experiment; it does not deliberately unplace I/O or clock infrastructure. It preserves original timing constraints. Existing pblocks are never deleted to force eligibility.

Regions are deduplicated by seed hash and resolved range. Density variants have independent action cooldowns and memory entries. A dedicated pass considers them after the ordinary deterministic opening actions, with fresh budget and economic checks before each trial. They can also appear in the eligible action list. A successful density does not automatically suppress all remaining densities: remaining budget, cooldowns, measured forecasts, and explicit timing-closure stopping determine whether more run.

The geometry check uses measured capacities rather than a uniform SLICE grid. It is still a conservative heuristic, not a placement-feasibility proof: control sets, routing congestion, device restrictions, and macro packing remain the placer's responsibility. Placement failure rolls back, and publication still requires implementation admission plus the PACT functional gate. Device geometry is remeasured rather than cached in this first implementation.

Code: [density selection and executor](../../src/meemar.py), [eligibility and search integration](../../src/controller.py), [cooldowns](../../src/policy.py), [planner normalization and dispatch](../../src/llm_optimizer.py).

## 3. Rescue scheduling and broader critical-path edits

With Meemar rescue scheduling enabled, the automatic original-input reimplementation lane runs after deterministic actions and density trials. It runs only if the incumbent's WNS has not improved over baseline by more than the configured `min_wns_delta`. Existing runtime and economic gates still apply. This is a conservative scheduling heuristic, not an assertion that any small gain means the design is near its optimum. Existing full-placement recipes remain separately available under their original eligibility rules.

`PATH_CLUSTER_REPLACE` is offered when:

- targeted actions and Meemar rescue are enabled;
- at least three measured paths have mean spread ≥30;
- at least 900 seconds remain beyond the reserve; and
- a completed cheap physical action on that seed was neutral or regressive, with no meaningful gain from the recorded cheap actions.

It collects cells directly from the top 50 target-clock timing paths. Only movable LUT/FD cells qualify: default scope **80 cells**, hard limit **160**. Other placed primitives are temporarily fixed, their original location/BEL lock flags are restored, and the design is rerouted. The existing exact-target evidence and checkpoint rollback machinery are reused. It is broader than the PACT terminal-cell action, but is not a general macro/CARRY/MUX restructuring operation.

The action can enter the existing enabling pool if its measured physical improvement satisfies that pool's rules. No second enabling pool or independent ancestor-polish loop was introduced.

Code: [target extraction and lock restoration](../../src/pact_actions.py), [pool integration](../../src/pact_search.py), [rescue predicate](../../src/meemar.py).

## 4. Timeout and cost attribution

`tool_timeline.jsonl` records a client call ID, start time, tool name, requested timeout when supplied, observed duration, completion state, and session uncertainty. Client totals may include transport and nested measurement work; they are not labeled as pure Vivado execution time.

The Vivado server emits `FPL26_COMMAND_EVENT` JSON records into its log with a server command ID, start time, effective timeout, synchronization wait, execution duration, observed duration, completion state, and pending-command status. Server command IDs and client call IDs are distinct; one client tool call may execute several Tcl commands. Correlation uses their timestamps and operation context rather than assuming a one-to-one mapping.

An execution duration on a timeout is an observed prefix, not the eventual completion cost. A command that returned to the Tcl prompt is recorded as completed even if its output contains a Tcl error; the client still evaluates the output for errors. Cancellation makes the client session unusable, just as a detected timeout does. MCP error text is preserved so timeout detection can see it.

Recipe records retain total wall-clock cost, context about the incumbent and seed, and an uncertainty flag. SQLite retains uncertain records for audit; forecasting excludes them. No duration-based rule guesses that a 300-second call timed out.

To inspect explicit server events later:

```powershell
python tools/meemar_timeline.py path/to/vivado-mcp.log
```

The reader reports missing evidence for historical logs without explicit events; it does not retroactively invent execution/synchronization splits.

Code: [server instrumentation](../../VivadoMCP/vivado_mcp_server.py), [client instrumentation](../../src/llm_optimizer.py), [memory forecast filter](../../src/outcome_memory.py), [timeline reader](../../tools/meemar_timeline.py).

## 5. Controls and boundaries

- `--no-density-search`: disable the density action and its dedicated trial pass.
- `--no-meemar-rescue`: disable the new path-cluster rescue and restore the earlier automatic reimplementation order.
- `--require-llm`: fail when credentials are absent.
- `--single-method DENSITY_REIMPLEMENTATION`: attempt the default density once, subject to normal eligibility and validation.
- `--no-targeted-actions`: also disables the broader path-cluster action.

`GenerationSearchConfig` holds the density size/runtime limits. The PACT validation reserve and strict final publication remain unchanged.

No benchmark fingerprints, literal benchmark placement boxes, permissive legality checks, semantic rewrites, retiming shortcuts, automatic model switching, or independent ancestor-polish loop were added. The optional model-fallback chain and ancestor polishing from the proposal remain future work. Persistent outcome memory and the existing cost-aware formula are retained.

## 6. Verification and remaining evidence

Static Python syntax parsing and patch whitespace checks were performed. [Offline regressions](../../tests/test_meemar.py) were added for capacity selection, infeasible census rejection, density cooldowns, byte-identical startup fallback, rescue conditions, and explicit timeline parsing. They were **not executed**. No Vivado, RapidWright, simulation, or optimization workload was run.

The Tcl relationship queries and clock-region pblock syntax were checked against AMD documentation: [get_cells](https://docs.amd.com/r/2022.1-English/ug835-vivado-tcl-commands/get_cells), [resize_pblock](https://docs.amd.com/r/JXswcrCHJROaHTz43h5g2Q/FW3hgWm5cHHoonLgmVwfiA). Installed-version compatibility, routing outcomes, end-to-end cancellation, and score improvement still require testing in the FPGA environment.

The next comparison should use identical inputs, tool/thread settings, runtime limits, and final-validation settings, and alternate run order. Compare delivered score/Fmax, validated completion rate, fallback reasons, total runtime, and incremental gain over the incumbent. Ablate density search and rescue scheduling independently before attributing gains to either.
