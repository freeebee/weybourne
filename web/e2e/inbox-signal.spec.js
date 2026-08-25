import { test, expect } from "./fixtures.js";

/* Read-only. Nothing here starts a sweep or the cross-document pass — both
   cost model calls, and the point of this file is that the page tells the
   truth about what it holds, not that it can go and fetch more. */

test.describe("Inbox signal", () => {
  /* One at a time. Every test here loads /api/inbox-signal, which reads every
     stored letter and matches ~50 managers against ~9,000 Notion funds — about
     two and a half seconds of work on a single-process backend. Run four wide
     they queue behind each other and the later ones time out waiting for a
     page that is only slow because the other three asked for it first, which
     reads as a broken page rather than as a busy server. The rest of the suite
     still runs in parallel around this file. */
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    // The dashboard's own opening runs once per session; it is not under test.
    await page.addInitScript(() => {
      window.sessionStorage.setItem("wb-signal-intro-seen", "1");
    });
    await page.goto("/#/inbox-signal");
  });

  test("the desk view reaches the read-across section", async ({ page }) => {
    const head = page.getByText("WHERE THE DESK CONTRADICTS ITSELF");
    await expect(head).toBeVisible({ timeout: 30000 });
    await head.scrollIntoViewIfNeeded();
    await expect(page.getByText(/Pairs of letters that look opposed/)).toBeVisible();
  });

  test("it says how much of the ground is still unread", async ({ page }) => {
    // The coverage line is the honest part: a thin section has to read as
    // unfinished work rather than as a quiet desk.
    const head = page.getByText("WHERE THE DESK CONTRADICTS ITSELF");
    await expect(head).toBeVisible({ timeout: 30000 });
    await head.scrollIntoViewIfNeeded();

    const button = page.getByRole("button", { name: /Read the \d+ unread pairs|Nothing left to read/ });
    await expect(button).toBeVisible();
    const label = (await button.textContent()).trim();
    if (label === "Nothing left to read") {
      await expect(button).toBeDisabled();
    } else {
      // Every unread pair is accounted for in the prose beside the control.
      await expect(button).toBeEnabled();
      await expect(page.getByText(/pairs? (is|are) still unread/)).toBeVisible();
    }
  });

  test("coming back to the page does not re-buy the payload", async ({ page }) => {
    // /api/inbox-signal reads every stored letter and matches ~50 managers
    // against ~9,000 Notion funds, so it takes seconds. Holding it in component
    // state meant leaving the page and returning paid that again and showed the
    // full loading state for figures that had not changed.
    await expect(page.getByText("MANAGERS HEARD FROM")).toBeVisible({ timeout: 30000 });

    /* The revalidation is held open rather than timed. Whether the page came
       back from cache is exactly the question "did it render before the
       network answered", so the test holds the answer back and looks. A
       wall-clock deadline was the first version of this and it measured how
       busy the machine was as much as anything else. */
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    let refetches = 0;
    await page.route("**/api/inbox-signal", async (route) => {
      refetches += 1;
      await held;
      await route.continue();
    });

    /* exact:true on both: the sidebar footer lists running jobs, and a sweep
       row reads "Inbox signal · sweep · 0s", which a substring match on
       "Inbox signal" picks up alongside the nav link. Whether that row exists
       depends on whether a job happens to be running, so a loose locator here
       fails only sometimes and for a reason nothing on screen explains. */
    await page.getByRole("link", { name: "Fund data", exact: true }).click();
    await expect(page).toHaveURL(/#\/fund-data/);
    await page.getByRole("link", { name: "Inbox signal", exact: true }).click();

    // Figures on screen with the request still in flight, and the loading
    // state never drawn — a page that had forgotten them would be showing it.
    await expect(page.getByText("MANAGERS HEARD FROM")).toBeVisible({ timeout: 10000 });
    expect(await page.getByText("Reading the shared inbox…").count()).toBe(0);

    // It still revalidates — a session-long cache with no refresh would go
    // stale behind background jobs writing to the same store.
    expect(refetches).toBe(1);
    release();
  });

  test("a tone box opens the letter its stance was read from", async ({ page }) => {
    // The stance is a reading of a letter; a coloured square nobody can open
    // asks to be taken on trust.
    await page.getByRole("button", { name: /Manager performance/i }).first().click();
    const box = page.getByRole("button", { name: /— open \d+ letters?$/ }).first();
    await expect(box).toBeVisible({ timeout: 30000 });
    await box.click();

    const drawer = page.locator(".wb-drawer");
    await expect(drawer).toBeVisible();
    // The evidence itself, and the way back to the original message. The link
    // is asserted, never clicked — following it would leave the app.
    await expect(drawer.locator("blockquote").first()
      .or(drawer.getByText(/reported without commenting/))).toBeVisible();
    await expect(drawer.getByRole("link", { name: "Open in Outlook" }).first()).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
  });

  test("letters that took no position are not quoted as views", async ({ page }) => {
    // 'The fund made a net return of -12.22% MTD' and 'we will circulate the
    // official factsheet' are facts the figures already carry, not views.
    await expect(page.getByText("IN THEIR WORDS")).toBeVisible({ timeout: 30000 });
    const heads = page.locator("section").getByText("NEUTRAL", { exact: true });
    await expect(heads).toHaveCount(0);
  });

  test("the strategy grouping never labels a manager it could not match",
    async ({ page }) => {
      // 'AM Squared' was being filed under 'Hamilton Square' and 'Tribeca
      // Investment Partners' under 'Green Investment Partners' — lookalike
      // firms the desk has never met. Unmatched managers must appear as
      // unclassified, not as a plausible-looking strategy.
      await page.getByRole("link", { name: "Inbox signal", exact: true }).click();
      const managers = page.getByRole("button", { name: /Manager performance/i }).first();
      if (await managers.isVisible().catch(() => false)) await managers.click();
      const payload = await page.evaluate(async () => {
        const r = await fetch("/api/inbox-signal");
        return (await r.json()).strategy_groups;
      });
      const labelled = new Set(payload.groups.flatMap((g) => g.managers));
      for (const org of payload.unclassified) {
        expect(labelled.has(org)).toBe(false);
      }
    });
});
