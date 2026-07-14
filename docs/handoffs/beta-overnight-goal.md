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

### Candidate A promotion update

| Field | Result |
| --- | --- |
| Branch / promoted commit | `feat/score-aware-optimizer-portfolio` / `75cf2498f0bb9a0d0b34c9e405d4f9086e900ba3` (`feat: stop low-value fast search expansion`) |
| Protected beta preview | Attempt #3 / `v_520de46a2c58`; score **10.616**; completed `2026-07-14T01:47:24Z`; no global failure |
| Submission | Confirmed `2026-07-14T01:25:04Z`; MD5 `94daa68fdd1794430b5edbb2b194f57c` |
| LogicNets | 403.551251 -> 414.250 MHz; +10.699 MHz; score 10.616; 210.633 s; $0.0195; all gates passed |
| Vex v2 | 397.456280 -> 397.456 MHz; 0 MHz; score 0; 100.498 s; $0.0098; all gates passed; `no_improvement` |
| Candidate A archive | `C:/tmp/fpl26_beta_candidate_a.zip`; 1,525,735 bytes; 468 entries |
| Archive hashes | SHA256 `337d9c4381c21cd99dce340b104d15faaa4e4e7027a92eeb6d61f80b5ae9b141`; MD5 `94daa68fdd1794430b5edbb2b194f57c` |
| Setup preflight | Exact extracted `make setup` passed on `i-010aa4c4964acf607` using the Vivado 2025.1 bundled JRE; no `default-jre` install |
| Package correction | First Windows repack rejected before submission after stripping `RapidWright/gradlew` executable metadata; final package preserved incumbent ZIP metadata and replaced only `src/search.py` and `src/llm_optimizer.py` |
| Non-test execution | Manual SSH run unavailable without an injected OpenRouter key; credentials were not transferred; official preview performed the full metered run |
| Artifacts | `C:/tmp/beta-preview-attempt3/{scorecard.json,logs.zip,dcp_results.zip}` |
| Decision | Promoted: +3.077 over 7.539. Candidate B skipped because its conditional gate was false |
| Instance / remaining budget | Validation instance stopped after setup preflight; 14.87 hours remained |
| Rollback history | `C:/tmp/fpl26_beta_submission_runtime_v2.zip` remains immutable for historical rollback only |
| Remaining action | Perform final freeze verification; Candidate A is the current protected incumbent |

The table below is the earlier attempt #2 handoff retained for history.

| Field | Result |
| --- | --- |
| Final branch / commit | `feat/score-aware-optimizer-portfolio` / `8d9c176` (`docs: record finn screening`) |
| Instance status / remaining budget | Fresh instance `i-087167ca2e3818d5b` at `32.198.39.190`; launched with 16.18 h remaining |
| Public benchmarks completed | 7/12 characterized; ISPD and four remaining designs still need production screening |
| Newly validated positive benchmarks | `boom_soc`: PBLOCK, +5.755825 MHz, validated score 5.460046 |
| Best validated aggregate public score | 116.676046 |
| Confirmed beta preview | Attempt #2, score 7.539; LogicNets +7.633 MHz and all gates passed; Vex v2 legal but neutral |
| Promoted policy/search changes | Score-status reporting added without changing score calculation or candidate promotion |
| Rejected experiments and evidence | AMD FANOUT regressed; corescore and FINN PBLOCK each had 0 MHz gain; all restored their roots |
| Unit test result | 57/57 passed locally and on the fresh contest instance |
| Beta archive path / SHA256 / size | `C:/tmp/fpl26_beta_submission_runtime_v2.zip` / `bf12a10ab56986a275f3275e4e8589a185a582361fbd8388da82dec4a545f5a0` / 1,526,639 bytes |
| Clean `make setup` result | Passed after extracting the exact archive on the contest instance |
| Clean default non-test optimizer result | Not rerun from the archive because credential transfer was blocked; the packaged code has earlier full non-test evidence |
| Remaining blocker | None for beta eligibility: the latest submission and positive preview are confirmed. Remaining ad-hoc screening is blocked by credential-transfer policy. |
| Exact next command | Preserve attempt #2 as the beta submission unless new fixed evidence justifies the risk of another preview before `2026-07-14T11:59:59Z` |

## Safety and Recovery

- Use `.\fpl26contest status`, `start`, `ssh`, and `scp` from the local repository. Stop the instance only after the archive and needed evidence have been copied safely.
- Source `/tools/Xilinx/2025.1/Vivado/settings64.sh` before real runs.
- Load OpenRouter credentials only from ignored `.env`; never print or commit them.
- `make validate` should discover Vivado's bundled JRE. If Java/RapidWright fails and bundled Java is unavailable, use the documented disposable-instance fallback `sudo apt install default-jre` and record that it was required.
- A regressed candidate must be rolled back. A regressed code experiment must be reverted or left unpromoted rather than stacked with more speculation.
- Never upload `upload270426.zip`; the read-only preflight in `docs/experiments/2026-07-13-beta-submission-rehearsal.md` proves it contains forbidden artifacts.
- Use SCP for workstation/instance deployment and artifact retrieval. Transfer a Git bundle rather than the dirty working tree; transfer `.env` separately; copy DCPs, logs, and token reports back outside Git.
- Follow the exact, secret-free SCP command sequence in `docs/strategy/validation-environment.md`; SSH is for remote execution, not for synthesizing file contents on the VM.
