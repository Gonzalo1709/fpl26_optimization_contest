import { expect, test } from "@playwright/test"

test("frequency cards and compact manual recipe orchestration", async ({
  page,
  request,
}) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "demo-run-2" })).toBeVisible()
  const candidate = page.locator(".react-flow__node").filter({ hasText: "c1" })
  await expect(candidate).toContainText("+23.81")
  await expect(candidate).toContainText("MHz ΔFmax")
  await expect(candidate).not.toContainText("ns WNS")
  await expect(
    candidate.getByRole("button", { name: "Run from c1", exact: true })
  ).toBeDisabled()
  await page.getByRole("tab", { name: "Playground", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Run sequence" })
  ).toBeDisabled()

  await page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "a-playground-fixture" })
    .click()
  await page
    .getByRole("button", { name: "Run from alternate", exact: true })
    .click()
  await expect(page.getByLabel("Checkpoint", { exact: true })).toHaveValue(
    "alternate"
  )
  await expect(
    page.getByRole("tab", { name: "Playground", exact: true })
  ).toHaveAttribute("aria-selected", "true")
  await page.getByLabel("Recipe", { exact: true }).selectOption("phys-opt")
  await page.getByRole("button", { name: "Add recipe", exact: true }).click()
  await page.getByLabel("directive", { exact: true }).selectOption("Explore")
  await page.getByLabel("Recipe", { exact: true }).selectOption("fanout")
  await page.getByRole("button", { name: "Add recipe", exact: true }).click()
  await page.getByLabel("top n nets", { exact: true }).fill("2")
  await page
    .getByRole("button", { name: "Move step 2 up", exact: true })
    .click()
  const list = page.getByRole("list", { name: "Recipe sequence" })
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
  await page.getByRole("tab", { name: "Search explorer", exact: true }).click()
  await page.screenshot({
    path: "test-results/playground-tree-actions.png",
    fullPage: true,
  })
  await page
    .getByRole("button", { name: "Run from baseline", exact: true })
    .click()
  await expect(page.getByLabel("Checkpoint", { exact: true })).toHaveValue(
    "baseline"
  )
  await page.getByRole("tab", { name: "Search explorer", exact: true }).click()
  await page
    .getByRole("button", { name: "Run from alternate", exact: true })
    .click()
  await expect(page.getByLabel("Checkpoint", { exact: true })).toHaveValue(
    "alternate"
  )
  await expect(list.getByRole("listitem")).toHaveCount(2)
  await expect(page.getByLabel("directive", { exact: true })).toHaveValue(
    "Explore"
  )
  await page.screenshot({
    path: "test-results/playground-desktop.png",
    fullPage: true,
    animations: "disabled",
  })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390
  )
  await page.screenshot({
    path: "test-results/playground-mobile.png",
    fullPage: true,
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  const queued = page.waitForResponse(
    (r) => r.url().endsWith("/playground") && r.request().method() === "POST"
  )
  await page.getByRole("button", { name: "Run sequence", exact: true }).click()
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
  await expect(page.getByRole("button", { name: "Cancel job" })).toBeVisible()
})
