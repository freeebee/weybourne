/* Off-main-thread force layout for the global view. The main thread sends
   seed positions and index-pair edges once; this worker runs the full
   simulation at its own pace and streams positions back after every tick
   (transferable Float32Array — no copies on the wire). The page thread
   never ticks physics, so panning and zooming stay at frame rate while
   the galaxy assembles. Force parameters MUST mirror ensureWorld's inline
   fallback in GlobalWeb.jsx. */
import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY,
} from "d3-force";

/* The recipe for the "constellation" look — honeycomb-tight clusters with
   clear space between them and a satellite ring at the rim:
   - short links with d3's DEFAULT strength (1/min degree), so a hub's
     hundred spokes each pull gently instead of collapsing into it, and
     single edges bridging two clusters stretch instead of merging them;
   - a collision force packs each cluster into evenly spaced shells — this
     is what turns overlapping mats into the dotted texture;
   - strong, far-reaching repulsion pushes whole clusters apart;
   - faint centering holds the disconnected satellites in orbit.
   Heavier per tick than the old blob (collide + charge are both quadtree
   passes), but this runs off-thread — the page never feels it. */
/* Two tunings share this worker. Global (no `ego` field): the
   constellation recipe below. Ego (`ego` present): the local view's
   feel — per-link rest lengths by relation type, per-node collide radii
   from label size, stronger charge, and pinned nodes (the center, an
   expand anchor) that the layout arranges around. */
self.onmessage = (ev) => {
  const { positions, count, degrees, edges, alphaMin, forces,
          anchors, ego } = ev.data;
  const f = forces
    || { center: 1, repel: 1, linkForce: 1, linkDist: 1, groupDamp: 0.3 };
  const damp = f.groupDamp ?? 0.3;
  const nodes = new Array(count);
  for (let i = 0; i < count; i++) {
    nodes[i] = { x: positions[2 * i], y: positions[2 * i + 1] };
  }
  if (ego && ego.fixed) {
    for (let i = 0; i < count; i++) {
      if (!Number.isNaN(ego.fixed[2 * i])) {
        nodes[i].fx = ego.fixed[2 * i];
        nodes[i].fy = ego.fixed[2 * i + 1];
      }
    }
  }
  const links = [];
  for (let i = 0; i < edges.length; i += 2) {
    links.push({ source: edges[i], target: edges[i + 1] });
  }
  const anchored = (l) => anchors
    && (anchors.st[l.source.index] > 0 || anchors.st[l.target.index] > 0);
  const sim = forceSimulation(nodes)
    .force("link", forceLink(links)
      .distance(ego ? (l, i) => ego.linkDists[i] * f.linkDist
                    : 40 * f.linkDist)
      // Global: degree-weighted pull (d3's default shape) scaled by the
      // slider — a mega-hub's spokes each tug gently, a 1:1 edge tugs
      // hard. Ego: the local view's flat strength. Either way, links
      // touching a sector-anchored node are damped so the anchor wins
      // and groups hold their shape (GROUP TIES slider × baseline).
      .strength(ego
        ? (l) => Math.min(1, 0.3 * f.linkForce) * (anchored(l) ? damp : 1)
        : (l) => Math.min(1, f.linkForce
            / Math.min(degrees[l.source.index] || 1,
                       degrees[l.target.index] || 1))
          * (anchored(l) ? damp : 1)))
    // NO distanceMax: a cutoff stamps a same-size "cleared ring" around
    // every cluster and the layout degenerates into overlapping circles
    // (observed 2026-08-23). Full-range repulsion, weaker per node and a
    // coarser theta, gives the smooth organic falloff instead.
    .force("charge", forceManyBody()
      .strength((ego ? ego.charge : -50) * f.repel).theta(1.3))
    .force("x", forceX(0).strength(0.02 * f.center))
    .force("y", forceY(0).strength(0.02 * f.center))
    .alphaDecay(0.03).alphaMin(alphaMin)
    .stop();
  // Grouping layers: anchored nodes (strength > 0) are pulled toward
  // their sector centroid, overpowering the weak global centering.
  if (anchors) {
    sim.force("ax", forceX((d, i) => anchors.ax[i])
      .strength((d, i) => anchors.st[i]));
    sim.force("ay", forceY((d, i) => anchors.ay[i])
      .strength((d, i) => anchors.st[i]));
  }
  // Collision is the most expensive force and only matters for the final
  // honeycomb packing — it joins late, so early ticks stay fast and the
  // untangling phase streams positions at a lively cadence.
  let collideOn = false;
  const pump = () => {
    if (!collideOn && sim.alpha() < 0.35) {
      sim.force("collide", forceCollide()
        .radius(ego ? (d, i) => ego.collideR[i]
                    : (d, i) => 10 + Math.min(12, Math.sqrt(degrees[i] || 0))));
      collideOn = true;
    }
    sim.tick();
    const done = sim.alpha() <= alphaMin;
    const out = new Float32Array(2 * count);
    for (let i = 0; i < count; i++) {
      out[2 * i] = nodes[i].x;
      out[2 * i + 1] = nodes[i].y;
    }
    self.postMessage({ positions: out, done }, [out.buffer]);
    if (!done) setTimeout(pump, 0);
  };
  pump();
};
