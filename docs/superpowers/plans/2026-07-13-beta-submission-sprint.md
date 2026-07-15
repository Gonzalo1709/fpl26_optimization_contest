# Beta Submission Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize benchmark-general validated contest score, then prove that the exact beta archive installs and runs through the organizer's `make setup` and repeated `make run_optimizer DCP=...` contract.

**Architecture:** Freeze the current score-aware optimizer as the control, screen the complete public benchmark suite with one fixed non-test profile, and permit policy or search changes only when cross-design evidence supports them. Preserve the existing recipe gates, generation-search checkpoints, score-aware promotion, and final legality/equivalence validation; finish with a clean submission rehearsal.

**Tech Stack:** Python 3.10+, `unittest`, Vivado 2025.1 Tcl, RapidWright/Java, OpenRouter, Make, Bash, Git/GitHub.

## Global Constraints

- Work on `feat/score-aware-optimizer-portfolio`; use conventional commits and push every verified milestone.
- Read `docs/experiments/2026-07-13-task10-prompt-optimization.md` and `docs/handoffs/beta-overnight-goal.md` before running experiments.
- Preserve the currently implemented PBLOCK, FANOUT, CELL_RELOCATION, PHYS_OPT, HARD_BLOCK, CRITICAL_PIN, ROUTE_PRESERVE, recipe gates, prompt contract, checkpoint rollback, and generation-search branching system.
- Never use `--test` as optimization or submission evidence.
- Measure only `clk_fpl26contest`; compute `Fmax = 1000 / (period_ns - wns_ns)` and score with the cost/runtime penalty in `src/scoring.py`.
- Do not promote an optimization on projected score alone. Positive finalists require route, error-level DRC, hold, pulse-width, structural, and 1,000-vector simulation checks.
- Keep `.env`, credentials, DCPs, archives, logs, `token_usage.json`, and generated experiment directories out of Git.
- Do not repeat rejected PBLOCK, HARD_BLOCK, GEPA-lite, or DSPy experiments without a new measured design signature or hypothesis.
- Reserve the last four instance-hours for regression tests, validation, archive construction, and clean extraction testing.
- Stop a speculative recipe after two non-improving real designs, and revert a code experiment immediately when the fixed comparison regresses aggregate validated score.

---

## Read Order and Operating Procedure

1. Read `docs/beta_submission.md` for the evaluator contract.
2. Read `docs/experiments/2026-07-13-task10-prompt-optimization.md` for the production control and rejected prompt candidates.
3. Read `docs/experiments/README.md` for score and promotion rules.
4. Execute Tasks 1-6 in order. Task 4 is conditional on the evidence gate written in that task.
5. After every remote run, add or update a record under `docs/experiments/` before starting a code change.
6. Keep the morning status table in `docs/handoffs/beta-overnight-goal.md` current.

### Task 1: Freeze and verify the production control

**Files:**
- Read: `src/scoring.py`
- Read: `src/policy.py`
- Read: `src/search.py`
- Read: `src/llm_optimizer.py`
- Read: `docs/experiments/2026-07-13-task10-prompt-optimization.md`
- Modify only if a test fails: the source file responsible for that failure

**Interfaces:**
- Consumes: branch `feat/score-aware-optimizer-portfolio` and production prompt hash `ee3acce412f63417`.
- Produces: a clean local test baseline and a recorded official-instance preflight.

- [ ] **Step 1: Confirm repository scope and branch without discarding changes**

Run locally:

```powershell
git status --short --branch
git branch --show-current
git submodule status
```

Expected: the current branch is `feat/score-aware-optimizer-portfolio`. If the tree is dirty, inspect and preserve unrelated user changes; do not reset them.

- [ ] **Step 2: Run the complete local test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass. Apply only a narrow root-cause fix if a regression exists, rerun the failing test, then rerun the suite.

- [ ] **Step 3: Verify the official instance and runtime**

