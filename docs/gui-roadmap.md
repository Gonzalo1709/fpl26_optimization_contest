# GUI roadmap implementation audit

All seven phases are implemented on branch `gui`. The framework services live
outside Streamlit in `framework/` and are also available through a Python API
and `python -m framework`.

| Phase | Implementation | Verification |
| --- | --- | --- |
| 1. Run control | Validated configuration, DCP picker, model/mode/profile, budgets, advanced settings, command preview and submission | CLI argument contract, empty-run-directory guard, Streamlit form submission |
| 2. Reliable job management | SQLite queue, detached scheduler/supervisors, process identities, console logs, cancellation, environment probe, recovery | Actual subprocess tests for queue persistence, concurrency, duplicate scheduler launches, cooperative/forced cancellation, checkpoint preservation, descendant cleanup and supervisor crash |
| 3. Live monitoring | Candidate/best-so-far timing, strategy/generation, recorded elapsed time, usage/cost, budgets and beam | Live trailing-write tests, measured-cost ingestion, missing-metric handling, application rendering |
| 4. Comparisons | Timing/score/cost/runtime table, checkpoint/tool/validation warnings, configuration differences, CSV/ZIP | Service comparison/export tests and populated Streamlit comparison panel |
| 5. Search inspection | Selectable ancestry plot, strategy filtering, linked decisions/policy/tool/publication records, verified evidence | Browser click selected candidate `c2`; linked-event and evidence tests; browser had no console errors |
| 6. Batch experiments | Benchmark selection, bounded Cartesian sweeps, shared concurrency, batch cancellation, per-job results and checkpoint/profile aggregates | Sweep expansion/limit checks, GUI batch submission, actual concurrent subprocess queue |
| 7. Reproducibility | Saved/imported/exported configurations, configuration reuse, input hash verification, environment/source metadata, portable HTML reports and analysis tables | Preset roundtrip, changed-input rejection, report/ZIP checks, configuration reconstruction |

## Validation result

On September 30, 2026, the focused suite passed **23 tests**:

```bash
python -m unittest tests.test_framework tests.test_gui tests.test_gui_app tests.test_run_logging tests.test_deep_run_logging
```

The complete repository suite ran **110 tests: 95 passed, 7 failed, and 8 errored**.
The same 15 failures were reproduced by loading the original `HEAD` version of
`src/llm_optimizer.py` and rerunning the affected analysis, phys-opt portfolio,
policy, search ranking, and checkpoint publication test modules. They concern
existing optimizer behavior and legacy method expectations; this implementation
does not claim that the full repository suite is green.

Browser verification covered the live inspector and configuration layout, and
selection of a search candidate through the graph. Demonstration measurements
are explicitly labelled synthetic. The local environment has no configured
Vivado executable or RapidWright Python package, so real FPGA execution has not
been verified here. Queue/process tests use controlled Python subprocesses and
do not launch FPGA tools or make paid LLM calls. POSIX process-group code is
implemented, while the live process containment tests ran on Windows.

The roadmap does not include checkpoint-based search resume, authenticated
remote workers, or migration to a separate web frontend.
