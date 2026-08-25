/* Charlotte's Web state, held at module scope (the signalStore pattern) so
   leaving the page keeps the loaded web and a running crawl keeps being
   polled. The graph itself merges across expands — node positions live here
   too, so re-layouts stay stable instead of reshuffling the world on every
   click. */
import { get, post } from "../../api.js";

/* One palette for both canvases AND the legend pills — literal hex because
   canvas fillStyle can't resolve CSS vars. Hues are deliberately spread
   (teal / navy / plum / brass / cool grey) so the kinds separate at
   2px-dot size, not just in the legend. */
export const KIND_COLORS = {
  fund: "#2E8B84",       // house teal
  company: "#1D3D52",    // deep navy
  contact: "#8A557E",    // plum — was slate, too close to navy and teal
  note: "#B0894E",       // brass
  external: "#91919E",   // cool grey — was warm grey, too close to brass
};

/* Visual + physics settings for both canvases (the Obsidian-style panel).
   Force values are MULTIPLIERS on each view's tuned baseline, so 1 is
   always "the default look" and the reset is trivial. */
export const VIZ_DEFAULTS = {
  arrows: false,
  textScale: 1,      // label font multiplier
  nodeScale: 1,      // node radius multiplier
  fadeAmount: 0.8,   // how far the kind filter fades the rest (0..0.95)
  center: 1,
  repel: 1,
  linkForce: 1,
  linkDist: 1,
  groupPull: 1,      // sector anchor strength (global view layers)
  groupTies: 1,      // how much links still tug sector-anchored funds
};

export const S = {
  status: null,          // /api/charlotte/status payload
  job: null,             // running crawl job summary, when one is going
  mode: "ego",           // "ego" (fund-centered) | "global" (whole snapshot)
  global: { nodes: null, edges: null, crawledAt: "", loading: false },
  center: null,
  hops: 2,
  nodes: {},             // id -> node (merged across expands)
  edges: [],             // deduped by (a, b, type)
  lp: [],                // LP candidates for the current center fund
  meta: null,
  positions: {},         // id -> {x, y}; written back by the sim on teardown
  viewEpoch: 0,          // bumped on centerOn — tells the canvas to re-fit
  expandAnchor: null,    // last expanded node — pinned during the re-settle
  expanding: null,       // node id whose expand fetch is IN FLIGHT — the
                         // canvas animates feeler lines out of it meanwhile
  selected: null,        // node id for the drawer
  selectedEdge: null,    // edge object for evidence view
  kinds: [],             // HIGHLIGHT — these kinds full strength, rest fades
  hidden: [],            // FILTERS — these kinds are removed from the graph
  // LAYERS — ordered grouping stacks for the global view. Fund layers
  // nest top-down (first row splits the widest sectors); contacts get
  // one optional group-by-type ring.
  // ALL groupings default off — the views open organic; grouping is an
  // opt-in via the GROUP pills in the filter tree. (Fund order still
  // matters once several are on: the top one splits first. The
  // PUBLIC/PRIVATE access layer was retired 24 Aug 2026.)
  layers: {
    fund: [
      { key: "asset_class", on: false },
      { key: "geography", on: false },
      { key: "quality", on: false },
    ],
    contact: [{ key: "contact_type", on: false }],
  },
  // Value-level removal, per sub-filter (both views): hide funds whose
  // asset class / geography / quality is toggled off, contacts of
  // hidden types. "" addresses blanks.
  valueHidden: { asset_class: [], geography: [],
                 quality: [], contact_type: [] },
  viz: { ...VIZ_DEFAULTS },
  loadingEgo: false,
  error: null,
  version: 0,
};

let listeners = new Set();
function emit() { S.version++; listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }

const edgeKey = (e) => `${e.a}|${e.b}|${e.type}`;

/* Merge an ego payload into the held graph. On replace, positions of nodes
   that survive are kept (the world stays put); on expand, new nodes spawn
   near the node that was expanded so growth reads as growth, not reshuffle.
   Exported for tests. */
