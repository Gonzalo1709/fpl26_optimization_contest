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
the 7.539 incumbent and remains the protected incumbent. The earlier Candidate
B `skipped` state was superseded by the user's `2026-07-14` authorization to
resume the bounded candidate sequence.

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
Every subsequent candidate remains subject to automatic restoration of
`C:/tmp/fpl26_beta_candidate_a.zip`, with MD5
`94daa68fdd1794430b5edbb2b194f57c` reconfirmed, if it is worse, equal, failed,
or unproven when the restoration window is reached. The deadline freeze
verification remains outstanding.

## Authorized Extended Candidate Window

On `2026-07-14`, the user authorized candidate work to resume. Candidate B is
active; its old `skipped` state is superseded. If B is exhausted, Candidate C
uses attempt #3 logs to identify one benchmark-independent fast-search/
early-stop or recipe-ordering improvement and changes one policy variable only.
Candidate D may attempt a deterministic design-signature planner bypass only if
B and C are exhausted, evidence is strong, and at least three hours remain.

No new candidate may start after `2026-07-14T09:45:00Z`. The hard experimental
freeze is extended from 08:30Z to `2026-07-14T10:30:00Z`. The existing PID
`38892` watcher at 08:30Z is read-only pre-freeze evidence, not the new hard
freeze.

## Candidate B Result and Mandatory Restoration

Candidate B used commits `ef62cd5` (`feat: try bounded neutral phys opt
fallback`) and `416e4aa` (`fix: make neutral phys opt rollback fail safe`). It
preserved the existing fast early stop, recipes, search controller, rollback,
ranking, specialist gates, and DSPy/GEPA integration. Targeted tests passed
26/26, and the complete suite passed 72/72 plus `compileall` and `git diff
--check` after the rollback review fix.

| Gate | Result |
| --- | --- |
| Archive | `C:/tmp/fpl26_beta_candidate_b.zip` |
| Size / entries | 1,526,812 bytes / 468 |
| SHA256 | `53d75b9d1205a83edd0db15c8d8c320f5bb2ac5433327f40f2247e44ee7a9684` |
| MD5 / server MD5 | `29a9c8e2161bd8daa85c0319f8302991` |
| Runtime delta from Candidate A | Replaced only `src/policy.py` and `src/llm_optimizer.py`; ZIP metadata and `RapidWright/gradlew` executable mode preserved |
| Transfer | Organizer `./fpl26contest scp` to `i-010122f97d9e8d2fd` |
| Exact extracted setup | Passed after sourcing `/tools/Xilinx/2025.1/Vivado/settings64.sh`; Vivado 2025.1 bundled Java 11 worked; `default-jre` was not installed |
| Full non-test evidence | Official preview attempt #4 |

Preview attempt #4 (`v_da0b3a97b453`) completed at
`2026-07-14T07:25:16Z` with total score **10.616** and no global failure:

| Benchmark | Input Fmax | Output Fmax | Delta Fmax | Runtime | Cost | Score | Validation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | 403.551251 MHz | 414.250 MHz | +10.699 MHz | 210.602 s | $0.0192 | 10.616 | Routed, DRC, hold, pulse-width, and simulation gates passed |
| `vexriscv_re-place_v2` | 397.456280 MHz | 397.456 MHz | 0 MHz | 148.383 s | $0.0098 | 0 | All gates passed; alternate CriticalPin remained neutral; `no_improvement` |

Attempt #4 artifacts are under
`C:/tmp/beta-preview-attempt4/results/beta/preview/attempt-4/`:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `scorecard.json` | 2,079 | `15aefeaa3d1de0631db20fd86e903ee71f0356e5f4cce25c35332b3f148616ce` |
| `logs.zip` | 114,341 | `17e87374f6700ae69dafe1c15399e464292b26cd2319d335480de142c8d97ab1` |
| `dcp_results.zip` | 15,129,955 | `0ce7d6293b1351cd7fa98eaf4275b4b78ab273960812a8dccea3bb00873c0906` |

