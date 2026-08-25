/* "Pressing these buttons moves my page back to the top" — the fault the user
   has corrected across the app repeatedly (calendar pick, prep tabs, note-taker
   tabs, saved-prep open, travel tabs, and on 21 Aug 2026 the Inbox Signal
   watchlist filters). Two mechanisms cause it and both are testable:

   1. An implicit submit: a <button> without type= defaults to "submit" and
      navigates inside any form. Swept statically over every .jsx file.
   2. Scroll clamping: a filter that shrinks the content below it lets the
      browser clamp the scroll upward. Guarded two ways — the useScrollHold
      hook's behaviour is exercised directly, and a static sweep requires
      every filter primitive (<Pill>, <GroupPills>, <PeriodScrubber>, raw
      is-pill buttons) to route its click through hold(). */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useScrollHold } from "./ui.jsx";

/* ---- the hook itself ------------------------------------------------------ */

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function defineValue(obj, prop, value) {
  Object.defineProperty(obj, prop, { value, configurable: true, writable: true });
}

function Harness() {
  const hold = useScrollHold();
  const [n, setN] = React.useState(0);
  return React.createElement("button", {
    type: "button",
    onClick: () => hold(() => setN(n + 1)),
  }, String(n));
}

describe("useScrollHold", () => {
  let container, root;

  beforeEach(() => {
    window.scrollTo = vi.fn();
    defineValue(window, "scrollY", 1234);
    defineValue(window, "innerHeight", 800);
    defineValue(document.documentElement, "scrollHeight", 5000);
    container = document.createElement("div");
    document.body.appendChild(container);
    act(() => { root = createRoot(container); root.render(React.createElement(Harness)); });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("does nothing on renders that were not a held click", () => {
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("re-asserts the pre-click scroll position after the swap renders", () => {
    act(() => container.querySelector("button")
      .dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(window.scrollTo).toHaveBeenCalledTimes(1);
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 1234, behavior: "auto" });
  });

  it("clamps to the new page height when the content shrank past the old spot", () => {
    defineValue(document.documentElement, "scrollHeight", 900);
    act(() => container.querySelector("button")
      .dispatchEvent(new MouseEvent("click", { bubbles: true })));
    // max = 900 - 800: as far down as the shorter page can go, never the top.
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "auto" });
  });

  it("holds once per click, not on every later render", () => {
    const btn = () => container.querySelector("button");
    act(() => btn().dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(window.scrollTo).toHaveBeenCalledTimes(1);
    act(() => btn().dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(window.scrollTo).toHaveBeenCalledTimes(2);
  });
});

/* ---- static sweep over every component ------------------------------------ */

const SRC = path.dirname(fileURLToPath(import.meta.url));

function jsxFiles(dir = SRC) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return jsxFiles(p);
    return e.name.endsWith(".jsx") ? [p] : [];
  });
}

const lineOf = (text, idx) => text.slice(0, idx).split("\n").length;

/* Each occurrence of `tag` in every source file, with the 400 characters that
   follow it — enough to span any of this codebase's multi-line openings. */
function occurrences(tag) {
  const out = [];
  for (const file of jsxFiles()) {
    const text = fs.readFileSync(file, "utf-8");
    const rel = path.relative(SRC, file).replace(/\\/g, "/");
    for (let i = text.indexOf(tag); i >= 0; i = text.indexOf(tag, i + 1)) {
      if (!/[\s/>]/.test(text[i + tag.length] || " ")) continue; // <Pillbox etc.
      out.push({ at: `${rel}:${lineOf(text, i)}`, window: text.slice(i, i + 400), rel });
    }
  }
  return out;
}

describe("scroll-jump sweep (static, every .jsx in src)", () => {
  it("every raw <button> carries an explicit type", () => {
    const missing = occurrences("<button")
      .filter((o) => !/\btype=/.test(o.window))
      .map((o) => o.at);
    expect(missing, `buttons without type= (implicit submit): ${missing.join(", ")}`)
      .toEqual([]);
  });

  it("every <Pill> click goes through a scroll hold", () => {
    const bare = occurrences("<Pill")
      .filter((o) => !o.window.includes("hold("))
      .map((o) => o.at);
    expect(bare, `Pill filters whose click can clamp the scroll: ${bare.join(", ")}`)
      .toEqual([]);
  });

  it("group selectors and the lookback scrubber go through a scroll hold", () => {
    const bare = [...occurrences("<GroupPills"), ...occurrences("<PeriodScrubber")]
      .filter((o) => !o.window.includes("hold("))
      .map((o) => o.at);
    expect(bare, `selectors whose change can clamp the scroll: ${bare.join(", ")}`)
      .toEqual([]);
  });

  it("raw is-pill buttons go through a scroll hold", () => {
    // shared.jsx defines the Pill primitive itself (its onClick is a pass-
    // through prop, enforced at the call sites by the <Pill> rule above).
    const bare = occurrences("<button")
      .filter((o) => o.window.includes("is-pill") && !o.rel.endsWith("shared.jsx"))
      .filter((o) => !o.window.includes("hold("))
      .map((o) => o.at);
    expect(bare, `is-pill buttons whose click can clamp the scroll: ${bare.join(", ")}`)
      .toEqual([]);
  });
});
