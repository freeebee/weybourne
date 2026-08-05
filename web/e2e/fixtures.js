import { test as base } from "@playwright/test";

/* Every real visit sees the opening animation once per browser session
   (Splash.jsx checks sessionStorage). Tests aren't testing the splash, so
   skip it the same way the app's own headless-screenshot workflow does. */
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem("wb-splash-seen", "1");
    });
    // Fail loudly on a client-side exception rather than letting the page
    // silently render blank — that is exactly the kind of bug worth catching.
    page.on("pageerror", (err) => {
      throw new Error(`Uncaught page error: ${err.message}`);
    });
    await use(page);
  },
});

export const expect = base.expect;
