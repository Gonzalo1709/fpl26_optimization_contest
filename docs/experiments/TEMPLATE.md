# Experiment: `<benchmark> / <variant>`

## Provenance

- UTC timestamp:
- Branch:
- Commit SHA:
- Benchmark and input SHA256:
- Official instance/runtime:
- Prompt path and SHA256-16:
- Model:
- Budget profile:
- Forced strategy, if any:
- Generation search: branch factor / beam width / generations / steps:
- Runtime and cost limits:

## Reproduction

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
make run_optimizer DCP=/absolute/path/input.dcp RUN_CWD=/absolute/path/run
```

Validation command:

```bash
make validate \
  GOLDEN=/absolute/path/input.dcp \
  REVISED=/absolute/path/output.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

## Scorecard

| Metric | Baseline | Candidate | Delta/status |
| --- | ---: | ---: | --- |
| `clk_fpl26contest` period (ns) | | | |
| `clk_fpl26contest` WNS (ns) | | | |
| Fmax (MHz) | | | |
| Runtime (seconds) | n/a | | |
| OpenRouter cost (USD) | n/a | | |
| Projected contest score | n/a | | |
| Routed / DRC clean | | | |
| Hold / pulse-width | | | |
| Structural / simulation | | | |

## Decision

- Candidate action/recipe:
- Eligible gate evidence:
- Accepted or rejected:
- Reason:
- Best incumbent retained:
- Aggregate-suite implication:

## Artifacts

- Run directory:
- `token_usage.json`:
- Input DCP:
- Best output DCP:
- Vivado timing/route reports:
- Validation report:

## Follow-up

- Failure or unexpected behavior:
- Next controlled experiment:
