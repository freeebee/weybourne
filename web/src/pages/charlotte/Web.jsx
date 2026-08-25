/* The local (ego) force-directed canvas. Since the fanout cap was removed
   a mega-hub's web runs to many thousands of nodes, so this canvas uses
   the FULL set of global-view rendering economics at local scale:

   SETTLING — physics run in the shared worker (globalSim.worker.js,
   `ego` tuning: per-link rest lengths, per-node collide radii, pinned
   center) and the page interpolates between its frames, direct-drawing
   a light scene (strided edges, dot rects, no labels) each frame.

   SETTLED — the full scene (discs, edges, nodes, labels) renders once
   into an offscreen bitmap padded beyond the viewport; frames blit it
   under the current transform and re-render only on pan past the
   margin, ~30% zoom drift, gesture idle (sharpening), or display
   changes. Frames with nothing new draw NOTHING — the store version,
   gestures, and animations set a dirty flag.

   The click highlight (hood + shortest chain home), rings, feelers and
   grow-in edges draw live as overlays over either regime; the hood is
   cached per selection, never rebuilt per frame. The world is
   0-centered; the auto-fit camera does the framing. Hit-testing
   inverts the {x, y, k} transform (geometry.js). */
import React from "react";
import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY,
} from "d3-force";
import * as cs from "./charlotteStore.js";
import { nodeRadius, pickEdge, pickNode, toWorld, zoomAround } from "./geometry.js";
import {
  ANCHOR_STRENGTH, ANCHORED_LINK_DAMP, drawGroupDiscs, drawGroupLabels,
  leafStats, plannedStats, sectorAnchors,
} from "./layers.js";

/* Node colors come from the shared palette in charlotteStore.js so the
   canvases and the legend pills can never drift apart. */
const KIND_FILL = cs.KIND_COLORS;
const KINDS = Object.keys(KIND_FILL);
const BRASS = "#B0894E";
const TEAL_HALO = "#84C7C2";
const EDGE_SOLID = "#D3C9B4";
const EDGE_DASHED = "#9A9385";
const INK = "#16415C";
const LABEL_MUTED = "#7A7468";
const PAPER = "#FCFAF5";   // --paper-000: halo behind labels over edge fans

const ALPHA_MIN = 0.03;
const DASH_EDGE_MAX = 2500;   // above this, inferred edges lose the dash
const ARROW_EDGE_MAX = 1500;  // above this, arrows only on focus edges
const RECT_NODE_MIN = 2500;   // above this, dots are rects at low zoom
const LABEL_CAP = 350;
const HOOD_LABEL_MAX = 60;    // label a clicked hood only while readable
const HOOD_DETAIL_MAX = 1500; // hood bigger than this: ink threads only
const SCENE_PAD = 300;        // css px of world rendered beyond the viewport
const SCENE_DRIFT = 1.3;      // re-render when blit scale leaves [1/d, d]
const SCENE_IDLE_MS = 160;    // sharpen a scaled blit once the wheel rests
const LIVE_STRIDE_MIN = 4000; // stride edges while settling above this

const clip = (s, n = 26) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

/* Undirected BFS shortest path from `from` back to `to` (the center).
   Returns {nodes: [ids], pairs: Set} or null if unreachable. Computed
   once per selection in the hood effect, never per frame. */
function shortestPath(edges, from, to) {
  if (!from || !to || from === to) return null;
  const adj = new Map();
  for (const e of edges) {
    if (!adj.has(e.a)) adj.set(e.a, []);
    if (!adj.has(e.b)) adj.set(e.b, []);
    adj.get(e.a).push(e.b);
    adj.get(e.b).push(e.a);
  }
  const prev = new Map([[to, null]]);
  const q = [to];
  for (let i = 0; i < q.length && !prev.has(from); i++) {
    for (const nb of adj.get(q[i]) || []) {
      if (!prev.has(nb)) {
        prev.set(nb, q[i]);
        q.push(nb);
      }
    }
  }
  if (!prev.has(from)) return null;
  const nodes = [];
  const pairs = new Set();
  let cur = from;
  while (cur) {
    nodes.push(cur);
    const nxt = prev.get(cur);
    if (nxt) pairs.add(cur < nxt ? `${cur}|${nxt}` : `${nxt}|${cur}`);
    cur = nxt;
  }
  return { nodes, pairs };
}

