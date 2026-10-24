import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(configDir, "../backend");

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  outputDir: "test-results",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn mcp_server.server:app --host 127.0.0.1 --port 8001",
      cwd: backendDir,
      url: "http://127.0.0.1:8001/healthz",
      timeout: 180_000,
      reuseExistingServer: true,
    },
    {
      command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: backendDir,
      url: "http://127.0.0.1:8000/healthz",
      timeout: 180_000,
      reuseExistingServer: true,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      cwd: configDir,
      url: "http://127.0.0.1:5173",
      timeout: 180_000,
      reuseExistingServer: true,
    },
  ],
});
