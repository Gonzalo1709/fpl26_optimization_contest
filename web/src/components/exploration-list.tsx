import { Trophy } from "lucide-react"
import { number, type SearchNode } from "@/lib/api"
import { nodeGroups, type Grouping, type NodeAnalysis } from "@/lib/exploration"

export function ExplorationList({
  nodes,
  analysis,
  grouping,
  onGrouping,
  selected,
  onSelect,
}: {
  nodes: SearchNode[]
  analysis: Map<string, NodeAnalysis>
  grouping: Grouping
  onGrouping: (value: Grouping) => void
  selected: string
  onSelect: (id: string) => void
}) {
  return (
    <section
      aria-label="Exploration nodes"
      className="exploration-list border-t"
    >
      <div className="graph-analysis-controls">
        <label>
          Group{" "}
          <select
            aria-label="Group nodes"
            value={grouping}
            onChange={(e) => onGrouping(e.target.value as Grouping)}
          >
            <option value="generation">Generation</option>
            <option value="decision">Decision</option>
            <option value="depth">Depth</option>
          </select>
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[10px]">
          <thead className="text-muted-foreground">
            <tr>
              <th>Node</th>
              <th>Decision</th>
              <th>Fmax</th>
              <th>Comparison</th>
            </tr>
          </thead>
          {nodeGroups(nodes, grouping, analysis).map(([group, members]) => (
            <tbody key={group} aria-label={group}>
              <tr>
                <th colSpan={4} className="bg-muted/40 font-medium">
                  {group}
                </th>
              </tr>
              {members.map((node) => (
                <tr
                  key={node.node_id}
                  data-node-id={node.node_id}
                  className={selected === node.node_id ? "bg-primary/5" : ""}
                >
                  <td>
                    <button
                      className="flex items-center gap-1.5 text-primary hover:underline"
                      aria-label={`Select ${node.local_node_id || node.node_id}`}
                      onClick={() => onSelect(node.node_id)}
                    >
                      <span className="max-w-28 truncate font-mono">
                        {node.local_node_id || node.node_id}
                      </span>
                      {node.is_best && (
                        <Trophy
                          className="size-3 shrink-0"
                          aria-label="Best observed Fmax"
                        />
                      )}
                    </button>
                    {node.manual && (
                      <span className="text-[9px] text-sky-600">Manual</span>
                    )}
                  </td>
                  <td>{node.strategy || "Baseline"}</td>
                  <td className="font-mono whitespace-nowrap">
                    {number(node.fmax_mhz, 1)} MHz
                  </td>
                  <td className="whitespace-nowrap text-muted-foreground">
                    {analysis.get(node.node_id)?.caption}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  )
}
