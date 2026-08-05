import { defineConfig } from "vitest/config";

/* The stores are plain module state, but they touch browser APIs on the way
   past (cancelAnimationFrame in stop(), for one), so they run under jsdom. */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.js"],
  },
});
