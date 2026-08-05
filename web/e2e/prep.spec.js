import { test, expect } from "./fixtures.js";

/* Opening a saved prep is a plain GET — nothing here starts a new prep job
   (which calls Claude for real) or writes anything.

   The calendar's event rows and the library's saved-prep rows share the same
   ".rrow.click" class, so ".first()" picks up whichever renders first in the
   DOM — the calendar, not the library. Anchoring on the LIBRARY heading and
   walking forward is what actually finds a saved prep. */
async function openFirstSavedPrep(page) {
  await page.goto("/#/prep");
  const row = page.getByText("LIBRARY · SAVED PREPS")
    .locator("xpath=following::*[contains(@class,'rrow') and contains(@class,'click')][1]");
  await expect(row).toBeVisible({ timeout: 10000 });
  await row.click();
}

test("a saved prep opens with the fold controls in place", async ({ page }) => {
  await openFirstSavedPrep(page);

  await expect(page.locator(".microlabel", { hasText: "MEETING PREP" })).toBeVisible();
  await expect(page.getByRole("button", { name: /minimize both/i })).toBeVisible();
});

test("MINIMIZE BOTH folds the screen and the briefing together, and EXPAND BOTH restores them", async ({ page }) => {
  await openFirstSavedPrep(page);
  await expect(page.locator(".microlabel", { hasText: "MEETING PREP" })).toBeVisible();

  const before = await page.getByRole("button", { name: "MINIMIZE", exact: true }).count();
  test.skip(before === 0, "this saved prep has nothing foldable");

  await page.getByRole("button", { name: /minimize both/i }).click();
  await expect(page.getByRole("button", { name: "MINIMIZE", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /expand both/i })).toBeVisible();

  await page.getByRole("button", { name: /expand both/i }).click();
  // "MINIMIZE" is also a substring of "MINIMIZE BOTH" — exact:true is what
  // keeps this asserting the per-section controls, not that combined one.
  await expect(page.getByRole("button", { name: "MINIMIZE", exact: true })).toHaveCount(before);
});

test("the widen handle takes over the column and can be reversed", async ({ page }) => {
  await openFirstSavedPrep(page);
  await expect(page.locator(".microlabel", { hasText: "MEETING PREP" })).toBeVisible();

  const handle = page.getByRole("button", { name: /^Widen/ }).first();
  test.skip((await handle.count()) === 0, "this saved prep has nothing widenable");

  await handle.click();
  const narrow = page.getByRole("button", { name: /^Narrow/ }).first();
  await expect(narrow).toBeVisible();
  await narrow.click();
  await expect(page.getByRole("button", { name: /^Widen/ }).first()).toBeVisible();
});

test("individually minimizing the screen leaves the briefing showing", async ({ page }) => {
  await openFirstSavedPrep(page);
  await expect(page.locator(".microlabel", { hasText: "MEETING PREP" })).toBeVisible();

  const minimizeButtons = page.getByRole("button", { name: "MINIMIZE", exact: true });
  const n = await minimizeButtons.count();
  test.skip(n < 2, "this saved prep does not have both a screen and a briefing");

  await minimizeButtons.first().click();
  // One fold collapsed; the other block's own MINIMIZE is still there, plus
  // the collapsed one's EXPAND — the total foldable-state count is unchanged.
  await expect(page.getByRole("button", { name: "MINIMIZE", exact: true })).toHaveCount(n - 1);
  await expect(page.getByRole("button", { name: "EXPAND" }).first()).toBeVisible();
});