Run locally:

```powershell
.\fpl26contest status
```

If stopped, run `.\fpl26contest start`, wait for readiness, then use `.\fpl26contest ssh`. On the instance run:

```bash
cd /home/ubuntu/fpl26_full
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
python3 --version
java -version
/tools/Xilinx/2025.1/Vivado/bin/vivado -version | head -n 1
make setup VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

Expected: Python, Java/RapidWright, Vivado, and setup succeed. If Java discovery fails after checking Vivado's bundled JRE, follow `docs/strategy/validation-environment.md` and use `sudo apt install default-jre` only on the disposable contest instance.

- [ ] **Step 4: Commit only if Task 1 required a source fix**

```powershell
git add tests src
git commit -m "fix: restore beta optimizer regression baseline"
git push origin feat/score-aware-optimizer-portfolio
```

Expected: no commit is created when no source change was necessary.

### Task 2: Screen every uncharacterized public benchmark

**Files:**
- Create: `docs/experiments/2026-07-13-beta-public-suite.md`
- Use template: `docs/experiments/TEMPLATE.md`
- Read generated remote files: `experiments/beta-screen/*/dcp_optimizer_run-*/token_usage.json`

**Interfaces:**
- Consumes: the unchanged production policy and prompt from Task 1.
- Produces: one comparable row for each of the nine remaining public benchmarks and validation evidence for every positive incumbent.

- [ ] **Step 1: Create the suite record before starting runs**

Create `docs/experiments/2026-07-13-beta-public-suite.md` with this table and fill cells immediately after each run:

```markdown
| Benchmark | Signature | Action | Initial WNS | Final WNS | Delta Fmax | Runtime | LLM cost | Projected score | Validation | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| amd_mini-isp | | | | | | | | | pending | pending |
| boom_soc | | | | | | | | | pending | pending |
| corescore_500_mod | | | | | | | | | pending | pending |
| finn_radioml | | | | | | | | | pending | pending |
| ispd16_example2 | | | | | | | | | pending | pending |
| rosetta_3d-rendering | | | | | | | | | pending | pending |
| rosetta_optical-flow | | | | | | | | | pending | pending |
| rosetta_spam-filter | | | | | | | | | pending | pending |
| vtr_mcml | | | | | | | | | pending | pending |
```

- [ ] **Step 2: Run the fixed production profile sequentially**

On the official instance:

```bash
cd /home/ubuntu/fpl26_full
source /tools/Xilinx/2025.1/Vivado/settings64.sh
set -a
source .env
set +a
mkdir -p experiments/beta-screen
for dcp in \
  amd_mini-isp_2025.1.dcp \
  boom_soc_2025.1.dcp \
  corescore_500_mod_2025.1.dcp \
  finn_radioml_2025.1.dcp \
  ispd16_example2_2025.1.dcp \
  rosetta_3d-rendering_2025.1.dcp \
  rosetta_optical-flow_2025.1.dcp \
  rosetta_spam-filter_2025.1.dcp \
  vtr_mcml_2025.1.dcp
do
  slug="${dcp%_2025.1.dcp}"
  mkdir -p "experiments/beta-screen/$slug"
  make run_optimizer \
    DCP="$PWD/fpl26_contest_benchmarks/$dcp" \
    RUN_CWD="$PWD/experiments/beta-screen/$slug" \
    VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado \
    OPT_ARGS="--system-prompt $PWD/SYSTEM_PROMPT.TXT --budget-profile fast --branches 1 --beam-width 1 --generations 2 --steps-per-branch 1 --max-runtime-minutes 30 --max-cost 0.10"
