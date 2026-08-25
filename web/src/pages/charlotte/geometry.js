/* Pure viewport math for the Charlotte's Web canvas.

   The canvas draws in world space through a {x, y, k} transform; hit-testing
   inverts that transform manually (a canvas has no per-element hit targets,
   unlike the SVG charts elsewhere in the app). Kept free of DOM so vitest
   can exercise every branch. */

export function toWorld(sx, sy, t) {
  return { x: (sx - t.x) / t.k, y: (sy - t.y) / t.k };
}

/* Node size grows gently with degree — a hub reads as a hub without a
   10k-note fund becoming a beach ball. */
export function nodeRadius(n, base = 7) {
  return base + Math.min(6, Math.sqrt(n?.degree || 0));
}

/* Nearest node whose disc (plus a little slack, in SCREEN pixels so it
   doesn't balloon when zoomed out) contains the world point. */
export function pickNode(nodes, positions, wx, wy, k, slack = 3, scale = 1) {
  let best = null;
  let bestD = Infinity;
  for (const n of nodes) {
    const p = positions[n.id];
    if (!p) continue;
    const d = Math.hypot(wx - p.x, wy - p.y);
    if (d <= nodeRadius(n) * scale + slack / (k || 1) && d < bestD) {
      best = n;
      bestD = d;
    }
  }
  return best;
}

export function segDist(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const len2 = vx * vx + vy * vy;
  if (len2 === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * vx + (py - ay) * vy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * vx), py - (ay + t * vy));
}

/* Nearest edge within `slack` screen pixels of the point — how a click on
   a dashed edge opens its evidence. */
export function pickEdge(edges, positions, wx, wy, k, slack = 4) {
  let best = null;
  let bestD = slack / (k || 1);
  for (const e of edges) {
    const a = positions[e.a];
    const b = positions[e.b];
    if (!a || !b) continue;
    const d = segDist(wx, wy, a.x, a.y, b.x, b.y);
    if (d <= bestD) {
      best = e;
      bestD = d;
    }
  }
  return best;
}

/* Zoom that keeps the world point under the cursor stationary. The floor
   sits well below 1 so a fully spread layout can be pulled back into one
   galaxy-wide view. */
export function zoomAround(t, sx, sy, factor, min = 0.05, max = 4) {
  const k = Math.max(min, Math.min(max, t.k * factor));
  const wx = (sx - t.x) / t.k;
  const wy = (sy - t.y) / t.k;
  return { k, x: sx - wx * k, y: sy - wy * k };
}
