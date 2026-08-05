import { test, expect } from "./fixtures.js";

/* Reopening a saved transcript is a plain GET (loadFromLibrary). Nothing here
   starts a recording, drafts a note (a real Claude call), or writes to Notion.

   The transcript library fetches after mount — wait for that specific call
   rather than counting cards before they exist. */
async function gotoLive(page) {
  const listLoaded = page.waitForResponse((r) =>
    r.url().includes("/api/transcripts") && r.status() === 200);
  await page.goto("/#/live");
  await listLoaded;
  // The response resolving is the network half; give React a moment to
  // actually repaint with it before anything counts DOM nodes (a plain
  // .count() does not retry the way expect(...) does).
  await page.waitForTimeout(200);
}

test("the note taker loads with its controls present", async ({ page }) => {
  await page.goto("/#/live");
  await expect(page.getByRole("button", { name: "Start listening" })).toBeVisible();
});

test("reopening a transcript that already has a note shows it with the questions minimized", async ({ page }) => {
  await gotoLive(page);
  const noted = page.locator(".spread", { hasText: "NOTE DRAFTED" }).first();
  test.skip((await noted.count()) === 0, "no saved transcript with a note right now");

  await noted.getByRole("button", { name: "Reopen" }).click();

  // The full questions panel (with its own MINIMIZE control) must NOT be
  // showing — only the folded summary bar with SHOW.
  await expect(page.getByText("QUESTIONS WORTH ASKING")).toHaveCount(0);
  await expect(page.getByText(/^QUESTIONS · \d+ OPEN · \d+ ANSWERED/)).toBeVisible();
  await expect(page.getByRole("button", { name: "SHOW" })).toBeVisible();

  // A note already exists, so the header offers to write it again — not
  // "Write the note" (that phrasing implies there isn't one yet), and there
  // is nothing running to cancel.
  await expect(page.getByRole("button", { name: "Write it again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel writing" })).toHaveCount(0);

  // SHOW un-folds them again.
  await page.getByRole("button", { name: "SHOW" }).click();
  await expect(page.getByText("QUESTIONS WORTH ASKING")).toBeVisible();
});

test("the note draft renders as markdown, not raw text", async ({ page }) => {
  await gotoLive(page);
  const noted = page.locator(".spread", { hasText: "NOTE DRAFTED" }).first();
  test.skip((await noted.count()) === 0, "no saved transcript with a note right now");
  await noted.getByRole("button", { name: "Reopen" }).click();
  await expect(page.getByText(/NOTE DRAFT/)).toBeVisible();
  // A markdown heading should render as an actual heading element, not as
  // literal "#" characters sitting in the text.
  await expect(page.locator("h1, h2, h3").first()).toBeVisible();
});
