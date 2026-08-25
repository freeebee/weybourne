/* Sector-anchored grouping for the global view.

   The active fund layers, in order, define a hierarchy (e.g. access →
   asset class → geography). Each level splits its parent's arc
   proportionally to member counts, so the top layer makes the biggest
   angular divisions and each further layer nests inside them. Every
   leaf group gets one anchor point on a ring; the simulation pulls its
   members there and charge/collide shape the blob organically.
   Contacts (when grouped by type) get their own sectors on an outer
   ring, independent of the fund stack. Companies and notes are never
   anchored — they follow their links. Pure functions, unit-tested. */

export const FUND_LAYER_LABELS = {
  asset_class: "ASSET CLASS",
  geography: "GEOGRAPHY",
  quality: "QUALITY",
};

/* Sector pull vs link pull decides whether groups actually read as
   groups: strong anchors + damped links on anchored nodes keep every
   member visibly inside its cluster while links still curve neighbors
   toward it. Baselines for the GROUP PULL / GROUP TIES sliders
   (multipliers, 1 = this look). Shared by both canvases and mirrored
   into globalSim.worker.js via the transferred strengths/forces. */
export const ANCHOR_STRENGTH = 0.4;
export const ANCHORED_LINK_DAMP = 0.3;

/* Muted tints for the group underlays, cycled in angular order so
   neighboring sectors never share a hue — what makes "these are
   different groupings" legible at a glance. All paper-compatible
   mid-tones from the house family (teal / navy / plum / brass +
   moss / rust / slate / aubergine). */
export const GROUP_TINTS = [
  "#2E8B84", "#8A557E", "#B0894E", "#1D3D52",
  "#6A7F4F", "#A65941", "#5A6E8C", "#7A4E5E",
];

/* Where each leaf group ACTUALLY sits: centroid + spread of its visible
   members' live positions (theoretical ring positions lie once links
   have tugged a blob). getPos maps a member node to its live {x, y} —
   the global view stores positions on the node itself (the default);
   the ego view keeps them in a separate sim map. Colors are assigned
   by angular position BEFORE any view filtering, so a group keeps its
   tint while panning. Cheap enough to run per frame. */
export function leafStats(groups, isHid, getPos = (n) => n) {
  const out = [];
  let tint = 0;
  for (const g of groups || []) {
    if (!g.nodes) continue;
    const pts = [];
    for (const n of g.nodes) {
      if (isHid && isHid(n)) continue;
      const p = getPos(n);
      if (p) pts.push(p);
    }
    if (!pts.length) continue;
    let cx = 0, cy = 0;
    for (const p of pts) {
      cx += p.x;
      cy += p.y;
    }
    cx /= pts.length;
    cy /= pts.length;
    let d2 = 0;
    for (const p of pts) {
      const dx = p.x - cx, dy = p.y - cy;
      d2 += dx * dx + dy * dy;
    }
    // RMS radius, capped near the collide-packing radius for the member
    // count — a handful of link-dragged outliers must not balloon the
    // disc over half the view.
    const rPack = Math.sqrt(pts.length) * 16 + 30;
    const r = Math.max(26,
      Math.min(Math.sqrt(d2 / pts.length) * 1.5 + 12, rPack));
    out.push({ label: g.label, count: pts.length, x: cx, y: cy, r,
               level: g.level || 0, leaf: !!g.leaf,
               // Tints cycle over LEAVES in angular order (neighbors
               // never share a hue); parent labels render neutral.
               color: g.leaf
                 ? GROUP_TINTS[tint++ % GROUP_TINTS.length] : null });
  }
  return out;
}

/* Where each group WILL sit — the theoretical skeleton, drawable the
   instant a layer changes, before a single node has migrated. Same
   shape as leafStats (tint order matches, so colors don't jump when
   the live stats take over after the settle). */
export function plannedStats(groups) {
  const out = [];
  let tint = 0;
  for (const g of groups || []) {
    if (!g.nodes) continue;
    const r = Math.max(26, Math.sqrt(g.count) * 16 + 30);
    out.push({ label: g.label, count: g.count, x: g.ax, y: g.ay, r,
               level: g.level || 0, leaf: !!g.leaf,
               color: g.leaf
                 ? GROUP_TINTS[tint++ % GROUP_TINTS.length] : null });
  }
  return out;
}

/* Group label pass — screen space, parents before children, sized up by
   distance above the leaves, overlap-culled by its own grid. Caller
   must have set the SCREEN transform (setTransform(dpr,0,0,dpr,0,0));
   ox/oy are the world origin's screen offset. */