done
```

Expected: nine full non-test runs complete or leave an explicit failure record. A failure does not silently remove a row from the suite table.

- [ ] **Step 3: Record provenance and scores**

For each run, copy these values from `token_usage.json` and Vivado output into the suite record: design signature, selected action/arguments, initial/final WNS, delta Fmax, elapsed seconds, OpenRouter cost, projected score, prompt hash, commit SHA, and output DCP path.

Expected: every table row contains numeric evidence or `failed:` followed by the root cause copied from the terminal or run log. Do not convert missing validation into zero; record it as `pending` or `unknown`.

- [ ] **Step 4: Validate every positive incumbent immediately**

For each row with projected score greater than zero, select and print the newest output for that benchmark, verify it matches the just-completed run timestamp, then validate it:

```bash
REVISED="$(find /home/ubuntu/fpl26_full/fpl26_contest_benchmarks -maxdepth 1 \
  -name 'amd_mini-isp_2025.1_optimized-*.dcp' -printf '%T@ %p\n' \
  | sort -n | tail -n 1 | cut -d' ' -f2-)"
printf 'Validating %s\n' "$REVISED"
make validate \
  GOLDEN=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/amd_mini-isp_2025.1.dcp \
  REVISED="$REVISED" \
  VECTORS=1000 \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

Change both occurrences of `amd_mini-isp` together for the other eight rows. Before validation, compare the printed path with the optimizer's output line so an older DCP cannot be validated accidentally. Then run `scripts/check_dcp_legality.tcl` through Vivado as documented by the final Task 10 experiment.

Expected: structural 4/4, 1,000 vectors with zero mismatches, all routable nets routed, zero route errors, zero error-level DRCs, nonnegative hold slack, and no pulse-width violators. A failed gate makes validated score zero and the candidate must not be promoted.

- [ ] **Step 5: Commit and push the suite evidence**

```powershell
git add docs/experiments/2026-07-13-beta-public-suite.md
git commit -m "docs: record beta public suite screening"
git push origin feat/score-aware-optimizer-portfolio
```

### Task 3: Derive cross-design recipe priors from measured evidence

**Files:**
- Modify: `src/policy.py`
- Modify: `src/llm_optimizer.py`
- Modify: `SYSTEM_PROMPT.TXT` only if deterministic gates cannot express the evidence
- Modify: `tests/test_policy.py`
- Modify: `tests/test_recipe_gates.py`
- Modify: `docs/experiments/2026-07-13-beta-public-suite.md`

**Interfaces:**
- Consumes: complete Task 2 matrix plus existing Vex, LogicNets, and Rosetta results.
- Produces: benchmark-name-independent action ordering or gates backed by at least two real designs, with unchanged rollback behavior.

- [ ] **Step 1: Classify outcomes without benchmark names**

Group rows by signature features: average/max critical-path spread, critical high-fanout count and net delay, congestion evidence, hard-block incidence, baseline WNS, and runtime. Add a `Cross-design findings` section that states which feature/action combinations improved, regressed, or remained neutral.

Expected: every proposed policy change cites at least two real designs or one positive result plus one protected regression. If the evidence does not clear that threshold, make no policy change.

- [ ] **Step 2: Write a failing gate or ordering test for each supported change**

Use the existing `DesignSignature` fixtures. A supported deterministic-prior test should follow this shape:

```python
def test_runtime_optimized_precedes_risky_recipes_for_local_ambiguous_signature(self):
    actions = gate_actions(local_ambiguous_signature, fast_budget, history=[])
    names = [action.strategy for action in actions]
    self.assertIn("PHYS_OPT", names)
    self.assertLess(names.index("PHYS_OPT"), names.index("CELL_RELOCATION"))
```

Run:

```powershell
python -m unittest tests.test_policy tests.test_recipe_gates -v
```

Expected before implementation: the new evidence-specific assertion fails.

- [ ] **Step 3: Implement the smallest signature-based policy change**

Keep public interfaces stable:

```python
def gate_actions(
    signature: DesignSignature,
    budget: RecipeBudget,
    history: Iterable[Mapping[str, object]],
) -> list[EligibleAction]:
    ...
```

