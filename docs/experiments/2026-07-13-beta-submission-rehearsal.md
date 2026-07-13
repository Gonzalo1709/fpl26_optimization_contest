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
- Preview attempt: `#2`, latest submission, initially `provisioning`
- Replaced preview attempt `#1`, whose scorecard was `0.0` because both public
  benchmarks produced no Fmax improvement.
- Attempt #1 scorecard, logs, and DCP results were downloaded before replacement
  to `C:/tmp/beta-preview-attempt1/` using the organizer's `--all` equivalent.
