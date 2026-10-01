# Optimizer experiment framework and GUI

The framework provides shared configuration, persistent jobs, run queries, and
reports. Streamlit is an optional interface: detached supervisors own optimizer
processes, so browser refreshes and disconnects do not restart jobs.

From the repository root, using Python 3.10 or newer:

```bash
python -m pip install -r requirements-gui.txt
python -m streamlit run gui/app.py --server.address 127.0.0.1
```

The selected **Optimizer Python executable** also needs `requirements.txt`,
Vivado, Java/RapidWright, and the normal setup from the main README. The dashboard
alone can inspect runs without those tools. Export `OPENROUTER_API_KEY` before
starting the dashboard/scheduler for LLM mode. Keys are inherited through the
environment and are not saved in configurations or manifests. A running
scheduler retains its startup environment; restart it if that environment changes.

The default workspace is `.optimizer-framework/`, ignored by Git. It contains
`jobs.sqlite3`, presets, scheduler metadata/logs, and one directory per job with
`optimized.dcp`, `console.log`, `manifest.json`, `worker.log`, and `run/`.

## Workflows

| Panel | Features |
| --- | --- |
| Configure | DCP picker/path, Python, mode/model, profiles, runtime/cost caps, advanced settings, command preview, environment probe, saved/imported settings, enqueue |
| Jobs | Persistent status, concurrency, console tail, cancellation, configuration reuse, manifest export, scheduler recovery |
| Inspect | Candidate and best-so-far WNS, final Fmax, recorded elapsed time, LLM usage, strategy/generation, budgets/beam, selectable ancestry, strategy filters, linked policy/tool/publication evidence, output validation and scores |
| Compare | Timing/score/cost/runtime tables, checkpoint/tool/validation compatibility warnings, configuration differences, CSV and table ZIP exports |
| Batch | Benchmark selection, Cartesian sweeps, preview/enqueue, shared concurrency, per-job metrics, checkpoint/profile aggregates, CSV export, batch cancellation |

Advanced settings use optimizer flag names with underscores, for example:

```json
{"branches": 2, "beam_width": 2, "generations": 3, "stop_when_timing_met": true}
```

Sweep values are nonempty lists of supported settings:

```json
{"profile": ["fast", "quality"], "beam_width": [1, 2]}
```

Sweeps are capped at 256 jobs per submission. Concurrency defaults to one and
supports 1–16 jobs; choose it for available licenses and memory. Lowering it
affects future starts without interrupting active jobs. Budgets apply per job.

## Cancellation and recovery

Queued jobs cancel immediately. Active jobs receive a persistent stop marker,
which the adaptive optimizer checks before another search step. Already
published checkpoints remain available. Active tool calls may take time to
finish. After 120 seconds the supervisor attempts an interrupt; after another
15 seconds it terminates the contained process tree. Forced termination may
leave no final optimizer summary, so managed job status is the authority for
process completion. It does not establish checkpoint validation.

Windows supervisors assign the optimizer to a Job Object before resuming it;
closing the supervisor kills its descendants. POSIX supervisors use a separate
process group. Process identities include creation time to guard against PID
reuse. Recovery marks a job interrupted when its process handles are gone, or
orphaned while its optimizer handle remains alive. Orphaned jobs still occupy a
concurrency slot and can be cancelled. Interrupted jobs are never automatically
rerun.

The scheduler remains alive while idle, protected by an OS file lock. Use
**Start or recover scheduler** after a scheduler crash. Existing supervisors
continue independently. Host restarts require starting the scheduler again;
this is not an installed OS service.

## Reproducibility and interpretation

Each managed job records its versioned configuration, exact argument list,
absolute checkpoint path and SHA-256, source revision, and environment probe.
The worker verifies the input hash again before launch. Optimizer summaries
provide tool versions, source state, timing, validation, and checkpoint identities.
Reusing a configuration creates a new job; it does not resume a search. Older
logs can reconstruct supported settings when sufficient metadata exists.

HTML reports contain a portable snapshot of results, configuration, and
publication metadata. CSV ZIPs contain derived analysis tables. Evidence
references remain linked to the original run and verify hash and length when
expanded; reports do not embed DCP binaries or full evidence.

Live reads ignore an incomplete trailing JSONL write, while complete malformed
records remain errors. Missing summaries are explicitly marked; they are not
used to infer that a process is running. Unknown metrics remain missing rather
than displaying zero. Published outputs can be unchanged baselines, and timing
improvement does not establish a validated contest score.

## Without Streamlit

Install `requirements-framework.txt` for workers. Configuration/run readers
themselves use the standard library.

```python
from pathlib import Path
from framework import JobManager, RunConfig, RunService

jobs = JobManager(Path(".optimizer-framework"))
job_id = jobs.enqueue([RunConfig("/absolute/path/design.dcp")])[0]
print(jobs.get(job_id))
# jobs.cancel(job_id)
print(RunService().discover(jobs.root))
```

```bash
python -m framework --help
python -m framework queue configuration.json
python -m framework jobs
python -m framework cancel JOB_ID
python -m framework recover
python -m framework concurrency 2
python -m framework inspect PATH_TO_RUN
python -m framework compare RUN_A RUN_B
python -m framework report PATH_TO_RUN report.html
```

CLI sweeps use `queue configuration.json --design DESIGN_A --design DESIGN_B
--sweep axes.json`. The optimizer CLI also supports `--run-dir` for a new or
empty directory, refusing to overwrite an existing run.

## Demonstration and checks

```bash
python -m tools.create_gui_demo .optimizer-framework/demo
python -m unittest tests.test_framework tests.test_gui tests.test_gui_app tests.test_run_logging tests.test_deep_run_logging
```

Choose `.optimizer-framework/demo` in the run-folder picker. Demo data is
labelled synthetic, has no validated scores, and cannot be rerun as real designs.
Tests use controlled subprocesses, without launching Vivado or spending LLM
credits. They cover queue concurrency, cancellation, descendant cleanup, crash
recovery, CLI contracts, live logs, comparisons, exports, and Streamlit panels.

Keep the dashboard bound to localhost: its folder picker and evidence viewer
expose research artifacts. This is a local framework with one host per workspace.
Checkpoint resume, authenticated remote workers, and a separate frontend are
outside this roadmap.
