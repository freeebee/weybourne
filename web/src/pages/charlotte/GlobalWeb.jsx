/* The global galaxy — every node in the snapshot on one canvas. Same
   pan/zoom transform as Web.jsx, different rendering economics: ~27k nodes
   and ~33k edges rule out per-node arcs, per-edge strokes, and dash
   patterns.

   Two rendering regimes:

   SETTLING — the physics runs in a Web Worker (globalSim.worker.js) whose
   ticks are slow at this scale (100-300ms each), so raw messages arrive at
   a few fps. The page INTERPOLATES between the last two position frames
   and direct-draws a lightweight scene (strided edges, dot rects, no
   labels) every animation frame — slow physics, smooth motion.

   SETTLED — the full scene (all edges, nodes, labels) renders once into an
   offscreen bitmap padded beyond the viewport; frames just blit it under
   the current transform. It re-renders only when the pan runs off the
   margin, the zoom drifts ~30% from the bitmap's scale, the gesture goes
   idle (sharpening), or display settings change. Frames with nothing new
   draw nothing.

   Hover highlights draw live on top of either regime via a precomputed
   adjacency map. The settled world is cached at module scope per crawl;
   Forces sliders restart the worker (debounced) from current positions. */
import React from "react";
import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY,
} from "d3-force";
import * as cs from "./charlotteStore.js";
import { toWorld, zoomAround } from "./geometry.js";
import {
  ANCHOR_STRENGTH, ANCHORED_LINK_DAMP, drawGroupDiscs, drawGroupLabels,
  leafStats, plannedStats, sectorAnchors,
} from "./layers.js";

const KIND_FILL = cs.KIND_COLORS;
const KINDS = Object.keys(KIND_FILL);
const EDGE_SOLID = "#D3C9B4";
const EDGE_DASHED = "#9A9385";
const INK = "#16415C";
const MUTED = "#7A7468";
const PAPER = "#FCFAF5";   // --paper-000: halo behind labels over edge fans

/* Removal predicate (kind filters + per-layer value hides) is shared
   with the ego view — see charlotteStore.makeHidden. */
const makeHidden = cs.makeHidden;

/* Labels over a mega-hub's edge fan are unreadable without a backing —
   stroke the text in paper first, then fill. */
function haloText(ctx, text, x, y, k) {
  ctx.strokeStyle = PAPER;
  ctx.lineWidth = 3 / k;
  ctx.lineJoin = "round";
  ctx.strokeText(text, x, y);
  ctx.fillText(text, x, y);
}

const ALPHA_MIN = 0.03;
const ARC_ZOOM = 1.4;          // below this nodes draw as rects, not arcs
const LABEL_CAP = 350;         // aligned with the local view
const HOOD_DETAIL_MAX = 1500;  // hood bigger than this: ink threads only
const SCENE_PAD = 300;         // css px of world rendered beyond the viewport
const SCENE_DRIFT = 1.3;       // re-render when blit scale leaves [1/d, d]
const SCENE_IDLE_MS = 160;     // sharpen a scaled blit once the wheel rests
const LIVE_EDGE_STRIDE = 6;    // 1-in-6 edges while assembling

/* Labels appear by importance, not all at once: the biggest hubs are named
   from far out, and the threshold relaxes as you zoom until everything in
   view is labelled. The ladder only ORDERS the flood — the occupancy grid
   is what limits density — so it opens fully at a moderate zoom: most of
   the 8.9k funds are degree-0, and gating them to k>=1.2 left swathes of
   empty paper with nameless dots (user-reported twice). byDegree is
   sorted desc, so the pass breaks early. */
const labelMinDegree = (k) =>
  (k >= 0.55 ? 0 : k >= 0.3 ? 5 : k >= 0.15 ? 25 : 60);

/* Screen-constant node radius — at galaxy scale a hub must stay a visible
   dot, and zoomed in it must not become a beach ball. Divide by k at draw. */
const screenR = (n) => 1.3 + Math.min(4.5, Math.sqrt(n.degree || 0) * 0.6);

/* One settled (or settling) world per crawl, shared across mounts. */
let world = null;

