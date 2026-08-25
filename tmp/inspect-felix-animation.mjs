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
  sessionStorage.setItem("wb-felix-compact", "0");
});
await page.goto("http://127.0.0.1:5173/#/felix", { waitUntil: "domcontentloaded" });
await page.locator(".px-office").waitFor({ state: "visible" });

async function forceContacts() {
  await page.evaluate(async () => {
    const fx = await import("/src/felixStore.js");
    Object.assign(fx.S.scene, {
      zone: "contacts",
      activity: "fix",
      selected: "contacts",
      direction: "left",
      caption: "filing contact",
      power: false,
      powerBanner: 0,
      labels: [],
      pickups: [],
    });
    fx.dropLabel("__visual-check__");
  });
}

async function capture(frame, firstVisible) {
  await page.addStyleTag({ content: `
    .px-felix, .px-felix-body, .px-felix-body .px-frame { animation: none !important; transition: none !important; }
    .px-felix-body .px-frame:first-child { opacity: ${firstVisible ? 1 : 0} !important; }
    .px-felix-body .px-frame:last-child { opacity: ${firstVisible ? 0 : 1} !important; }
  ` });
  await forceContacts();
  const metrics = await page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
    };
    const imgs = [...document.querySelectorAll(".px-felix-sprite")];
    return {
      viewport: { width: innerWidth, height: innerHeight },
      office: rect(q(".px-office")),
      stage: rect(q(".px-stage")),
      background: rect(q(".px-office-bg")),
      felix: rect(q(".px-felix")),
      felixBody: rect(q(".px-felix-body")),
      sprites: imgs.map((img) => ({ rect: rect(img), src: img.src, transform: getComputedStyle(img).transform, opacity: getComputedStyle(img.parentElement).opacity })),
      officeObjectFit: getComputedStyle(q(".px-office-bg")).objectFit,
      officeObjectPosition: getComputedStyle(q(".px-office-bg")).objectPosition,
      stageTransform: getComputedStyle(q(".px-stage")).transform,
    };
  });
  await forceContacts();
  await page.screenshot({ path: `../tmp/felix-contacts-${frame}-viewport.png` });
  await forceContacts();
  await page.locator(".px-workshop-sticky").screenshot({ path: `../tmp/felix-contacts-${frame}-office.png` });
  return metrics;
}

const frameA = await capture("a", true);
const frameB = await capture("b", false);
const spriteComponents = await page.evaluate(async () => {
  const urls = [
    "/mascot/felix-v2/felix-8bit-v8-contacts-drop-a.png",
    "/mascot/felix-v2/felix-8bit-v9-contacts-no-card-b.png",
  ];
  const result = {};
  for (const url of urls) {
    const bitmap = await createImageBitmap(await (await fetch(url)).blob());
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(bitmap, 0, 0);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const seen = new Uint8Array(canvas.width * canvas.height);
    const components = [];
    for (let start = 0; start < seen.length; start++) {
      if (seen[start] || data[start * 4 + 3] < 16) continue;
      const stack = [start];
      seen[start] = 1;
      let count = 0, minX = canvas.width, minY = canvas.height, maxX = 0, maxY = 0;
      while (stack.length) {
        const index = stack.pop();
        const x = index % canvas.width;
        const y = Math.floor(index / canvas.width);
        count++;
        minX = Math.min(minX, x); minY = Math.min(minY, y);
        maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
        for (const next of [index - 1, index + 1, index - canvas.width, index + canvas.width]) {
          if (next < 0 || next >= seen.length || seen[next] || data[next * 4 + 3] < 16) continue;
          const nx = next % canvas.width;
          if (Math.abs(nx - x) > 1) continue;
          seen[next] = 1;
          stack.push(next);
        }
      }
      if (count >= 8) components.push({ count, x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 });
    }
    result[url] = { width: canvas.width, height: canvas.height, components: components.sort((a, b) => b.count - a.count).slice(0, 12) };
  }
  return result;
});
console.log(JSON.stringify({ frameA, frameB, spriteComponents }, null, 2));
await browser.close();
