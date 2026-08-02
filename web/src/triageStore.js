/* Inbox-triage session store — module scope, outside React, so a running
   triage keeps applying results while the user is on other pages. */
import { get, post } from "./api.js";
import { setInboxCount } from "./uiStore.js";

export const S = {
  days: 3, top: 25,
  messages: null, notionLive: true,
  flags: {},            // id -> {flag, reason}
  flagsBusy: false,
  results: {},          // id -> triage result
  selected: new Set(),
  inFlight: new Set(),  // message ids submitted to a running triage job
  activeId: null,
  scanBusy: false,
  jobs: {},             // jobId -> {done, total, current, elapsed, eta}
  work: {},             // msgId -> per-message workflow state (screen/drafts/…)
  error: null, notice: null,
  version: 0,
};

let listeners = new Set();
const pollTimers = {};

function emit() { S.version++; listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
export function set(patch) { Object.assign(S, patch); emit(); }

export async function scan() {
  S.scanBusy = true; S.error = null; S.results = {}; S.flags = {};
  S.notice = null; S.activeId = null; S.jobs = {}; S.work = {};
  S.inFlight = new Set(); emit();
  try {
    const data = await get(`/api/inbox?days=${S.days}&top=${S.top}`);
    S.messages = data.messages;
    S.notionLive = data.notion_live;
    S.selected = new Set();   // nothing pre-selected — you choose what to triage
    S.activeId = data.messages[0]?.id ?? null;
    setInboxCount(data.messages.length);
    emit();
    fetchFlags();   // fire and forget — quick pre-sort of the scan
  } catch (e) { S.error = e.message; }
  S.scanBusy = false; emit();
}

async function fetchFlags() {
  if (!S.messages?.length) return;
  S.flagsBusy = true; emit();
  try {
    const { flags } = await post("/api/inbox/flags", {
      messages: S.messages.map((m) => ({
        id: m.id, subject: m.subject, sender_name: m.sender_name,
        sender_email: m.sender_email, body_preview: m.body_preview,
      })),
    });
    S.flags = Object.fromEntries(flags.map((f) => [f.id, f]));
    // Flags are suggestions only — selection stays yours.
  } catch (e) {
    S.error = `Quick flags unavailable: ${e.message}`;
  }
  S.flagsBusy = false; emit();
}

export function toggle(id) {
  const next = new Set(S.selected);
  next.has(id) ? next.delete(id) : next.add(id);
  S.selected = next; emit();
}

export function selectAll(on) {
  S.selected = on ? new Set(S.messages.map((m) => m.id)) : new Set();
  emit();
}

export function triageable() {
  /* Selected messages that are neither triaged already nor in a running job. */
  if (!S.messages) return [];
  return S.messages.filter((m) =>
    S.selected.has(m.id) && !S.results[m.id] && !S.inFlight.has(m.id));
}

export async function startTriage() {
  const targets = triageable();
  if (!targets.length) return;
  S.error = null; emit();
  try {
    const res = await fetch("/api/jobs/triage", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: targets }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    const job = await res.json();
    targets.forEach((m) => S.inFlight.add(m.id));
    S.jobs = { ...S.jobs, [job.id]: {
      done: 0, total: targets.length, current: "", elapsed: 0, eta: job.eta,
      ids: targets.map((m) => m.id),
    } };
    emit();
    poll(job.id);
  } catch (e) { S.error = e.message; emit(); }
}

function applyResult(id, r) {
  if (S.results[id]) return;
  S.results = { ...S.results, [id]: r };
  S.inFlight.delete(id);
  // Seed the per-message workflow with default approvals. Only investment-
  // relevant mail pre-approves creations; for anything else the proposals are
  // shown but nothing is ticked by default.
  S.work[id] = S.work[id] || {};
  if (!S.work[id].approved) {
    S.work[id].approved = r.is_investment
      ? (r.proposals || []).filter((p) => !p.needs_review).map((p) => p.kind)
      : [];
  }
  if (r.is_investment
      && !Object.entries(S.results).some(([k, x]) => k !== id && x.is_investment)) {
    S.activeId = id;   // jump to the first investment-relevant hit
  }
}

function poll(jobId) {
  clearInterval(pollTimers[jobId]);
  pollTimers[jobId] = setInterval(async () => {
    try {
      const [summary, partial] = await Promise.all([
        get(`/api/jobs/${jobId}`),
        get(`/api/jobs/${jobId}/partial`),
      ]);
      Object.entries(partial.partial).forEach(([id, r]) => applyResult(id, r));
      if (S.jobs[jobId]) {
        S.jobs = { ...S.jobs, [jobId]: { ...S.jobs[jobId],
          done: partial.done, total: partial.total,
          current: partial.current, elapsed: summary.elapsed, eta: summary.eta } };
      }
      emit();
      if (summary.status !== "running") {
        clearInterval(pollTimers[jobId]);
        if (summary.status === "error") S.error = summary.error;
        (S.jobs[jobId]?.ids || []).forEach((id) => S.inFlight.delete(id));
        const { [jobId]: _, ...rest } = S.jobs;
        S.jobs = rest;
        emit();
      }
    } catch {
      // transient — keep polling
    }
  }, 1500);
}

/* Re-attach after a reload: pick up any running triage jobs. */
export async function restore() {
  if (Object.keys(S.jobs).length || S.messages) return;
  try {
    const { jobs } = await get("/api/jobs?kind=triage");
    jobs.filter((j) => j.status === "running").forEach((j) => {
      S.jobs = { ...S.jobs, [j.id]: {
        done: j.done || 0, total: j.total || 0, current: j.current || "",
        elapsed: j.elapsed, eta: j.eta, ids: [],
      } };
      poll(j.id);
    });
    emit();
  } catch { /* nothing to restore */ }
}

/* ---- per-message workflow (survives navigation: lives here, not in React) -- */

function workOf(id) {
  if (!S.work[id]) S.work[id] = { approved: [] };
  return S.work[id];
}

export function getWork(id) { return workOf(id); }

export function setWork(id, patch) {
  S.work[id] = { ...workOf(id), ...patch };
  emit();
}

async function workCall(id, busyLabel, fn) {
  setWork(id, { busy: busyLabel, error: null });
  try { await fn(workOf(id)); }
  catch (e) { setWork(id, { error: e.message }); }
  setWork(id, { busy: "" });
}

export function runScreen(msg) {
  const r = S.results[msg.id];
  return workCall(msg.id, "screen", async () => {
    const screen = await post("/api/screen",
      { entity: r.entity, key_facts: r.key_facts });
    setWork(msg.id, { screen });
  });
}

export function genDrafts(msg) {
  const r = S.results[msg.id];
  return workCall(msg.id, "drafts", async (w) => {
    const res = await post("/api/drafts",
      { message: msg, entity: r.entity, screen: w.screen || null,
        dedupe: r.dedupe || null });
    setWork(msg.id, { options: res.options, chosen: 0,
                      draftBody: res.options[0]?.body || "" });
  });
}

/* Per-proposal edits: the user can change any property value before the
   Notion entry is created. Stored as work.edits = {kind: {prop: value}}. */
export function setProposalEdit(id, kind, prop, value) {
  const w = workOf(id);
  const edits = { ...(w.edits || {}) };
  edits[kind] = { ...(edits[kind] || {}), [prop]: value };
  setWork(id, { edits });
}

export function toggleProposalEdit(id, kind) {
  const w = workOf(id);
  const editing = { ...(w.editing || {}) };
  editing[kind] = !editing[kind];
  setWork(id, { editing });
}

export function applyPlan(msg) {
  const r = S.results[msg.id];
  return workCall(msg.id, "apply", async (w) => {
    const res = await post("/api/notion/apply",
      { proposals: r.proposals, approved_kinds: w.approved || [],
        edits: w.edits || {} });
    setWork(msg.id, {
      notice: `Created: ${res.created.map((c) => c[0]).join(", ") || "none"}.`
        + (res.live ? "" : " (Demo mode — nothing was actually written.)"),
    });
  });
}

function emailNotePayload(msg) {
  const r = S.results[msg.id];
  const d = r?.dedupe || {};
  const linked = (kind) =>
    d[kind]?.action === "link_existing" && d[kind]?.match_id ? [d[kind].match_id] : [];
  const linkedNames = (kind) =>
    d[kind]?.action === "link_existing" && d[kind]?.match ? [d[kind].match] : [];
  return {
    message: msg,
    summary: r?.entity?.summary || r?.rationale || "",
    company_name: r?.entity?.company_name || "",
    contact_ids: linked("contact"),
    company_ids: linked("company"),
    fund_ids: linked("fund"),
    company_names: linkedNames("company"),
    fund_names: linkedNames("fund"),
  };
}

/* Step 1 of saving an email: fetch the exact properties the note would be
   created with, so the user can review and edit them before anything is written. */
export function previewEmailNote(msg) {
  return workCall(msg.id, "emailnote", async () => {
    const res = await post("/api/notion/save-email",
      { ...emailNotePayload(msg), preview: true });
    setWork(msg.id, { emailNote: res, emailNoteEdits: {} });
  });
}

export function setEmailNoteEdit(id, prop, value) {
  const w = workOf(id);
  setWork(id, { emailNoteEdits: { ...(w.emailNoteEdits || {}), [prop]: value } });
}

export function cancelEmailNote(id) {
  setWork(id, { emailNote: null, emailNoteEdits: {}, emailNoteEditing: {} });
}

export function toggleEmailNoteFieldEdit(id, prop) {
  const w = workOf(id);
  const editing = { ...(w.emailNoteEditing || {}) };
  editing[prop] = !editing[prop];
  setWork(id, { emailNoteEditing: editing });
}

export function saveEmailNote(msg) {
  return workCall(msg.id, "emailnote", async (w) => {
    // The previewed values (including the generated summary) are the baseline;
    // anything the user edited overrides them.
    const res = await post("/api/notion/save-email",
      { ...emailNotePayload(msg),
        edits: { ...(w.emailNote?.editable || {}), ...(w.emailNoteEdits || {}) } });
    setWork(msg.id, {
      emailNoteUrl: res.url, emailNote: null,
      notice: "Email saved to Notion as a note (Note Type: Email, marked Done)."
        + (res.live ? "" : " (Demo mode — nothing was actually written.)"),
    });
  });
}

export function saveDraft(msg) {
  return workCall(msg.id, "save", async (w) => {
    const res = await post("/api/drafts/save",
      { message_id: msg.id, body: w.draftBody });
    setWork(msg.id, {
      notice: "Draft saved to Outlook — review and send it there."
        + (res.live ? "" : " (Demo mode — no draft was actually created.)"),
    });
  });
}

export async function deleteMessage(m) {
  S.error = null; emit();
  try {
    const r = await post("/api/messages/delete", { message_id: m.id });
    S.messages = S.messages.filter((x) => x.id !== m.id);
    const next = new Set(S.selected); next.delete(m.id); S.selected = next;
    if (S.activeId === m.id) S.activeId = S.messages[0]?.id ?? null;
    S.notice = "Moved to Deleted Items — recoverable in Outlook."
      + (r.live ? "" : " (Demo mode — nothing was actually moved.)");
  } catch (e) { S.error = e.message; }
  emit();
}