function startSim(w, viz) {
  const f = { center: viz.center, repel: viz.repel,
              linkForce: viz.linkForce, linkDist: viz.linkDist,
              groupDamp: Math.min(1,
                ANCHORED_LINK_DAMP * (viz.groupTies ?? 1)) };
  const pull = ANCHOR_STRENGTH * (viz.groupPull ?? 1);
  // Grouping layers → per-node sector anchors (none active = organic;
  // GROUP PULL at zero disables the sectors — and their discs — too).
  const fundKeys = cs.S.layers.fund.filter((l) => l.on).map((l) => l.key);
  const contactOn = cs.S.layers.contact.some((l) => l.on);
  let anchorMap = null;
  w.groups = [];
  if ((fundKeys.length || contactOn) && pull > 0) {
    const res = sectorAnchors(w.nodes, fundKeys, contactOn, w.R);
    anchorMap = res.anchors;
    w.groups = res.groups;
  }
  try {
    const worker = new Worker(
      new URL("./globalSim.worker.js", import.meta.url), { type: "module" });
    const pos = new Float32Array(2 * w.nodes.length);
    w.nodes.forEach((n, i) => {
      pos[2 * i] = n.x;
      pos[2 * i + 1] = n.y;
    });
    const deg = new Int32Array(w.nodes.length);
    w.nodes.forEach((n, i) => { deg[i] = n.degree || 0; });
    const idx = new Map(w.nodes.map((n, i) => [n, i]));
    const eArr = new Int32Array(2 * w.edges.length);
    w.edges.forEach((e, i) => {
      eArr[2 * i] = idx.get(e.a);
      eArr[2 * i + 1] = idx.get(e.b);
    });
    w.prev = null;
    w.next = null;
    w.lastMsg = 0;
    w.gap = 250;
    worker.onmessage = (ev) => {
      // Buffer frames for interpolation — the draw loop tweens between
      // prev and next so slow ticks still animate smoothly.
      w.prev = w.next || ev.data.positions;
      w.next = ev.data.positions;
      const now = performance.now();
      if (w.lastMsg) {
        w.gap = Math.min(1000, w.gap * 0.7 + (now - w.lastMsg) * 0.3);
      }
      w.lastMsg = now;
      w.moved = true;
      if (ev.data.done) {
        const p = ev.data.positions;
        for (let i = 0; i < w.nodes.length; i++) {
          w.nodes[i].x = p[2 * i];
          w.nodes[i].y = p[2 * i + 1];
        }
        w.settled = true;
        worker.terminate();
        // Message handlers fire even in a hidden tab (rAF does not) —
        // pre-render the full scene, labels included, so the user comes
        // back to a finished galaxy (mirrors the local view).
        if (w.prerender) w.prerender();
      }
    };
    let anchorArrays = null;
    const transfers = [pos.buffer, deg.buffer, eArr.buffer];
    if (anchorMap) {
      const ax = new Float32Array(w.nodes.length);
      const ay = new Float32Array(w.nodes.length);
      const st = new Float32Array(w.nodes.length);
      w.nodes.forEach((n, i) => {
        const a = anchorMap.get(n);
        if (a) {
          ax[i] = a.x;
          ay[i] = a.y;
          st[i] = pull;
        }
      });
      anchorArrays = { ax, ay, st };
      transfers.push(ax.buffer, ay.buffer, st.buffer);
    }
    worker.postMessage(
      { positions: pos, count: w.nodes.length, degrees: deg, edges: eArr,
        alphaMin: ALPHA_MIN, forces: f, anchors: anchorArrays },
      transfers);
    w.worker = worker;
    w.inlineSim = null;
  } catch {
    // No Worker (odd embedder): budget-tick on the main thread instead.
    // Parameters mirror the worker's — keep them in sync.
    w.prev = null;
    w.next = null;
    w.inlineSim = forceSimulation(w.nodes)
      .force("link",
        forceLink(w.edges.map((e) => ({ source: e.a, target: e.b })))
          .distance(40 * f.linkDist)
          .strength((l) => Math.min(1, f.linkForce
            / Math.min(l.source.degree || 1, l.target.degree || 1))
            * (anchorMap && (anchorMap.has(l.source)
                             || anchorMap.has(l.target))
               ? f.groupDamp : 1)))
      .force("charge", forceManyBody().strength(-50 * f.repel).theta(1.3))
      .force("collide", forceCollide()
        .radius((d) => 10 + Math.min(12, Math.sqrt(d.degree || 0))))
      .force("x", forceX(0).strength(0.02 * f.center))
      .force("y", forceY(0).strength(0.02 * f.center))
      .alphaDecay(0.03).alphaMin(ALPHA_MIN)
      .stop();
    if (anchorMap) {
      w.inlineSim
        .force("ax", forceX((d) => anchorMap.get(d)?.x || 0)
          .strength((d) => (anchorMap.get(d) ? pull : 0)))
        .force("ay", forceY((d) => anchorMap.get(d)?.y || 0)
          .strength((d) => (anchorMap.get(d) ? pull : 0)));
    }
  }
}

