import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { ARTIFACTS, E2E, E2E_DIR } from "./env";

const chrome = {
  ...devices["Desktop Chrome"],
  // Branded Chrome ships the AAC and H.264 decoders the fixture recordings need; bundled Chromium does not.
  channel: "chrome",
  viewport: { width: 1600, height: 1000 },
  launchOptions: {
    // Caddy serves a `tls internal` certificate. The service worker refuses to register on an untrusted
    // certificate unless Chrome itself ignores certificate errors.
    args: ["--ignore-certificate-errors"],
  },
};

export default defineConfig({
  testDir: path.join(E2E_DIR, "specs"),
  // Specs are *.e2e.ts so Vitest (npm test) never collects them.
  testMatch: "*.e2e.ts",
  outputDir: path.join(ARTIFACTS, "test-results"),
  globalSetup: path.join(E2E_DIR, "global-setup.ts"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(ARTIFACTS, "results.json") }],
    ["html", { outputFolder: path.join(ARTIFACTS, "html-report"), open: "never" }],
  ],
  use: {
    baseURL: E2E.baseURL,
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
  },
  projects: [
    { name: "kiosk-chrome", use: chrome, testIgnore: "ask-model-down.e2e.ts" },
    // Needs the api restarted with an unreachable answer model first (stack.ps1 llm-down).
    { name: "model-down", use: chrome, testMatch: "ask-model-down.e2e.ts" },
  ],
});