Do not branch on filenames or benchmark names. Do not loosen the tightened PBLOCK or HARD_BLOCK thresholds without new positive validation evidence.

- [ ] **Step 4: Verify locally and run fixed remote A/Bs**

Run locally:

```powershell
python -m unittest discover -s tests -v
```

Then rerun the changed policy on the smallest fixed subset containing every signature class affected by the change. Use exactly the Task 2 model, prompt, search controls, runtime cap, and cost cap.

Expected: aggregate validated score does not regress; runtime or LLM cost must not increase without a larger Fmax gain.

- [ ] **Step 5: Commit only a promoted policy**

```powershell
git add src/policy.py src/llm_optimizer.py SYSTEM_PROMPT.TXT tests docs/experiments/2026-07-13-beta-public-suite.md
git commit -m "feat: order recipes by measured design signatures"
git push origin feat/score-aware-optimizer-portfolio
```

If the A/B regresses, restore only the experimental edits, record the rejection, and commit the documentation as `docs: reject beta recipe prior experiment`.

### Task 4: Add bounded repeated physical evaluation only when justified

**Evidence gate:** Execute this task only if Task 2 or a fixed rerun shows the same action on the same input varies by at least 1.0 MHz delta Fmax and at least eight instance-hours remain. Otherwise check this task as `skipped: insufficient variance or budget` in the handoff.

**Files:**
- Modify: `src/search.py`
- Modify: `src/llm_optimizer.py`
- Modify: `dcp_optimizer.py`
- Create: `tests/test_action_repeats.py`
- Modify: `docs/experiments/2026-07-13-beta-public-suite.md`

**Interfaces:**
- Consumes: `GenerationSearchConfig`, parent checkpoint restore, `_candidate_sort_key()`, and the existing per-action executor.
- Produces: `GenerationSearchConfig.action_repeats: int = 1` and CLI `--action-repeats {1,2,3}`; repeated trials start from the same parent and only the best legal candidate is retained.

- [ ] **Step 1: Write failing configuration and selection tests**

```python
def test_action_repeats_defaults_to_one(self):
    self.assertEqual(GenerationSearchConfig().action_repeats, 1)

def test_repeat_selection_keeps_highest_score_candidate(self):
    candidates = [candidate(projected_score=4.0), candidate(projected_score=7.0)]
    self.assertEqual(select_best_repeat(candidates).projected_score, 7.0)
```

Run:

```powershell
python -m unittest tests.test_action_repeats -v
```

Expected: failure because `action_repeats` and `select_best_repeat` do not exist.

- [ ] **Step 2: Add the bounded interface**

Add to `src/search.py`:

```python
@dataclass
class GenerationSearchConfig:
    action_repeats: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.action_repeats <= 3:
            raise ValueError("action_repeats must be between 1 and 3")


def select_best_repeat(candidates: Sequence[SearchCandidate]) -> SearchCandidate:
    if not candidates:
        raise ValueError("at least one repeated candidate is required")
    return max(candidates, key=candidate_sort_key)
```

If `_candidate_sort_key()` must remain owned by `DCPOptimizer`, implement `select_best_repeat()` as an optimizer method using that exact existing key rather than duplicating ranking logic.

- [ ] **Step 3: Restore the same parent before every repeat**

In the generation branch, evaluate an already selected `(strategy, args)` up to `action_repeats` times. Before each attempt call `_restore_candidate_state(parent)`, save a distinct checkpoint/candidate ID, and charge all elapsed time and OpenRouter cost to the candidate. Do not repeat PBLOCK or HARD_BLOCK; initially allow repeats only for FANOUT and PHYS_OPT.

- [ ] **Step 4: Expose the CLI with a conservative default**

Add:

```python
parser.add_argument(
    "--action-repeats",
    type=int,
    choices=[1, 2, 3],
    default=1,
    help="Repeat eligible FANOUT/PHYS_OPT actions from the same parent (default: 1)",
)
```

