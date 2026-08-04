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
    zone: "contacts", activity: "tinker",  // tinker | walk | fix | type
    selected: "",          // the station the user clicked, if any
    labels: [], caption: "tinkering…",
    power: false,          // POWER UP: a run is underway — flames on
    powerBanner: 0,        // timestamp key; re-renders the POWER UP splash
    researching: false,    // the run is in a web-research stage — desk time
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

// Speech-bubble phrase pools — spawned ONLY from real change events.
const PHRASES = {
  fix_formatting: ["Nice!", "Record sorted!", "Tidy!", "Spick and span!"],
  fix_icon: ["Icon polished!", "Nice!", "Shiny!"],
  fix_relation: ["Link repaired!", "Rewired!", "Reconnected!"],
  fill_missing: ["Gap filled!", "Detail sorted!", "Nice!"],
  merge: ["Duplicates squashed!", "Merged!", "Two became one!"],
  merge_transfer: ["Detail carried over!", "Nothing lost!"],
  archive: ["Duplicate shelved!", "Filed away!"],
  recommendation: ["Hmm — flagged it.", "One for you to check."],
};
const DB_PHRASES = {
  contacts: "Contact sorted!", companies: "Company sorted!",
  funds: "Fund sorted!", notes: "Note sorted!",
};
const UNDO_PHRASES = ["Whoopsie!", "Oops, my bad!", "Undoing that one!",
                      "Sorry! Rolling it back."];

function phraseFor(ev) {
  const pool = PHRASES[ev.type] || ["Nice!"];
  // Every third fix or so, name the database GDS-style.
  if (Math.random() < 0.34 && DB_PHRASES[ev.db] && ev.type !== "recommendation") {
    return DB_PHRASES[ev.db];
  }
  return pool[Math.floor(Math.random() * pool.length)];
}

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
  // "easy" is a client-side view over the awaiting queue (high-confidence
  // mechanical fixes) — the API only knows review statuses.
  const apiFilter = { ...S.changesFilter };
  if (apiFilter.review === "easy") apiFilter.review = "Awaiting Review";
  const q = new URLSearchParams(
    Object.entries(apiFilter).filter(([, v]) => v));
  try {
    const d = await get(`/api/felix/changes?${q}&limit=100`);
    S.changes = d.changes || [];
  } catch (e) { S.error = e.message; }
  emit();
}

/* Clicking a station is a real action, not decoration: Felix walks over and
   the review list below filters to that database. Clicking it again clears
   the filter. The research desk has no database of its own — it stands for
   the web lookups, so it just sends him there. */
export function selectStation(zone) {
  const same = S.scene.selected === zone;
  S.scene.selected = same ? "" : zone;
  if (!same) {
    if (S.scene.zone !== zone) {
      S.scene.zone = zone;
      S.scene.activity = "walk";
      S.scene.caption = `heading to ${zone}…`;
      phaseUntil = Date.now() + 1100;
    }
    const db = ZONES.includes(zone) ? zone : "";
    fetchChanges({ ...S.changesFilter, db });
  } else {
    const { db, ...rest } = S.changesFilter;   // eslint-disable-line no-unused-vars
    fetchChanges(rest);
  }
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

export async function startRun({ dryRun, webResearch } = {}) {
  S.busy = webResearch ? "search" : "start"; S.error = null; emit();
  try {
    const body = {};
    if (dryRun !== undefined) body.dry_run = dryRun;
    if (webResearch) body.web_research = true;
    const job = await post("/api/jobs/felix", body);
    attach(job.id);
    powerUp();
    lastEventAt = Date.now();
  } catch (e) { S.error = e.message; }
  S.busy = ""; emit();
}

function powerUp() {
  if (!S.scene.power) {
    S.scene.power = true;
    S.scene.powerBanner = Date.now();
    emit();
  }
}

function powerDown() {
  if (S.scene.power) {
    S.scene.power = false;
    emit();
  }
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
      if (summary.status === "running") powerUp();
      // Web-research stages put Felix at his computer desk.
      const stage = (summary.stages || [])[summary.stages?.length - 1];
      S.scene.researching = summary.status === "running"
        && !!stage && /^Researching/.test(stage.label || "");
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
        powerDown();
        S.scene.researching = false;
        S.lastResult = summary.result || null;
        refreshStatus();
        fetchChanges();
      }
      emit();
    } catch { /* transient — keep polling */ }
  }, 2000);
}

// ---- review --------------------------------------------------------------- //

/* `edit` carries the reviewer's own wording or tags: {value} for text and
   single selects, {values} for multi-selects. Omitted means "approve exactly
   what Felix planned". */
