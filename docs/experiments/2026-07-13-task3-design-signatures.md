# Experiment: Task 3 representative design signatures

## Provenance

- UTC date: 2026-07-13
- Branch: `feat/score-aware-optimizer-portfolio`
- Base commit: `6a22f80`; Task 3 working tree was deployed on top
- Runtime: official FPL'26 Ubuntu 22.04 / Vivado 2025.1 instance
- OpenRouter calls/cost: 0 / $0.00
- Output root: `/home/ubuntu/fpl26_full/experiments/task3-signatures`

## Reproduction

```bash
source /tools/Xilinx/2025.1/Vivado/settings64.sh
export VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
python3 collect_design_signatures.py \
  --output-root experiments/task3-signatures \
  fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  fpl26_contest_benchmarks/logicnets_jscl_2025.1.dcp \
  fpl26_contest_benchmarks/rosetta_digit-recognition_2025.1.dcp \
  fpl26_contest_benchmarks/corescore_500_mod_2025.1.dcp
```

## Results

| Benchmark | Period | WNS | Fmax | Avg/max spread | Fanout candidates | Critical hard block | Congestion | Analysis |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| VexRiscv | 1.570 ns | -1.654 ns | 310.174 MHz | 53.50 / 93 tiles | 0 | BRAM | level 5, severe | 20.72 s |
| LogicNets | 1.500 ns | -0.978 ns | 403.551 MHz | 111.86 / 198 tiles | 24 | none | level 5, severe | 29.87 s |
| Rosetta digit | 1.700 ns | -1.025 ns | 366.972 MHz | 131.38 / 283 tiles | 9 | URAM | unavailable | 31.32 s |
| CoreScore 500 | 1.667 ns | -1.238 ns | 344.234 MHz | 232.36 / 448 tiles | 0 | BRAM | level 5, severe | 78.10 s |

All timing fields were measured only on `clk_fpl26contest`. The optional
congestion report was unavailable for Rosetta digit recognition; the signature
recorded that field under `unavailable` and retained the remaining evidence.

## Policy implications

- VexRiscv's average spread does not clear the existing strong PBLOCK threshold,
  matching the two measured PBLOCK regressions.
- LogicNets has both strong spread and multiple shared critical fanout candidates;
  Task 4 should expose PBLOCK and FANOUT while allowing score-aware branching.
- Rosetta digit recognition has a 1,172-fanout critical net and URAM incidence;
  FANOUT should precede hard-block relocation, with PBLOCK as another eligible
  branch rather than an unconditional choice.
- CoreScore has extreme spread but no high-fanout candidate; PBLOCK and PHYS_OPT
  are plausible while FANOUT must be gated out.
