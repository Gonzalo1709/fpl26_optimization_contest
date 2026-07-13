# Planner Prompt Optimization

Prompt optimization is an offline policy-improvement step. It does not replace
the deterministic recipe gates, generation search, checkpoint rollback, target
clock measurement, score ranking, or final validation.

## Reproducible workflow

1. Add sanitized examples from measured decisions to
   `prompt_eval_examples/planner_examples.jsonl`. Include the available action
   schema, expected strategy, and concise evidence; never include credentials or
   raw DCP data.
2. Evaluate `SYSTEM_PROMPT.TXT` with temperature zero and record the prompt
   hash, examples hash, model, and per-example results.
3. Run both `gepa-lite` and `dspy-gepa`. Evaluate their output with the same
   model and corpus.
4. Run a fixed full, non-test benchmark subset with the same search and cost
   controls. A candidate may be promoted only if it improves offline behavior
   and does not reduce projected score or validation quality on that subset.
5. Keep the shorter production prompt if timing is tied and the candidate only
   increases token cost.

```bash
export OPENROUTER_API_KEY=... # load from ignored .env; never commit it
python3 prompt_optimizer.py evaluate \
  --candidate SYSTEM_PROMPT.TXT \
  --output prompt-eval-baseline.json
python3 prompt_optimizer.py gepa-lite \
  --iterations 3 \
  --output-dir prompt-optimization-runs/gepa-lite
python3 prompt_optimizer.py dspy-gepa \
  --dspy-lm openrouter/openai/gpt-5 \
  --reflection-model openrouter/openai/gpt-5 \
  --auto light \
  --output optimized-system-prompt.txt
```

The optional DSPy environment is installed with
`pip install -r requirements-prompt-opt.txt`. On the contest Ubuntu image,
Python 3.10 user-site installation worked when `python3-venv` was unavailable:

```bash
python3 -m pip install --user dspy openai
```

## Current corpus and promotion rule

The seven-example corpus includes extreme-spread PBLOCK, shared-path FANOUT,
stagnation cleanup, a measured LogicNets PBLOCK rejection, the strong Vex
`RuntimeOptimized` incumbent, neutral Rosetta FANOUT followed by URAM analysis,
and validation-reserve `NO_OP`. The corpus hash is stored in every JSON result,
so changed evidence cannot be compared accidentally as if it were identical.

OpenRouter planner calls use `temperature=0`. Provider/model behavior can still
change, so the real Vivado A/B remains authoritative. Compare projected contest
score, not WNS alone, because a longer prompt can tie timing while costing more.
All generated prompt and JSON artifacts are written explicitly as UTF-8. This
is required on Windows: a CP1252 em dash in an otherwise valid prompt caused a
remote `UnicodeDecodeError` before a full candidate run could start.

## Runtime environment recovery

Use `make validate`, which first resolves the JRE bundled with Vivado. If
RapidWright still reports that Java or `libjvm.so` is unavailable and no
existing `JAVA_HOME` works, use the documented fallback:

```bash
sudo apt update
sudo apt install default-jre
java -version
make validate GOLDEN=golden.dcp REVISED=revised.dcp VECTORS=1000
```

Do not install system Java merely because `java` is absent from the initial
`PATH`; the Vivado-bundled JRE is preferred and worked on the public instance.