export async function review(changeId, action, survivorId = "", edit = null) {
  S.busy = `review-${changeId}`; emit();
  try {
    const res = await post(`/api/felix/changes/${changeId}/review`,
                           { action, survivor_id: survivorId, ...(edit || {}) });
    const next = { approve: "Approved", dismiss: "Dismissed",
                   undo: "Undo Requested" }[action];
    const change = S.changes.find((c) => c.change_id === changeId);
    S.changes = S.changes.map((c) => c.change_id === changeId
      ? { ...c, review_status: next } : c);
    if (action === "undo") {
      spawnLabel(UNDO_PHRASES[Math.floor(Math.random() * UNDO_PHRASES.length)],
                 "caution");
    } else if (action === "approve" && change) {
      if (res.execution_status === "Applied") {
        // The approval genuinely wrote to Notion — Felix runs over to that
        // database's station and celebrates the real fix.
        eventQueue.push({
          change_id: `${changeId}-approved`, db: change.database,
          record: change.record_name, type: change.change_type,
          status: "Applied", label: "fixed on your say-so",
        });
        lastEventAt = Date.now();
      } else {
        spawnLabel("Filed away!", "teal");
      }
    }
    fetchChanges();   // twins of this finding get superseded server-side
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
  sceneTimer = setInterval(tick, 400);
}

const TINKER_LINES = ["tinkering…", "tightening bolts…", "oiling the hinges…",
                      "checking the wiring…", "calibrating…", "polishing…"];
const RESEARCH_LINES = ["searching the web…", "digging on LinkedIn…",
                        "cross-checking names…", "reading team pages…",
                        "typing furiously…", "comparing fund docs…"];

function tick() {
  const now = Date.now();
  if (now < phaseUntil) return;
  const power = S.scene.power;
  const walkMs = power ? 850 : 900;      // matches .fx-sprite's .8s travel
  const fixMs = power ? 900 : 1400;

  // A real event: dash to its zone, wrench it, say something.
  if (eventQueue.length) {
    const ev = eventQueue.shift();
    const zone = ZONES.includes(ev.db) ? ev.db : S.scene.zone;
    if (S.scene.zone !== zone && S.scene.activity !== "walk") {
      S.scene.zone = zone;
      set("walk", `dashing to ${zone}…`, walkMs);
      eventQueue.unshift(ev);            // wrench it after arriving
    } else {
      set("fix", `${ev.record || "record"} — ${ev.label || "fixing"}`, fixMs);
      if (["Applied", "Planned (dry-run)"].includes(ev.status)) {
        spawnLabel(phraseFor(ev),
                   ev.status === "Applied" ? "positive" : "teal");
      } else if (ev.status === "Recommended") {
        spawnLabel(phraseFor({ ...ev, type: "recommendation" }), "caution");
      } else if (ev.status === "Failed") {
        spawnLabel("Hmm, that one wouldn't budge.", "caution");
      }
    }
    emit();
    return;
  }

  // Web research underway: Felix sits at his computer desk, typing away.
  if (S.scene.researching) {
    if (S.scene.zone !== "research") {
      S.scene.zone = "research";
      set("walk", "heading to the research desk…", walkMs);
    } else {
      set("type", RESEARCH_LINES[Math.floor(Math.random() * RESEARCH_LINES.length)],
          1100 + Math.random() * 900);
    }
    emit();
    return;
  }
  if (S.scene.zone === "research") {
    // Research over — back to the workshop floor.
    S.scene.zone = ZONES[Math.floor(Math.random() * ZONES.length)];
    set("walk", "back to the floor…", walkMs);
    emit();
    return;
  }

  // No sleep, ever: Felix is always tinkering with SOMETHING — hopping
  // between stations and wrenching away (without claiming fixes).
  if (S.scene.activity === "walk") {
    set("fix", TINKER_LINES[Math.floor(Math.random() * TINKER_LINES.length)],
        power ? 1500 : 3200 + Math.random() * 2500);
  } else {
    // Wander roughly every other phase; otherwise keep tinkering here.
    if (Math.random() < 0.45) {
      const next = ZONES[(ZONES.indexOf(S.scene.zone) + 1 +
                          Math.floor(Math.random() * 3)) % ZONES.length];
      S.scene.zone = next;
      set("walk", "dashing over…", walkMs);
    } else {
      set("fix", TINKER_LINES[Math.floor(Math.random() * TINKER_LINES.length)],
          power ? 1500 : 3200 + Math.random() * 2500);
    }
  }
  emit();
}

export function dropLabel(id) {
  S.scene.labels = S.scene.labels.filter((l) => l.id !== id);
  emit();
}
