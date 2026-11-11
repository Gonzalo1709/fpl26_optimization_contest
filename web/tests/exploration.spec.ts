import { expect, test } from "@playwright/test"
import {
  analyzeNodes,
  nodeGroups,
  orderedNodes,
  tracePath,
} from "../src/lib/exploration"
import type { SearchNode } from "../src/lib/api"

const node = (
  id: string,
  parent: string | undefined,
  fmax: number | null,
  extra: Partial<SearchNode> = {}
): SearchNode => ({
  node_id: id,
  parent_node_id: parent,
  node_type: "candidate",
  fmax_mhz: fmax,
  state: "candidate",
  in_beam: false,
  is_best: false,
  ...extra,
})
const nodes = [
  node("root", undefined, 300, { generation: 0 }),
  node("middle", "root", 250, { search_generation: 1 }),
  node("auto", "middle", 330, { strategy: "ROUTE", search_generation: 2 }),
  node("manual", "middle", 375, {
    manual: true,
    generation: 1,
    strategy: "PHYS_OPT",
    is_best: true,
  }),
  node("pending", "middle", 999, {
    node_type: "manual_execution",
    state: "queued",
    manual: true,
  }),
]

test("references distinguish local progress, overall progress and the observed best", () => {
  expect(analyzeNodes(nodes, "parent").get("manual")?.caption).toBe(
    "50.0% higher than parent"
  )
  expect(analyzeNodes(nodes, "initial").get("manual")?.caption).toBe(
    "25.0% higher than initial"
  )
  expect(analyzeNodes(nodes, "best").get("auto")?.caption).toBe(
    "12.0% lower than best"
  )
  expect(analyzeNodes(nodes, "best").get("manual")?.caption).toBe(
    "Current best"
  )
  expect(analyzeNodes(nodes, "parent").get("middle")?.caption).toBe(
    "16.7% lower than parent"
  )
})

test("alternatives are measured siblings and exclude the checkpoint itself and queued work", () => {
  const analysis = analyzeNodes(nodes, "alternative")
  expect(analysis.get("auto")?.caption).toBe("12.0% lower than alternative")
  expect(analysis.get("manual")?.caption).toBe("13.6% higher than alternative")
  expect(analysis.get("middle")?.caption).toBe("Alternative unavailable")
  expect(analysis.get("pending")?.percent).toBeNull()
  expect(
    analyzeNodes(
      [node("root", undefined, 0), node("child", "root", 400)],
      "parent"
    ).get("child")?.percent
  ).toBeNull()
})

test("comparison ordering retains unknown work last and does not mutate exploration order", () => {
  const analysis = analyzeNodes(nodes, "parent")
  expect(orderedNodes(nodes, "change", analysis).map((n) => n.node_id)).toEqual(
    ["manual", "auto", "middle", "root", "pending"]
  )
  expect(orderedNodes(nodes, "fmax", analysis).map((n) => n.node_id)).toEqual([
    "manual",
    "auto",
    "root",
    "middle",
    "pending",
  ])
  expect(
    orderedNodes(nodes, "explored", analysis).map((n) => n.node_id)
  ).toEqual(nodes.map((n) => n.node_id))
})

test("grouping uses recorded generations, recipes, and the actual cross-run ancestry", () => {
  const analysis = analyzeNodes(nodes, "parent")
  const generations = new Map(nodeGroups(nodes, "generation", analysis))
  expect(
    generations.get("Manual · Generation 1")?.map((n) => n.node_id)
  ).toEqual(["manual"])
  expect(
    generations.get("Generation not recorded")?.map((n) => n.node_id)
  ).toEqual(["pending"])
  expect(
    new Map(nodeGroups(nodes, "decision", analysis)).get("PHYS_OPT")?.[0]
      .node_id
  ).toBe("manual")
  expect(
    new Map(nodeGroups(nodes, "depth", analysis))
      .get("Depth 2")
      ?.map((n) => n.node_id)
  ).toEqual(["auto", "manual", "pending"])
  expect([...tracePath(nodes, "manual")]).toEqual(["manual", "middle", "root"])
  expect(tracePath(nodes, "absent").size).toBe(0)
})
