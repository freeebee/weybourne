import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const label = process.argv[2] || "capture";
const output = path.resolve("..", "tmp", "playwright", label);
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1800, height: 1100 }, deviceScaleFactor: 1 });
await page.addInitScript(() => sessionStorage.setItem("wb-splash-seen", "1"));
await page.goto("http://127.0.0.1:5173/#/felix", { waitUntil: "domcontentloaded" });
await page.locator(".px-office").waitFor({ state: "visible" });

async function capture(name) {
  const office = page.locator(".px-office");
  await office.screenshot({ path: path.join(output, `${name}.png`) });
  const measurements = await page.locator(".px-stage").evaluate((stage) => {
    const felix = stage.querySelector(".px-felix");
    const sprite = stage.querySelector(".px-felix-sprite");
    const office = stage.parentElement;
    const stageBox = stage.getBoundingClientRect();
    const felixBox = felix?.getBoundingClientRect();
    return {
      stage: { width: stageBox.width, height: stageBox.height },
      officeHeight: office?.getBoundingClientRect().height,
      felix: felixBox && {
        left: felixBox.left - stageBox.left,
        top: felixBox.top - stageBox.top,
        width: felixBox.width,
        height: felixBox.height,
      },
      sprite: sprite?.getAttribute("src"),
      spriteTransform: sprite && getComputedStyle(sprite).transform,
      caption: document.querySelector(".px-console-text")?.textContent,
    };
  });
  console.log(name, JSON.stringify(measurements));
}

async function freezeAnimationPhase(selector, ratio) {
  await page.locator(selector).evaluateAll((frames, phase) => {
    for (const frame of frames) {
      for (const animation of frame.getAnimations()) {
        const duration = Number(animation.effect?.getTiming().duration) || 1;
        animation.pause();
        animation.currentTime = duration * phase;
      }
    }
  }, ratio);
}

async function capturePair(name, includeFlame = false) {
  await freezeAnimationPhase(".px-felix-body > .px-frame", 0.25);
  if (includeFlame) await freezeAnimationPhase(".px-flames > .px-frame", 0.25);
  await capture(`${name}-a`);
  await freezeAnimationPhase(".px-felix-body > .px-frame", 0.75);
  if (includeFlame) await freezeAnimationPhase(".px-flames > .px-frame", 0.75);
  await capture(`${name}-b`);
}

async function beginTravel(zone) {
  // Put Felix elsewhere first so capturing Contacts is deterministic even
  // when the autonomous patrol happened to begin at Contacts.
  await page.evaluate(async (target) => {
    const felix = await import("/src/felixStore.js");
    felix.S.scene.zone = target === "contacts" ? "companies" : "contacts";
    felix.S.scene.selected = "";
    felix.selectStation(target);
  }, zone);
}

async function selectAndWait(zone, spriteFragment) {
  await beginTravel(zone);
  await page.locator(`img[src*="${spriteFragment}"]`).first().waitFor({ state: "visible", timeout: 7000 });
  await page.waitForTimeout(120);
}

await capture("idle");
await selectAndWait("contacts", "felix-8bit-v7-contacts");
await capturePair("contacts");
await selectAndWait("companies", "felix-8bit-v7-repair");
await capturePair("companies");
await selectAndWait("funds", "felix-8bit-v7-repair");
await capturePair("funds");
await selectAndWait("notes", "felix-8bit-v7-notes");
await capturePair("notes");

await page.evaluate(async () => {
  const felix = await import("/src/felixStore.js");
  felix.S.scene.researching = true;
  felix.selectStation("research");
});
await page.locator('img[src*="felix-8bit-v7-research"]').first().waitFor({ state: "visible", timeout: 7000 });
await page.waitForTimeout(120);
await capturePair("research");

// Exercise the powered presentation without starting a backend job. Selecting
// a station emits the already-mutated scene state and begins the fast journey.
await page.evaluate(async () => {
  const felix = await import("/src/felixStore.js");
  felix.S.scene.power = true;
  felix.S.scene.researching = false;
  felix.S.scene.zone = "companies";
  felix.S.scene.selected = "";
  felix.selectStation("funds");
});
await page.locator(".px-flames").waitFor({ state: "visible", timeout: 3000 });
await page.locator('img[src*="felix-8bit-v7-repair"]').first()
  .waitFor({ state: "visible", timeout: 5000 });
await capturePair("powered", true);

await page.getByRole("button", { name: "Minimize Felix workshop" }).click();
await page.evaluate(async () => {
  const felix = await import("/src/felixStore.js");
  felix.S.scene.power = false;
  felix.S.scene.activity = "walk";
  felix.S.scene.direction = "left";
  felix.S.scene.zone = "contacts";
  felix.S.scene.pickups = [{ id: 999001, type: "merge" }];
  felix.selectStation("contacts");
});
await page.locator(".px-mini-pickup").waitFor({ state: "visible" });
await freezeAnimationPhase(".px-mini-pickup", 0.35);
await page.locator(".px-workshop-sticky").screenshot({
  path: path.join(output, "compact.png"),
});
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(150);
await page.locator(".px-workshop-sticky").screenshot({
  path: path.join(output, "compact-sticky.png"),
});

await browser.close();
console.log(`Screenshots: ${output}`);