export function drawGroupLabels(ctx, stats, k, ox, oy, textScale,
                                muted, paper) {
  if (!stats.length) return;
  const base = 9.5 * textScale;
  const maxLv = stats.reduce((m, g) => Math.max(m, g.level), 0);
  const ordered = [...stats].sort((g1, g2) =>
    g1.level - g2.level || g2.count - g1.count);
  const cells = new Set();
  const claim = (x, y, cw, ch) => {
    const c0 = Math.floor(x / 24), c1 = Math.floor((x + cw) / 24);
    const r0 = Math.floor(y / 14), r1 = Math.floor((y + ch) / 14);
    for (let cx = c0; cx <= c1; cx++) {
      for (let cy = r0; cy <= r1; cy++) {
        if (cells.has(`${cx}|${cy}`)) return false;
      }
    }
    for (let cx = c0; cx <= c1; cx++) {
      for (let cy = r0; cy <= r1; cy++) cells.add(`${cx}|${cy}`);
    }
    return true;
  };
  ctx.lineJoin = "round";
  ctx.lineWidth = 3;
  ctx.strokeStyle = paper;
  for (const g of ordered) {
    const text = String(g.label || "").toUpperCase();
    if (!text) continue;
    const gfs = base * Math.min(1.4, 1 + 0.18 * (maxLv - g.level));
    ctx.font = `600 ${gfs}px "IBM Plex Mono", monospace`;
    ctx.fillStyle = g.leaf ? g.color : muted;
    const gx = g.x * k + ox;
    const gy = g.leaf ? (g.y - g.r) * k + oy - 5 : g.y * k + oy;
    const gw = text.length * gfs * 0.62;
    if (!claim(gx - gw / 2, gy - gfs, gw, gfs * 1.4)) continue;
    ctx.strokeText(text, gx - gw / 2, gy);
    ctx.fillText(text, gx - gw / 2, gy);
  }
}

/* Faint tinted discs under the LEAF groups — the thing that makes
   sectors legible at a glance. World-space; call with the world
   transform already set. */
export function drawGroupDiscs(ctx, stats, k) {
  if (!stats.length) return;
  ctx.lineWidth = 1 / k;
  for (const gs of stats) {
    if (!gs.leaf) continue;
    ctx.fillStyle = gs.color;
    ctx.strokeStyle = gs.color;
    ctx.beginPath();
    ctx.arc(gs.x, gs.y, gs.r, 0, Math.PI * 2);
    ctx.globalAlpha = 0.07;
    ctx.fill();
    ctx.globalAlpha = 0.18;
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

const val = (n, key) => {
  const v = n[key];
  const s = v === undefined || v === null ? "" : String(v).trim();
  return s || "OTHER";
};

/* Buckets of members by one attribute, largest first (name breaks ties)
   so arc order is stable across re-runs. */
function orderedBuckets(members, key) {
  const buckets = new Map();
  for (const n of members) {
    const v = val(n, key);
    let b = buckets.get(v);
    if (!b) buckets.set(v, b = []);
    b.push(n);
  }
  return [...buckets.entries()].sort(
    (x, y) => y[1].length - x[1].length || (x[0] < y[0] ? -1 : 1));
}

function subdivide(members, keys, depth, a0, span, path, out) {
  if (depth >= keys.length) {
    const mid = a0 + span / 2;
    const x = Math.cos(mid) * out.leafR;
    const y = Math.sin(mid) * out.leafR;
    for (const n of members) out.anchors.set(n, { x, y });
    out.groups.push({
      x: Math.cos(mid) * out.labelR,
      y: Math.sin(mid) * out.labelR,
      // The anchor point — where this blob WILL sit. plannedStats draws
      // the instant skeleton from these before any node has moved.
      ax: x,
      ay: y,
      label: path[path.length - 1] || "",
      count: members.length,
      top: false,
      level: path.length - 1,
      leaf: true,
      // Member refs let the renderer find where the group ACTUALLY
      // settled (links drag blobs off the theoretical ring) and draw
      // its label + backing disc on the real cluster.
      nodes: members,
    });
    return;
  }
  let a = a0;
  for (const [v, list] of orderedBuckets(members, keys[depth])) {
    const s = span * (list.length / members.length);
    // EVERY internal level emits a labeled group too — a middle layer
    // (e.g. geography between access and asset class) must be visible
    // by name, not only through blob positions (user-reported: moved
    // GEOGRAPHY up the stack and couldn't find it anywhere). Renderers
    // place these at the live centroid of their members, sized up by
    // how far above the leaves they sit.
    if (depth < keys.length - 1) {
      const mid = a + s / 2;
      out.groups.push({
        x: Math.cos(mid) * out.labelR,
        y: Math.sin(mid) * out.labelR,
        ax: Math.cos(mid) * out.leafR,
        ay: Math.sin(mid) * out.leafR,
        label: v,
        count: list.length,
        top: depth === 0,
        level: depth,
        leaf: false,
        nodes: list,
      });
    }
    subdivide(list, keys, depth + 1, a, s, [...path, v], out);
    a += s;
  }
}

/* nodes: the full global node list (objects with kind + attrs).
   fundLayerKeys: ordered ACTIVE fund layer keys ([] = no fund grouping).
   contactOn: group contacts by contact_type on the outer ring.
   R: the world's seed-disc radius (sets the ring scale).
   Returns { anchors: Map(node -> {x,y}), groups: [{x,y,label,count,top}] }. */
export function sectorAnchors(nodes, fundLayerKeys, contactOn, R) {
  const anchors = new Map();
  const groups = [];
  const funds = [];
  const contacts = [];
  for (const n of nodes) {
    if (n.kind === "fund") funds.push(n);
    else if (n.kind === "contact") contacts.push(n);
  }
  if (fundLayerKeys.length && funds.length) {
    const out = { anchors, groups, leafR: R * 0.55, labelR: R * 0.95 };
    subdivide(funds, fundLayerKeys, 0, -Math.PI / 2, Math.PI * 2, [], out);
  }
  if (contactOn && contacts.length) {
    const out = { anchors, groups, leafR: R * 1.3, labelR: R * 1.5 };
    subdivide(contacts, ["contact_type"], 0, -Math.PI / 2, Math.PI * 2,
              [], out);
  }
  return { anchors, groups };
}
