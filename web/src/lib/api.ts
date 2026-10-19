export type Fields = Record<string, unknown>
export type RunEvent = Fields & {
  sequence: number
  event: string
  elapsed_seconds?: number
  timestamp_utc?: string
  candidate_id?: string
  decision_id?: string
  attempt_id?: string
  policy_eval_id?: string
}
export type SearchNode = Fields & {
  node_id: string
  node_type: string
  parent_node_id?: string
  candidate_id?: string
  attempt_id?: string
  decision_id?: string
  strategy?: string
  wns_ns?: number | null
  delta_wns_ns?: number | null
  search_generation?: number
  search_branch?: number
  selection_source?: string
  state: string
  in_beam: boolean
  is_best: boolean
}
export type RunEntry = {
  id: string
  name: string
  path: string
  job_id: string | null
  source: "imported" | "managed" | "folder"
}
export type Configuration = {
  input_dcp: string
  python: string
  mode: string
  profile: string
  model: string
  max_runtime_minutes: number
  max_cost: number | null
  method: string
  advanced: Fields
  schema_version?: number
}
export type Job = {
  id: string
  status: string
  config: Configuration
  created: number
  directory: string
  error: string | null
  exit_code: number | null
}
export type Snapshot = {
  id: string
  name: string
  path: string
  status: string
  sequence: number
  demo: boolean
  imported: {
    source_archive: string
    imported_at_utc: string
    snapshot: boolean
  } | null
  job: Job | null
  summary: Fields
  artifact: Fields
  manifest: Fields
  monitor: {
    initial_wns_ns: number | null
    best_wns_ns: number | null
    final_fmax_mhz: number | null
    elapsed_seconds: number | null
    cost_usd: number | null
    llm_calls: number
    cost_verified: boolean | null
    budget: Fields
    latest_beam: Fields
    current_action: Fields
    timing: {
      sequence: number
      candidate_wns_ns: number
      best_wns_ns: number
    }[]
  }
  nodes: SearchNode[]
  edges: { source_id: string; target_id: string; strategy?: string }[]
  events: RunEvent[]
  activity: RunEvent[]
}
export type Settings = {
  workspace: string
  roots: string[]
  defaults: Configuration
  profiles: string[]
  methods: string[]
}

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    signal,
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-Optimizer-Client": "web" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail)
    )
  return data as T
}

export async function uploadBundle(
  file: File
): Promise<{ id: string; count: number }> {
  const response = await fetch("/api/runs/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/zip",
      "X-Optimizer-Client": "web",
      "X-Optimizer-Filename": encodeURIComponent(file.name),
    },
    body: file,
  })
  const data = await response.json()
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Cannot import this analysis ZIP"
    )
  return data
}

export const number = (value: unknown, digits = 3) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—"

export function elapsed(value: number | null | undefined) {
  if (value == null) return "—"
  const seconds = Math.floor(value)
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

export const activeStatuses = new Set([
  "queued",
  "starting",
  "running",
  "cancelling",
  "orphaned",
])

export function linkedEvents(events: RunEvent[], node: SearchNode) {
  const policyIds = new Set(
    events
      .filter((e) => node.decision_id && e.decision_id === node.decision_id)
      .map((e) => e.policy_eval_id)
      .filter(Boolean)
  )
  return events.filter(
    (e) =>
      (node.decision_id && e.decision_id === node.decision_id) ||
      (node.attempt_id && e.attempt_id === node.attempt_id) ||
      (node.candidate_id &&
        [
          "candidate_id",
          "seed_candidate_id",
          "parent_candidate_id",
          "best_candidate_id",
        ].some((key) => e[key] === node.candidate_id)) ||
      (e.policy_eval_id && policyIds.has(e.policy_eval_id))
  )
}
