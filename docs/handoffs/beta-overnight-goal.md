# Overnight Goal: Beta Submission Sprint

## Read This First

1. Read `docs/superpowers/plans/2026-07-13-beta-submission-sprint.md` completely.
2. Read `docs/experiments/2026-07-13-task10-prompt-optimization.md` so rejected GEPA/DSPy, PBLOCK, HARD_BLOCK, and route experiments are not repeated without new evidence.
3. Read `docs/experiments/README.md` for the score formula and promotion rules.
4. Continue on `feat/score-aware-optimizer-portfolio`; preserve all existing recipes, gates, branching, checkpoint rollback, score ranking, and validation behavior.

## Copy/Paste Goal

> Execute `docs/superpowers/plans/2026-07-13-beta-submission-sprint.md` task-by-task and work persistently toward the best benchmark-general validated beta submission. Start by verifying the current branch and full unit suite, then use the official contest instance to run the unchanged production optimizer in full non-test mode across all nine still-uncharacterized public DCPs. Record every run, including failures and rollbacks, in `docs/experiments/2026-07-13-beta-public-suite.md`, and immediately run full legality/equivalence validation for every positive-score incumbent.
>
> After the public-suite matrix is complete, derive policy changes only from benchmark-name-independent design signatures and fixed real A/B evidence. Preserve the existing recipes and generation-search controller. Do not loosen PBLOCK or HARD_BLOCK gates, promote GEPA/DSPy prompts, or add speculative transformations without new validated evidence. Implement bounded FANOUT/PHYS_OPT action repeats only if repeated real runs demonstrate at least 1.0 MHz Fmax variability and at least eight instance-hours remain; promote them only if aggregate validated contest score improves after runtime and OpenRouter cost penalties.
>
> Keep projected, pending, failed-validation, and validated scores distinct. Make small conventional commits, push each verified milestone to `origin/feat/score-aware-optimizer-portfolio`, and never commit `.env`, credentials, DCPs, archives, logs, or generated run directories. Reserve the final four instance-hours for the complete unit suite, final validation, and a clean beta archive rehearsal using exactly the organizer contract: extract the archive, `make setup`, then default `make run_optimizer DCP=...` without `--test`.
>
> Do not stop after obtaining one positive result. Continue until all Definition of Done gates in the beta sprint plan are satisfied, or until further work would consume the reserved submission-rehearsal window. If blocked, exhaust safe diagnostics and record the precise command, error, attempted fixes, remaining instance budget, and best next action in this handoff.

## Operating Priorities

1. Complete public-suite coverage and validate positives.
2. Improve cross-design recipe ordering only from measured evidence.
3. Evaluate bounded physical repeats only if the evidence/time gate passes.
4. Add explicit score-status reporting.
5. Produce and test a clean beta archive.

Prompt optimization is not a priority: the current production prompt beat both GEPA-lite and DSPy in real score despite their higher offline scores.

## Known Production Control

| Field | Current value |
| --- | --- |
| Branch | `feat/score-aware-optimizer-portfolio` |
| Production prompt hash | `ee3acce412f63417` |
| Vex validated result | WNS `-1.654 -> -0.886`, delta Fmax `+96.992 MHz`, score `96.626` |
| LogicNets validated result | WNS `-0.978 -> -0.891`, delta Fmax `+14.684 MHz`, score `14.590` |
| Validated public subtotal | `111.216` |
| Rosetta digit | Neutral; rolled back |
| Fixed screening profile | `fast`, branches 1, beam 1, generations 2, one step/branch, 30 minutes, $0.10 |

## Morning Handoff

| Field | Result |
| --- | --- |
| Final branch / commit | pending |
| Instance status / remaining budget | pending |
| Public benchmarks completed | 3/12 characterized before this sprint |
| Newly validated positive benchmarks | pending |
| Best validated aggregate public score | 111.216 before this sprint |
| Promoted policy/search changes | pending |
| Rejected experiments and evidence | pending |
| Unit test result | pending |
| Beta archive path / SHA256 / size | pending |
| Clean `make setup` result | pending |
| Clean default non-test optimizer result | pending |
| Remaining blocker | none recorded |
| Exact next command | follow Task 1 in the beta sprint plan |

## Safety and Recovery

- Use `.\fpl26contest status`, `start`, `ssh`, and `scp` from the local repository. Stop the instance only after the archive and needed evidence have been copied safely.
- Source `/tools/Xilinx/2025.1/Vivado/settings64.sh` before real runs.
- Load OpenRouter credentials only from ignored `.env`; never print or commit them.
- `make validate` should discover Vivado's bundled JRE. If Java/RapidWright fails and bundled Java is unavailable, use the documented disposable-instance fallback `sudo apt install default-jre` and record that it was required.
- A regressed candidate must be rolled back. A regressed code experiment must be reverted or left unpromoted rather than stacked with more speculation.
