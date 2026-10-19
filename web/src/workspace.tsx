import { useCallback, useEffect, useState, type FormEvent } from "react"
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  Clock3,
  Cpu,
  FolderOpen,
  GitBranch,
  LoaderCircle,
  Plus,
  Search,
  Square,
  Terminal,
  Workflow,
} from "lucide-react"
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SearchGraph } from "@/components/search-graph"
import { RunForm } from "@/components/run-form"
import {
  activeStatuses,
  api,
  elapsed,
  linkedEvents,
  number,
  type Configuration,
  type Job,
  type RunEntry,
  type RunEvent,
  type SearchNode,
  type Settings,
  type Snapshot,
} from "@/lib/api"

function StateBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={`state-badge state-${status}`}>
      {activeStatuses.has(status) && <span className="status-dot" />}
      {status.replaceAll("_", " ")}
    </Badge>
  )
}

function EventDetail({ runId, event }: { runId: string; event: RunEvent }) {
  const [expanded, setExpanded] = useState<unknown>()
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  async function expand() {
    setBusy(true)
    setError("")
    try {
      setExpanded(await api(`/runs/${runId}/events/${event.sequence}/evidence`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3 border-t pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs">
          #{event.sequence} {event.event}
        </span>
        <Button
          variant="outline"
          size="xs"
          onClick={() => void expand()}
          disabled={busy}
        >
          {busy ? "Loading…" : "Expand evidence"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      <pre className="json-block">
        {JSON.stringify(expanded ?? event, null, 2)}
      </pre>
    </div>
  )
}

function NodeInspector({
  snapshot,
  node,
}: {
  snapshot: Snapshot
  node?: SearchNode
}) {
  const [eventId, setEventId] = useState<number>()
  if (!node)
    return (
      <aside className="inspector">
        <div className="empty-panel">
          <Search />
          <h3>Follow a decision</h3>
          <p>
            Select a checkpoint or attempt to inspect its recorded decisions and
            evidence.
          </p>
        </div>
      </aside>
    )
  const events = linkedEvents(snapshot.events, node)
  const event = events.find((e) => e.sequence === eventId)
  return (
    <aside className="inspector">
      <div className="section-heading">
        <span>DECISION INSPECTOR</span>
        <StateBadge status={node.state} />
      </div>
      <h3 className="mt-4 text-base font-semibold">
        {node.strategy || "Baseline checkpoint"}
      </h3>
      <p className="mt-1 font-mono text-[10px] break-all text-muted-foreground">
        {node.node_id}
      </p>
      <div className="detail-grid">
        <span>Selection source</span>
        <strong>{node.selection_source || "Not recorded"}</strong>
        <span>Generation / branch</span>
        <strong>
          {node.search_generation ?? "—"} / {node.search_branch ?? "—"}
        </strong>
        <span>WNS</span>
        <strong>{number(node.wns_ns)} ns</strong>
        <span>WNS change</span>
        <strong>{number(node.delta_wns_ns)} ns</strong>
        <span>Published</span>
        <strong>{node.published === true ? "Yes" : "Not recorded"}</strong>
      </div>
      <details className="mb-5 border p-3">
        <summary className="cursor-pointer text-xs">
          Checkpoint & validation fields
        </summary>
        <pre className="json-block mt-3">{JSON.stringify(node, null, 2)}</pre>
      </details>
      <p className="mb-3 text-xs text-muted-foreground">
        Recorded choices and policy reasons. Planner proposals and executed
        actions may differ.
      </p>
      <div className="event-list">
        {events.map((e) => (
          <button
            key={e.sequence}
            onClick={() => setEventId(e.sequence)}
            className={`event-button ${e.sequence === eventId ? "is-active" : ""}`}
          >
            <span className="font-mono text-[10px] text-muted-foreground">
              #{e.sequence}
            </span>
            <span className="min-w-0 truncate">
              {e.event.replaceAll("_", " ")}
            </span>
            <ChevronRight className="ml-auto size-3 shrink-0" />
          </button>
        ))}
      </div>
      {!events.length && (
        <p className="text-xs text-muted-foreground">
          No linked events were recorded.
        </p>
      )}
      {event && (
        <EventDetail key={event.sequence} runId={snapshot.id} event={event} />
      )}
    </aside>
  )
}

function Timeline({ snapshot }: { snapshot: Snapshot }) {
  const [filter, setFilter] = useState("")
  const [limit, setLimit] = useState(150)
  const [selected, setSelected] = useState<number>()
  const events = snapshot.events.filter((e) =>
    `${e.event} ${e.decision_id || ""} ${e.attempt_id || ""} ${e.candidate_id || ""}`
      .toLowerCase()
      .includes(filter.toLowerCase())
  )
  const event = snapshot.events.find((e) => e.sequence === selected)
  return (
    <div className="timeline-layout">
      <div className="min-w-0">
        <div className="mb-4 flex items-center justify-between gap-3">
          <Input
            aria-label="Filter events"
            placeholder="Filter by event or ID…"
            className="max-w-sm"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <span className="text-xs text-muted-foreground">
            {events.length} events
          </span>
        </div>
        <div className="event-table">
          <table>
            <thead>
              <tr>
                <th>Sequence</th>
                <th>Elapsed</th>
                <th>Event</th>
                <th>Decision / attempt</th>
              </tr>
            </thead>
            <tbody>
              {events
                .slice(-limit)
                .reverse()
                .map((e) => (
                  <tr
                    key={e.sequence}
                    className={selected === e.sequence ? "selected-row" : ""}
                  >
                    <td>#{e.sequence}</td>
                    <td>{elapsed(e.elapsed_seconds)}</td>
                    <td>
                      <button
                        className="text-left font-medium hover:text-primary"
                        onClick={() => setSelected(e.sequence)}
                      >
                        {e.event.replaceAll("_", " ")}
                      </button>
                    </td>
                    <td className="font-mono text-[10px]">
                      {e.decision_id || e.attempt_id || "—"}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {events.length > limit && (
          <Button
            variant="outline"
            className="mt-3"
            onClick={() => setLimit((n) => n + 150)}
          >
            Show earlier events
          </Button>
        )}
      </div>
      <div className="min-w-0">
        {event ? (
          <EventDetail key={event.sequence} runId={snapshot.id} event={event} />
        ) : (
          <div className="empty-panel">
            <Activity />
            <p>Select an event to inspect its payload and verified evidence.</p>
          </div>
        )}
      </div>
    </div>
  )
}

function Output({ snapshot }: { snapshot: Snapshot }) {
  const validation =
    snapshot.artifact.validation ?? snapshot.summary.validation ?? null
  return (
    <div className="grid gap-5 p-5 lg:grid-cols-2">
      <div>
        <h3 className="mb-3 font-semibold">Published checkpoint</h3>
        <p className="mb-4 text-xs text-muted-foreground">
          A published checkpoint can be the baseline. Timing gain, publication,
          and validation are separate results.
        </p>
        <pre className="json-block">
          {JSON.stringify(snapshot.artifact, null, 2)}
        </pre>
        <h3 className="mt-5 mb-3 font-semibold">Validation</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Ignored or missing checks do not establish a clean result.
        </p>
        <pre className="json-block">{JSON.stringify(validation, null, 2)}</pre>
      </div>
      <div>
        <h3 className="mb-3 font-semibold">Run summary</h3>
        <pre className="json-block">
          {JSON.stringify(snapshot.summary, null, 2)}
        </pre>
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-medium">
            Reproducibility manifest
          </summary>
          <pre className="json-block mt-3">
            {JSON.stringify(snapshot.manifest, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  )
}

function useRun(id: string, live: boolean) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connection, setConnection] = useState("connecting")
  const [error, setError] = useState("")
  useEffect(() => {
    const controller = new AbortController()
    let source: EventSource | undefined
    api<Snapshot>(`/runs/${id}`, undefined, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setSnapshot(data)
        setError("")
        setConnection(live ? "connecting" : "paused")
        if (!live) return
        source = new EventSource(`/api/runs/${id}/stream`)
        source.addEventListener("snapshot", (e) => {
          if (controller.signal.aborted) return
          setSnapshot(JSON.parse((e as MessageEvent).data))
          setConnection("connected")
          setError("")
        })
        source.addEventListener("read_error", (e) => {
          setError(JSON.parse((e as MessageEvent).data).detail)
          setConnection("read error")
        })
        source.onerror = () => {
          setConnection("reconnecting")
          setError(
            "Connection interrupted. Retrying automatically; the last received snapshot remains visible."
          )
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError((e as Error).message)
          setConnection("unavailable")
        }
      })
    return () => {
      controller.abort()
      source?.close()
    }
  }, [id, live])
  return { snapshot, connection, error }
}

function RunWorkspace({
  id,
  onReuse,
  onCancel,
}: {
  id: string
  onReuse: (config: Configuration) => void
  onCancel: (id: string) => Promise<void>
}) {
  const [live, setLive] = useState(true)
  const [selected, setSelected] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const { snapshot, connection, error: readError } = useRun(id, live)
  async function reuse() {
    setBusy(true)
    try {
      onReuse(await api<Configuration>(`/runs/${id}/configuration`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  if (!snapshot)
    return (
      <div className="empty-panel">
        <LoaderCircle className="animate-spin" />
        <h3>Opening run</h3>
        {readError && (
          <p className="error-banner" role="alert">
            {readError}
          </p>
        )}
      </div>
    )
  const monitor = snapshot.monitor
  const selectedId =
    selected ||
    snapshot.nodes.find((n) => n.is_best)?.node_id ||
    snapshot.nodes[0]?.node_id ||
    ""
  const node = snapshot.nodes.find((n) => n.node_id === selectedId)
  const current = snapshot.activity.at(-1)
  return (
    <>
      <header className="workspace-header">
        <div className="min-w-0">
          <div className="eyebrow">EXPERIMENT / RUN INSPECTOR</div>
          <h1
            className="mt-2 truncate text-xl font-semibold"
            title={snapshot.path}
          >
            {snapshot.name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <StateBadge status={snapshot.status} />
            <span className="font-mono text-[10px] text-muted-foreground">
              {snapshot.sequence} events
            </span>
            <span className="text-[10px] text-muted-foreground">
              {connection === "connected"
                ? "Live updates connected"
                : connection}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="outline" onClick={() => setLive((v) => !v)}>
            <Activity />
            {live ? "Pause updates" : "Follow live"}
          </Button>
          <Button
            variant="outline"
            disabled={snapshot.demo || busy}
            onClick={() => void reuse()}
          >
            <Plus />
            Reuse configuration
          </Button>
          <a
            href={`/api/runs/${id}/report`}
            className="inline-flex h-8 items-center gap-1.5 border px-2.5 text-xs font-medium hover:bg-muted"
            download
          >
            <ArrowDownToLine className="size-4" />
            Report
          </a>
          {snapshot.job && activeStatuses.has(snapshot.status) && (
            <Button
              variant="destructive"
              disabled={snapshot.status === "cancelling"}
              onClick={() => void onCancel(snapshot.job!.id)}
            >
              <Square />
              Cancel run
            </Button>
          )}
        </div>
      </header>
      {(readError || error) && (
        <p role="alert" className="error-banner mx-6 mt-4">
          {readError || error}
        </p>
      )}
      {snapshot.demo && (
        <p className="demo-banner">
          SYNTHETIC DEMONSTRATION · No FPGA tools were run. These measurements
          are for interface exploration.
        </p>
      )}
      <div className="metric-grid">
        {[
          [
            "Best observed WNS",
            number(monitor.best_wns_ns),
            "ns",
            `Initial ${number(monitor.initial_wns_ns)} ns`,
          ],
          [
            "Final Fmax",
            number(monitor.final_fmax_mhz, 1),
            "MHz",
            "From recorded final timing",
          ],
          [
            "Recorded elapsed",
            elapsed(monitor.elapsed_seconds),
            "",
            "At the latest event",
          ],
          [
            "LLM usage",
            monitor.cost_usd == null ? "—" : `$${number(monitor.cost_usd, 4)}`,
            "",
            `${monitor.llm_calls} calls · cost ${monitor.cost_verified === true ? "verified" : monitor.cost_verified === false ? "unverified" : "unknown"}`,
          ],
        ].map(([label, value, unit, caption]) => (
          <Card className="metric-card" key={label}>
            <span className="text-[11px] text-muted-foreground">{label}</span>
            <div className="my-2 font-mono text-2xl font-medium tracking-tight">
              {value}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                {unit}
              </span>
            </div>
            <span className="text-[10px] text-muted-foreground">{caption}</span>
          </Card>
        ))}
      </div>
      <div className="activity-strip">
        <Activity
          className={`size-3.5 ${snapshot.activity.length ? "text-primary" : "text-muted-foreground"}`}
        />
        <span>
          {current
            ? `${activeStatuses.has(snapshot.status) ? (current.event === "llm_call_started" ? "Planner working" : "Tool executing") : "Last unfinished call (activity unconfirmed)"} · ${String(current.tool_name || current.model || "")}`
            : activeStatuses.has(snapshot.status)
              ? "Waiting for the next recorded activity"
              : "Recorded execution history"}
        </span>
        <span className="ml-auto hidden font-mono text-[10px] sm:block">
          {String(monitor.current_action.strategy || "No strategy recorded")}
        </span>
      </div>
      <Tabs defaultValue="search" className="run-tabs">
        <div className="flex items-center justify-between border-b px-6">
          <TabsList variant="line">
            <TabsTrigger value="search">
              <GitBranch />
              Search explorer
            </TabsTrigger>
            <TabsTrigger value="timeline">
              <Activity />
              Timeline
            </TabsTrigger>
            <TabsTrigger value="output">
              <ArrowUpRight />
              Output & validation
            </TabsTrigger>
          </TabsList>
          <span className="hidden text-[10px] text-muted-foreground md:block">
            {snapshot.nodes.length} nodes · {snapshot.edges.length} branches
          </span>
        </div>
        <TabsContent value="search">
          <div className="search-layout">
            <div className="min-w-0">
              <SearchGraph
                snapshot={snapshot}
                selected={selectedId}
                onSelect={setSelected}
              />
              <div className="chart-section">
                <div className="section-heading">
                  <span>TIMING PROGRESS</span>
                  <span className="font-normal tracking-normal text-muted-foreground normal-case">
                    WNS · higher is better
                  </span>
                </div>
                {monitor.timing.length ? (
                  <div className="timing-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={monitor.timing}
                        margin={{ top: 14, right: 15, bottom: 0, left: 0 }}
                      >
                        <XAxis
                          dataKey="sequence"
                          tick={{ fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          width={46}
                          tick={{ fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          domain={["auto", "auto"]}
                        />
                        <Tooltip />
                        <Line
                          dataKey="candidate_wns_ns"
                          name="Candidate WNS"
                          stroke="var(--muted-foreground)"
                          strokeWidth={1.2}
                          dot={{ r: 2 }}
                          isAnimationActive={false}
                        />
                        <Line
                          dataKey="best_wns_ns"
                          name="Best WNS"
                          stroke="var(--primary)"
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="py-7 text-xs text-muted-foreground">
                    No candidate timing recorded yet.
                  </p>
                )}
              </div>
            </div>
            <NodeInspector key={selectedId} snapshot={snapshot} node={node} />
          </div>
        </TabsContent>
        <TabsContent value="timeline" className="p-5">
          <Timeline snapshot={snapshot} />
        </TabsContent>
        <TabsContent value="output">
          <Output snapshot={snapshot} />
        </TabsContent>
      </Tabs>
    </>
  )
}

function JobWorkspace({
  job,
  onCancel,
}: {
  job: Job
  onCancel: (id: string) => Promise<void>
}) {
  const [consoleText, setConsoleText] = useState("")
  const [error, setError] = useState("")
  useEffect(() => {
    let cancelled = false
    async function read() {
      try {
        const data = await api<{ text: string }>(`/jobs/${job.id}/console`)
        if (!cancelled) {
          setConsoleText(data.text)
          setError("")
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    }
    void read()
    const timer = setInterval(() => void read(), 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [job.id])
  return (
    <div className="p-6">
      <div className="eyebrow">EXPERIMENT / JOB</div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">
          {job.config.input_dcp.split(/[\\/]/).at(-1)}
        </h1>
        <StateBadge status={job.status} />
        {activeStatuses.has(job.status) && (
          <Button
            variant="destructive"
            disabled={job.status === "cancelling"}
            onClick={() => void onCancel(job.id)}
          >
            Cancel job
          </Button>
        )}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        The run inspector opens here automatically when the optimizer creates
        its event log.
      </p>
      {(error || job.error) && (
        <p className="error-banner mt-4" role="alert">
          {error || job.error}
        </p>
      )}
      <div className="mt-6 flex items-center gap-2 text-xs font-medium">
        <Terminal className="size-4" />
        Console · exit code {job.exit_code ?? "—"}
      </div>
      <pre className="console-block mt-3">
        {consoleText || "No console output yet."}
      </pre>
    </div>
  )
}

export default function Workspace() {
  const [runs, setRuns] = useState<RunEntry[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [settings, setSettings] = useState<Settings>()
  const [selected, setSelected] = useState("")
  const [search, setSearch] = useState("")
  const [error, setError] = useState("")
  const [loaded, setLoaded] = useState(false)
  const [newRun, setNewRun] = useState(false)
  const [draft, setDraft] = useState<Configuration>()
  const [openFolder, setOpenFolder] = useState(false)
  const [folder, setFolder] = useState("")
  const [folderError, setFolderError] = useState("")
  const [opening, setOpening] = useState(false)
  const refresh = useCallback(async () => {
    try {
      const [r, j, s] = await Promise.all([
        api<RunEntry[]>("/runs"),
        api<{ jobs: Job[] }>("/jobs"),
        api<Settings>("/settings"),
      ])
      setRuns(r)
      setJobs(j.jobs)
      setSettings(s)
      setError("")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoaded(true)
    }
  }, [])
  useEffect(() => {
    const initial = setTimeout(() => void refresh(), 0)
    const timer = setInterval(() => void refresh(), 3000)
    return () => {
      clearTimeout(initial)
      clearInterval(timer)
    }
  }, [refresh])
  async function importFolder(e: FormEvent) {
    e.preventDefault()
    setOpening(true)
    setFolderError("")
    try {
      const result = await api<{ id: string }>("/runs/open", { path: folder })
      await refresh()
      setSelected(result.id)
      setOpenFolder(false)
      setFolderError("")
    } catch (e) {
      setFolderError((e as Error).message)
    } finally {
      setOpening(false)
    }
  }
  async function cancel(id: string) {
    try {
      await api(`/jobs/${id}/cancel`, {})
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const selection =
    selected || runs[0]?.id || (jobs[0] ? `job:${jobs[0].id}` : "")
  const selectedJob = jobs.find((j) => `job:${j.id}` === selection)
  const selectedRun = runs.find(
    (r) => r.id === selection || (selectedJob && r.job_id === selectedJob.id)
  )
  const unlinkedJobs = jobs.filter((j) => !runs.some((r) => r.job_id === j.id))
  const visibleRuns = runs.filter((r) =>
    `${r.name} ${r.path}`.toLowerCase().includes(search.toLowerCase())
  )
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <Workflow className="size-5" />
          </div>
          <div>
            <strong>Optimizer</strong>
            <span>EXPERIMENT WORKSPACE</span>
          </div>
        </div>
        <div className="sidebar-actions">
          <Button
            className="w-full"
            disabled={!settings}
            onClick={() => {
              setDraft(undefined)
              setNewRun(true)
            }}
          >
            <Plus />
            New experiment
          </Button>
          <Button
            variant="outline"
            className="mt-2 w-full"
            onClick={() => setOpenFolder(true)}
          >
            <FolderOpen />
            Open run folder
          </Button>
        </div>
        <div className="px-4">
          <div className="relative">
            <Search className="absolute top-2.5 left-2.5 size-3 text-muted-foreground" />
            <Input
              aria-label="Search runs"
              className="pl-8"
              placeholder="Find an experiment…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
        <div className="sidebar-section">
          <span>EXPERIMENTS</span>
          <span>{runs.length + unlinkedJobs.length}</span>
        </div>
        <nav aria-label="Experiments" className="run-navigation">
          {unlinkedJobs
            .filter((j) =>
              j.config.input_dcp.toLowerCase().includes(search.toLowerCase())
            )
            .map((j) => (
              <button
                key={j.id}
                className={`run-link ${selection === `job:${j.id}` ? "is-active" : ""}`}
                onClick={() => setSelected(`job:${j.id}`)}
              >
                <Clock3 className="size-4 shrink-0" />
                <div className="min-w-0">
                  <strong>{j.config.input_dcp.split(/[\\/]/).at(-1)}</strong>
                  <span>
                    {j.status} · {j.id.slice(0, 8)}
                  </span>
                </div>
              </button>
            ))}
          {visibleRuns.map((r) => (
            <button
              key={r.id}
              className={`run-link ${selectedRun?.id === r.id ? "is-active" : ""}`}
              onClick={() => setSelected(r.id)}
            >
              <GitBranch className="size-4 shrink-0" />
              <div className="min-w-0">
                <strong title={r.path}>{r.name}</strong>
                <span>{r.job_id ? "Managed experiment" : "Recorded run"}</span>
              </div>
              <ChevronRight className="ml-auto size-3 shrink-0" />
            </button>
          ))}
          {loaded && !runs.length && !jobs.length && (
            <p className="p-4 text-xs leading-relaxed text-muted-foreground">
              Open an existing run folder or start your first experiment.
            </p>
          )}
          {loaded &&
            search &&
            !visibleRuns.length &&
            !unlinkedJobs.some((j) =>
              j.config.input_dcp.toLowerCase().includes(search.toLowerCase())
            ) && (
              <p className="p-4 text-xs text-muted-foreground">
                No matching experiments.
              </p>
            )}
        </nav>
        <div className="sidebar-footer">
          <Cpu className="size-4" />
          <div>
            <strong>Local execution host</strong>
            <span>
              {jobs.filter((j) => activeStatuses.has(j.status)).length} active
              jobs · browser independent
            </span>
          </div>
        </div>
      </aside>
      <main className="workspace">
        {error && (
          <div role="alert" className="error-banner m-4">
            {error}
            <Button
              size="xs"
              variant="outline"
              className="ml-3"
              onClick={() => void refresh()}
            >
              Retry
            </Button>
          </div>
        )}
        {selectedRun ? (
          <RunWorkspace
            key={selectedRun.id}
            id={selectedRun.id}
            onReuse={(c) => {
              setDraft(c)
              setNewRun(true)
            }}
            onCancel={cancel}
          />
        ) : selectedJob ? (
          <JobWorkspace
            key={selectedJob.id}
            job={selectedJob}
            onCancel={cancel}
          />
        ) : (
          <div className="welcome">
            <div className="welcome-icon">
              <Workflow />
            </div>
            <div className="eyebrow">YOUR SEARCH, MADE VISIBLE</div>
            <h1>
              Every branch.
              <br />
              Every decision.
            </h1>
            <p>
              Launch an optimization or open a previous run to explore
              checkpoint ancestry, planner choices, and tool evidence in one
              place.
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              <Button
                disabled={!settings}
                onClick={() => {
                  setDraft(undefined)
                  setNewRun(true)
                }}
              >
                <Plus />
                New experiment
              </Button>
              <Button variant="outline" onClick={() => setOpenFolder(true)}>
                <FolderOpen />
                Open run folder
              </Button>
            </div>
            <div className="mt-10 flex flex-wrap justify-center gap-5 text-xs text-muted-foreground">
              <span className="flex items-center gap-2">
                <GitBranch className="size-3.5" />
                Search ancestry
              </span>
              <span className="flex items-center gap-2">
                <Activity className="size-3.5" />
                Live execution
              </span>
              <span className="flex items-center gap-2">
                <Terminal className="size-3.5" />
                Recorded evidence
              </span>
            </div>
            {!loaded && <LoaderCircle className="mt-6 size-4 animate-spin" />}
          </div>
        )}
      </main>
      <Dialog open={newRun} onOpenChange={setNewRun}>
        {settings && (
          <RunForm
            key={JSON.stringify(draft || null) + String(newRun)}
            settings={settings}
            initial={draft}
            onQueued={(id) => {
              setSelected(`job:${id}`)
              setNewRun(false)
              void refresh()
            }}
          />
        )}
      </Dialog>
      <Dialog open={openFolder} onOpenChange={setOpenFolder}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Open run folder</DialogTitle>
            <DialogDescription>
              Enter a run folder containing events.jsonl, or its parent folder,
              on the execution host.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={importFolder} className="space-y-4">
            <Label htmlFor="run-folder">Folder path</Label>
            <Input
              id="run-folder"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder="Absolute path to your run folder"
              required
            />
            {folderError && (
              <p className="error-banner" role="alert">
                {folderError}
              </p>
            )}
            <div className="flex items-center justify-between">
              <Button
                variant="ghost"
                type="button"
                onClick={() => setOpenFolder(false)}
              >
                <ArrowLeft />
                Back
              </Button>
              <Button type="submit" disabled={opening}>
                {opening ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <FolderOpen />
                )}
                Open folder
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
