# Optimizer web workspace

The React/Vite interface uses shadcn preset `b3RqiTiFM` (Base Lyra, zinc,
indigo, Inter, pointer controls). FastAPI serves its production build and wraps
the existing `JobManager` and `RunService`; it does not own optimizer processes.
The Streamlit dashboard and CLI remain available.

## Build and run

From the repository root, with Python 3.10+ and a Node version supported by Vite:

```sh
python -m pip install -r requirements-web.txt
cd web
npm ci
npm run build
cd ..
python -m framework.web
```

Open **http://127.0.0.1:8765**. The single local server serves both the UI and API.
No Vite development server is required. Stop the web server with Ctrl+C; existing
jobs continue under their detached supervisors.

Use a specific persistent job workspace and any number of run roots:

```sh
python -m framework.web --workspace .optimizer-framework --runs /path/to/runs --port 8765
```

`--runs` can be repeated. A root may be a run containing `events.jsonl`, a parent
containing run directories, or the existing framework workspace. Discovery is
shallow, matching `RunService`; use **Open run folder** to select deeper archives.
Folders opened in the UI remain available until the server stops; use `--runs`
to restore them on the next server start. All paths refer to the execution host.

The inspector works without FPGA dependencies. For real jobs, the **Optimizer
Python executable** in Advanced settings must have `requirements.txt`, Vivado,
Java/RapidWright, and the setup documented in the main README. For LLM mode,
set `OPENROUTER_API_KEY` in the scheduler's environment before starting it.
Credentials are not entered or stored through this UI.

## Workflow

- Open previous runs from the sidebar or **Open run folder**.
- Select graph nodes or edges to follow candidate ancestry. Cards distinguish
  active, failed, interrupted, unknown, and finished-without-candidate attempts;
  the current beam and best candidate have explicit markers.
- The decision inspector links planner choices, policy gates, tool calls and
  outcomes. **Expand evidence** verifies and reads the existing evidence blobs.
  Selection source identifies LLM, deterministic, forced, and fallback choices.
- **Timeline** filters recorded events; **Output & validation** exposes checkpoint,
  summary, and validation fields. Missing and ignored checks remain visible.
- Live updates use SSE. Reconnect sends a complete snapshot including events
  missed during disconnection; the client replaces its snapshot, avoiding duplicates.
  **Pause updates** pauses viewing, not execution. Live subscriptions do not reset
  graph selection or the viewport on metric-only changes.
- **New experiment** validates settings through the existing configuration
  contract, previews arguments, optionally checks the runtime, then enqueues.
  Jobs without logs show their console and cancellation control. When logs appear,
  the selected job automatically becomes a run inspector. **Reuse configuration**
  creates a new job; it does not resume an old search.
- **Cancel** uses existing cooperative/forced cancellation semantics. Browser
  refreshes do not cancel jobs. Process completion does not establish validation.

Only managed job status confirms active execution. A legacy log without a final
summary has unknown status; an unfinished call alone does not prove it is running.
Live updates are at event boundaries, usually within one second of a log write;
the interface does not stream private model reasoning or fabricate progress inside
a tool that has not logged another event. The run/job list refreshes every 3 seconds.

The server binds to loopback, rejects foreign Host/Origin headers, and requires a
same-origin client header for mutations. Run directories contain private research
artifacts; this version is intended for a trusted local operator, without public
hosting, multi-user authorization, or remote workers.

## Checks

```sh
python -m pip install httpx
python -m unittest tests.test_web tests.test_gui tests.test_run_logging
cd web
npm run lint
npm run build
npx playwright install chromium
npm test
```

Alternatively use an installed browser with `PLAYWRIGHT_CHANNEL=chrome` or
`PLAYWRIGHT_CHANNEL=msedge`. The browser test starts and stops a disposable server,
uses labelled synthetic logs, and suppresses only actual scheduler startup; queue,
configuration, evidence, live file ingestion, refresh and cancellation are real.
It also captures desktop and mobile screenshots under ignored `web/test-results/`.
It does not launch Vivado or make paid LLM requests.

The shadcn generator is a development dependency. At implementation time,
`npm audit --omit=dev` reported zero advisories; the generator's transitive glob
packages reported seven high advisories. No forced major-version downgrade was
applied. The frontend build reports a large bundle warning for the graph/chart UI.