Because equality is not promotion, Candidate B was rejected. Candidate A was
resubmitted at `2026-07-14T07:57:27Z`; the service confirmed protected MD5
`94daa68fdd1794430b5edbb2b194f57c`. Restoration preview attempt #5
(`v_a6e8e4d1915a`) completed at `2026-07-14T08:19:13Z` with score **10.788**,
no global failure, and no newer pending preview.

### Restored Candidate A attempt #5

| Benchmark | Input Fmax | Output Fmax | Delta Fmax | Runtime | Cost | Score | Validation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `logicnets_jscl` | 403.551251 MHz | 414.422 MHz | +10.871 MHz | 207.683 s | $0.0183 | 10.788 | Routed, DRC, hold, pulse-width, and simulation gates passed |
| `vexriscv_re-place_v2` | 397.456280 MHz | 397.456 MHz | 0 MHz | 99.892 s | $0.0098 | 0 | All gates passed; `no_improvement` |

Attempt #5 used the same protected archive and MD5 as attempt #3; measured
FANOUT variation raised the score from 10.616 to **10.788**. Complete artifacts
are under `C:/tmp/beta-preview-attempt5/results/beta/preview/attempt-5/`:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `scorecard.json` | 2,079 | `dcda55b6f2486045e5693dabf6f3ca27a2745a8c8ce5ca060370d2d10bda26f4` |
| `logs.zip` | 114,245 | `8417456d2bd24cbe590e18ac92882cd19da2b945e58bcc178f2478bb183363ef` |
| `dcp_results.zip` | 15,126,058 | `77fb1320f5eeeceea3c14ec712833a9ab8d6f786078b6e2f313f3c49358a5112` |

Candidate C was skipped because attempt #3 provided no evidence-supported
single variable. Its strongest hypothesis was allowing another fast generation,
but the only fixed second-generation gain was +0.018 ns, below the preserved
0.020 ns acceptance gate; its extra runtime predicted about -0.049 score. The
apparent FANOUT `top_n` alternatives were not real breadth comparisons because
the fast executor caps them to one net.

Candidate D's narrow hypothesis was to bypass the planner only for the two
repeatedly measured signature classes, saving at most about 0.0209 score on the
positive row from its $0.0195 planner call plus small API latency. It was skipped
because Candidate B was still nonterminal at `2026-07-14T07:30:05Z`, when fewer
than the mandatory three hours remained before the 10:30Z freeze. No source or
package was produced for C or D. The now-unused validation instance was
terminated with 13h52m budget remaining.

## Pre-Freeze Readiness Checkpoint

At `2026-07-14T02:49:29Z`, the organizer service again reported Candidate A as
the confirmed beta submission, attempt #3 as completed with score **10.616**, no
newer attempt, no running validation instance, and 14h52m remaining. The archive
still matched SHA256
`337d9c4381c21cd99dce340b104d15faaa4e4e7027a92eeb6d61f80b5ae9b141`
and MD5 `94daa68fdd1794430b5edbb2b194f57c`.

The final artifact set was refreshed with the organizer's `--all` command into
`C:/tmp/fpl26-beta-freeze-final/results/beta/preview/attempt-3/`:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `scorecard.json` | 2,079 | `1d7dd95e0ebc272a2513e8ab4ab34268ed58704836d4f72cbe1ca169ee8b9b7c` |
| `logs.zip` | 118,549 | `c4cd02b238a754e767fc8f53bb909501772035f92db45cb491d12d22e825a92e` |
| `dcp_results.zip` | 15,129,275 | `080bdb0b067302418cc98ce5408fa96a7cad794169dd978d445dbbe57dcd8676` |

The full local suite passed 63/63 and `compileall` passed at 02:51Z. This is a
readiness checkpoint only. The PID `38892` watcher at 08:30Z provides read-only
pre-freeze evidence; the user-authorized candidate window and the 10:30Z hard
freeze remain pending.
