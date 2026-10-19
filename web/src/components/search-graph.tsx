import { useMemo } from "react"
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
  return (
    <div
      className={`candidate-card ${selected ? "is-selected" : ""} ${n.is_best ? "is-best" : ""} ${n.state === "failed" ? "is-failed" : ""}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="flex items-center justify-between gap-2">
        <span className="node-label">{n.strategy || "Baseline"}</span>
        {n.is_best ? (
          <Trophy className="size-3.5 text-emerald-700" />
        ) : n.state === "running" ? (
          <LoaderCircle className="size-3.5 animate-spin text-primary" />
        ) : (
          <GitBranch className="size-3.5 text-muted-foreground" />
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1 font-mono text-lg font-semibold">
        {number(n.wns_ns)}
        <span className="text-[10px] font-normal text-muted-foreground">
          ns WNS
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span
          className="truncate font-mono text-[10px] text-muted-foreground"
          title={n.node_id}
        >
          {n.node_id.slice(0, 14)}
        </span>
        <Badge
          variant="outline"
          className={n.in_beam ? "border-primary/50 text-primary" : ""}
        >
          {n.is_best
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
    ariaLabel: `${record.strategy || "Baseline"} ${record.node_id} ${record.state}`,
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
    style: { stroke: "var(--muted-foreground)", strokeWidth: 1.2 },
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
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}
