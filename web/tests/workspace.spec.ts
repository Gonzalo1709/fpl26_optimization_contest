import { appendFileSync, readFileSync } from "node:fs"
import path from "node:path"
import { expect, test } from "@playwright/test"

test("history, decisions, evidence, live reconnect, queue and cancellation", async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on("pageerror", (e) => {
    errors.push(e.message)
    console.error(e.message)
  })
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "demo-run-2" })).toBeVisible()
  await expect(page.getByText("Live updates connected")).toBeVisible()
  await expect(
    page.getByText("SYNTHETIC DEMONSTRATION", { exact: false })
  ).toBeVisible()
  const c1 = page.locator(".react-flow__node").filter({ hasText: "c1" })
  await c1.click()
  await expect(page.locator(".inspector")).toContainText("demo")
  await page
    .locator(".inspector")
    .getByRole("button", { name: "#3 action selected", exact: true })
    .click()
  await page.getByRole("button", { name: "Expand evidence" }).click()
  await expect(page.locator(".inspector .json-block").last()).toContainText(
    "Synthetic policy evidence"
  )
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  })

  await page.getByRole("tab", { name: "Timeline" }).click()
  await page
    .getByRole("textbox", { name: "Filter events" })
    .fill("attempt_aborted")
  await page
    .getByRole("button", { name: "attempt aborted", exact: true })
    .click()
  await expect(page.locator(".timeline-layout .json-block")).toContainText(
    "SyntheticFailure"
  )
  await page.getByRole("tab", { name: "Output & validation" }).click()
  await expect(
    page.getByText("Ignored or missing checks do not establish a clean result.")
  ).toBeVisible()

  // Pause closes the stream; append at the real file boundary and resume it.
  await page.getByRole("button", { name: "Pause updates" }).click()
  const runs = await (await request.get("/api/runs")).json()
  const run = runs.find((r: { name: string }) => r.name === "demo-run-2")
  const before = await (await request.get(`/api/runs/${run.id}`)).json()
  const log = path.join(run.path, "events.jsonl")
  appendFileSync(
    log,
    JSON.stringify({
      schema_version: 1,
      run_id: before.events[0].run_id,
      sequence: before.sequence + 1,
      event: "browser_reconnect_marker",
    }) + "\n"
  )
  await page.getByRole("button", { name: "Follow live" }).click()
  await expect(
    page.getByText(`${before.sequence + 1} events`, { exact: true })
  ).toBeVisible()
  await expect(page.getByText("Live updates connected")).toBeVisible()
  // A second write while connected exercises the ongoing stream, not just reload.
  appendFileSync(
    log,
    JSON.stringify({
      schema_version: 1,
      run_id: before.events[0].run_id,
      sequence: before.sequence + 2,
      event: "browser_live_marker",
    }) + "\n"
  )
  await expect(
    page.getByText(`${before.sequence + 2} events`, { exact: true })
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByText(`${before.sequence + 2} events`, { exact: true })
  ).toBeVisible()
  expect(readFileSync(log, "utf8")).toContain("browser_live_marker")

  await page
    .getByRole("button", { name: "Import / open runs", exact: true })
    .first()
    .click()
  await page.getByRole("tab", { name: "Open host folder" }).click()
  await page
    .getByLabel("Folder or events.jsonl path on the UI host")
    .fill(path.join(run.path, "missing-folder"))
  await page.getByRole("button", { name: "Open folder", exact: true }).click()
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "does not exist"
  )
  await page
    .getByLabel("Folder or events.jsonl path on the UI host")
    .fill(run.path)
  await page.getByRole("button", { name: "Open folder", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "demo-run-2" })).toBeVisible()

  await page
    .getByRole("button", { name: "New experiment", exact: true })
    .first()
    .click()
  await page
    .getByLabel("Input checkpoint")
    .fill(path.resolve(run.path, "../../fixture.dcp"))
  await page.getByRole("button", { name: "Preview", exact: true }).click()
  await expect(
    page.getByText("Argument preview (paths assigned when queued)")
  ).toBeVisible()
  await page.getByRole("button", { name: "Enqueue experiment" }).click()
  await expect(page.getByRole("heading", { name: "fixture.dcp" })).toBeVisible()
  await expect(page.locator(".workspace .state-badge")).toHaveText("queued")
  await page.reload()
  // Queue ownership survives browser refresh; selecting the persistent job exposes cancellation.
  await page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "fixture.dcp" })
    .click()
  await page.getByRole("button", { name: "Cancel job", exact: true }).click()
  await expect(page.locator(".workspace .state-badge")).toHaveText("cancelled")

  await page.setViewportSize({ width: 390, height: 844 })
  await page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "demo-run-1" })
    .click()
  await expect(page.getByRole("heading", { name: "demo-run-1" })).toBeVisible()
  await page.screenshot({
    path: "test-results/workspace-mobile.png",
    fullPage: true,
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBeTruthy()
  expect(errors).toEqual([])
})

test("upload cloud analysis ZIP and retain imported evidence after refresh", async ({
  page,
  request,
}) => {
  const runs = await (await request.get("/api/runs")).json()
  const source = runs.find(
    (r: { name: string; source: string }) =>
      r.name === "demo-run-1" && r.source === "folder"
  )
  const beforeJobs = (await (await request.get("/api/jobs")).json()).jobs.length
  const download = await request.get(`/api/runs/${source.id}/bundle`)
  expect(download.ok()).toBeTruthy()
  const bundle = await download.body()
  await page.goto("/")
  await page
    .getByRole("button", { name: "Import / open runs", exact: true })
    .first()
    .click()
  await page.getByRole("tab", { name: "How to export" }).click()
  await expect(
    page.getByText("python -m tools.run_bundle export", { exact: false })
  ).toBeVisible()
  await page.getByRole("tab", { name: "Upload cloud ZIP" }).click()
  await page.getByLabel("Analysis ZIP file").setInputFiles({
    name: "invalid.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("invalid"),
  })
  await page.getByRole("button", { name: "Import ZIP", exact: true }).click()
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "not a zip"
  )
  await page.getByLabel("Analysis ZIP file").setInputFiles({
    name: "cloud-experiment.zip",
    mimeType: "application/zip",
    buffer: bundle,
  })
  await page.screenshot({
    path: "test-results/import-cloud-dialog.png",
    fullPage: true,
  })
  await page.getByRole("button", { name: "Import ZIP", exact: true }).click()
  await expect(
    page.locator(".demo-banner").filter({ hasText: "IMPORTED SNAPSHOT" })
  ).toContainText("cloud-experiment.zip")
  await expect(page.getByRole("button", { name: "Pause updates" })).toHaveCount(
    0
  )
  await expect(
    page.getByRole("button", { name: "Reuse configuration" })
  ).toBeDisabled()
  await page.locator(".react-flow__node").filter({ hasText: "c1" }).click()
  await page
    .locator(".inspector")
    .getByRole("button", { name: "#3 action selected", exact: true })
    .click()
  await page.getByRole("button", { name: "Expand evidence" }).click()
  await expect(page.locator(".inspector .json-block").last()).toContainText(
    "Synthetic policy evidence"
  )
  await page.reload()
  const imported = page
    .getByRole("navigation", { name: "Experiments" })
    .getByRole("button")
    .filter({ hasText: "Imported snapshot" })
  await expect(imported).toHaveCount(1)
  await imported.click()
  await expect(
    page.locator(".demo-banner").filter({ hasText: "IMPORTED SNAPSHOT" })
  ).toBeVisible()
  expect((await (await request.get("/api/jobs")).json()).jobs.length).toBe(
    beforeJobs
  )
})
