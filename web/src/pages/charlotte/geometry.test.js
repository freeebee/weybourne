import { describe, expect, it } from "vitest";

import {
  nodeRadius, pickEdge, pickNode, segDist, toWorld, zoomAround,
} from "./geometry.js";

describe("Charlotte's Web geometry", () => {
  it("inverts the pan/zoom transform", () => {
    const t = { x: 40, y: -10, k: 2 };
    const w = toWorld(140, 90, t);
    expect(w).toEqual({ x: 50, y: 50 });
  });

  it("picks the node under the cursor, nearest first", () => {
    const nodes = [{ id: "a", degree: 0 }, { id: "b", degree: 0 }];
    const positions = { a: { x: 100, y: 100 }, b: { x: 108, y: 100 } };
    const hit = pickNode(nodes, positions, 106, 100, 1);
    expect(hit.id).toBe("b");
    expect(pickNode(nodes, positions, 300, 300, 1)).toBeNull();
  });

  it("slack shrinks with zoom so hit areas stay screen-sized", () => {
    const nodes = [{ id: "a", degree: 0 }];
    const positions = { a: { x: 0, y: 0 } };
    // 9px away: inside radius 7 + 3-slack at k=1, outside at k=4.
    expect(pickNode(nodes, positions, 9, 0, 1)?.id).toBe("a");
    expect(pickNode(nodes, positions, 9.9, 0, 4)).toBeNull();
  });

  it("point-segment distance clamps to the endpoints", () => {
    expect(segDist(0, 5, 0, 0, 10, 0)).toBe(5);        // above the middle
    expect(segDist(-3, 0, 0, 0, 10, 0)).toBe(3);       // beyond an endpoint
    expect(segDist(4, 0, 5, 5, 5, 5)).toBeCloseTo(Math.hypot(1, 5)); // zero-length
  });

  it("picks an edge only when genuinely close", () => {
    const edges = [{ a: "a", b: "b", type: "discussed" }];
    const positions = { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } };
    expect(pickEdge(edges, positions, 50, 3, 1)).toBe(edges[0]);
    expect(pickEdge(edges, positions, 50, 9, 1)).toBeNull();
  });

  it("zoomAround keeps the point under the cursor fixed", () => {
    const t = { x: 0, y: 0, k: 1 };
    const zoomed = zoomAround(t, 100, 100, 2);
    const before = toWorld(100, 100, t);
    const after = toWorld(100, 100, zoomed);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
    expect(zoomed.k).toBe(2);
  });

  it("clamps zoom to sane bounds", () => {
    expect(zoomAround({ x: 0, y: 0, k: 1 }, 0, 0, 100).k).toBe(4);
    expect(zoomAround({ x: 0, y: 0, k: 1 }, 0, 0, 0.001).k).toBe(0.05);
  });

  it("node radius grows gently with degree", () => {
    expect(nodeRadius({ degree: 0 })).toBe(7);
    expect(nodeRadius({ degree: 10000 })).toBe(13);   // capped
  });
});