export function mergeView(body, { replace = false, anchor = null } = {}) {
  if (replace) {
    const survivors = new Set((body.nodes || []).map((n) => n.id));
    for (const id of Object.keys(S.positions)) {
      if (!survivors.has(id)) delete S.positions[id];
    }
    S.nodes = {};
    S.edges = [];
  }
  const at = anchor ? S.positions[anchor] : null;
  for (const n of body.nodes || []) {
    S.nodes[n.id] = { ...(S.nodes[n.id] || {}), ...n };
    if (at && !S.positions[n.id]) {
      S.positions[n.id] = { x: at.x + (Math.random() - 0.5) * 70,
                            y: at.y + (Math.random() - 0.5) * 70 };
    }
  }
  const seen = new Set(S.edges.map(edgeKey));
  for (const e of body.edges || []) {
    const k = edgeKey(e);
    if (!seen.has(k)) { seen.add(k); S.edges.push(e); }
  }
  if (replace || (body.lp_candidates || []).length) {
    S.lp = body.lp_candidates || (replace ? [] : S.lp);
  }
  S.meta = body.meta || S.meta;
}

let statusInFlight = null;
export function ensureStatus() {
  if (statusInFlight) return statusInFlight;
  statusInFlight = get("/api/charlotte/status")
    .then((st) => {
      S.status = st;
      S.error = null;
      if (st.job?.id && st.job.status === "running") attachJob(st.job.id);
      return st;
    })
    .catch((e) => { S.error = e.message; })
    .finally(() => { statusInFlight = null; emit(); });
  return statusInFlight;
}

let pollTimer = null;
function attachJob(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const j = await get(`/api/jobs/${jobId}`);
      S.job = j;
      if (j.status !== "running") {
        clearInterval(pollTimer);
        pollTimer = null;
        S.job = null;
        // Fresh snapshot on disk: refresh status, and rebuild the current
        // view on top of it if one is open.
        await ensureStatus();
        if (S.center) await centerOn(S.center);
      }
      emit();
    } catch {
      clearInterval(pollTimer);
      pollTimer = null;
      S.job = null;
      emit();
    }
  }, 2000);
}

export async function startCrawl() {
  S.error = null;
  try {
    const j = await post("/api/charlotte/refresh");
    S.job = j;
    attachJob(j.id);
  } catch (e) {
    S.error = e.message;
  }
  emit();
}

export async function centerOn(id) {
  S.loadingEgo = true;
  S.error = null;
  emit();
  try {
    const body = await get(
      `/api/charlotte/ego?node=${encodeURIComponent(id)}`
      + `&hops=${S.hops}&max_nodes=20000`);
    if (!body.ready) {
      S.error = "The web has not been built yet — press Build the web first.";
      return;
    }
    S.center = id;
    S.selected = null;
    S.selectedEdge = null;
    mergeView(body, { replace: true });
    S.expandAnchor = null;
    S.viewEpoch++;
  } catch (e) {
    S.error = e.message;
  } finally {
    S.loadingEgo = false;
    emit();
  }
}

export async function expand(id) {
  S.loadingEgo = true;
  S.expanding = id;
  emit();
  try {
    const body = await get(
      `/api/charlotte/ego?node=${encodeURIComponent(id)}&hops=1&max_nodes=8000`);
    if (body.ready) {
      mergeView(body, { anchor: id });
      // The expanded node is the user's point of attention — the canvas
      // pins it in place while the new neighbors settle around it.
      S.expandAnchor = id;
    }
  } catch (e) {
    S.error = e.message;
  } finally {
    S.loadingEgo = false;
    S.expanding = null;
    emit();
  }
}

export function setMode(m) {
  S.mode = m;
  emit();
}

/* How many hops the ego BFS walks (server clamps to 3). Re-centers the
   open web so the change is visible immediately. */
export function setHops(n) {
  const h = Math.max(1, Math.min(3, n));
  if (h === S.hops) return;
  S.hops = h;
  emit();
  if (S.center) centerOn(S.center);
}

/* Fetch the whole snapshot once per crawl. Edges arrive as index pairs and
   are rehydrated to direct node references — d3-force takes objects, and it
   avoids keeping a 27k-entry id map alive. */
