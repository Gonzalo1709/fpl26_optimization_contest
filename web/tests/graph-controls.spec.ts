import { expect, test } from "@playwright/test"

for (const theme of ["light", "dark"] as const) {
  test(`tree controls retain contrast and work in ${theme} mode`, async ({
    page,
  }) => {
    await page.addInitScript(
      (theme) => localStorage.setItem("theme", theme),
      theme
    )
    await page.goto("/")
    await page
      .getByRole("navigation", { name: "Experiments" })
      .getByRole("button")
      .filter({ hasText: "Workshop example" })
      .click()
    await page.locator('.react-flow__node[data-id="middle"]').click()
    const header = page.locator(".run-tab-header")
    await expect(header).toHaveCSS("overflow-y", "hidden")
    expect(
      await header.evaluate((el) => el.scrollHeight - el.clientHeight)
    ).toBeLessThanOrEqual(0)
    await expect(page.locator("html")).toHaveCSS("color-scheme", theme)
    const zoom = page.getByRole("button", { name: "Zoom In", exact: true })
    await expect(zoom).toBeVisible()
    // Resolve CSS colors to sRGB so this checks rendered contrast, including OKLCH tokens.
    const contrast = await zoom.evaluate((button) => {
      function rgb(color: string) {
        const context = document.createElement("canvas").getContext("2d")!
        context.fillStyle = color
        context.fillRect(0, 0, 1, 1)
        return [...context.getImageData(0, 0, 1, 1).data]
          .slice(0, 3)
          .map((v) => v / 255)
      }
      function luminance(color: string) {
        const values = rgb(color).map((v) =>
          v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
        )
        return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
      }
      const style = getComputedStyle(button)
      const foreground = luminance(
        getComputedStyle(button.querySelector("svg")!).fill
      )
      const background = luminance(style.backgroundColor)
      return (
        (Math.max(foreground, background) + 0.05) /
        (Math.min(foreground, background) + 0.05)
      )
    })
    expect(contrast).toBeGreaterThan(4.5)
    const canvas = page.getByLabel("Search ancestry graph", { exact: true })
    const map = page.locator(".react-flow__minimap")
    await expect(map.locator(".react-flow__minimap-node")).toHaveCount(3)
    await expect(map.locator("svg")).toHaveAttribute("width", "110")
    await expect(map.locator("svg")).toHaveAttribute("height", "70")
    const mapColors = await map.evaluate((element) => {
      const style = getComputedStyle(element)
      const flow = element.closest(".react-flow")!
      const context = document.createElement("canvas").getContext("2d")!
      const pixels = (color: string) => {
        context.clearRect(0, 0, 1, 1)
        context.fillStyle = color
        context.fillRect(0, 0, 1, 1)
        return [...context.getImageData(0, 0, 1, 1).data]
      }
      return {
        background: pixels(style.backgroundColor),
        card: pixels(getComputedStyle(flow).getPropertyValue("--card").trim()),
        mask: getComputedStyle(
          element.querySelector(".react-flow__minimap-mask")!
        ).fill,
      }
    })
    expect(mapColors.background).toEqual(mapColors.card)
    expect(mapColors.mask).not.toBe("rgba(240, 240, 240, 0.6)")
    const viewport = canvas.locator(".react-flow__viewport")
    const before = await viewport.getAttribute("style")
    await zoom.click()
    await expect(viewport).not.toHaveAttribute("style", before!)
    const zoomOut = page.getByRole("button", { name: "Zoom Out", exact: true })
    await zoomOut.click()
    await zoomOut.click()
    const beforeFit = await viewport.getAttribute("style")
    await page.getByRole("button", { name: "Fit View", exact: true }).click()
    await expect(viewport).not.toHaveAttribute("style", beforeFit!)
    const beforeMap = await viewport.getAttribute("style")
    const mapBox = (await map.boundingBox())!
    await page.mouse.move(mapBox.x + 30, mapBox.y + 25)
    await page.mouse.down()
    await page.mouse.move(mapBox.x + 50, mapBox.y + 35, { steps: 5 })
    await page.mouse.up()
    await expect(viewport).not.toHaveAttribute("style", beforeMap!)
    await page.getByRole("button", { name: "Fit View", exact: true }).click()
    await expect(canvas).toBeVisible()
    await page.screenshot({
      path: `test-results/graph-controls-${theme}.png`,
      fullPage: true,
      animations: "disabled",
    })
  })
}
