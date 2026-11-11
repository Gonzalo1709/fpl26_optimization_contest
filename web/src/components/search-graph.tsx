import { useEffect, useMemo } from "react"
import dagre from "@dagrejs/dagre"
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  useReactFlow,
  useStore,
  getNodesBounds,
  getViewportForBounds,
  type Node,
  type NodeProps,
} from "@xyflow/react"
import { GitBranch, LoaderCircle, Trophy } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { number, type SearchNode, type Snapshot } from "@/lib/api"
import "@xyflow/react/dist/style.css"

type CandidateNode = Node<{ record: SearchNode }, "candidate">

function Candidate({ data, selected }: NodeProps<CandidateNode>) {
  const n = data.record
  const initialFmax =
    n.fmax_mhz != null && n.fmax_improvement_mhz != null
      ? n.fmax_mhz - n.fmax_improvement_mhz
      : null
  const change =
    initialFmax && initialFmax > 0 && n.fmax_improvement_mhz != null
      ? (n.fmax_improvement_mhz / initialFmax) * 100
      : null
  return (
    <div
      className={`candidate-card ${selected ? "is-selected" : ""} ${n.is_best ? "is-best" : ""} ${n.state === "failed" ? "is-failed" : ""} ${n.manual ? "is-manual" : ""}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="flex items-center justify-between gap-2">
        <span className="node-label min-w-0 flex-1">
          {n.strategy || (n.parent_node_id ? "Checkpoint" : "Baseline")}
        </span>
        {n.is_best ? (
          <Trophy className="size-3.5 text-emerald-700" />
        ) : n.state === "running" ? (
          <LoaderCircle className="size-3.5 animate-spin text-primary" />
        ) : (
          <GitBranch className="size-3.5 text-muted-foreground" />
        )}
      </div>
      <div
        className="mt-2 flex items-center gap-3"
        title="Theoretical Fmax from target-clock timing"
      >
        <div className="min-w-0 flex-1 text-center">
          <div className="flex items-baseline justify-center gap-1 font-mono text-xl font-semibold">
            {number(n.fmax_mhz, 1)}
            <span className="text-[9px] font-normal text-muted-foreground">
              MHz
            </span>
          </div>
          <div
            className={`mt-0.5 text-[9px] ${change != null && change > 0 ? "text-emerald-600" : "text-muted-foreground"}`}
          >
            {change == null
              ? "Fmax"
              : change === 0
                ? "Initial Fmax"
                : `${number(Math.abs(change), 1)}% ${change > 0 ? "higher" : "lower"}`}
          </div>
        </div>
        <div className="shrink-0 text-right font-mono text-[9px] text-muted-foreground">
          <span className="block">WNS</span>
          <span>{number(n.wns_ns)} ns</span>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span
          className="truncate font-mono text-[10px] text-muted-foreground"
          title={n.local_node_id || n.node_id}
        >
          {n.node_type === "manual_execution"
            ? "Experiment"
            : (n.local_node_id || n.node_id).slice(0, 14)}
        </span>
        <Badge
          variant="outline"
          className={n.in_beam ? "border-primary/50 text-primary" : ""}
        >
          {n.manual
            ? `Manual · ${(n.job_status || n.state).replaceAll("_", " ")}`
            : n.is_best
              ? "Best"
              : n.in_beam
                ? "Beam"
                : n.state.replaceAll("_", " ")}
        </Badge>
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}
const nodeTypes = { candidate: Candidate }

function FitOnResize({
  bounds,
}: {
  bounds: { x: number; y: number; width: number; height: number }
}) {
  const { x, y, width: boundsWidth, height: boundsHeight } = bounds
  const width = useStore((state) => state.width)
  const height = useStore((state) => state.height)
  const { setViewport, viewportInitialized } = useReactFlow()
  useEffect(() => {
    if (width && height && viewportInitialized)
      void setViewport(
        getViewportForBounds(
          { x, y, width: boundsWidth, height: boundsHeight },
          width,
          height,
          0.15,
          1,
          0.22
        )
      )
  }, [
    width,
    height,
    x,
    y,
    boundsWidth,
    boundsHeight,
    setViewport,
    viewportInitialized,
  ])
  return null
}

export function SearchGraph({
  snapshot,
  selected,
  onSelect,
}: {
  snapshot: Snapshot
  selected: string
  onSelect: (id: string) => void
}) {
  // Metric-only updates do not move the layout or reset the user's viewport.
  const topology = JSON.stringify({
    nodes: snapshot.nodes.map((n) => n.node_id),
    edges: snapshot.edges.map((e) => [e.source_id, e.target_id]),
  })
  const positions = useMemo(() => {
    const shape = JSON.parse(topology) as {
      nodes: string[]
      edges: [string, string][]
    }
    const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
    graph.setGraph({
      rankdir: "LR",
      nodesep: 28,
      ranksep: 80,
      marginx: 24,
      marginy: 24,
    })
    shape.nodes.forEach((id) => graph.setNode(id, { width: 208, height: 118 }))
    shape.edges.forEach(([a, b]) => graph.setEdge(a, b))
    dagre.layout(graph)
    return Object.fromEntries(
      shape.nodes.map((id) => [
        id,
        { x: graph.node(id).x - 104, y: graph.node(id).y - 59 },
      ])
    )
  }, [topology])
  const nodes: CandidateNode[] = snapshot.nodes.map((record) => ({
    id: record.node_id,
    type: "candidate",
    position: positions[record.node_id],
    data: { record },
    selected: record.node_id === selected,
    ariaLabel: `${record.strategy || (record.parent_node_id ? "Checkpoint" : "Baseline")} ${record.node_id} ${record.state}`,
  }))
  const edges = snapshot.edges.map((e) => ({
    id: `${e.source_id}-${e.target_id}`,
    source: e.source_id,
    target: e.target_id,
    type: "smoothstep",
    animated: snapshot.nodes.some(
      (n) => n.node_id === e.target_id && n.state === "running"
    ),
    label: e.strategy?.replaceAll("_", " "),
    markerEnd: { type: MarkerType.ArrowClosed },
    style: {
      stroke: e.manual ? "#0ea5e9" : "var(--muted-foreground)",
      strokeWidth: e.manual ? 1.8 : 1.2,
      strokeDasharray: e.manual ? "6 4" : undefined,
    },
    labelStyle: { fontSize: 10, fill: "var(--muted-foreground)" },
    labelBgStyle: { fill: "var(--background)" },
  }))
  if (!nodes.length)
    return (
      <div className="empty-panel">
        <GitBranch />
        <h3>Waiting for the first candidate</h3>
        <p>
          Planner and tool activity will appear in the timeline as events
          arrive.
        </p>
      </div>
    )
  return (
    <div className="graph-canvas" aria-label="Search ancestry graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.22, maxZoom: 1 }}
        minZoom={0.15}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={(_, n) => onSelect(n.id)}
        onEdgeClick={(_, e) => onSelect(e.target)}
        onNodesChange={(changes) => {
          const selection = changes.find(
            (change) => change.type === "select" && change.selected
          )
          if (selection?.type === "select" && selection.id !== selected)
            onSelect(selection.id)
        }}
      >
        <FitOnResize
          bounds={getNodesBounds(
            nodes.map((node) => ({ ...node, width: 208, height: 118 }))
          )}
        />
        <Background gap={20} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
        <MiniMap<CandidateNode>
          pannable
          zoomable
          nodeColor={(n) => (n.data.record.is_best ? "#047857" : "#a1a1aa")}
        />
        <Panel position="top-left">
          <div className="graph-caption">
            CHECKPOINT ANCESTRY <span>Parent → explored branch</span>
            {snapshot.nodes.some((n) => n.manual) && (
              <span className="text-sky-700 dark:text-sky-300">
                Dashed blue · Manual
              </span>
            )}
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}
