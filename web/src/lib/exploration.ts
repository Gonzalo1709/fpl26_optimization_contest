import { number, type SearchNode } from "./api"

export type Comparison = "parent" | "initial" | "alternative" | "best"
export type Ordering = "explored" | "fmax" | "change"
export type Grouping = "generation" | "decision" | "depth"
export type NodeAnalysis = {
  percent: number | null
  caption: string
  depth: number
}

export function analyzeNodes(nodes: SearchNode[], comparison: Comparison) {
  const byId = new Map(nodes.map((n) => [n.node_id, n]))
  const initial = nodes.find(
    (n) => !n.parent_node_id && n.node_type === "candidate"
  )
  const best = nodes.find((n) => n.is_best)
  const depths = new Map<string, number>()
  function depth(id: string, visiting = new Set<string>()): number {
    if (depths.has(id)) return depths.get(id)!
    const parent = byId.get(id)?.parent_node_id
    if (!parent || !byId.has(parent) || visiting.has(id)) return 0
    visiting.add(id)
    const value = depth(parent, visiting) + 1
    depths.set(id, value)
    return value
  }
  function frequency(node: SearchNode | undefined) {
    return node?.node_type === "candidate" &&
      typeof node.fmax_mhz === "number" &&
      Number.isFinite(node.fmax_mhz) &&
      node.fmax_mhz > 0
      ? node.fmax_mhz
      : null
  }
  return new Map(
    nodes.map((node): [string, NodeAnalysis] => {
      let reference =
        comparison === "parent"
          ? byId.get(node.parent_node_id || "")
          : comparison === "best"
            ? best
            : initial
      if (comparison === "alternative") {
        reference = nodes
          .filter(
            (sibling) =>
              !!node.parent_node_id &&
              sibling.parent_node_id === node.parent_node_id &&
              sibling.node_id !== node.node_id &&
              frequency(sibling) !== null
          )
          .sort((a, b) => b.fmax_mhz! - a.fmax_mhz!)[0]
      }
      const current = frequency(node),
        target = frequency(reference)
      const percent =
        current !== null && target !== null
          ? ((current - target) / target) * 100
          : null
      const caption =
        current === null
          ? "Not measured"
          : comparison === "parent" && !node.parent_node_id
            ? "Initial Fmax"
            : !reference || target === null
              ? `${comparison === "alternative" ? "Alternative" : "Reference"} unavailable`
              : reference.node_id === node.node_id
                ? comparison === "best"
                  ? "Current best"
                  : "Initial Fmax"
                : `${number(Math.abs(percent!), 1)}% ${percent! > 0 ? "higher than" : percent! < 0 ? "lower than" : "same as"} ${comparison}`
      return [node.node_id, { percent, caption, depth: depth(node.node_id) }]
    })
  )
}

export function orderedNodes(
  nodes: SearchNode[],
  order: Ordering,
  analysis: Map<string, NodeAnalysis>
) {
  if (order === "explored") return [...nodes]
  const score = (n: SearchNode) => {
    const value =
      order === "fmax"
        ? n.node_type === "candidate" && n.fmax_mhz != null && n.fmax_mhz > 0
          ? n.fmax_mhz
          : null
        : analysis.get(n.node_id)?.percent
    return typeof value === "number" && Number.isFinite(value) ? value : null
  }
  return [...nodes].sort((a, b) => {
    const first = score(a),
      second = score(b)
    return first == null
      ? second == null
        ? 0
        : 1
      : second == null
        ? -1
        : second - first
  })
}

export function tracePath(nodes: SearchNode[], selected: string) {
  const byId = new Map(nodes.map((n) => [n.node_id, n]))
  const path = new Set<string>()
  let current: SearchNode | undefined = byId.get(selected)
  while (current && !path.has(current.node_id)) {
    path.add(current.node_id)
    current = byId.get(current.parent_node_id || "")
  }
  return path
}

export function nodeGroups(
  nodes: SearchNode[],
  grouping: Grouping,
  analysis: Map<string, NodeAnalysis>
) {
  const groups = new Map<string, SearchNode[]>()
  for (const node of nodes) {
    const generation = node.search_generation ?? node.generation
    const label =
      grouping === "decision"
        ? node.strategy || (node.parent_node_id ? "Checkpoint" : "Baseline")
        : grouping === "depth"
          ? `Depth ${analysis.get(node.node_id)?.depth ?? 0}`
          : generation == null
            ? "Generation not recorded"
            : `${node.manual ? "Manual · " : ""}Generation ${generation}`
    groups.set(label, [...(groups.get(label) || []), node])
  }
  return [...groups].sort(([a], [b]) =>
    a.localeCompare(b, undefined, { numeric: true })
  )
}