function ensureWorld(g) {
  if (world && world.crawledAt === g.crawledAt) return world;
  if (world?.worker) world.worker.terminate();
  const R = Math.max(700, Math.sqrt(g.nodes.length) * 24);
  for (const n of g.nodes) {
    if (n.x === undefined) {
      const a = Math.random() * Math.PI * 2;
      const r = R * Math.sqrt(Math.random());
      n.x = Math.cos(a) * r;
      n.y = Math.sin(a) * r;
    }
  }
  const adj = new Map();
  for (const e of g.edges) {
    let la = adj.get(e.a);
    if (!la) adj.set(e.a, la = []);
    la.push(e);
    let lb = adj.get(e.b);
    if (!lb) adj.set(e.b, lb = []);
    lb.push(e);
  }
  const byDegree = [...g.nodes].sort(
    (a, b) => (b.degree || 0) - (a.degree || 0));
  world = { crawledAt: g.crawledAt, nodes: g.nodes, edges: g.edges,
            adj, byDegree, R, settled: false, moved: true };
  startSim(world, cs.S.viz);
  return world;
}

/* Full-detail scene render at transform t into the offscreen bitmap —
   settled regime only. */
function renderScene(scene, w, t, viewW, viewH, dpr, viz, flt, isHid) {
  const cssW = viewW + SCENE_PAD * 2;
  const cssH = viewH + SCENE_PAD * 2;
  const bw = Math.round(cssW * dpr);
  const bh = Math.round(cssH * dpr);
  if (scene.canvas.width !== bw || scene.canvas.height !== bh) {
    scene.canvas.width = bw;
    scene.canvas.height = bh;
  }
  const fadeA = Math.max(0.05, 1 - viz.fadeAmount);
  const ctx = scene.ctx;
  const ox = t.x + SCENE_PAD;
  const oy = t.y + SCENE_PAD;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * ox, dpr * oy);

  const pad = 20 / t.k;
  const tl = toWorld(-SCENE_PAD, -SCENE_PAD, t);
  const br = toWorld(viewW + SCENE_PAD, viewH + SCENE_PAD, t);
  const x0 = tl.x - pad, y0 = tl.y - pad;
  const x1 = br.x + pad, y1 = br.y + pad;
  const inView = (p) => p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1;

  // Group underlays go first — everything else draws over the tint.
  const gstats = leafStats(w.groups, isHid).filter((gs) =>
    gs.x + gs.r >= x0 && gs.x - gs.r <= x1
    && gs.y + gs.r >= y0 && gs.y - gs.r <= y1);
  drawGroupDiscs(ctx, gstats, t.k);

  // Edges: two batched paths (dash patterns are unaffordable here —
  // inferred edges read as the fainter grey instead). Under a kind filter
  // the whole thread layer steps back so the chosen kinds pop.
  ctx.lineWidth = 0.7 / t.k;
  for (const inferred of [false, true]) {
    ctx.beginPath();
    for (const e of w.edges) {
      if (e.inferred !== inferred) continue;
      if (isHid && (isHid(e.a) || isHid(e.b))) continue;
      if (!inView(e.a) && !inView(e.b)) continue;
      ctx.moveTo(e.a.x, e.a.y);
      ctx.lineTo(e.b.x, e.b.y);
    }
    ctx.globalAlpha = (inferred ? 0.16 : 0.28) * (flt ? 0.5 : 1);
    ctx.strokeStyle = inferred ? EDGE_DASHED : EDGE_SOLID;
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  // Nodes: batched per kind so fillStyle changes four times, not 27k.
  // Rects below the arc zoom — at dot scale the eye can't tell. Kinds a
  // filter excludes fade back instead of disappearing.
  const asArcs = t.k >= ARC_ZOOM;
  let visNodes = 0;
  for (const kind of KINDS) {
    ctx.fillStyle = KIND_FILL[kind];
    ctx.globalAlpha = flt && !flt.has(kind) ? fadeA : 1;
    ctx.beginPath();
    for (const n of w.nodes) {
      if ((KIND_FILL[n.kind] ? n.kind : "external") !== kind) continue;
      if (isHid && isHid(n)) continue;
      if (!inView(n)) continue;
      visNodes++;
      const r = (screenR(n) * viz.nodeScale) / t.k;
      if (asArcs) {
        ctx.moveTo(n.x + r, n.y);
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      } else {
        ctx.rect(n.x - r, n.y - r, r * 2, r * 2);
      }
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Labels: greedy, collision-culled, in scene space. With a kind filter
  // on, every survivor qualifies at ANY zoom — the occupancy grid limits
  // density instead of a zoom threshold guessing at it; without one, the
  // degree ladder gates candidacy. byDegree order means the biggest hubs
  // claim their space first.
  // The degree ladder only matters when the view is CROWDED. When
  // filters (or zoom) leave few nodes on screen, whitespace is the
  // resource — label everything the occupancy grid will take
  // (user-reported: filtered view, all whitespace, no labels).
  const minDeg = (flt || visNodes <= 2000) ? 0 : labelMinDegree(t.k);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const fs = 10.5 * viz.textScale;
  ctx.font = `${fs}px "Hanken Grotesk", sans-serif`;
  ctx.fillStyle = INK;
  ctx.strokeStyle = PAPER;
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";
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
  // Sector labels first — group names claim their spots before node
  // labels compete for them, PARENT layers before their children (a
  // middle layer like geography must be readable by name, not only by
  // blob position). Labels sit on live centroids: leaves just above
  // their tinted blob, parents over their whole region, sized up by how
  // far above the leaves they sit. The grid culls overlap.
  if (gstats.length) {
    const base = 9.5 * viz.textScale;
    const maxLv = gstats.reduce((m, g) => Math.max(m, g.level), 0);
    const gs = [...gstats].sort((g1, g2) =>
      g1.level - g2.level || g2.count - g1.count);
    let gDrawn = 0;
    for (const g of gs) {
      if (gDrawn >= 110) break;
      const text = String(g.label || "").toUpperCase();
      if (!text) continue;
      const gfs = base * Math.min(1.4, 1 + 0.18 * (maxLv - g.level));
      ctx.font = `600 ${gfs}px "IBM Plex Mono", monospace`;
      ctx.fillStyle = g.leaf ? g.color : MUTED;
      const gx = g.x * t.k + ox;
      const gy = g.leaf ? (g.y - g.r) * t.k + oy - 5 : g.y * t.k + oy;
      const gw = text.length * gfs * 0.62;
      if (!claim(gx - gw / 2, gy - gfs, gw, gfs * 1.4)) continue;
      ctx.strokeText(text, gx - gw / 2, gy);
      ctx.fillText(text, gx - gw / 2, gy);
      gDrawn++;
    }
    ctx.font = `${fs}px "Hanken Grotesk", sans-serif`;
    ctx.fillStyle = INK;
  }
  let drawn = 0;
  for (const n of w.byDegree) {
    if (drawn >= LABEL_CAP) break;
    if ((n.degree || 0) < minDeg) break;
    if (isHid && isHid(n)) continue;
    if (flt && !flt.has(n.kind)) continue;
    if (!inView(n) || !n.label) continue;
    const sx = n.x * t.k + ox + screenR(n) * viz.nodeScale + 3;
    const sy = n.y * t.k + oy + 3;
    const cw = n.label.length * fs * 0.56;
    if (!claim(sx, sy - fs, cw, fs * 1.3)) continue;
    ctx.strokeText(n.label, sx, sy);
    ctx.fillText(n.label, sx, sy);
    drawn++;
  }
  scene.k = t.k;
  scene.x = ox;
  scene.y = oy;
  scene.cssW = cssW;
  scene.cssH = cssH;
}

/* Lightweight direct draw for the settling regime — every frame, straight
   to the visible canvas: strided edges, dot rects, no labels. Must stay
   comfortably under a frame budget at 27k nodes. */
function renderLive(ctx, w, t, viewW, viewH, dpr, viz, flt, isHid,
                    baseAlpha) {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, viewW, viewH);
  ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y);
  const pad = 20 / t.k;
  const tl = toWorld(0, 0, t);
  const br = toWorld(viewW, viewH, t);
  const x0 = tl.x - pad, y0 = tl.y - pad;
  const x1 = br.x + pad, y1 = br.y + pad;
  const inView = (p) => p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1;

  // While SETTLING, draw the PLANNED skeleton — discs and labels at
  // their target positions, visible the instant a layer changes; the
  // points migrate into it. Once settled (mid-gesture light frames),
  // track the real blobs so nothing wiggles against the crisp scene.
  const skeleton = w.groups && w.groups.length
    ? (w.settled ? leafStats(w.groups, isHid) : plannedStats(w.groups))
    : null;
  if (skeleton) drawGroupDiscs(ctx, skeleton, t.k);

  ctx.lineWidth = 0.7 / t.k;
  ctx.strokeStyle = EDGE_SOLID;
  ctx.globalAlpha = 0.26 * baseAlpha * (flt ? 0.5 : 1);
  ctx.beginPath();
  for (let i = 0; i < w.edges.length; i += LIVE_EDGE_STRIDE) {
    const e = w.edges[i];
    if (isHid && (isHid(e.a) || isHid(e.b))) continue;
    if (!inView(e.a) && !inView(e.b)) continue;
    ctx.moveTo(e.a.x, e.a.y);
    ctx.lineTo(e.b.x, e.b.y);
  }
  ctx.stroke();

  for (const kind of KINDS) {
    ctx.fillStyle = KIND_FILL[kind];
    ctx.globalAlpha = (flt && !flt.has(kind)
      ? Math.max(0.05, 1 - viz.fadeAmount) : 1) * baseAlpha;
    ctx.beginPath();
    for (const n of w.nodes) {
      if ((KIND_FILL[n.kind] ? n.kind : "external") !== kind) continue;
      if (isHid && isHid(n)) continue;
      if (!inView(n)) continue;
      const r = (screenR(n) * viz.nodeScale) / t.k;
      ctx.rect(n.x - r, n.y - r, r * 2, r * 2);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // Group names land with the skeleton, not after the settle.
  if (skeleton) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawGroupLabels(ctx, skeleton, t.k, t.x, t.y, viz.textScale,
                    MUTED, PAPER);
  }
}

export default function GlobalWeb() {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  const hostRef = React.useRef(null);
  const canvasRef = React.useRef(null);
  const transform = React.useRef(null);   // null until first fit-to-world
  const drag = React.useRef(null);
  const hood = React.useRef(null);   // {center, nodes: Set, edges: []} —
                                     // the CLICKED node's neighborhood
  const scene = React.useRef(null);
  const blitDirty = React.useRef(true);
  const lastGesture = React.useRef(0);
  const firstForces = React.useRef(true);
  const [dragging, setDragging] = React.useState(false);

  const s = cs.S;
  const g = s.global;
  const ready = !!g.nodes;

  // Display settings and the kind filter live in the scene bitmap — any
  // change invalidates it (cheap: one re-render, not a re-simulation).
  const layersKey = s.layers.fund
    .map((l) => `${l.key}${l.on ? "+" : "-"}`).join(",")
    + "|" + s.layers.contact
      .map((l) => `${l.key}${l.on ? "+" : "-"}`).join(",");
  const valueKey = cs.valueHiddenKey(s);
  const sceneKey = `${s.viz.nodeScale}|${s.viz.textScale}`
    + `|${s.viz.fadeAmount}|${s.kinds.join(",")}|${s.hidden.join(",")}`
    + `|${valueKey}|${layersKey}`;
  React.useEffect(() => {
    if (scene.current) {
      scene.current.k = 0;
      blitDirty.current = true;
    }
  }, [sceneKey]);

  // The highlight follows the SELECTION (mouseover no longer highlights):
  // clicking a node inks its neighborhood over the scene; clicking empty
  // space — or closing the drawer — clears it. Rebuilt on filter changes
  // so hidden nodes drop out of an open highlight too.
  React.useEffect(() => {
    if (!world) return;
    const n = s.selected ? g.byId?.get(s.selected) : null;
    if (n) {
      const isHid = makeHidden(cs.S);
      const edges = (world.adj.get(n) || []).filter((e) => !isHid
        || (!isHid(e.a) && !isHid(e.b)));
      const nodes = new Set([n]);
      for (const e of edges) nodes.add(e.a === n ? e.b : e.a);
      hood.current = { center: n, nodes, edges };
    } else {
      hood.current = null;
    }
    blitDirty.current = true;
  }, [s.selected, ready, g, sceneKey]);

  // Forces and layer changes restart the worker from current positions,
  // debounced so a slider drag doesn't spawn thirty workers.
  const forceKey = `${s.viz.center}|${s.viz.repel}`
    + `|${s.viz.linkForce}|${s.viz.linkDist}`
    + `|${s.viz.groupPull}|${s.viz.groupTies}|${layersKey}`;
  React.useEffect(() => {
    if (firstForces.current) {
      firstForces.current = false;
      return undefined;
    }
    const id = setTimeout(() => {
      if (!world) return;
      if (world.worker) world.worker.terminate();
      world.settled = false;
      startSim(world, cs.S.viz);
    }, 250);
    return () => clearTimeout(id);
  }, [forceKey]);

  React.useEffect(() => {
    if (!ready) return undefined;
    const w = ensureWorld(g);
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return undefined;
    const ctx = canvas.getContext("2d");
    if (!scene.current) {
      const off = document.createElement("canvas");
      scene.current = { canvas: off, ctx: off.getContext("2d"), k: 0 };
    }
    scene.current.k = 0;   // data or mount changed — force a scene render
    blitDirty.current = true;
    // Paint the settled scene outside the rAF loop — the worker done-
    // handler calls this so a hidden tab settles AND renders while the
    // user is away.
    w.prerender = () => {
      const rect = host.getBoundingClientRect();
      if (!rect.width || !transform.current) return;
      renderScene(scene.current, w, transform.current, rect.width,
                  rect.height, window.devicePixelRatio || 1, cs.S.viz,
                  cs.S.kinds.length ? new Set(cs.S.kinds) : null,
                  makeHidden(cs.S));
      w.moved = false;
      blitDirty.current = true;
    };
    const onVisible = () => { blitDirty.current = true; };
    document.addEventListener("visibilitychange", onVisible);
    let raf = 0;

    // Selection highlight, drawn live over either regime: the clicked
    // node's threads pop in ink, its neighbors redraw and get labelled —
    // purely additive, the rest of the scene stays full strength.
    const overlays = (t, dpr, viz) => {
      const hd = hood.current;
      if (!hd) return;
      const hov = hd.center;
      ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y);
      // A mega-hub's hood is thousands of members and the overlay runs
      // per frame while panning — cull to the viewport and batch, and
      // above HOOD_DETAIL_MAX skip per-node decoration entirely: the
      // inked threads ARE the story at that scale.
      const vw = canvas.width / dpr;
      const vh = canvas.height / dpr;
      const tl = toWorld(0, 0, t);
      const br = toWorld(vw, vh, t);
      const pad = 20 / t.k;
      const inV = (p) => p.x >= tl.x - pad && p.x <= br.x + pad
        && p.y >= tl.y - pad && p.y <= br.y + pad;
      const detail = hd.nodes.size <= HOOD_DETAIL_MAX;
      if (hd) {
        ctx.beginPath();
        for (const e of hd.edges) {
          if (!inV(e.a) && !inV(e.b)) continue;
          ctx.moveTo(e.a.x, e.a.y);
          ctx.lineTo(e.b.x, e.b.y);
        }
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.1 / t.k;
        ctx.stroke();
        ctx.globalAlpha = 1;
        if (viz.arrows && detail) {
          ctx.beginPath();
          for (const e of hd.edges) {
            if (!inV(e.a) && !inV(e.b)) continue;
            const dx = e.b.x - e.a.x;
            const dy = e.b.y - e.a.y;
            const len = Math.hypot(dx, dy) || 1;
            const ux = dx / len;
            const uy = dy / len;
            const rb = (screenR(e.b) * viz.nodeScale + 2) / t.k;
            const tx = e.b.x - ux * rb;
            const ty = e.b.y - uy * rb;
            const wl = 5 / t.k;
            ctx.moveTo(tx - ux * wl - uy * wl * 0.55,
                       ty - uy * wl + ux * wl * 0.55);
            ctx.lineTo(tx, ty);
            ctx.lineTo(tx - ux * wl + uy * wl * 0.55,
                       ty - uy * wl - ux * wl * 0.55);
          }
          ctx.strokeStyle = INK;
          ctx.lineWidth = 1.1 / t.k;
          ctx.stroke();
        }
        if (detail) {
          // Neighbor redraws batched per kind — one fill each, not one
          // canvas call per node.
          const paths = {};
          for (const n of hd.nodes) {
            if (!inV(n)) continue;
            const kind = KIND_FILL[n.kind] ? n.kind : "external";
            const p = paths[kind] || (paths[kind] = new Path2D());
            const r = (screenR(n) * viz.nodeScale) / t.k;
            p.moveTo(n.x + r, n.y);
            p.arc(n.x, n.y, r, 0, Math.PI * 2);
          }
          for (const kind of Object.keys(paths)) {
            ctx.fillStyle = KIND_FILL[kind];
            ctx.fill(paths[kind]);
          }
        }
        if (hd.nodes.size <= 60) {
          ctx.font = `${(10.5 * viz.textScale) / t.k}px "Hanken Grotesk", sans-serif`;
          ctx.fillStyle = INK;
          for (const n of hd.nodes) {
            if (n === hov || !n.label) continue;
            haloText(ctx, n.label,
                     n.x + (screenR(n) * viz.nodeScale + 3) / t.k,
                     n.y + 3 / t.k, t.k);
          }
        }
      }
      if (hov) {
        ctx.beginPath();
        ctx.arc(hov.x, hov.y,
                (screenR(hov) * viz.nodeScale + 3) / t.k, 0, Math.PI * 2);
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.5 / t.k;
        ctx.stroke();
        ctx.font = `600 ${(11 * viz.textScale) / t.k}px "Hanken Grotesk", sans-serif`;
        ctx.fillStyle = INK;
        haloText(ctx, hov.label || "",
                 hov.x + (screenR(hov) * viz.nodeScale + 5) / t.k,
                 hov.y + 3.5 / t.k, t.k);
      }
    };

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const rect = host.getBoundingClientRect();
      if (!rect.width) return;
      const dpr = window.devicePixelRatio || 1;
      const bw = Math.round(rect.width * dpr);
      const bh = Math.round(rect.height * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
        scene.current.k = 0;
        blitDirty.current = true;
      }
      if (!transform.current) {
        // First sight of the world: fit the seeded disc into the canvas.
        const k = Math.min(rect.width, rect.height) / (2 * w.R * 1.08);
        transform.current = { k, x: rect.width / 2, y: rect.height / 2 };
      }
      const t = transform.current;
      const sc = scene.current;
      const now = performance.now();
      const viz = cs.S.viz;
      const flt = cs.S.kinds.length ? new Set(cs.S.kinds) : null;
      const isHid = makeHidden(cs.S);

      // Fallback only — with a live worker the physics never runs here.
      if (w.inlineSim && !w.settled && !drag.current) {
        const t0 = performance.now();
        while (w.inlineSim.alpha() > ALPHA_MIN
               && performance.now() - t0 < 12) {
          w.inlineSim.tick();
        }
        if (w.inlineSim.alpha() <= ALPHA_MIN) w.settled = true;
      }

      if (!w.settled) {
        // SETTLING: tween between the worker's last two frames and
        // direct-draw a light scene — smooth motion from slow physics.
        if (w.next && w.prev) {
          const f = w.prev === w.next ? 1
            : Math.min(1, (now - w.lastMsg) / (w.gap || 250));
          for (let i = 0; i < w.nodes.length; i++) {
            const n = w.nodes[i];
            const j = 2 * i;
            n.x = w.prev[j] + (w.next[j] - w.prev[j]) * f;
            n.y = w.prev[j + 1] + (w.next[j + 1] - w.prev[j + 1]) * f;
          }
        }
        renderLive(ctx, w, t, rect.width, rect.height, dpr, viz, flt,
                   isHid, 1);
        overlays(t, dpr, viz);
        return;
      }
      if (w.moved) {
        // Settle just landed — one full-detail render, then blit forever.
        w.moved = false;
        sc.k = 0;
        blitDirty.current = true;
      }

      const ratio = sc.k ? t.k / sc.k : 0;
      const offX = sc.k ? t.x - ratio * sc.x : 0;
      const offY = sc.k ? t.y - ratio * sc.y : 0;
      const uncovered = !sc.k
        || offX > 0 || offY > 0
        || offX + sc.cssW * ratio < rect.width
        || offY + sc.cssH * ratio < rect.height;
      const drifted = sc.k
        && (ratio > SCENE_DRIFT || ratio < 1 / SCENE_DRIFT);
      const idleStale = sc.k && Math.abs(ratio - 1) > 1e-6
        && now - lastGesture.current > SCENE_IDLE_MS;
      // MID-GESTURE a full scene render (labels and all) is a visible
      // hitch — draw the light version live instead and repaint full
      // detail once the wheel rests (mirrors the local view).
      const gesturing = now - lastGesture.current < SCENE_IDLE_MS;
      if ((uncovered || drifted) && gesturing && sc.k) {
        renderLive(ctx, w, t, rect.width, rect.height, dpr, viz, flt,
                   isHid, 1);
        overlays(t, dpr, viz);
        blitDirty.current = true;
        return;
      }
      if (uncovered || drifted || idleStale) {
        renderScene(sc, w, t, rect.width, rect.height, dpr, viz, flt,
                    isHid);
        blitDirty.current = true;
      }
      if (!blitDirty.current) return;   // nothing new — free frame
      blitDirty.current = false;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      const r2 = t.k / sc.k;
      ctx.drawImage(sc.canvas, t.x - r2 * sc.x, t.y - r2 * sc.y,
                    sc.cssW * r2, sc.cssH * r2);
      overlays(t, dpr, viz);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVisible);
      w.prerender = null;
    };
  }, [ready, g]);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (ev) => {
      ev.preventDefault();
      if (!transform.current) return;
      const rect = canvas.getBoundingClientRect();
      transform.current = zoomAround(
        transform.current, ev.clientX - rect.left, ev.clientY - rect.top,
        Math.exp(-ev.deltaY * 0.0015));
      lastGesture.current = performance.now();
      blitDirty.current = true;
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  /* Kind-filtered-out nodes are background — clicks pass through them. */
  const pick = (ev) => {
    if (!world || !transform.current) return null;
    const rect = canvasRef.current.getBoundingClientRect();
    const p = toWorld(ev.clientX - rect.left, ev.clientY - rect.top,
                      transform.current);
    const k = transform.current.k;
    const ns = cs.S.viz.nodeScale;
    const flt = cs.S.kinds.length ? new Set(cs.S.kinds) : null;
    const isHid = makeHidden(cs.S);
    let best = null;
    let bestD2 = Infinity;
    for (const n of world.nodes) {
      if (isHid && isHid(n)) continue;
      if (flt && !flt.has(n.kind)) continue;
      const dx = p.x - n.x;
      const dy = p.y - n.y;
      const d2 = dx * dx + dy * dy;
      const r = (screenR(n) * ns + 3) / k;
      if (d2 <= r * r && d2 < bestD2) { best = n; bestD2 = d2; }
    }
    return best;
  };

  const onDown = (ev) => {
    drag.current = { sx: ev.clientX, sy: ev.clientY,
                     x0: transform.current?.x || 0,
                     y0: transform.current?.y || 0, moved: false };
    setDragging(true);
  };
  const onMove = (ev) => {
    if (drag.current && transform.current) {
      const dx = ev.clientX - drag.current.sx;
      const dy = ev.clientY - drag.current.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
      transform.current = { ...transform.current,
                            x: drag.current.x0 + dx, y: drag.current.y0 + dy };
      lastGesture.current = performance.now();
      blitDirty.current = true;
    }
  };
  const onUp = (ev) => {
    const wasDrag = drag.current?.moved;
    drag.current = null;
    setDragging(false);
    if (wasDrag) return;
    // A click opens the node drawer (same as the local view); diving into
    // the local web is the drawer's explicit "Zoom in" button.
    const node = pick(ev);
    cs.select(node ? node.id : null);
  };

  return (
    <div ref={hostRef} className="cw-canvas">
      <canvas ref={canvasRef} className={dragging ? "dragging" : ""}
        style={{ width: "100%", height: "100%" }}
        onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp}
        onMouseLeave={() => { drag.current = null; setDragging(false); }} />
    </div>
  );
}
