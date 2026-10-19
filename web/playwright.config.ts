import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8766",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    headless: true,
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: `${process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python"} -m tests.web_fixture`,
    cwd: "..",
    url: "http://127.0.0.1:8766/api/settings",
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
