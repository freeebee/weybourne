/* Tiny cross-page UI state (module scope): the triage unread count shown in
   the sidebar, set by the Triage page after a scan. */
const S = { inboxCount: null, version: 0 };
let listeners = new Set();

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function getVersion() { return S.version; }
export const ui = S;
export function setInboxCount(n) { S.inboxCount = n; S.version++; listeners.forEach((f) => f()); }
