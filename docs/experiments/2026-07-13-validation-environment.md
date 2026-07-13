# Validation Environment Smoke Test

- Date: 2026-07-13
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `0d7342b`
- Code under test: Task 1 working tree later committed with this record
- Instance: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- Benchmark: `vexriscv_re-place_2025.1.dcp`
- Comparison: benchmark DCP against itself
- OpenRouter calls/cost: 0 / $0.00

## Commands

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
export VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
python3 -m unittest tests.test_validation_environment -v
python3 validate_dcps.py \
  fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  --vectors 1000

make validate \
  GOLDEN=fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  REVISED=fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

## Results

| Entry point | Structural | Simulation | Runtime | Result |
| --- | --- | --- | ---: | --- |
| Direct Python | 4/4 | 1,000 vectors, 0 mismatches | 44.9 s | Pass |
| `make validate` | 4/4 | 1,000 vectors, 0 mismatches | 44.6 s | Pass |

Direct invocation resolved the Java runtime from the Vivado installation using
`VIVADO_EXEC`; `default-jre` was not installed. The Ubuntu fallback is recorded
in `docs/strategy/validation-environment.md` for instances where neither the
system nor bundled JRE is usable.

Remote reports were preserved at:

- `/home/ubuntu/fpl26_full/dcp_validation_4nln8qi0/validation_report.json`
- `/home/ubuntu/fpl26_full/dcp_validation_5yxzxqz7/validation_report.json`
