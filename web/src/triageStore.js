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
  activeId: null,
  scanBusy: false,
  job: null,            // {id, done, total, current, elapsed, eta}
  error: null, notice: null,
  version: 0,
};

let listeners = new Set();
let pollTimer = null;

function emit() { S.version++; listeners.forEach((f) => f()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
export function set(patch) { Object.assign(S, patch); emit(); }

export async function scan() {
  S.scanBusy = true; S.error = null; S.results = {}; S.flags = {};
  S.notice = null; S.activeId = null; S.job = null; emit();
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

export async function startTriage() {
  if (!S.selected.size || S.job) return;
  S.error = null; emit();
  try {
    const res = await fetch("/api/jobs/triage", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: S.messages.filter((m) => S.selected.has(m.id)) }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    const job = await res.json();
    S.job = { id: job.id, done: 0, total: S.selected.size, current: "", elapsed: 0, eta: job.eta };
    emit();
    poll(job.id);
  } catch (e) { S.error = e.message; emit(); }
}

function poll(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const [summary, partial] = await Promise.all([
        get(`/api/jobs/${jobId}`),
        get(`/api/jobs/${jobId}/partial`),
      ]);
      Object.entries(partial.partial).forEach(([id, r]) => {
        if (!S.results[id]) {
          S.results = { ...S.results, [id]: r };
          if (r.is_investment && !Object.values(S.results)
              .some((x) => x !== r && x.is_investment)) {
            S.activeId = id;   // jump to the first investment-relevant hit
          }
        }
      });
      S.job = { id: jobId, done: partial.done, total: partial.total,
                current: partial.current, elapsed: summary.elapsed, eta: summary.eta };
      emit();
      if (summary.status !== "running") {
        clearInterval(pollTimer);
        if (summary.status === "error") S.error = summary.error;
        S.job = null;
        emit();
      }
    } catch {
      // transient — keep polling
    }
  }, 1500);
}

/* Re-attach after a reload: pick up a running triage job if one exists. */
export async function restore() {
  if (S.job || S.messages) return;
  try {
    const { jobs } = await get("/api/jobs?kind=triage");
    const running = jobs.find((j) => j.status === "running");
    if (running) {
      S.job = { id: running.id, done: running.done || 0, total: running.total || 0,
                current: running.current || "", elapsed: running.elapsed, eta: running.eta };
      emit();
      poll(running.id);
    }
  } catch { /* nothing to restore */ }
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
