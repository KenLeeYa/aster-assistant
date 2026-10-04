import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const repositoryRoot = path.resolve(__dirname, "../..");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run python tests/e2e/run_core.py",
      cwd: repositoryRoot,
      reuseExistingServer: false,
      timeout: 120_000,
      url: "http://127.0.0.1:8765/health",
    },
    {
      command:
        "corepack pnpm@11.24.0 --dir apps/web exec next dev --hostname 127.0.0.1 --port 3100",
      cwd: repositoryRoot,
      reuseExistingServer: false,
      timeout: 120_000,
      url: "http://127.0.0.1:3100",
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
