// @ts-check
import { defineConfig, devices } from "@playwright/test";

/* Runs against the already-running app server (`run.bat`, port 8000), which
   serves the built `web/dist`. No webServer block here on purpose: run.bat is
   a long-lived foreground process the user owns, and these tests must never
   start or stop it — `npm run build` first if dist is stale, then run.bat,
   then `npm run test:e2e`. */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // The backend is one real, shared server (not a fresh instance per worker),
  // so too much parallelism just means every request queues behind the
  // others — that showed up as a page that had genuinely finished loading
  // (its network response had already resolved) not yet having repainted by
  // the time the next assertion ran. A cap, plus one retry to absorb whatever
  // slack remains, is cheaper than chasing that timing on a single box.
  workers: 4,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
