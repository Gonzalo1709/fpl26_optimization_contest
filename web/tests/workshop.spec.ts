import { expect, test } from "@playwright/test"

test("node selection drives Workshop beside the tree without losing the recipe draft", async ({
  page,
  request,
}) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "demo-run-2" })).toBeVisible()
  const candidate = page.locator(".react-flow__node").filter({ hasText: "c1" })
  await expect(candidate).toContainText("357.1")
  await expect(candidate).toContainText("7.1% higher")
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
    .filter({ hasText: "a-playground-fixture" })
    .click()
  const baseline = page
    .locator(".react-flow__node")
    .filter({ hasText: "baseline" })
  const alternate = page
    .locator(".react-flow__node")
    .filter({ hasText: "alternate" })
  await expect(baseline).toContainText("333.3")
  await expect(alternate).toContainText("285.7")
  await expect(alternate).toContainText("14.3% lower")
  await expect(alternate.locator(".text-xl")).not.toContainText("-")
  await alternate.click()
  await expect(workshop).toBeVisible()
  await expect(workshop.getByTestId("workshop-source")).toHaveText("alternate")
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
  await alternate.click()
  await expect(workshop.getByTestId("workshop-source")).toHaveText("alternate")
  await page
    .getByRole("button", { name: "Close Workshop", exact: true })
    .click()
  await expect(workshop).toBeHidden()
  await expect(graph).toBeVisible()
  await alternate.click()
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
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(390)
  await expect(graph).toBeVisible()
  await expect(workshop).toBeVisible()
  await expect
    .poll(async () => {
      const box = await alternate.boundingBox()
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
  expect(job.config.parent_checkpoint.candidate_id).toBe("alternate")
  expect(job.config.manual_plan).toEqual([
    { strategy: "PHYS_OPT", args: { directive: "Explore" } },
    { strategy: "FANOUT", args: { top_n_nets: 2 } },
  ])
  await expect(graph).toBeVisible()
  await expect(workshop.getByRole("status")).toContainText("Run created")
  await workshop.getByRole("button", { name: "Open run", exact: true }).click()
  await expect(page.getByRole("button", { name: "Cancel job" })).toBeVisible()
})
