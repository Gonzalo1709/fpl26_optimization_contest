# Beta Preview Improvement Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the confirmed beta preview score above 7.539 while guaranteeing that the latest submission at the deadline is a proven positive incumbent.

**Architecture:** Treat the contest preview as a serialized A/B evaluator. Make one signature-based policy change per candidate, package only the runtime closure, validate `make setup`, submit once, download all artifacts, and either promote the winner or immediately restore the incumbent.

**Tech Stack:** Python 3, `unittest`, Vivado 2025.1, RapidWright, OpenRouter through the contest harness, PowerShell contest API calls, Git, ZIP, SCP for any disposable-VM transfer.

## Global Constraints

- Deadline: `2026-07-14T11:59:59Z`; stop new experiments at `2026-07-14T08:30:00Z`.
- Never leave an unproven candidate as the latest beta submission at the freeze time.
- Never submit while another preview is provisioning or running.
- Promote only a score strictly greater than the incumbent with no global failure and all placement, DRC, hold, pulse-width, and simulation gates passing.
- Use design signatures, never benchmark names, in optimizer behavior.
- Preserve existing recipes, branch/beam search, checkpoint rollback, score ranking, and specialist gates.
- Do not transfer `.env` or API credentials when the execution safety gate prohibits it.
- Do not use `--test` as full-optimizer evidence.
- Use conventional commits and push verified milestones; keep ZIPs, DCPs, logs, keys, credentials, and preview bundles outside Git.

## Protected Incumbent

| Field | Value |
| --- | --- |
| Preview | Attempt #2 / `v_cafee7d2e8e6` |
| Score | **7.539** |
| Submission MD5 | `9b55acba24a3788449a2b0b175d77ec3` |
| Archive | `C:/tmp/fpl26_beta_submission_runtime_v2.zip` |
| SHA256 | `bf12a10ab56986a275f3275e4e8589a185a582361fbd8388da82dec4a545f5a0` |
| Packaged source | `8d9c176` |
| LogicNets | +7.633 MHz, score 7.539, all gates passed |
| Vex v2 | 0 MHz, all gates passed |
| Restore action | Resubmit the archive above and confirm its MD5 |

Attempt #2 artifacts are in `C:/tmp/beta-preview-attempt2/`. The disposable VM was stopped with 15.19 hours remaining.

## Evidence and Approach

Read before editing:

1. `docs/experiments/2026-07-13-beta-submission-rehearsal.md`
2. `docs/experiments/2026-07-13-beta-public-suite.md`
3. `docs/experiments/2026-07-13-task10-prompt-optimization.md`
4. `C:/tmp/beta-preview-attempt2/scorecard.json`
5. `C:/tmp/beta-preview-attempt2-logs/logicnets_jscl.harness.log`
6. `C:/tmp/beta-preview-attempt2-logs/vexriscv_re-place_v2.harness.log`

Preferred approach: combine an evidence-based early stop after a positive fast-profile incumbent with one bounded alternative PHYS_OPT attempt after a neutral `RuntimeOptimized` result. This targets the wasted second LogicNets generation and the neutral Vex result without broadening specialist recipes.

Alternatives, in order: (1) early-stop only for the lowest-risk cost/runtime improvement; (2) bounded PHYS_OPT fallback only; (3) deterministic planner bypass for strong signatures. Do not attempt (3) unless the first two are exhausted because it changes general planner behavior.

## Task 1: Freeze and Verify the Incumbent

- [ ] Confirm `beta_status=confirmed`, MD5 `9b55acba24a3788449a2b0b175d77ec3`, and attempt #2 score 7.539.
- [ ] Recompute the incumbent ZIP SHA256 and MD5.
- [ ] Run the full local suite: `.venv/Scripts/python.exe -m unittest discover -s tests -v`; expect 57 passing tests before new tests.
- [ ] Record the current UTC time and remaining experiment window in the rehearsal document.

## Task 2: Candidate A — Score-Aware Fast Early Stop

**Files:** modify `src/search.py`, `src/llm_optimizer.py`; test `tests/test_search_ranking.py`.

- [ ] Add a failing test proving that only the `fast` profile stops expansion after a candidate has positive projected score and an accepted WNS/Fmax gain; zero-gain roots and other profiles remain expandable.
- [ ] Run the targeted test and observe the expected failure.
- [ ] Implement the smallest pure helper in `src/search.py` and call it after updating `best_candidate` in `_optimize_generational`.
- [ ] Run targeted and full tests; commit `feat: stop low-value fast search expansion`.
- [ ] Package, audit, run extracted `make setup`, submit, and wait for the preview.
- [ ] Promote only if score exceeds 7.539 with all gates passing; otherwise restore the incumbent immediately.

## Task 3: Candidate B — Bounded Neutral PHYS_OPT Fallback

Run only if time remains and Candidate A did not produce a sufficient improvement.

**Files:** modify `src/policy.py`, `src/llm_optimizer.py`; test `tests/test_phys_opt_portfolio.py` and `tests/test_policy.py`.

- [ ] Add failing tests for exactly one alternate PHYS_OPT directive after `RuntimeOptimized` yields zero gain on a no-critical-fanout signature with clean budget/signoff state.
- [ ] Prove the fallback is disabled after positive gain, with critical fanout evidence, inside the validation reserve, or after one alternate attempt.
- [ ] Implement the bounded fallback without widening PBLOCK/HARD_BLOCK eligibility.
- [ ] Run targeted and full tests; commit `feat: try bounded neutral phys opt fallback`.
- [ ] Package and preview through the same promotion/restoration gate.

## Task 4: Runtime-Only Packaging Gate

- [ ] Include only `Makefile`, `requirements.txt`, `dcp_optimizer.py`, `SYSTEM_PROMPT.TXT`, `src/`, `RapidWrightMCP/`, `VivadoMCP/`, and build-required RapidWright sources.
- [ ] Keep RapidWright's Java package named `tests`; v3 proved production classes import it.
- [ ] Reject any ZIP containing Git metadata, credentials, keys, DCPs, logs, documentation, generated runs, or standalone test suites.
- [ ] Extract into a fresh directory and run exact `make setup` before every submission.

## Task 5: Serialized Preview and Restoration Loop

- [ ] Confirm no preview is running, submit one candidate, and confirm its MD5.
- [ ] Wait for the terminal preview state; do not supersede it.
- [ ] Download scorecard, logs, and DCP results with the `--preview --attempt N --all` equivalent.
- [ ] Record score, per-row Fmax, cost, runtime, gates, archive hashes, commit, and decision.
- [ ] If worse/equal/failed, resubmit the protected incumbent and confirm restoration.
- [ ] If better and fully valid, update the protected-incumbent table and keep the winning archive immutable.

## Task 6: Deadline Freeze

- [ ] At `2026-07-14T08:30:00Z`, stop new candidates.
- [ ] Restore the last proven incumbent if the latest candidate is unproven.
- [ ] Verify the latest beta MD5, `confirmed` status, positive preview, and no newer pending attempt.
- [ ] Download final `--all` artifacts, stop unused instances after SCP retrieval, update the rehearsal/public-suite/handoff documents, and push the final conventional documentation commit.

## Definition of Done

- The latest confirmed beta is the highest fully validated preview score found, never below 7.539.
- Its runtime-only ZIP passes an extracted exact `make setup` and has recorded SHA256/MD5/size.
- Every attempt has complete artifacts and a documented promotion or restoration decision.
- The final handoff records score, attempt, validation ID, MD5, commit, archive, deadline status, and remaining budget.
