/* The dashboard payload, held at module scope so leaving the page does not
   throw it away.

   /api/inbox-signal takes a couple of seconds: it reads every stored letter,
   matches ~50 reporting managers against ~9,000 Notion funds, and runs eight
   cross-sectional readings over the result. Holding it in component state
   meant that cost was paid again every time the page was mounted — clicking
   away to Triage and back showed the full loading state for a payload that had
   not changed, which reads as the app doing work rather than as the app having
   forgotten.

   So: the first visit fetches, and later visits render what is already held
   while revalidating behind the scenes. The revalidation matters as much as
   the cache — the store is written by background jobs and by anything else
   touching data/inbox_signal, so a session-long cache with no refresh would go
   quietly stale. Nothing is persisted beyond the session; this is a cache, not
   a record. */
import { get } from "../../api.js";

const S = {
  data: null,
  error: null,
  loadedAt: 0,      // ms epoch of the last successful fetch
  loading: false,   // a fetch with nothing to show behind it
  revalidating: false,
  version: 0,
};

let listeners = new Set();
let inFlight = null;

function emit() { S.version++; listeners.forEach((f) => f()); }

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getSnapshot() { return S.version; }
export function state() { return S; }

/* One fetch at a time. Two components mounting together, or a revalidation
   landing on top of an in-flight first load, must not become two requests for
   a payload this expensive. */
function fetchOnce() {
  if (inFlight) return inFlight;
  inFlight = get("/api/inbox-signal")
    .then((data) => {
      S.data = data;
      S.error = null;
      S.loadedAt = Date.now();
      return data;
    })
    .catch((e) => {
      // A failed revalidation keeps the last good payload on screen: stale
      // figures the reader can see beat an error page replacing them.
      S.error = e.message;
      if (!S.data) throw e;
      return S.data;
    })
    .finally(() => {
      inFlight = null;
      S.loading = false;
      S.revalidating = false;
      emit();
    });
  return inFlight;
}

/* Called on mount. Fetches if there is nothing to show; otherwise shows what
   is held and refreshes it behind the page. */
export function ensure() {
  if (S.data) {
    S.revalidating = true;
    emit();
  } else {
    S.loading = true;
    emit();
  }
  return fetchOnce().catch(() => {});
}

/* After a job that changed the stored letters. Same request, but the caller is
   waiting on it rather than the page quietly catching up. */
export function refresh() {
  S.revalidating = true;
  emit();
  return fetchOnce().catch(() => {});
}

export function clear() {
  S.data = null;
  S.error = null;
  S.loadedAt = 0;
  emit();
}
