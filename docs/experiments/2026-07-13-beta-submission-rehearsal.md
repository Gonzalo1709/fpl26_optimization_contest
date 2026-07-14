# Beta Submission Rehearsal

## Local archive preflight

- Date: 2026-07-13
- Branch: `feat/score-aware-optimizer-portfolio`
- Commit at audit start: `d88e8b4`
- Evaluator contract: extract an archive containing a top-level
  `fpl26_optimization_contest/`, then run `make setup` and repeated default
  `make run_optimizer DCP=...` invocations.

The existing local `upload270426.zip` was inspected read-only and is **not a
beta candidate**:

| Check | Existing archive result | Required result |
| --- | --- | --- |
| Size | 1,276,956,005 bytes | Less than 4,294,967,296 bytes |
| Top-level project directory | Missing; repository files are at archive root | `fpl26_optimization_contest/` |
| `.git` metadata | Present | Excluded |
| Contest SSH private key | `fpl26contest-key.pem` present | Excluded |
| Benchmark DCPs | Present | Excluded |
| `.env` | Not found | Excluded |

Do not upload or reuse `upload270426.zip`. It contains credential material and
does not satisfy the documented extraction layout.

## Current package footprint

| Component | Measured unpacked bytes |
| --- | ---: |
| Main-repository tracked regular files | 8,843,087 |
| Current RapidWright checkout | 237,843,851 |

The clean-clone packaging approach in
`docs/superpowers/plans/2026-07-13-beta-submission-sprint.md` has ample room
under the 4 GiB limit. The final archive must still be built after all source
changes are committed and must be audited independently.

## Final rehearsal checklist

| Gate | Result |
| --- | --- |
| Packaged branch commit | `8d9c176` (`docs: record finn screening`) |
| RapidWright commit | `35da0b4ea46ecccb6e09207573ca13531eb02d6c` |
| Clean archive path | `C:/tmp/fpl26_beta_submission_runtime_v2.zip` |
| SHA256 | `bf12a10ab56986a275f3275e4e8589a185a582361fbd8388da82dec4a545f5a0` |
| MD5 | `9b55acba24a3788449a2b0b175d77ec3` |
| Byte size | 1,526,639 bytes |
| Runtime-only audit | Passed: 468 entries under one correct top-level directory and only eight required runtime roots |
| Extracted `make setup` | Passed on contest instance `i-087167ca2e3818d5b` |
| Extracted default non-test optimizer | Not rerun: the execution environment blocked transferring the OpenRouter credential even after user approval |
| Optimized DCP validation | Not applicable without the blocked archive smoke run; the same packaged code has prior full non-test validated BOOM, VexRiscv, and LogicNets evidence |

The final archive was built as a whitelist from a clean clone on the official
VM, retrieved by SCP, and audited locally. Its only roots are `Makefile`,
`requirements.txt`, `dcp_optimizer.py`, `SYSTEM_PROMPT.TXT`, `src/`,
`RapidWrightMCP/`, `VivadoMCP/`, and the build-required RapidWright sources.
It contains no Git metadata, credentials, private keys, benchmark DCPs, logs,
documentation, generated run directories, or standalone test suites.

An attempted v3 removal of RapidWright's Java package named `tests` was rejected
after the extracted `make setup` correctly failed compilation: production
RapidWright classes import `CodePerfTracker` and other utilities from that
package. V2 is therefore the smallest tested archive, not merely the smallest
archive produced.

## Beta Submission

- Confirmed at: `2026-07-13T22:42:12Z`
- Server MD5: `9b55acba24a3788449a2b0b175d77ec3`
- Deadline reported by server: `2026-07-14T11:59:59Z`
- Preview attempt: `#2`, latest submission, completed at
  `2026-07-13T23:05:22Z` with score **7.539**
- Replaced preview attempt `#1`, whose scorecard was `0.0` because both public
  benchmarks produced no Fmax improvement.
- Attempt #1 scorecard, logs, and DCP results were downloaded before replacement
  to `C:/tmp/beta-preview-attempt1/` using the organizer's `--all` equivalent.
- Attempt #2 scorecard, logs, and DCP results were downloaded to
  `C:/tmp/beta-preview-attempt2/` using the same `--all` equivalent.

### Preview attempt #2 scorecard

| Benchmark | Delta Fmax | Runtime | OpenRouter cost | Score | Validation |
| --- | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | +7.633 MHz | 306.496 s | $0.0386 | 7.539 | All placement, DRC, hold, pulse-width, and simulation gates passed |
| `vexriscv_re-place_v2` | 0 MHz | 99.215 s | $0.0098 | 0 | All gates passed; `RuntimeOptimized` PHYS_OPT produced no improvement on the v2 checkpoint |

The preview had no global failure and both benchmarks produced legal validated
outputs. No attempt #3 was submitted because the zero Vex row already selected
the intended low-risk PHYS_OPT directive and there is no fixed evidence that a
policy change would improve the distinct `v2` checkpoint without risking the
confirmed positive LogicNets result.

## Candidate A Promotion

The earlier decision was superseded by the bounded Candidate A change at
`75cf2498f0bb9a0d0b34c9e405d4f9086e900ba3`
(`feat: stop low-value fast search expansion`). Candidate A strictly improved
the 7.539 incumbent, so Candidate B's conditional gate was false and Candidate
B was skipped.

### Final Candidate A archive preflight

| Gate | Result |
| --- | --- |
| Archive | `C:/tmp/fpl26_beta_candidate_a.zip` |
| SHA256 | `337d9c4381c21cd99dce340b104d15faaa4e4e7027a92eeb6d61f80b5ae9b141` |
| MD5 / server MD5 | `94daa68fdd1794430b5edbb2b194f57c` |
| Byte size | 1,525,735 bytes |
| Entries | 468 |
| Packaging method | Preserved all incumbent ZIP metadata; replaced only `src/search.py` and `src/llm_optimizer.py` |
| Extracted `make setup` | Passed on disposable instance `i-010aa4c4964acf607` using the Vivado 2025.1 bundled JRE; no `default-jre` install was needed |
| Manual non-test SSH run | Not possible: the SSH environment lacked an injected OpenRouter key, and credentials were not transferred |
| Official non-test evidence | Preview attempt #3 performed the full run with metering |

The first Windows repack was rejected before submission because it stripped
the executable metadata from `RapidWright/gradlew`. The submitted package
preserved all incumbent ZIP metadata and changed only the two Candidate A
source files. The validation instance was stopped after setup preflight with
14.87 hours remaining.

### Preview attempt #3 scorecard

- Submission confirmed: `2026-07-14T01:25:04Z`
- Validation: `v_520de46a2c58`
- Completed: `2026-07-14T01:47:24Z`
- Total score: **10.616**
- Global status: completed; global failure: null
- Artifacts:
  `C:/tmp/beta-preview-attempt3/{scorecard.json,logs.zip,dcp_results.zip}`

| Benchmark | Input Fmax | Output Fmax | Delta Fmax | Runtime | Cost | Score | Validation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | 403.551251 MHz | 414.250 MHz | +10.699 MHz | 210.633 s | $0.0195 | 10.616 | Routed, DRC, hold, pulse-width, and simulation gates all passed |
| `vexriscv_re-place_v2` | 397.456280 MHz | 397.456 MHz | 0 MHz | 100.498 s | $0.0098 | 0 | All gates passed; failure reason `no_improvement` |

Candidate A improves the former 7.539 incumbent by 3.077 points and is now the
protected incumbent. The previous archive remains immutable at
`C:/tmp/fpl26_beta_submission_runtime_v2.zip` for historical rollback only.
The deadline freeze verification remains outstanding.
