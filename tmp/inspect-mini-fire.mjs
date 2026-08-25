import { chromium } from "../web/node_modules/@playwright/test/index.mjs";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.route("**/api/felix/status", (route) => route.fulfill({
  contentType: "application/json",
  body: JSON.stringify({ live: false, running: null, stats: {} }),
}));
await page.route("**/api/felix/changes**", (route) => route.fulfill({
  contentType: "application/json",
  body: JSON.stringify({ changes: [] }),
}));
await page.addInitScript(() => {
  sessionStorage.setItem("wb-splash-seen", "1");
  sessionStorage.setItem("wb-felix-compact", "1");
});
await page.goto("http://127.0.0.1:5173/#/felix", { waitUntil: "domcontentloaded" });
await page.locator(".px-mini-track").waitFor({ state: "visible" });

async function setPower(power) {
  await page.evaluate(async (enabled) => {
    const fx = await import("/src/felixStore.js");
    Object.assign(fx.S.scene, {
      zone: "contacts",
      activity: "fix",
      selected: "contacts",
      direction: "left",
      caption: enabled ? "powered visual check" : "stopped visual check",
      power: enabled,
      labels: [],
      pickups: [],
    });
    fx.dropLabel("__mini-fire-check__");
  }, power);
}

await setPower(true);
const fire = page.locator(".px-mini-fire");
await fire.evaluate((el) => { el.dataset.mountToken = "persistent-fire"; });
await page.locator(".px-mini-track").screenshot({ path: "../tmp/mini-fire-powered.png" });
await page.screenshot({ path: "../tmp/mini-fire-powered-viewport.png" });

const powered = await page.evaluate(() => {
  const fireEl = document.querySelector(".px-mini-fire");
  const flame = document.querySelector(".px-mini-flames-back");
  const sprite = document.querySelector(".px-mini-felix img");
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  };
  return {
    fireVisibility: getComputedStyle(fireEl).visibility,
    fireZ: Number(getComputedStyle(fireEl).zIndex),
    spriteZ: Number(getComputedStyle(sprite).zIndex),
    fireBox: box(flame),
    spriteBox: box(sprite),
    spriteTransition: getComputedStyle(sprite).transitionProperty,
  };
});

await setPower(false);
await page.locator(".px-mini-track").screenshot({ path: "../tmp/mini-fire-stopped.png" });
await page.waitForTimeout(450);
await page.locator(".px-mini-track").screenshot({ path: "../tmp/mini-fire-stopped-after-450ms.png" });

const stopped = await page.evaluate(() => {
  const fireEl = document.querySelector(".px-mini-fire");
  const images = [...document.querySelectorAll(".px-mini-felix img")];
  return {
    fireVisibility: getComputedStyle(fireEl).visibility,
    mountToken: fireEl.dataset.mountToken,
    imageCount: images.length,
    imageAnimations: images.map((el) => getComputedStyle(el).animationName),
    imageTransitions: images.map((el) => getComputedStyle(el).transitionProperty),
  };
});

console.log(JSON.stringify({ powered, stopped }, null, 2));
await browser.close();
