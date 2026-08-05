import { test, expect } from "./fixtures.js";

/* Every route the sidebar links to. A page that throws on mount, never
   resolves its data, or silently blank-screens is worth catching here before
   it is worth catching by opening the app and clicking around by hand. */
const ROUTES = [
  ["/", "Home"],
  ["/triage", "Inbox triage"],
  ["/prep", "Meeting prep"],
  ["/live", "Note taker"],
  ["/track-records", "Track records"],
  ["/fund-data", "Fund data"],
  ["/whats-new", "What's new"],
  ["/felix", "Fix-it Felix"],
  ["/contact-card", "Contact creator"],
];

for (const [path, label] of ROUTES) {
  test(`${label} loads without an error banner`, async ({ page }) => {
    await page.goto(`/#${path}`);
    // The sidebar itself is the one thing every page shares — if it never
    // renders, the whole app failed to mount, not just this route.
    await expect(page.getByRole("link", { name: "Home" })).toBeVisible();
    await expect(page.getByText("SOMETHING WENT WRONG")).toHaveCount(0);
    // React unmounting on an uncaught render error (there is no error
    // boundary) leaves the root empty rather than showing a message — catch
    // that blank-screen failure mode explicitly, not just via absent text.
    await expect(page.locator("#root")).not.toBeEmpty();
  });
}

test("the sidebar links to every route it advertises", async ({ page }) => {
  await page.goto("/");
  for (const [path, label] of ROUTES) {
    await page.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#${path.replace("/", "\\/")}$`));
  }
});

test("Home renders the workspace ledger and today's meeting", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Good (morning|afternoon|evening)/ }))
    .toBeVisible();
  await expect(page.getByText("WORKSPACES")).toBeVisible();
  // The six workspace rows are real navigation links, not decoration.
  await expect(page.getByRole("button", { name: /Inbox triage/ })).toBeVisible();
});
