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
| Clean archive path | `C:/tmp/fpl26_beta_submission.zip` |
| SHA256 | `2443b5e50cc6118a14b26a54d78b9c6892b174ffa0db45958284c551508e8165` |
| Byte size | 12,933,968 bytes |
| Forbidden-entry scan | Passed: 870 entries, one correct top-level directory, zero forbidden entries |
| Extracted `make setup` | Passed on contest instance `i-087167ca2e3818d5b` |
| Extracted default non-test optimizer | Not rerun: the execution environment blocked transferring the OpenRouter credential even after user approval |
| Optimized DCP validation | Not applicable without the blocked archive smoke run; the same packaged code has prior full non-test validated BOOM, VexRiscv, and LogicNets evidence |

The archive was built from a clean clone on the official VM, retrieved by SCP,
and audited locally. It contains the pinned RapidWright sources but no Git
metadata, credentials, private keys, benchmark DCPs, logs, or generated run
directories. No upload or submission has been performed.
