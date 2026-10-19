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
shallow, matching `RunService`; use **Import / open runs → Open host folder** to select deeper archives.
Folders opened in the UI remain available until the server stops; use `--runs`
to restore them on the next server start. All paths refer to the execution host.

The inspector works without FPGA dependencies. For real jobs, the **Optimizer
Python executable** in Advanced settings must have `requirements.txt`, Vivado,
Java/RapidWright, and the setup documented in the main README. For LLM mode,
set `OPENROUTER_API_KEY` in the scheduler's environment before starting it.
Credentials are not entered or stored through this UI.

## Cloud run → ZIP → local UI

Use the branch containing this tool on the cloud instance. No web server, Node,
or frontend dependencies are needed there for export; the command uses the Python
standard library. Deep logging must already exist in the source run: an old console
log or CSV alone cannot reconstruct past planner decisions.

1. Run the optimizer with your usual settings. It prints `Run dir: ...`. To choose
   a predictable location, add `--run-dir /path/runs/experiment-01` to your command;
   the folder must be new or empty. Each experiment needs its own directory.
2. After the experiment finishes, fails, or is stopped, export that directory from
   the cloud repository root:

   ```sh
   python -m tools.run_bundle export /path/runs/experiment-01 --out experiment-01.zip
   ```

   For multiple runs in one ZIP:

   ```sh
   python -m tools.run_bundle export /path/runs/run-a /path/runs/run-b --out batch.zip
   ```

   An existing export is never overwritten. If a process died mid-write or left
   corrupt/missing evidence, export reports the problem instead of claiming a
   complete transfer. Do not delete or repair original run files just to import.
3. Copy the archive to your local computer using your existing SSH alias/file
   transfer tool. For example, run locally:

   ```sh
   scp YOUR_SSH_ALIAS:/absolute/path/to/experiment-01.zip .
   ```

4. Start the local web UI and choose **Import / open runs → Upload cloud ZIP →
   Import ZIP**. The sidebar lists every imported run. Select a node and expand
   its evidence, or use Timeline and Output & validation.

The archive layout is one named folder per run:

```text
experiment-01.zip
└── experiment-01/
    ├── events.jsonl
    ├── run_summary.json          # when available
    ├── published_artifact.json   # when available
    ├── recipe_outcomes.jsonl     # when available
    └── evidence/                # referenced planner/tool payloads
```

Other known analysis JSON files and a managed-job manifest are included when
available. DCP files, environments, keys and arbitrary workspace files are excluded.
An `events.jsonl` file by itself does not include its referenced evidence blobs.
Treat the ZIP as a private research artifact: prompts/design reports can still
contain sensitive content despite existing credential redaction.

Uploads are limited to 64 MiB compressed, 256 MiB extracted, and 4096 entries;
each evidence payload is capped at 32 MiB after decompression. Invalid paths,
links, encrypted ZIPs, mismatched summaries and corrupt evidence are rejected
before publication. Import the exporter-generated ZIP for the supported layout.
Each upload is saved under `.optimizer-framework/imports/<import-id>/<run-name>`
(or the configured workspace) and remains discoverable after a server restart.
The original source logs are preserved.

Imported runs display **Imported snapshot**, with archive name and import time.
They do not subscribe to cloud updates or enable cancellation/configuration reuse.
Analyze a newer cloud run by exporting/uploading a new ZIP. **Analysis ZIP** on
an existing run also downloads this portable format; **Report** downloads an HTML
summary, which is not an importable run archive.

For live cloud monitoring, run the UI on the cloud host next to the actual log
directory, keep it bound to loopback, and forward its port using your configured
SSH alias (`ssh -L 8765:127.0.0.1:8765 YOUR_SSH_ALIAS`). This is a separate option
from uploading a snapshot; opening a path in the local UI does not reach the cloud.

## Workflow

- Open previous runs from the sidebar or **Import / open runs**. Choose upload
  for cloud ZIPs, or host-folder access for existing files on the UI machine.
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
python -m unittest tests.test_run_bundle tests.test_web tests.test_gui tests.test_run_logging
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
