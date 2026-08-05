import { test, expect } from "./fixtures.js";

/* console.error calls that don't throw are the quiet failures — a caught
   fetch rejection, a missing image, a key warning. Collected per route so a
   genuine one is easy to spot rather than scrolling a mixed test log. */
const ROUTES = ["/", "/triage", "/prep", "/live", "/track-records",
                "/fund-data", "/whats-new", "/felix", "/contact-card"];

for (const path of ROUTES) {
  test(`${path || "/"} logs no console errors on load`, async ({ page }) => {
    const errors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("requestfailed", (req) => {
      // A cancelled navigation-away request is not a real failure.
      if (req.failure()?.errorText !== "net::ERR_ABORTED") {
        errors.push(`request failed: ${req.url()} — ${req.failure()?.errorText}`);
      }
    });
    await page.goto(`/#${path}`);
    await page.waitForTimeout(1200);   // let async data loads land
    expect(errors, errors.join("\n")).toEqual([]);
  });
}