Pass it into `GenerationSearchConfig`. The submission default remains one until a fixed A/B proves that two repeats improve aggregate score after runtime penalty.

- [ ] **Step 5: Verify and promote only after fixed real A/Bs**

Run:

```powershell
python -m unittest discover -s tests -v
```

On the official instance, compare `--action-repeats 1` and `--action-repeats 2` on LogicNets plus every Task 2 benchmark where FANOUT or PHYS_OPT was positive. All other controls must match Task 2.

Expected: promote repeat two only if aggregate validated contest score improves after runtime penalty. Otherwise leave the default at one and record the rejection.

- [ ] **Step 6: Commit the measured outcome**

Promoted implementation:

```powershell
git add dcp_optimizer.py src/search.py src/llm_optimizer.py tests/test_action_repeats.py docs/experiments/2026-07-13-beta-public-suite.md
git commit -m "feat: add bounded physical action repeats"
git push origin feat/score-aware-optimizer-portfolio
```

Rejected implementation: revert the source/test experiment, retain its measured documentation, and commit `docs: reject repeated physical evaluation`.

### Task 5: Make zero-score and validation state unambiguous

**Files:**
- Modify: `src/scoring.py`
- Modify: `src/llm_optimizer.py`
- Modify: `tests/test_scoring.py`
- Modify: `docs/experiments/README.md`

**Interfaces:**
- Consumes: `ContestScoreInput` and `ContestScore`.
- Produces: `score_status` with one of `positive`, `no_fmax_gain`, `negative_gain_clamped`, `validation_pending`, or `validation_failed` in `token_usage.json`.

- [ ] **Step 1: Write failing reason tests**

```python
def test_zero_delta_reports_no_fmax_gain(self):
    result = calculate_contest_score(score_input(delta_fmax_mhz=0.0))
    self.assertEqual(result.score_status, "no_fmax_gain")

def test_incomplete_validation_reports_pending(self):
    result = calculate_contest_score(score_input(delta_fmax_mhz=10.0))
    self.assertEqual(result.score_status, "validation_pending")
```

Add corresponding tests for negative clamping, validation failure, and positive validated score.

- [ ] **Step 2: Implement one pure status classifier**

```python
def classify_score_status(
    delta_fmax_mhz: float,
    projected_score: float,
    validation: ValidationStatus,
) -> str:
    if validation.complete and not validation.passed:
        return "validation_failed"
    if delta_fmax_mhz < 0:
        return "negative_gain_clamped"
    if delta_fmax_mhz == 0:
        return "no_fmax_gain"
    if not validation.complete:
        return "validation_pending"
    return "positive"
```

Serialize the value without changing the score formula or promotion ordering.

- [ ] **Step 3: Verify and commit**

```powershell
python -m unittest tests.test_scoring -v
python -m unittest discover -s tests -v
git add src/scoring.py src/llm_optimizer.py tests/test_scoring.py docs/experiments/README.md
git commit -m "feat: explain optimizer score status"
git push origin feat/score-aware-optimizer-portfolio
```

### Task 6: Rehearse the exact beta evaluator contract

**Files:**
- Modify if required: `Makefile`
- Modify if required: `requirements.txt`
- Create: `docs/experiments/2026-07-13-beta-submission-rehearsal.md`
- Create outside Git: `/home/ubuntu/fpl26_beta_submission.zip`

**Interfaces:**
- Consumes: final pushed branch, initialized RapidWright submodule, ignored local credentials.
- Produces: an archive under 4 GiB whose extracted root is `fpl26_optimization_contest` and passes setup plus one full non-test optimization.

- [ ] **Step 1: Freeze the final candidate**

Run locally and remotely:

```bash
git status --short --branch
git log -1 --oneline
git submodule status
python3 -m unittest discover -s tests -v
```

