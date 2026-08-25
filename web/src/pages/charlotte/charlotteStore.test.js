import { beforeEach, describe, expect, it } from "vitest";

import { S, mergeView } from "./charlotteStore.js";

const node = (id, kind = "contact") => ({ id, kind, label: id.toUpperCase() });

beforeEach(() => {
  S.nodes = {};
  S.edges = [];
  S.lp = [];
  S.positions = {};
  S.center = null;
  S.meta = null;
});

describe("charlotteStore.mergeView", () => {
  it("replace keeps positions of surviving nodes and drops the rest", () => {
    S.positions = { a: { x: 1, y: 2 }, gone: { x: 9, y: 9 } };
    mergeView({ nodes: [node("a"), node("b")], edges: [] }, { replace: true });
    expect(Object.keys(S.nodes).sort()).toEqual(["a", "b"]);
    expect(S.positions.a).toEqual({ x: 1, y: 2 });     // world stays put
    expect(S.positions.gone).toBeUndefined();
  });

  it("expand merges without duplicating nodes or edges", () => {
    mergeView({ nodes: [node("a"), node("b")],
                edges: [{ a: "a", b: "b", type: "discussed" }] },
              { replace: true });
    mergeView({ nodes: [node("b"), node("c")],
                edges: [{ a: "a", b: "b", type: "discussed" },
                        { a: "b", b: "c", type: "employed_by" }] });
    expect(Object.keys(S.nodes).sort()).toEqual(["a", "b", "c"]);
    expect(S.edges).toHaveLength(2);
  });

  it("expand seeds new nodes near the anchor so growth reads as growth", () => {
    S.positions = { hub: { x: 200, y: 300 } };
    mergeView({ nodes: [node("hub"), node("fresh")], edges: [] },
              { anchor: "hub" });
    const p = S.positions.fresh;
    expect(Math.abs(p.x - 200)).toBeLessThanOrEqual(35);
    expect(Math.abs(p.y - 300)).toBeLessThanOrEqual(35);
  });

  it("same edge with a different type is a different connection", () => {
    mergeView({ nodes: [node("a"), node("f", "fund")],
                edges: [{ a: "a", b: "f", type: "discussed" },
                        { a: "a", b: "f", type: "known_lp" }] },
              { replace: true });
    expect(S.edges).toHaveLength(2);
  });

  it("lp candidates replace on recenter, persist through expands", () => {
    mergeView({ nodes: [node("f", "fund")], edges: [],
                lp_candidates: [{ id: "a", tier: "T1" }] }, { replace: true });
    expect(S.lp).toHaveLength(1);
    mergeView({ nodes: [node("x")], edges: [] });   // expand payload, no lp
    expect(S.lp).toHaveLength(1);
  });
});
