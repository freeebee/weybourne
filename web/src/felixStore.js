/* Fix-it Felix — game + run state at module scope, so a clean-up run keeps
   polling (and Felix keeps working) while you browse other tabs.

   Honesty rule baked in here: "fixed!" labels are spawned ONLY from real
   change events reported by the backend run. Idle behaviour (patrolling,
   inspecting, sleeping) never claims a fix. */
import { get, post } from "./api.js";

export const ZONES = ["contacts", "companies", "funds", "notes"];

export const S = {
  status: null,            // /api/felix/status payload
  stats: null,
  changes: [],             // review list cache
  changesFilter: { review: "Awaiting Review" },
  runJob: null,            // summary of the running/last-polled felix job
  lastResult: null,
  scene: {
    zone: "contacts", activity: "sleep",   // walk | fix | inspect | sleep
    labels: [], caption: "asleep at the toolbox",
  },
  busy: "", error: null, version: 0,
};

let listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
function emit() { S.version++; listeners.forEach((f) => f()); }

let pollTimer = null, sceneTimer = null, labelSeq = 1;
let eventQueue = [];             // real change events awaiting theatrics
let seenEvents = new Set();
let lastEventAt = 0, phaseUntil = 0, restored = false;

const LABEL_TEXT = {
  fix_formatting: "Record tidied!",
  fix_icon: "Icon polished!",
  fix_relation: "Relation repaired!",
  fill_missing: "Detail filled in!",
  merge: "Duplicate merged!",
  merge_transfer: "Detail transferred!",
  archive: "Duplicate archived!",
  recommendation: "Flagged for review",
};

// ---- data loading --------------------------------------------------------- //

export async function refreshStatus() {
  try {
    S.status = await get("/api/felix/status");
    S.stats = S.status.stats;
    if (S.status.running && !pollTimer) attach(S.status.running.id);
    emit();
  } catch { /* backend down — page shows what it has */ }
}

export async function fetchChanges(filter) {
  if (filter) S.changesFilter = filter;
  const q = new URLSearchParams(
    Object.entries(S.changesFilter).filter(([, v]) => v));
  try {
    const d = await get(`/api/felix/changes?${q}&limit=100`);
    S.changes = d.changes || [];
  } catch (e) { S.error = e.message; }
  emit();
}

export function restore() {
  if (restored) return;
  restored = true;
  refreshStatus();
  fetchChanges();
  ensureSceneLoop();
}

// ---- runs ----------------------------------------------------------------- //

export async function startRun({ dryRun } = {}) {
  S.busy = "start"; S.error = null; emit();
  try {
    const job = await post("/api/jobs/felix",
                           dryRun === undefined ? {} : { dry_run: dryRun });
    attach(job.id);
    lastEventAt = Date.now();
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export async function cancelRun() {
  if (S.runJob?.id) {
    try { await post(`/api/jobs/${S.runJob.id}/cancel`); } catch { /* gone */ }
  }
}

function attach(jobId) {
  clearInterval(pollTimer);
  ensureSceneLoop();
  pollTimer = setInterval(async () => {
    try {
      const [summary, partial] = await Promise.all([
        get(`/api/jobs/${jobId}`),
        get(`/api/jobs/${jobId}/partial`).catch(() => null),
      ]);
      S.runJob = summary;
      const events = partial?.partial?.events || [];
      for (const ev of events) {
        const key = ev.change_id + ev.status;
        if (!seenEvents.has(key)) {
          seenEvents.add(key);
          eventQueue.push(ev);
          lastEventAt = Date.now();
        }
      }
      if (summary.status !== "running") {
        clearInterval(pollTimer); pollTimer = null;
        S.lastResult = summary.result || null;
        refreshStatus();
        fetchChanges();
      }
      emit();
    } catch { /* transient — keep polling */ }
  }, 2000);
}

// ---- review --------------------------------------------------------------- //

export async function review(changeId, action) {
  S.busy = `review-${changeId}`; emit();
  try {
    await post(`/api/felix/changes/${changeId}/review`, { action });
    S.changes = S.changes.map((c) => c.change_id === changeId
      ? { ...c, review_status: action === "approve" ? "Approved" : "Undo Requested" }
      : c);
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

export async function setConfig(patch) {
  try {
    const cfg = await post("/api/felix/config", patch);
    if (S.status) S.status = { ...S.status, ...cfg };
    emit();
  } catch (e) { S.error = e.message; emit(); }
}

// ---- the game loop -------------------------------------------------------- //

function spawnLabel(text, tone) {
  S.scene.labels = [...S.scene.labels.slice(-4),
                    { id: labelSeq++, text, tone, zone: S.scene.zone }];
}

function set(activity, caption, ms) {
  S.scene.activity = activity;
  S.scene.caption = caption;
  phaseUntil = Date.now() + ms;
}

function ensureSceneLoop() {
  if (sceneTimer) return;
  sceneTimer = setInterval(tick, 700);
}

function tick() {
  const now = Date.now();
  if (now < phaseUntil) return;
  const running = S.runJob?.status === "running";

  // A real event: walk to its zone, then fix, then float the label.
  if (eventQueue.length) {
    const ev = eventQueue.shift();
    const zone = ZONES.includes(ev.db) ? ev.db : S.scene.zone;
    if (S.scene.zone !== zone && S.scene.activity !== "walk") {
      S.scene.zone = zone;
      set("walk", `heading to ${zone}…`, 1700);
      eventQueue.unshift(ev);          // fix it after arriving
    } else {
      set("fix", `${ev.record || "record"} — ${ev.label || "fixing"}`, 1500);
      if (["Applied", "Planned (dry-run)"].includes(ev.status)) {
        spawnLabel(LABEL_TEXT[ev.type] || "Fixed!",
                   ev.status === "Applied" ? "positive" : "teal");
      } else if (ev.status === "Recommended") {
        spawnLabel("Flagged for review", "caution");
      } else if (ev.status === "Failed") {
        spawnLabel("Couldn't fix — logged", "caution");
      }
    }
    emit();
    return;
  }

  const idleFor = now - lastEventAt;
  if (running) {
    // Between events mid-run: keep inspecting the current zone.
    set("inspect", `checking ${S.scene.zone}…`, 2600);
  } else if (idleFor > 180000) {
    if (S.scene.activity !== "sleep") set("sleep", "asleep at the toolbox", 8000);
    else phaseUntil = now + 8000;
  } else if (idleFor > 20000) {
    // Gentle patrol — never claims a fix.
    if (S.scene.activity === "walk") {
      set("inspect", `inspecting ${S.scene.zone}…`, 4000 + Math.random() * 4000);
    } else {
      const next = ZONES[(ZONES.indexOf(S.scene.zone) + 1 +
                          Math.floor(Math.random() * 3)) % ZONES.length];
      S.scene.zone = next;
      set("walk", `patrolling…`, 1700);
    }
  } else {
    set("inspect", `looking things over…`, 3000);
  }
  emit();
}

export function dropLabel(id) {
  S.scene.labels = S.scene.labels.filter((l) => l.id !== id);
  emit();
}