Expected: intended source/docs are committed, tests pass, and RapidWright points to a known commit. Do not package `.env` or generated artifacts.

- [ ] **Step 2: Build a clean archive from a disposable copy**

On the official instance:

```bash
cd /home/ubuntu
rm -rf /tmp/fpl26_beta_package
mkdir -p /tmp/fpl26_beta_package
git clone --recurse-submodules /home/ubuntu/fpl26_full /tmp/fpl26_beta_package/fpl26_optimization_contest
cd /tmp/fpl26_beta_package/fpl26_optimization_contest
git checkout feat/score-aware-optimizer-portfolio
git submodule update --init --recursive
rm -rf .git RapidWright/.git fpl26_contest_benchmarks experiments batch_logs branching_sweep_logs
rm -f .env fpl26contest key *.dcp *.log *.jou *.tar.gz token_usage.json
cd /tmp/fpl26_beta_package
zip -qr /home/ubuntu/fpl26_beta_submission.zip fpl26_optimization_contest
stat -c '%n %s bytes' /home/ubuntu/fpl26_beta_submission.zip
```

Expected: archive size is less than `4294967296` bytes and inspection with `unzip -l` shows no `.env`, key, DCP, log, or generated experiment artifact.

- [ ] **Step 3: Extract and execute exactly like the evaluator**

```bash
rm -rf /tmp/fpl26_beta_verify
mkdir -p /tmp/fpl26_beta_verify
cd /tmp/fpl26_beta_verify
unzip -q /home/ubuntu/fpl26_beta_submission.zip
cd fpl26_optimization_contest
source /tools/Xilinx/2025.1/Vivado/settings64.sh
export OPENROUTER_API_KEY="$(sed -n 's/^OPENROUTER_API_KEY=//p' /home/ubuntu/fpl26_full/.env | tail -n 1)"
make setup VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
make run_optimizer \
  DCP=/home/ubuntu/fpl26_full/fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp \
  VIVADO_EXEC=/tools/Xilinx/2025.1/Vivado/bin/vivado
```

Expected: setup succeeds from the extracted archive and the default, non-test optimizer produces an optimized DCP without relying on files omitted from the archive.

- [ ] **Step 4: Validate the rehearsal output and record provenance**

Run `make validate` with VexRiscv as golden and the exact newly printed output as revised, using 1,000 vectors, followed by the legality Tcl checker.

Record archive SHA256, byte size, branch commit, RapidWright commit, setup duration, optimizer duration/cost, output score, and all validation gates in `docs/experiments/2026-07-13-beta-submission-rehearsal.md`.

- [ ] **Step 5: Fix only verified packaging/runtime blockers**

If the clean rehearsal fails, diagnose the root cause, add a regression test where practical, make the smallest fix, rerun Tasks 6.2-6.4, and commit with a scoped conventional message such as:

```powershell
git commit -m "fix: make beta archive self-contained"
```

- [ ] **Step 6: Push and complete the morning handoff**

```powershell
git push origin feat/score-aware-optimizer-portfolio
```

Update `docs/handoffs/beta-overnight-goal.md` with the final commit, complete benchmark matrix, accepted and rejected changes, validated aggregate score, archive hash/size/path, exact remaining blocker, and next command.

## Definition of Done

- All twelve public benchmarks have an explicit production-policy result: the existing Vex, LogicNets, and Rosetta digit records plus nine Task 2 rows.
- Every claimed positive score has complete legality and equivalence evidence; pending validation is never called validated.
- Policy changes are based on design signatures and fixed A/B comparisons, never benchmark names.
- The full local unit suite passes after the final change.
- The final branch is pushed with small conventional commits and complete experiment documentation.
- A clean archive under 4 GiB passes `make setup` and a default full `make run_optimizer` invocation after extraction.
- The handoff identifies the best validated aggregate public score, remaining uncertainty about the hidden benchmark, and the exact beta artifact.
