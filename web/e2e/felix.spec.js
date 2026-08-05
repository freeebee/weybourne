import { test, expect } from "./fixtures.js";

/* The review queue loads asynchronously after mount (restore() fetches it) —
   wait for that specific call rather than for a fixed delay or for text that
   is genuinely absent when the queue is empty. */
async function gotoFelix(page) {
  const changesLoaded = page.waitForResponse((r) =>
    r.url().includes("/api/felix/changes") && r.status() === 200);
  await page.goto("/#/felix");
  await changesLoaded;
  // The response resolving is the network half; give React a moment to
  // actually repaint with it before anything counts DOM nodes (a plain
  // .count() does not retry the way expect(...) does).
  await page.waitForTimeout(200);
}

/* Fix-it Felix writes real, reversible changes to the live Notion workspace
   the moment Approve or Run Felix is pressed. These tests read and select —
   never approve, discard, undo, or start a run — so nothing here mutates the
   workspace. */

test("the room and the HUD render", async ({ page }) => {
  await page.goto("/#/felix");
  await expect(page.locator(".px-office")).toBeVisible();
  await expect(page.locator(".px-console")).toBeVisible();
  await expect(page.getByText("CLEANED UP SINCE THE START")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run Felix" })).toBeVisible();
  for (const label of ["CONTACTS", "COMPANIES", "FUNDS", "NOTES", "RESEARCH"]) {
    await expect(page.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  }
});

test("the review queue lists real awaiting findings", async ({ page }) => {
  await gotoFelix(page);
  await expect(page.getByText("WHAT FELIX FOUND")).toBeVisible();
  await expect(page.locator(".microlabel", { hasText: /SHOWN$/ })).toBeVisible();
});

test("selecting rows reveals a bulk bar that names the count, without approving anything", async ({ page }) => {
  await gotoFelix(page);
  const boxes = page.getByRole("checkbox", { name: /Select .* for bulk approval/ });
  const count = await boxes.count();
  test.skip(count === 0, "nothing awaiting review right now");

  await expect(page.getByText(/SELECTED$/)).toHaveCount(0);
  await boxes.first().check();
  await expect(page.getByText("1 SELECTED")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve 1" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Discard 1" })).toBeEnabled();

  if (count > 1) {
    await boxes.nth(1).check();
    await expect(page.getByText("2 SELECTED")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve 2" })).toBeVisible();
  }

  // Unchecking drops the bar rather than showing "0 selected".
  await boxes.first().uncheck();
  if (count > 1) await boxes.nth(1).uncheck();
  await expect(page.getByText(/SELECTED$/)).toHaveCount(0);
});

test("select-all picks every awaiting row and none other", async ({ page }) => {
  await gotoFelix(page);
  const selectAll = page.getByText(/^SELECT ALL \d+ SHOWN$/);
  const present = await selectAll.count();
  test.skip(present === 0, "nothing awaiting review right now");

  const label = await selectAll.textContent();
  const n = Number(label.match(/\d+/)[0]);
  await page.getByRole("checkbox").first().check();   // the select-all box
  await expect(page.getByText(`${n} SELECTED`)).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Select .* for bulk approval/ }))
    .toHaveCount(n);
  const checked = await page.getByRole("checkbox", { name: /Select .* for bulk approval/ })
    .evaluateAll((els) => els.filter((e) => e.checked).length);
  expect(checked).toBe(n);
});

test("switching the review filter clears the selection", async ({ page }) => {
  await gotoFelix(page);
  const boxes = page.getByRole("checkbox", { name: /Select .* for bulk approval/ });
  test.skip((await boxes.count()) === 0, "nothing awaiting review right now");
  await boxes.first().check();
  await expect(page.getByText("1 SELECTED")).toBeVisible();
  await page.getByRole("combobox").first().selectOption("done");
  await expect(page.getByText(/SELECTED$/)).toHaveCount(0);
});
