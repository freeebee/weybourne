import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const label = process.argv[2] || "compact-scale";
const output = path.resolve("..", "tmp", "playwright", label);
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1800, height: 900 } });
await page.addInitScript(() => sessionStorage.setItem("wb-splash-seen", "1"));
await page.goto("http://127.0.0.1:5173/#/felix", { waitUntil: "domcontentloaded" });
await page.getByRole("button", { name: "Minimize Felix workshop" }).click();

async function setScene(activity) {
  await page.evaluate(async (nextActivity) => {
    const felix = await import("/src/felixStore.js");
    felix.S.scene.zone = "companies";
    felix.S.scene.activity = nextActivity;
    felix.S.scene.direction = "right";
    felix.S.scene.power = false;
    felix.selectStation("companies");
  }, activity);
  await page.waitForTimeout(80);
}

async function measure(name) {
  const result = await page.locator(".px-mini-felix img").first().evaluate(async (img) => {
    if (!img.complete) await new Promise((resolve) => img.addEventListener("load", resolve, { once: true }));
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(img, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let minX = canvas.width, minY = canvas.height, maxX = -1, maxY = -1;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        if (pixels[(y * canvas.width + x) * 4 + 3] > 16) {
          minX = Math.min(minX, x); minY = Math.min(minY, y);
          maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
        }
      }
    }
    const rect = img.getBoundingClientRect();
    const sourceWidth = maxX - minX + 1;
    const sourceHeight = maxY - minY + 1;
    return {
      src: img.getAttribute("src"),
      cssBox: { width: rect.width, height: rect.height },
      visibleBox: {
        width: rect.width * sourceWidth / canvas.width,
        height: rect.height * sourceHeight / canvas.height,
      },
      transform: getComputedStyle(img).transform,
    };
  });
  await page.locator(".px-workshop-sticky").screenshot({
    path: path.join(output, `${name}.png`),
  });
  return result;
}

await setScene("walk");
const running = await measure("running");
await setScene("fix");
const working = await measure("working");

const visibleWidthRatio = working.visibleBox.width / running.visibleBox.width;
console.log(JSON.stringify({ running, working, visibleWidthRatio }, null, 2));

await browser.close();