export default function Web() {
  React.useSyncExternalStore(cs.subscribe, cs.getVersion);
  const hostRef = React.useRef(null);
  const canvasRef = React.useRef(null);
  const simNodes = React.useRef(new Map());   // id -> live sim node {x, y}
  const world = React.useRef(null);           // worker/interp machinery
  const byDegree = React.useRef([]);          // store nodes, degree desc
  const transform = React.useRef({ x: 0, y: 0, k: 1 });
  const drag = React.useRef(null);
  // While true the camera re-fits to the whole web every frame — so a new
  // center or a STEPS change lands framed, tracking the layout as it
  // settles. Any manual pan/zoom hands the camera back to the user.
  const autoFit = React.useRef(true);
  const scene = React.useRef(null);           // offscreen settled bitmap
  const blitDirty = React.useRef(true);
  const lastGesture = React.useRef(0);
  const lastVersion = React.useRef(-1);
  const prerenderRef = React.useRef(null);    // paints the scene off-rAF
                                              // (worker settles in a
                                              // hidden tab — see below)
  const hoodRef = React.useRef(null);         // cached click highlight
  const [dragging, setDragging] = React.useState(false);
  // Expand choreography: edges that arrived from an expand draw themselves
  // outward from the expanded node (edge key -> animation start time).
  const knownEdges = React.useRef(new Set());
  const growE = React.useRef(new Map());

  const s = cs.S;
  React.useEffect(() => { autoFit.current = true; }, [s.viewEpoch]);
  const nodeCount = Object.keys(s.nodes).length;
  const edgeCount = s.edges.length;
  // Grouping LAYERS work here too: sector groups from the active stack,
  // rendered as tinted discs + labels.
  const groupsRef = React.useRef([]);
  const layersKey = s.layers.fund
    .map((l) => `${l.key}${l.on ? "+" : "-"}`).join(",")
    + "|" + s.layers.contact
      .map((l) => `${l.key}${l.on ? "+" : "-"}`).join(",");

  // Anything baked into the settled bitmap invalidates it when it moves.
  const sceneKey = `${s.viz.nodeScale}|${s.viz.textScale}|${s.viz.fadeAmount}`
    + `|${s.viz.arrows}|${s.kinds.join(",")}|${s.hidden.join(",")}`
    + `|${layersKey}`;
  React.useEffect(() => {
    if (scene.current) scene.current.k = 0;
    blitDirty.current = true;
  }, [sceneKey]);

  React.useEffect(() => {
    const keys = cs.S.edges.map((e) => `${e.a}|${e.b}|${e.type}`);
    // Only an EXPAND animates its new edges (staggered, so the growth
    // ripples out); a re-center replaces the world wholesale and just
    // renders it — knownEdges resets silently.
    if (cs.S.expandAnchor && knownEdges.current.size) {
      const t0 = performance.now();
      let i = 0;
      for (const k of keys) {
        if (!knownEdges.current.has(k)) {
          growE.current.set(k, t0 + Math.min(i, 24) * 40);
          i++;
        }
      }
    } else {
      growE.current.clear();
    }
    knownEdges.current = new Set(keys);
  }, [edgeCount, s.viewEpoch]);

  // The click highlight, built ONCE per selection (a mega-hub's hood is
  // thousands of members — rebuilding it per frame was the local view's
  // biggest per-frame cost): the hood set, its edges, and the shortest
  // chain back to the center.
  React.useEffect(() => {
    const focus = s.selected;
    if (!focus || !cs.S.nodes[focus]) {
      hoodRef.current = null;
      blitDirty.current = true;
      return;
    }
    const set = new Set([focus]);
    const edges = [];
    for (const e of cs.S.edges) {
      if (e.a === focus || e.b === focus) {
        edges.push(e);
        set.add(e.a === focus ? e.b : e.a);
      }
    }
    let path = null;
    if (cs.S.center && focus !== cs.S.center) {
      // The chain home may only pass through nodes that are on screen —
      // a path through a filtered-out node would draw broken. The center
      // is exempt from filters, so its edges stay walkable.
      const isHid = cs.makeHidden(cs.S);
      const okEnd = (id) => id === cs.S.center
        || !(isHid && isHid(cs.S.nodes[id]));
      const pathEdges = !isHid ? cs.S.edges
        : cs.S.edges.filter((e) => okEnd(e.a) && okEnd(e.b));
      path = shortestPath(pathEdges, focus, cs.S.center);
      if (path) for (const id of path.nodes) set.add(id);
    }
    hoodRef.current = { focus, set, edges, path };
    blitDirty.current = true;
  }, [s.selected, edgeCount, s.hidden.join(","), cs.valueHiddenKey(s),
      s.viewEpoch]);

  // (Re)build the simulation when the graph's shape changes. Existing nodes
  // keep their current coordinates; new ones start from the store's seeded
  // spot (near the expanded node) or near the middle.
  React.useEffect(() => {
    const host = hostRef.current;
    if (!host || !nodeCount) return undefined;
    const prev = simNodes.current;
    const next = new Map();
    const sims = [];
    // FILTERS (kind toggles AND per-layer value hides) remove nodes
    // outright: they leave the simulation, so the layout reclaims the
    // space (everything downstream — drawing, picking, labels — skips
    // them automatically via the missing sim entry). The CENTER is
    // exempt — the searched node stays on screen no matter what.
    const hid = cs.makeHidden(cs.S);
    for (const n of Object.values(cs.S.nodes)) {
      if (hid && hid(n) && n.id !== cs.S.center) continue;
      const kept = prev.get(n.id);
      const seed = cs.S.positions[n.id];
      const sn = kept || {
        id: n.id,
        x: seed ? seed.x : (Math.random() - 0.5) * 400,
        y: seed ? seed.y : (Math.random() - 0.5) * 400,
      };
      delete sn.fx;
      delete sn.fy;
      next.set(n.id, sn);
      sims.push(sn);
    }
    simNodes.current = next;
    const centerSim = cs.S.center && next.get(cs.S.center);
    if (centerSim) {
      centerSim.fx = 0;
      centerSim.fy = 0;
    }
    // The just-expanded node holds its ground while its new neighbors
    // settle around it — otherwise the re-heat sweeps it away and the
    // user loses the node they were following.
    const anchorSim = cs.S.expandAnchor && next.get(cs.S.expandAnchor);
    if (anchorSim && anchorSim !== centerSim) {
      anchorSim.fx = anchorSim.x;
      anchorSim.fy = anchorSim.y;
    }
    byDegree.current = sims.map((sn) => cs.S.nodes[sn.id]).filter(Boolean)
      .sort((a, b) => (b.degree || 0) - (a.degree || 0));
    const edgesArr = cs.S.edges.filter((e) => next.has(e.a) && next.has(e.b));
    const vz = cs.S.viz;
    // Active LAYERS pull funds/contacts toward sector anchors around the
    // pinned center — same recipe as the global view, scaled down.
    const fundKeys = cs.S.layers.fund.filter((l) => l.on).map((l) => l.key);
    const contactOn = cs.S.layers.contact.some((l) => l.on);
    const pull = ANCHOR_STRENGTH * (vz.groupPull ?? 1);
    const damp = Math.min(1, ANCHORED_LINK_DAMP * (vz.groupTies ?? 1));
    let anchorById = null;
    groupsRef.current = [];
    if ((fundKeys.length || contactOn) && pull > 0) {
      const storeNodes = sims.map((sn) => cs.S.nodes[sn.id]).filter(Boolean);
      const R = Math.max(320, Math.sqrt(storeNodes.length) * 40);
      const res = sectorAnchors(storeNodes, fundKeys, contactOn, R);
      anchorById = new Map();
      for (const [n, a] of res.anchors) anchorById.set(n.id, a);
      groupsRef.current = res.groups;
    }

    const w = { order: sims, prev: null, next: null, lastMsg: 0, gap: 250,
                settled: false, justSettled: false, worker: null,
                inlineSim: null };
    world.current = w;
    if (scene.current) scene.current.k = 0;
    blitDirty.current = true;

    // Main-thread twin of the worker's ego tuning — reduced-motion and
    // no-Worker environments. Parameters MUST mirror the postMessage.
    const startInline = () => {
      const sim = forceSimulation(sims)
        .force("link", forceLink(edgesArr.map((e) =>
            ({ source: e.a, target: e.b, type: e.type })))
          .id((d) => d.id)
          .distance((l) => (l.type === "employed_by" || l.type === "managed_by"
            ? 100 : 170) * vz.linkDist)
          .strength((l) => Math.min(1, 0.3 * vz.linkForce)
            * (anchorById && (anchorById.has(l.source.id)
                              || anchorById.has(l.target.id)) ? damp : 1)))
        .force("charge", forceManyBody().strength(-360 * vz.repel))
        .force("collide", forceCollide()
          .radius((d) => nodeRadius(cs.S.nodes[d.id]) * vz.nodeScale + 12))
        .force("x", forceX(0).strength(0.02 * vz.center))
        .force("y", forceY(0).strength(0.02 * vz.center))
        .alphaDecay(0.03).alphaMin(ALPHA_MIN)
        .stop();
      if (anchorById) {
        sim.force("ax", forceX((d) => anchorById.get(d.id)?.x ?? 0)
            .strength((d) => (anchorById.has(d.id) ? pull : 0)))
           .force("ay", forceY((d) => anchorById.get(d.id)?.y ?? 0)
            .strength((d) => (anchorById.has(d.id) ? pull : 0)));
      }
      return sim;
    };

    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      // Settle synchronously and present the final arrangement — no
      // swirling. Tick count shrinks for big webs so the block stays sane.
      const sim = startInline();
      const ticks = sims.length > 1500 ? 80 : 300;
      for (let i = 0; i < ticks; i++) sim.tick();
      sim.stop();
      w.settled = true;
      w.justSettled = true;
    } else {
      try {
        const worker = new Worker(
          new URL("./globalSim.worker.js", import.meta.url),
          { type: "module" });
        const count = sims.length;
        const posArr = new Float32Array(2 * count);
        const deg = new Int32Array(count);
        const collideR = new Float32Array(count);
        const fixed = new Float32Array(2 * count).fill(NaN);
        const idx = new Map();
        sims.forEach((sn, i) => {
          idx.set(sn.id, i);
          posArr[2 * i] = sn.x;
          posArr[2 * i + 1] = sn.y;
          const n = cs.S.nodes[sn.id];
          deg[i] = n?.degree || 0;
          collideR[i] = nodeRadius(n) * vz.nodeScale + 12;
          if (sn.fx !== undefined) {
            fixed[2 * i] = sn.fx;
            fixed[2 * i + 1] = sn.fy;
          }
        });
        const eArr = new Int32Array(2 * edgesArr.length);
        const linkDists = new Float32Array(edgesArr.length);
        edgesArr.forEach((e, i) => {
          eArr[2 * i] = idx.get(e.a);
          eArr[2 * i + 1] = idx.get(e.b);
          linkDists[i] = (e.type === "employed_by"
            || e.type === "managed_by") ? 100 : 170;
        });
        let anchorArrays = null;
        const transfers = [posArr.buffer, deg.buffer, eArr.buffer,
                           linkDists.buffer, collideR.buffer, fixed.buffer];
        if (anchorById) {
          const ax = new Float32Array(count);
          const ay = new Float32Array(count);
          const st = new Float32Array(count);
          sims.forEach((sn, i) => {
            const a = anchorById.get(sn.id);
            if (a) {
              ax[i] = a.x;
              ay[i] = a.y;
              st[i] = pull;
            }
          });
          anchorArrays = { ax, ay, st };
          transfers.push(ax.buffer, ay.buffer, st.buffer);
        }
        worker.onmessage = (ev) => {
          // Buffer frames for interpolation — the draw loop tweens
          // between prev and next so slow ticks still animate smoothly.
          w.prev = w.next || ev.data.positions;
          w.next = ev.data.positions;
          const now = performance.now();
          if (w.lastMsg) {
            w.gap = Math.min(1000, w.gap * 0.7 + (now - w.lastMsg) * 0.3);
          }
          w.lastMsg = now;
          if (ev.data.done) {
            const p = ev.data.positions;
            sims.forEach((sn, i) => {
              sn.x = p[2 * i];
              sn.y = p[2 * i + 1];
            });
            w.settled = true;
            worker.terminate();
            // Message handlers fire even in a hidden tab (rAF does not),
            // so the full scene — labels included — pre-renders while
            // the user is away and greets them finished when they return.
            if (prerenderRef.current) {
              w.justSettled = false;
              prerenderRef.current();
            } else {
              w.justSettled = true;
            }
          }
        };
        worker.postMessage(
          { positions: posArr, count, degrees: deg, edges: eArr,
            alphaMin: ALPHA_MIN,
            forces: { center: vz.center, repel: vz.repel,
                      linkForce: vz.linkForce, linkDist: vz.linkDist,
                      groupDamp: damp },
            anchors: anchorArrays,
            ego: { linkDists, collideR, charge: -360, fixed } },
          transfers);
        w.worker = worker;
      } catch {
        // No Worker (odd embedder): budget-tick on the main thread inside
        // the draw loop instead.
        w.inlineSim = startInline();
      }
    }
    return () => {
      if (w.worker) w.worker.terminate();
      if (w.inlineSim) w.inlineSim.stop();
      // Remember settled spots so the next merge grows the world in place.
      for (const [id, sn] of next) cs.S.positions[id] = { x: sn.x, y: sn.y };
    };
  }, [nodeCount, edgeCount, s.center, s.hidden.join(","),
      cs.valueHiddenKey(s), s.viz.center, s.viz.repel, s.viz.linkForce,
      s.viz.linkDist, s.viz.nodeScale, s.viz.groupPull, s.viz.groupTies,
      layersKey]);

  // Draw loop.
  React.useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return undefined;
    const ctx = canvas.getContext("2d");
    if (!scene.current) {
      const off = document.createElement("canvas");
      scene.current = { canvas: off, ctx: off.getContext("2d"), k: 0 };
    }
    scene.current.k = 0;
    blitDirty.current = true;
    let raf = 0;

    const pos = (id) => simNodes.current.get(id);

    /* Full-detail scene render into the offscreen bitmap — settled
       regime only, selection-independent (highlights are overlays). */
    const renderScene = (sc, t, rect, dpr) => {
      const cssW = rect.width + SCENE_PAD * 2;
      const cssH = rect.height + SCENE_PAD * 2;
      const bw = Math.round(cssW * dpr);
      const bh = Math.round(cssH * dpr);
      if (sc.canvas.width !== bw || sc.canvas.height !== bh) {
        sc.canvas.width = bw;
        sc.canvas.height = bh;
      }
      const c = sc.ctx;
      const v = cs.S.viz;
      const fadeA = Math.max(0.05, 1 - v.fadeAmount);
      const flt = cs.S.kinds.length ? new Set(cs.S.kinds) : null;
      const ox = t.x + SCENE_PAD;
      const oy = t.y + SCENE_PAD;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, cssW, cssH);
      c.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * ox, dpr * oy);
      const pad = 30 / t.k;
      const tl = toWorld(-SCENE_PAD, -SCENE_PAD, t);
      const br = toWorld(rect.width + SCENE_PAD, rect.height + SCENE_PAD, t);
      const vx0 = tl.x - pad, vy0 = tl.y - pad;
      const vx1 = br.x + pad, vy1 = br.y + pad;
      const inView = (p) => p.x >= vx0 && p.x <= vx1
        && p.y >= vy0 && p.y <= vy1;

      let gstats = null;
      if (groupsRef.current.length) {
        gstats = leafStats(groupsRef.current, null, (n) => pos(n.id));
        drawGroupDiscs(c, gstats, t.k);
      }

      // Edges: three batched paths. Dashes and arrowheads only while the
      // web is small enough to afford them. On big webs the thread layer
      // steps way back (the galaxy's trick) — thousands of full-strength
      // lines read as noise, and the click highlight inks the story.
      const calm = cs.S.edges.length > 3000 ? 0.3
        : cs.S.edges.length > 800 ? 0.6 : 1;
      const edgeMul = (flt ? 0.5 : 1) * calm;
      const dashOK = cs.S.edges.length <= DASH_EDGE_MAX;
      const arrowsOK = v.arrows && cs.S.edges.length <= ARROW_EDGE_MAX;
      const bSolid = [], bLp = [], bInf = [];
      for (const e of cs.S.edges) {
        const a = pos(e.a);
        const b = pos(e.b);
        if (!a || !b) continue;
        if (!inView(a) && !inView(b)) continue;
        (e.inferred ? bInf : e.type === "known_lp" ? bLp : bSolid)
          .push([a, b]);
      }
      const strokeBatch = (list, style, width, alpha, dash) => {
        if (!list.length) return;
        c.beginPath();
        for (const [a, b] of list) {
          c.moveTo(a.x, a.y);
          c.lineTo(b.x, b.y);
        }
        c.setLineDash(dash);
        c.strokeStyle = style;
        c.lineWidth = width;
        c.globalAlpha = alpha;
        c.stroke();
      };
      strokeBatch(bSolid, EDGE_SOLID, 1.1 / t.k, edgeMul, []);
      // The explicit LP relation is the answer — it reads as such.
      strokeBatch(bLp, BRASS, 2.2 / t.k, edgeMul, []);
      strokeBatch(bInf, EDGE_DASHED, 1 / t.k, (dashOK ? 1 : 0.55) * edgeMul,
                  dashOK ? [4 / t.k, 3 / t.k] : []);
      c.setLineDash([]);
      c.globalAlpha = 1;
      if (arrowsOK) {
        // Direction reads a → b (employee → employer, note → fund, …).
        c.beginPath();
        for (const list of [bSolid, bLp, bInf]) {
          for (const [a, b] of list) {
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const len = Math.hypot(dx, dy) || 1;
            const ux = dx / len;
            const uy = dy / len;
            const tx = b.x - ux * (8 / t.k);
            const ty = b.y - uy * (8 / t.k);
            const wl = 5 / t.k;
            c.moveTo(tx - ux * wl - uy * wl * 0.55,
                     ty - uy * wl + ux * wl * 0.55);
            c.lineTo(tx, ty);
            c.lineTo(tx - ux * wl + uy * wl * 0.55,
                     ty - uy * wl - ux * wl * 0.55);
          }
        }
        c.strokeStyle = EDGE_SOLID;
        c.lineWidth = 1 / t.k;
        c.globalAlpha = 0.9 * edgeMul;
        c.stroke();
        c.globalAlpha = 1;
      }

      // Nodes: one batched path per kind; rects at dot scale on very
      // large webs (the eye can't tell, the frame budget can).
      const asArcs = nodeCount <= RECT_NODE_MIN || t.k >= 0.8;
      const fewDetails = nodeCount <= 400;
      let visNodes = 0;
      for (const kind of KINDS) {
        c.fillStyle = KIND_FILL[kind];
        c.globalAlpha = flt && !flt.has(kind) ? fadeA : 1;
        c.beginPath();
        for (const n of byDegree.current) {
          if ((KIND_FILL[n.kind] ? n.kind : "external") !== kind) continue;
          const p = pos(n.id);
          if (!p || !inView(p)) continue;
          visNodes++;
          const r = nodeRadius(n) * v.nodeScale;
          if (asArcs) {
            c.moveTo(p.x + r, p.y);
            c.arc(p.x, p.y, r, 0, Math.PI * 2);
          } else {
            c.rect(p.x - r, p.y - r, r * 2, r * 2);
          }
        }
        c.fill();
      }
      c.globalAlpha = 1;
      // LP-candidate rings, one batched path.
      c.beginPath();
      for (const n of byDegree.current) {
        if (!n.lp_candidate) continue;
        const p = pos(n.id);
        if (!p || !inView(p)) continue;
        const r = nodeRadius(n) * v.nodeScale + 2.5 / t.k;
        c.moveTo(p.x + r, p.y);
        c.arc(p.x, p.y, r, 0, Math.PI * 2);
      }
      c.strokeStyle = BRASS;
      c.lineWidth = 2 / t.k;
      c.stroke();
      // "+N more" markers on small webs (the selected node's marker is
      // drawn live in the overlay so the scene stays selection-free).
      if (fewDetails) {
        c.font = `${(9 * v.textScale) / t.k}px "IBM Plex Mono", monospace`;
        c.fillStyle = LABEL_MUTED;
        const dim = (n) => flt && !flt.has(n.kind);
        for (const n of byDegree.current) {
          if (!(n.hidden_neighbors > 0) || dim(n)) continue;
          const p = pos(n.id);
          if (!p || !inView(p)) continue;
          c.fillText(`+${n.hidden_neighbors}`,
                     p.x + nodeRadius(n) * v.nodeScale + 4 / t.k,
                     p.y + 14 / t.k);
        }
      }

      // Labels: greedy, collision-culled, in scene space, walking the
      // degree-presorted list. Group labels claim their spots first.
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      const fs = 11 * v.textScale;
      c.font = `${fs}px "Hanken Grotesk", sans-serif`;
      c.lineJoin = "round";
      c.lineWidth = 3;
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
      if (gstats && gstats.length) {
        // Parents before children — a middle layer (e.g. geography) must
        // be readable by NAME, not only via blob positions; label size
        // grows with distance above the leaves.
        const base = 9.5 * v.textScale;
        const maxLv = gstats.reduce((m, g) => Math.max(m, g.level), 0);
        const ordered = [...gstats].sort((g1, g2) =>
          g1.level - g2.level || g2.count - g1.count);
        c.strokeStyle = PAPER;
        for (const g of ordered) {
          const text = String(g.label || "").toUpperCase();
          if (!text) continue;
          const gfs = base * Math.min(1.4, 1 + 0.18 * (maxLv - g.level));
          c.font = `600 ${gfs}px "IBM Plex Mono", monospace`;
          c.fillStyle = g.leaf ? g.color : LABEL_MUTED;
          const gx = g.x * t.k + ox;
          const gy = g.leaf ? (g.y - g.r) * t.k + oy - 5 : g.y * t.k + oy;
          const gw = text.length * gfs * 0.62;
          if (!claim(gx - gw / 2, gy - gfs, gw, gfs * 1.4)) continue;
          c.strokeText(text, gx - gw / 2, gy);
          c.fillText(text, gx - gw / 2, gy);
        }
        c.font = `${fs}px "Hanken Grotesk", sans-serif`;
      }
      c.fillStyle = INK;
      c.strokeStyle = PAPER;
      const few = nodeCount <= 60;
      // The ladder only ORDERS the flood — the occupancy grid limits
      // density — and it applies at all only when the view is CROWDED:
      // when filters or zoom leave few nodes on screen, whitespace is
      // the resource and everything the grid will take gets a name.
      const minDeg = visNodes <= 2000 ? 0
        : t.k > 0.55 ? 0 : t.k > 0.3 ? 5 : t.k > 0.15 ? 25 : 60;
      const dim = (n) => flt && !flt.has(n.kind);
      const place = (n, force) => {
        if (!n || !n.label) return false;
        const p = pos(n.id);
        if (!p || !inView(p)) return false;
        const sx = p.x * t.k + ox + nodeRadius(n) * v.nodeScale * t.k + 4;
        const sy = p.y * t.k + oy + 3.5;
        const text = clip(n.label);
        const cw = text.length * fs * 0.56;
        if (!claim(sx, sy - fs, cw, fs * 1.3) && !force) return false;
        c.strokeText(text, sx, sy);
        c.fillText(text, sx, sy);
        return true;
      };
      place(cs.S.nodes[cs.S.center], true);
      let placed = 0;
      for (const n of byDegree.current) {
        if (placed >= LABEL_CAP) break;
        if (n.id === cs.S.center || dim(n)) continue;
        const qual = flt ? flt.has(n.kind)
          : (few || (n.degree || 0) >= minDeg);
        if (!qual) {
          // byDegree is sorted desc — once the ladder rejects, everything
          // after it is smaller (unless a filter widens candidacy).
          if (!flt && !few) break;
          continue;
        }
        if (place(n, false)) placed++;
      }
      sc.k = t.k;
      sc.x = ox;
      sc.y = oy;
      sc.cssW = cssW;
      sc.cssH = cssH;
    };

    /* Light direct draw for the settling regime: strided batched edges,
       dot rects, discs, no labels. */
    const renderLive = (t, rect, dpr) => {
      const v = cs.S.viz;
      const flt = cs.S.kinds.length ? new Set(cs.S.kinds) : null;
      const fadeA = Math.max(0.05, 1 - v.fadeAmount);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y);
      const tl = toWorld(0, 0, t);
      const br = toWorld(rect.width, rect.height, t);
      const pad = 30 / t.k;
      const vx0 = tl.x - pad, vy0 = tl.y - pad;
      const vx1 = br.x + pad, vy1 = br.y + pad;
      const inView = (p) => p.x >= vx0 && p.x <= vx1
        && p.y >= vy0 && p.y <= vy1;
      // While SETTLING, the PLANNED skeleton (discs + labels at target
      // positions) shows instantly and the points migrate into it; on
      // settled light frames, track the real blobs.
      const skeleton = groupsRef.current.length
        ? (world.current?.settled
            ? leafStats(groupsRef.current, null, (n) => pos(n.id))
            : plannedStats(groupsRef.current))
        : null;
      if (skeleton) drawGroupDiscs(ctx, skeleton, t.k);
      const stride = cs.S.edges.length > LIVE_STRIDE_MIN ? 3 : 1;
      ctx.beginPath();
      for (let i = 0; i < cs.S.edges.length; i += stride) {
        const e = cs.S.edges[i];
        const a = pos(e.a);
        const b = pos(e.b);
        if (!a || !b) continue;
        if (!inView(a) && !inView(b)) continue;
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
      }
      ctx.strokeStyle = EDGE_SOLID;
      ctx.lineWidth = 1 / t.k;
      ctx.globalAlpha = (cs.S.edges.length > 3000 ? 0.35 : 0.6)
        * (flt ? 0.5 : 1);
      ctx.stroke();
      ctx.globalAlpha = 1;
      const asArcs = nodeCount <= 1200;
      for (const kind of KINDS) {
        ctx.fillStyle = KIND_FILL[kind];
        ctx.globalAlpha = flt && !flt.has(kind) ? fadeA : 1;
        ctx.beginPath();
        for (const n of byDegree.current) {
          if ((KIND_FILL[n.kind] ? n.kind : "external") !== kind) continue;
          const p = pos(n.id);
          if (!p || !inView(p)) continue;
          const r = nodeRadius(n) * v.nodeScale;
          if (asArcs) {
            ctx.moveTo(p.x + r, p.y);
            ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
          } else {
            ctx.rect(p.x - r, p.y - r, r * 2, r * 2);
          }
        }
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      // Group names land with the skeleton, not after the settle.
      if (skeleton) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        drawGroupLabels(ctx, skeleton, t.k, t.x, t.y, v.textScale,
                        LABEL_MUTED, PAPER);
      }
    };

    /* Selection highlight, rings, feelers and grow-in edges — drawn live
       over either regime. Purely additive; nothing else fades. */
    const overlays = (t, rect, dpr, nowMs) => {
      const v = cs.S.viz;
      ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y);
      const hd = hoodRef.current;
      // A mega-hub's hood runs to thousands — cull to the viewport, and
      // above HOOD_DETAIL_MAX draw only the inked threads (rings on 6k
      // dots are mush anyway; the threads are the story).
      const tl = toWorld(0, 0, t);
      const br = toWorld(rect.width, rect.height, t);
      const vpad = 20 / t.k;
      const inV = (p) => p.x >= tl.x - vpad && p.x <= br.x + vpad
        && p.y >= tl.y - vpad && p.y <= br.y + vpad;
      if (hd && cs.S.nodes[hd.focus]) {
        const detail = hd.set.size <= HOOD_DETAIL_MAX;
        // Immediate connections of the clicked node ink over the web.
        ctx.beginPath();
        for (const e of hd.edges) {
          const a = pos(e.a);
          const b = pos(e.b);
          if (!a || !b) continue;
          if (!inV(a) && !inV(b)) continue;
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
        }
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.6 / t.k;
        ctx.globalAlpha = 0.9;
        ctx.stroke();
        ctx.globalAlpha = 1;
        // The chain home draws in heavier ink over everything else.
        if (hd.path) {
          ctx.beginPath();
          for (let i = 0; i + 1 < hd.path.nodes.length; i++) {
            const a = pos(hd.path.nodes[i]);
            const b = pos(hd.path.nodes[i + 1]);
            if (!a || !b) continue;
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
          }
          ctx.strokeStyle = INK;
          ctx.lineWidth = 2 / t.k;
          ctx.stroke();
        }
        // Hood rings, one batched path, viewport-culled — skipped
        // entirely on huge hoods.
        if (detail) {
          ctx.beginPath();
          for (const id of hd.set) {
            if (id === hd.focus) continue;
            const p = pos(id);
            if (!p || !inV(p)) continue;
            const r = nodeRadius(cs.S.nodes[id]) * v.nodeScale + 3 / t.k;
            ctx.moveTo(p.x + r, p.y);
            ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
          }
          ctx.strokeStyle = TEAL_HALO;
          ctx.lineWidth = 2 / t.k;
          ctx.stroke();
        }
      }
      const ring = (id, extra, style, width) => {
        const p = id && pos(id);
        if (!p) return;
        const r = nodeRadius(cs.S.nodes[id]) * v.nodeScale + extra / t.k;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.strokeStyle = style;
        ctx.lineWidth = width / t.k;
        ctx.stroke();
      };
      ring(cs.S.center, 6, TEAL_HALO, 3);
      if (cs.S.expandAnchor !== cs.S.center) {
        // A lighter halo marks the node the user just expanded.
        ring(cs.S.expandAnchor, 3.5, TEAL_HALO, 1.6);
      }
      ring(cs.S.selected, 4.5, INK, 1.5);
      // Grow-in edges from an expand, animated individually (few).
      if (growE.current.size) {
        for (const e of cs.S.edges) {
          const gk = `${e.a}|${e.b}|${e.type}`;
          const g0 = growE.current.get(gk);
          if (g0 === undefined) continue;
          const a = pos(e.a);
          const b = pos(e.b);
          if (!a || !b) continue;
          const pr = (nowMs - g0) / 450;
          if (pr >= 1) {
            growE.current.delete(gk);
            continue;
          }
          if (pr <= 0) continue;
          const ease = 1 - (1 - pr) ** 3;
          let x0 = a.x, y0 = a.y, x1, y1;
          if (e.b === cs.S.expandAnchor) {
            x0 = b.x;
            y0 = b.y;
            x1 = b.x + (a.x - b.x) * ease;
            y1 = b.y + (a.y - b.y) * ease;
          } else {
            x1 = a.x + (b.x - a.x) * ease;
            y1 = a.y + (b.y - a.y) * ease;
          }
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          ctx.strokeStyle = e.inferred ? EDGE_DASHED : EDGE_SOLID;
          ctx.lineWidth = 1.1 / t.k;
          ctx.stroke();
        }
      }
      // Expand feelers: while the expand fetch is in flight, short lines
      // pulse outward from the double-clicked node in rotating directions
      // — the wait reads as the web actively growing, not a stall.
      const expP = cs.S.expanding && pos(cs.S.expanding);
      if (expP) {
        const rr = nodeRadius(cs.S.nodes[cs.S.expanding]) * v.nodeScale;
        ctx.strokeStyle = TEAL_HALO;
        ctx.lineWidth = 1.6 / t.k;
        for (let i = 0; i < 6; i++) {
          const cyc = Math.floor((nowMs + i * 150) / 900);
          const ph = ((nowMs + i * 150) % 900) / 900;
          const ang = i * 1.0471975 + (cyc % 7) * 0.897;
          const ease = 1 - (1 - ph) ** 3;
          const len = (26 + 64 * ease) / t.k;
          ctx.globalAlpha = 0.75 * (1 - ph);
          ctx.beginPath();
          ctx.moveTo(expP.x + Math.cos(ang) * (rr + 2 / t.k),
                     expP.y + Math.sin(ang) * (rr + 2 / t.k));
          ctx.lineTo(expP.x + Math.cos(ang) * (rr + len),
                     expP.y + Math.sin(ang) * (rr + len));
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      // Labels for the story: the selection in bold, its hood while it
      // stays a readable size, its "+N more" marker.
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const fs = 11 * v.textScale;
      ctx.lineJoin = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = PAPER;
      const label = (id, bold) => {
        const n = cs.S.nodes[id];
        const p = n && pos(id);
        if (!p || !n.label) return;
        ctx.font = `${bold ? "600 " : ""}${fs}px "Hanken Grotesk", sans-serif`;
        ctx.fillStyle = INK;
        const sx = p.x * t.k + t.x + nodeRadius(n) * v.nodeScale * t.k + 4;
        const sy = p.y * t.k + t.y + 3.5;
        if (sx < -240 || sy < -20
            || sx > rect.width || sy > rect.height + 20) return;
        const text = clip(n.label);
        ctx.strokeText(text, sx, sy);
        ctx.fillText(text, sx, sy);
      };
      if (hd && hd.set.size <= HOOD_LABEL_MAX) {
        for (const id of hd.set) {
          if (id !== hd.focus) label(id, false);
        }
      }
      if (cs.S.selected) {
        label(cs.S.selected, true);
        const n = cs.S.nodes[cs.S.selected];
        const p = n && pos(cs.S.selected);
        if (p && n.hidden_neighbors > 0) {
          ctx.font = `${9 * v.textScale}px "IBM Plex Mono", monospace`;
          ctx.fillStyle = LABEL_MUTED;
          ctx.fillText(`+${n.hidden_neighbors} more`,
                       p.x * t.k + t.x + nodeRadius(n) * v.nodeScale * t.k + 4,
                       p.y * t.k + t.y + 16);
        }
      }
    };

    // Paint the settled scene outside the rAF loop — called by the worker
    // done-handler so a hidden tab comes back with labels already there.
    prerenderRef.current = () => {
      const rect = host.getBoundingClientRect();
      if (!rect.width || !world.current?.settled) return;
      if (autoFit.current && simNodes.current.size) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        simNodes.current.forEach((p) => {
          if (p.x < x0) x0 = p.x;
          if (p.x > x1) x1 = p.x;
          if (p.y < y0) y0 = p.y;
          if (p.y > y1) y1 = p.y;
        });
        const pad = 48;
        const k = Math.max(0.03, Math.min(1.15,
          (rect.width - 2 * pad) / ((x1 - x0) || 1),
          (rect.height - 2 * pad) / ((y1 - y0) || 1)));
        transform.current = { k,
          x: rect.width / 2 - k * (x0 + x1) / 2,
          y: rect.height / 2 - k * (y0 + y1) / 2 };
      }
      renderScene(scene.current, transform.current, rect,
                  window.devicePixelRatio || 1);
      blitDirty.current = true;
    };
    const onVisible = () => { blitDirty.current = true; };
    document.addEventListener("visibilitychange", onVisible);

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
      const nowMs = performance.now();
      // Any store change (selection, filters, sliders, data) redraws.
      if (cs.S.version !== lastVersion.current) {
        lastVersion.current = cs.S.version;
        blitDirty.current = true;
      }
      const w = world.current;
      if (w && !w.settled) {
        if (w.inlineSim) {
          const t0 = performance.now();
          while (w.inlineSim.alpha() > ALPHA_MIN
                 && performance.now() - t0 < 12) {
            w.inlineSim.tick();
          }
          if (w.inlineSim.alpha() <= ALPHA_MIN) {
            w.settled = true;
            w.justSettled = true;
          }
        } else if (w.next && w.prev) {
          const f = w.prev === w.next ? 1
            : Math.min(1, (nowMs - w.lastMsg) / (w.gap || 250));
          for (let i = 0; i < w.order.length; i++) {
            const sn = w.order[i];
            const j = 2 * i;
            sn.x = w.prev[j] + (w.next[j] - w.prev[j]) * f;
            sn.y = w.prev[j + 1] + (w.next[j + 1] - w.prev[j + 1]) * f;
          }
        }
      }
      if (autoFit.current && simNodes.current.size) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        simNodes.current.forEach((p) => {
          if (p.x < x0) x0 = p.x;
          if (p.x > x1) x1 = p.x;
          if (p.y < y0) y0 = p.y;
          if (p.y > y1) y1 = p.y;
        });
        const pad = 48;
        const k = Math.max(0.03, Math.min(1.15,
          (rect.width - 2 * pad) / ((x1 - x0) || 1),
          (rect.height - 2 * pad) / ((y1 - y0) || 1)));
        const nt = { k,
          x: rect.width / 2 - k * (x0 + x1) / 2,
          y: rect.height / 2 - k * (y0 + y1) / 2 };
        const ot = transform.current;
        if (Math.abs(nt.k - ot.k) > 1e-4 || Math.abs(nt.x - ot.x) > 0.5
            || Math.abs(nt.y - ot.y) > 0.5) {
          transform.current = nt;
          blitDirty.current = true;
        }
      }
      const t = transform.current;

      const settling = w && !w.settled;
      if (settling) {
        renderLive(t, rect, dpr);
        overlays(t, rect, dpr, nowMs);
        blitDirty.current = true;   // keep animating next frame
        return;
      }
      if (w && w.justSettled) {
        w.justSettled = false;
        scene.current.k = 0;
        blitDirty.current = true;
      }
      // Animations over the settled scene keep frames flowing.
      if (growE.current.size || cs.S.expanding) blitDirty.current = true;

      const sc = scene.current;
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
        && nowMs - lastGesture.current > SCENE_IDLE_MS;
      // MID-GESTURE a full scene render (labels and all) is a visible
      // hitch on a big web — draw the light version live instead and
      // repaint full detail once the wheel rests. A scaled blit covers
      // small drift for free.
      const gesturing = nowMs - lastGesture.current < SCENE_IDLE_MS;
      if ((uncovered || drifted) && gesturing && sc.k) {
        renderLive(t, rect, dpr);
        overlays(t, rect, dpr, nowMs);
        blitDirty.current = true;
        return;
      }
      if (uncovered || drifted || idleStale) {
        renderScene(sc, t, rect, dpr);
        blitDirty.current = true;
      }
      if (!blitDirty.current) return;   // nothing new — free frame
      blitDirty.current = false;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      const r2 = t.k / sc.k;
      ctx.drawImage(sc.canvas, t.x - r2 * sc.x, t.y - r2 * sc.y,
                    sc.cssW * r2, sc.cssH * r2);
      overlays(t, rect, dpr, nowMs);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVisible);
      prerenderRef.current = null;
    };
  }, []);

  // Wheel zoom must preventDefault, so it is registered non-passively and
  // only on the canvas — page scroll everywhere else is untouched.
  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (ev) => {
      ev.preventDefault();
      autoFit.current = false;
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

  const positionsObj = () => {
    const out = {};
    simNodes.current.forEach((v, k) => { out[k] = v; });
    return out;
  };
  const worldOf = (ev) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return toWorld(ev.clientX - rect.left, ev.clientY - rect.top,
                   transform.current);
  };

  const onDown = (ev) => {
    drag.current = { sx: ev.clientX, sy: ev.clientY,
                     x0: transform.current.x, y0: transform.current.y,
                     moved: false };
    setDragging(true);
  };
  const onMove = (ev) => {
    if (drag.current) {
      const dx = ev.clientX - drag.current.sx;
      const dy = ev.clientY - drag.current.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) {
        drag.current.moved = true;
        autoFit.current = false;
      }
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
    const w = worldOf(ev);
    const pos = positionsObj();
    const node = pickNode(Object.values(cs.S.nodes), pos, w.x, w.y,
                          transform.current.k, 3, cs.S.viz.nodeScale);
    if (node) { cs.select(node.id); return; }
    const edge = pickEdge(cs.S.edges, pos, w.x, w.y, transform.current.k);
    if (edge) { cs.selectEdge(edge); return; }
    cs.select(null);
    cs.selectEdge(null);
  };
  const onDouble = (ev) => {
    const w = worldOf(ev);
    const node = pickNode(Object.values(cs.S.nodes), positionsObj(),
                          w.x, w.y, transform.current.k, 3,
                          cs.S.viz.nodeScale);
    if (node) cs.expand(node.id);
  };

  return (
    <div ref={hostRef} className="cw-canvas">
      <canvas ref={canvasRef} className={dragging ? "dragging" : ""}
        style={{ width: "100%", height: "100%" }}
        onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp}
        onMouseLeave={() => { drag.current = null; setDragging(false); }}
        onDoubleClick={onDouble} />
    </div>
  );
}
