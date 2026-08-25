import { describe, expect, it } from "vitest";

import { sectorAnchors } from "./layers.js";

const fund = (id, attrs = {}) => ({ id, kind: "fund", ...attrs });
const contact = (id, t) => ({ id, kind: "contact", contact_type: t });

describe("sectorAnchors", () => {
  it("splits arcs proportionally and anchors members together", () => {
    const nodes = [
      fund("a", { access: "Private" }),
      fund("b", { access: "Private" }),
      fund("c", { access: "Private" }),
      fund("d", { access: "Public" }),
    ];
    const { anchors, groups } = sectorAnchors(nodes, ["access"], false, 100);
    // One anchor point per group, shared by its members.
    expect(anchors.get(nodes[0])).toEqual(anchors.get(nodes[1]));
    expect(anchors.get(nodes[0])).toEqual(anchors.get(nodes[2]));
    expect(anchors.get(nodes[3])).not.toEqual(anchors.get(nodes[0]));
    // Anchors sit on the leaf ring (R * 0.55).
    const p = anchors.get(nodes[0]);
    expect(Math.hypot(p.x, p.y)).toBeCloseTo(55, 5);
    // Largest group first, counts carried.
    expect(groups.map((g) => [g.label, g.count]))
      .toEqual([["Private", 3], ["Public", 1]]);
    // Leaf groups carry member refs so the renderer can draw labels and
    // backing discs on the settled blob, not the theoretical ring.
    expect(groups[0].nodes).toEqual([nodes[0], nodes[1], nodes[2]]);
  });

  it("nests by layer order — reordering changes the leaves", () => {
    const nodes = [
      fund("a", { access: "Private", geography: "US" }),
      fund("b", { access: "Private", geography: "Europe" }),
      fund("c", { access: "Public", geography: "US" }),
    ];
    const byAccess = sectorAnchors(nodes, ["access", "geography"], false, 100);
    const byGeo = sectorAnchors(nodes, ["geography", "access"], false, 100);
    const leaves = (r) => r.groups.filter((g) => !g.top)
      .map((g) => `${g.label}:${g.count}`).sort();
    // Same leaf partitions here, but different anchor placement: the two
    // US funds split under access-first yet sit adjacent under geo-first.
    expect(leaves(byAccess)).toEqual(["Europe:1", "US:1", "US:1"]);
    expect(byAccess.anchors.get(nodes[0]))
      .not.toEqual(byGeo.anchors.get(nodes[0]));
    // Top-level context labels come from the FIRST layer.
    expect(byAccess.groups.filter((g) => g.top).map((g) => g.label))
      .toEqual(["Private", "Public"]);
    expect(byGeo.groups.filter((g) => g.top).map((g) => g.label))
      .toEqual(["US", "Europe"]);
  });

  it("buckets blank values as OTHER", () => {
    const nodes = [fund("a", {}), fund("b", { access: "Private" })];
    const { groups } = sectorAnchors(nodes, ["access"], false, 100);
    expect(groups.map((g) => g.label).sort()).toEqual(["OTHER", "Private"]);
  });

  it("groups contacts on the outer ring independently", () => {
    const nodes = [
      fund("f", { access: "Private" }),
      contact("p1", "GP - Investments"),
      contact("p2", "Other"),
    ];
    const { anchors } = sectorAnchors(nodes, [], true, 100);
    // No fund layers active: funds unanchored, contacts on R * 1.3.
    expect(anchors.has(nodes[0])).toBe(false);
    const p = anchors.get(nodes[1]);
    expect(Math.hypot(p.x, p.y)).toBeCloseTo(130, 5);
  });

  it("anchors nothing when no layers are active", () => {
    const { anchors, groups } = sectorAnchors(
      [fund("a", { access: "Private" }), contact("p", "Other")],
      [], false, 100);
    expect(anchors.size).toBe(0);
    expect(groups).toEqual([]);
  });
});
