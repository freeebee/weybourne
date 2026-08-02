/* Tiny cross-page UI state (module scope): the triage unread count shown in
   the sidebar, plus the Outlook refresh job — module scope so a running
   refresh keeps polling (and its countdown keeps ticking) across page
   changes. */
const S = {
  inboxCount: null,
  refresh: { running: false, jobId: null, eta: 0, elapsed: 0, note: null },
  version: 0,
};
let listeners = new Set();

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
export const ui = S;
function emit() { S.version++; listeners.forEach((f) => f()); }
export function setInboxCount(n) { S.inboxCount = n; emit(); }

/* ---- Outlook refresh (background job; survives navigation) -------------- */

let refreshPoll = null;

function attachRefresh(jobId, eta) {
  S.refresh = { running: true, jobId, eta: eta || 480, elapsed: 0, note: null };
  emit();
  clearInterval(refreshPoll);
  refreshPoll = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = await res.json();
      S.refresh = { ...S.refresh, elapsed: j.elapsed, eta: j.eta || S.refresh.eta };
      if (j.status !== "running") {
        clearInterval(refreshPoll);
        const r = j.result || {};
        S.refresh = {
          running: false, jobId: null, eta: 0, elapsed: 0,
          note: j.status === "error"
            ? { tone: "error", text: j.error }
            : j.status === "cancelled"
              ? { tone: "warning", text: "Outlook refresh cancelled." }
              : { tone: "success",
                  text: `Outlook refreshed: ${r.inbox ?? 0} inbox, `
                    + `${r.calendar ?? 0} calendar, ${r.shared ?? 0} shared item(s).` },
        };
      }
      emit();
    } catch { /* transient — keep polling */ }
  }, 2000);
}

export async function startOutlookRefresh() {
  if (S.refresh.running) return;
  try {
    const res = await fetch("/api/jobs/outlook-refresh", { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    const job = await res.json();
    attachRefresh(job.id, job.eta);
  } catch (e) {
    S.refresh = { ...S.refresh, note: { tone: "error", text: e.message } };
    emit();
  }
}

/* Re-attach to a refresh already running server-side (page reload, other tab). */
export async function restoreOutlookRefresh() {
  if (S.refresh.running) return;
  try {
    const res = await fetch("/api/jobs?kind=outlook-refresh");
    const { jobs } = await res.json();
    const running = jobs.find((j) => j.status === "running");
    if (running) attachRefresh(running.id, running.eta);
  } catch { /* nothing to restore */ }
}