export async function loadGlobal() {
  if (S.global.loading) return;
  const at = S.status?.crawled_at || "";
  if (S.global.nodes && S.global.crawledAt === at) return;
  S.global = { ...S.global, loading: true };
  S.error = null;
  emit();
  try {
    const body = await get("/api/charlotte/full");
    if (!body.ready) {
      S.error = "The web has not been built yet — press Build the web first.";
      S.global = { ...S.global, loading: false };
    } else {
      const nodes = body.nodes;
      const types = body.types || [];
      const edges = (body.edges || []).map(([a, b, inf, ti]) => ({
        a: nodes[a], b: nodes[b], inferred: !!inf, type: types[ti] || "" }));
      const byId = new Map(nodes.map((n) => [n.id, n]));
      S.global = { nodes, edges, byId,
                   crawledAt: body.crawled_at, loading: false };
    }
  } catch (e) {
    S.error = e.message;
    S.global = { ...S.global, loading: false };
  }
  emit();
}

/* A click in the galaxy dives into that node's own web. */
export function openFromGlobal(id) {
  S.mode = "ego";
  centerOn(id);
}

export function select(id) {
  S.selected = id;
  if (id) S.selectedEdge = null;
  emit();
}

export function selectEdge(e) {
  S.selectedEdge = e;
  if (e) S.selected = null;
  emit();
}

export function toggleKind(k) {
  S.kinds = S.kinds.includes(k)
    ? S.kinds.filter((x) => x !== k)
    : [...S.kinds, k];
  emit();
}

export function clearKinds() {
  S.kinds = [];
  emit();
}

export function toggleHidden(k) {
  if (S.hidden.includes(k)) {
    S.hidden = S.hidden.filter((x) => x !== k);
  } else {
    S.hidden = [...S.hidden, k];
    // A removed kind can't stay highlighted — it isn't on screen.
    S.kinds = S.kinds.filter((x) => x !== k);
  }
  emit();
}

export function clearHidden() {
  S.hidden = [];
  emit();
}

export function toggleLayer(scope, key) {
  S.layers = { ...S.layers,
    [scope]: S.layers[scope].map((l) =>
      (l.key === key ? { ...l, on: !l.on } : l)) };
  emit();
}

export function moveLayer(scope, from, to) {
  const list = [...S.layers[scope]];
  if (from < 0 || from >= list.length || to < 0 || to >= list.length
      || from === to) return;
  const [row] = list.splice(from, 1);
  list.splice(to, 0, row);
  S.layers = { ...S.layers, [scope]: list };
  emit();
}

export const FUND_VALUE_FIELDS = ["asset_class", "geography", "quality"];

/* Combined removal predicate for FILTERS: kind toggles plus value-level
   hides on each grouping layer. Null when nothing is hidden. Shared by
   both canvases (the ego view exempts its center separately). */
export function makeHidden(s) {
  const kinds = s.hidden.length ? new Set(s.hidden) : null;
  const fv = [];
  for (const f of FUND_VALUE_FIELDS) {
    if (s.valueHidden[f]?.length) fv.push([f, new Set(s.valueHidden[f])]);
  }
  const ct = s.valueHidden.contact_type?.length
    ? new Set(s.valueHidden.contact_type) : null;
  if (!kinds && !fv.length && !ct) return null;
  return (n) => {
    if (!n) return false;
    if (kinds && kinds.has(n.kind)) return true;
    if (n.kind === "fund") {
      for (const [f, set] of fv) {
        if (set.has(n[f] || "")) return true;
      }
    } else if (n.kind === "contact" && ct
               && ct.has(n.contact_type || "")) {
      return true;
    }
    return false;
  };
}

/* Dependency key for effects that must react to any value-hide change. */
export const valueHiddenKey = (s) => [...FUND_VALUE_FIELDS, "contact_type"]
  .map((f) => (s.valueHidden[f] || []).join(",")).join("|");

export function toggleValueHidden(field, value) {
  const cur = S.valueHidden[field] || [];
  S.valueHidden = { ...S.valueHidden,
    [field]: cur.includes(value)
      ? cur.filter((x) => x !== value)
      : [...cur, value] };
  emit();
}

export function setViz(patch) {
  S.viz = { ...S.viz, ...patch };
  emit();
}

export function resetViz() {
  S.viz = { ...VIZ_DEFAULTS };
  emit();
}
