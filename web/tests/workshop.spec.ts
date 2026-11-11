import { expect, test } from "@playwright/test"
import path from "node:path"

test("node selection drives Workshop beside the tree without losing the recipe draft", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000)
  await page.goto("/")
  await page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "demo-run-2" })
    .click()
  await expect(page.getByRole("heading", { name: "demo-run-2" })).toBeVisible()
  const candidate = page.locator(".react-flow__node").filter({ hasText: "c1" })
  await expect(candidate).toContainText("357.1")
  await expect(candidate).toContainText("7.1% higher")
  await expect(candidate).toContainText("than parent")
  const frequencyBox = await candidate.locator(".text-xl").boundingBox()
  const labelBox = await candidate.locator(".node-label").boundingBox()
  expect(Math.abs(frequencyBox!.x - labelBox!.x)).toBeLessThan(1)
  await expect(candidate).toContainText("WNS")
  await expect(
    page.getByRole("tab", { name: /Playground|Workshop/ })
  ).toHaveCount(0)
  await expect(candidate.getByRole("button", { name: /Run from/ })).toHaveCount(
    0
  )
  await candidate.click()
  const workshop = page.getByRole("complementary", {
    name: "Workshop",
    exact: true,
  })
  const graph = page.getByLabel("Search ancestry graph", { exact: true })
  await expect(workshop).toBeVisible()
  await expect(graph).toBeVisible()
  await expect(
    workshop.getByRole("button", { name: "Run sequence" })
  ).toBeDisabled()
  await expect(
    workshop.getByRole("combobox", { name: "Checkpoint" })
  ).toHaveCount(0)

  await page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "Workshop example" })
    .click()
  const baseline = page
    .locator(".react-flow__node")
    .filter({ hasText: "baseline" })
  const middle = page.locator(".react-flow__node").filter({ hasText: "middle" })
  await expect(baseline).toContainText("333.3")
  await expect(middle).toContainText("285.7")
  await expect(middle).toContainText("14.3% lower")
  await expect(middle.locator(".text-xl")).not.toContainText("-")
  await middle.click()
  await expect(workshop).toBeVisible()
  await expect(workshop.getByTestId("workshop-source")).toHaveText("middle")
  await expect(graph).toBeVisible()
  const graphBox = await graph.boundingBox()
  const panelBox = await workshop.boundingBox()
  expect(graphBox!.x + graphBox!.width).toBeLessThanOrEqual(panelBox!.x + 1)

  await workshop.getByLabel("Recipe", { exact: true }).selectOption("phys-opt")
  await workshop
    .getByRole("button", { name: "Add recipe", exact: true })
    .click()
  await workshop
    .getByLabel("directive", { exact: true })
    .selectOption("Explore")
  await workshop.getByLabel("Recipe", { exact: true }).selectOption("fanout")
  await workshop
    .getByRole("button", { name: "Add recipe", exact: true })
    .click()
  await workshop.getByLabel("top n nets", { exact: true }).fill("2")
  await workshop
    .getByRole("button", { name: "Move step 2 up", exact: true })
    .click()
  const list = workshop.getByRole("list", { name: "Recipe sequence" })
  await expect(list.getByRole("listitem").first()).toContainText(
    "Fanout optimization"
  )
  await list
    .getByRole("listitem")
    .first()
    .dragTo(list.getByRole("listitem").last())
  await expect(list.getByRole("listitem").first()).toContainText(
    "Physical optimization"
  )

  // The graph remains interactive while the same editor keeps its draft.
  await baseline.click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText("baseline")
  await expect(list.getByRole("listitem")).toHaveCount(2)
  await middle.click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText("middle")
  await page
    .getByRole("button", { name: "Close Workshop", exact: true })
    .click()
  await expect(workshop).toBeHidden()
  await expect(graph).toBeVisible()
  await middle.click()
  await expect(workshop).toBeVisible()
  await expect(list.getByRole("listitem")).toHaveCount(2)
  await expect(workshop.getByLabel("directive", { exact: true })).toHaveValue(
    "Explore"
  )
  await page.getByRole("tab", { name: "Timeline", exact: true }).click()
  await page.getByRole("tab", { name: "Search explorer", exact: true }).click()
  await expect(workshop).toBeVisible()
  await expect(list.getByRole("listitem")).toHaveCount(2)
  await page.screenshot({
    path: "test-results/workshop-desktop.png",
    fullPage: true,
    animations: "disabled",
  })
  await page.setViewportSize({ width: 390, height: 844 })
  const tabHeader = page.locator(".run-tab-header")
  await expect(tabHeader).toHaveCSS("overflow-y", "hidden")
  expect(
    await tabHeader.evaluate((el) => el.scrollHeight - el.clientHeight)
  ).toBeLessThanOrEqual(0)
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(390)
  await expect(graph).toBeVisible()
  await expect(workshop).toBeVisible()
  await expect
    .poll(async () => {
      const box = await middle.boundingBox()
      return !!box && box.x >= 0 && box.x + box.width <= 391
    })
    .toBe(true)
  const mobileGraph = await graph.boundingBox()
  const mobilePanel = await workshop.boundingBox()
  expect(mobilePanel!.y).toBeGreaterThanOrEqual(
    mobileGraph!.y + mobileGraph!.height
  )
  await page.screenshot({
    path: "test-results/workshop-mobile.png",
    fullPage: true,
    animations: "disabled",
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  const queued = page.waitForResponse(
    (r) => r.url().endsWith("/playground") && r.request().method() === "POST"
  )
  await workshop
    .getByRole("button", { name: "Run sequence", exact: true })
    .click()
  const response = await queued
  expect(response.status()).toBe(201)
  const { job_id: id } = await response.json()
  const jobs = (await (await request.get("/api/jobs")).json()).jobs
  const job = jobs.find((j: { id: string }) => j.id === id)
  expect(job.config.mode).toBe("manual")
  expect(job.config.parent_checkpoint.candidate_id).toBe("middle")
  expect(job.config.manual_plan).toEqual([
    { strategy: "PHYS_OPT", args: { directive: "Explore" } },
    { strategy: "FANOUT", args: { top_n_nets: 2 } },
  ])
  await expect(graph).toBeVisible()
  await expect(workshop.getByRole("status")).toContainText("Run created")
  const manualHead = page.locator(`.react-flow__node[data-id="manual:${id}"]`)
  await expect(manualHead).toBeVisible()
  await expect(manualHead).toContainText("Manual · queued")
  await workshop
    .getByRole("button", { name: "Show branch", exact: true })
    .click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText(
    "Manual experiment"
  )
  await expect(
    workshop.getByRole("button", { name: "Run sequence", exact: true })
  ).toBeDisabled()
  const headers = { "X-Optimizer-Client": "web" }
  await request.post(`/__test__/manual/${id}/running`, { headers, data: {} })
  await expect(manualHead).toContainText("Manual · running")
  await request.post(`/__test__/manual/${id}/completed`, { headers, data: {} })
  await expect(manualHead).toContainText("Manual · completed")
  const secondResult = page.locator(
    `.react-flow__node[data-id="manual:${id}:attempt-2"]`
  )
  await expect(secondResult).toBeVisible()
  await expect(page.locator(".react-flow__minimap-node")).toHaveCount(5)
  await expect(secondResult).toContainText("416.7")
  await expect(secondResult).toContainText("Best · Manual")
  await expect(secondResult.locator(".is-best")).toHaveCount(1)
  await expect(
    page.locator(".metric-card").filter({ hasText: "Best Fmax" })
  ).toContainText("416.7")
  const automatic = page.locator(
    '.react-flow__node[data-id="automatic-result"]'
  )
  await expect(automatic.locator(".is-best")).toHaveCount(0)
  const compare = page.getByRole("combobox", { name: "Compare Fmax" })
  await expect(automatic).toContainText("29.6% higher than parent")
  await compare.selectOption("initial")
  await expect(secondResult).toContainText("25.0% higher than initial")
  await compare.selectOption("alternative")
  await expect(automatic).toContainText("9.3% higher than alternative")
  await expect(secondResult).toContainText("Alternative unavailable")
  await compare.selectOption("best")
  await expect(secondResult).toContainText("Current best")
  await expect(automatic).toContainText("11.1% lower than best")
  await compare.selectOption("parent")
  await expect(secondResult).toContainText("22.9% higher than parent")
  await page.getByRole("combobox", { name: "Order nodes" }).selectOption("fmax")
  // Sorting keeps ancestry intact and puts the best node first in its column.
  await expect
    .poll(async () => {
      const measured = await page
        .locator(".react-flow__node")
        .evaluateAll((elements) =>
          elements.map((e) => ({
            id: e.getAttribute("data-id"),
            x: (e as HTMLElement).style.transform,
            top: e.getBoundingClientRect().top,
            left: e.getBoundingClientRect().left,
          }))
        )
      const best = measured.find((e) => e.id === `manual:${id}:attempt-2`)!
      return measured
        .filter((e) => Math.abs(e.left - best.left) < 1)
        .every((e) => best.top <= e.top)
    })
    .toBe(true)
  await page.getByRole("button", { name: "Node list", exact: true }).click()
  const nodeList = page.getByRole("region", { name: "Exploration nodes" })
  await expect(nodeList).toBeVisible()
  await expect(
    nodeList.getByRole("rowgroup", { name: "Generation 1", exact: true })
  ).toContainText("middle")
  await expect(
    nodeList.getByRole("rowgroup", {
      name: "Manual · Generation 2",
      exact: true,
    })
  ).toContainText("416.7")
  await page
    .getByRole("combobox", { name: "Group nodes" })
    .selectOption("decision")
  await expect(
    nodeList.getByRole("rowgroup", { name: "FANOUT", exact: true })
  ).toContainText("manual-result-2")
  await page
    .getByRole("combobox", { name: "Group nodes" })
    .selectOption("depth")
  await expect(
    nodeList.getByRole("rowgroup", { name: "Depth 3", exact: true })
  ).toContainText("manual-result-2")
  await nodeList
    .getByRole("button", { name: "Select manual-result-2", exact: true })
    .click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText(
    "manual-result-2"
  )
  await expect(list.getByRole("listitem")).toHaveCount(2)
  await page.getByRole("button", { name: "Trace path", exact: true }).click()
  await expect(automatic).toHaveCSS("opacity", "0.35")
  await expect(middle).toHaveCSS("opacity", "1")
  await expect(secondResult).toHaveCSS("opacity", "1")
  await expect(automatic).toBeVisible()
  await page.getByRole("button", { name: "Trace path", exact: true }).click()
  await expect(automatic).toHaveCSS("opacity", "1")
  await page
    .getByRole("combobox", { name: "Order nodes" })
    .selectOption("change")
  await expect(graph).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(390)
  await expect(nodeList).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole("button", { name: "Node list", exact: true }).click()
  await expect(nodeList).toBeHidden()
  const manualEdge = page.locator(
    `.react-flow__edge[data-id="middle-manual:${id}"] path.react-flow__edge-path`
  )
  await expect(manualEdge).toHaveCSS("stroke", "rgb(14, 165, 233)")
  await expect(manualEdge).toHaveCSS("stroke-dasharray", "6px, 4px")
  await expect(
    page.locator('.react-flow__node[data-id="automatic-result"]')
  ).toBeVisible()
  await expect(
    page.locator('.react-flow__edge[data-id^="middle-"]')
  ).toHaveCount(2)
  await expect(
    page.locator(
      '.react-flow__edge[data-id="middle-automatic-result"] path.react-flow__edge-path'
    )
  ).toHaveCSS("stroke-dasharray", "none")
  await secondResult.click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText(
    "manual-result-2"
  )
  await expect(
    workshop.getByRole("button", { name: "Run sequence", exact: true })
  ).toBeEnabled()
  await workshop.getByText("Node details", { exact: true }).click()
  await workshop.getByRole("button", { name: /action selected/ }).click()
  await workshop
    .getByRole("button", { name: "Expand evidence", exact: true })
    .click()
  await expect(workshop.locator(".inspector .json-block").last()).toContainText(
    "Manual branch fixture evidence"
  )
  await workshop.getByText("Node details", { exact: true }).click()
  await page.emulateMedia({ colorScheme: "dark" })
  await expect(page.locator("html")).toHaveClass(/dark/)
  await page.getByRole("button", { name: "Node list", exact: true }).click()
  await page.screenshot({
    path: "test-results/workshop-manual-branch.png",
    fullPage: true,
    animations: "disabled",
  })

  // Reuse an admitted manual result: the next branch belongs to this result.
  const forked = page.waitForResponse(
    (r) => r.url().endsWith("/playground") && r.request().method() === "POST"
  )
  await workshop
    .getByRole("button", { name: "Run sequence", exact: true })
    .click()
  const forkResponse = await forked
  expect(forkResponse.status()).toBe(201)
  const { job_id: forkId } = await forkResponse.json()
  const forkJobs = (await (await request.get("/api/jobs")).json()).jobs
  const forkJob = forkJobs.find((j: { id: string }) => j.id === forkId)
  expect(forkJob.config.parent_checkpoint.candidate_id).toBe("manual-result-2")
  expect(forkJob.config.parent_checkpoint.run_path).toBe(
    path.join(job.directory, "run")
  )
  await workshop
    .getByRole("button", { name: "Show branch", exact: true })
    .click()
  await workshop
    .getByRole("button", { name: "Cancel experiment", exact: true })
    .click()
  await expect(
    page.locator(`.react-flow__node[data-id="manual:${forkId}"]`)
  ).toContainText("Manual · cancelled")
})
