# Weybourne assistant — project conventions

## UI: no control may throw the page back to the top

The user has corrected this same fault repeatedly (calendar pick, prep
source tabs, note-taker tabs, saved-prep open, travel/inbox tabs). Two
mechanisms cause it; both are banned:

1. **Scroll clamping on pane swaps.** Switching between panes of very
   different heights lets the browser clamp the scroll to the shorter
   page. Any tab switch or pane swap MUST go through
   `useTabScrollMemory(tab, setTab)` in `web/src/ui.jsx` — never hand a
   tab straight to setState. In-place filters (filter pills, group
   selectors, scrubbers — anything that re-scopes content without being
   a pane) clamp the same way when the filtered list shrinks: route
   those through `useScrollHold()` in ui.jsx instead
   (`onClick={() => hold(() => setFilter(x))}`). The rules are enforced
   by `web/src/scrollJumps.test.js`, which also sweeps every `<Pill>`,
   `<GroupPills>`, `<PeriodScrubber>` and `is-pill` button for the
   hold, and every `<button>` for an explicit type.
2. **Implicit submit buttons.** A `<button>` without `type` is
   `type="submit"`. Every raw `<button>` in this codebase carries
   `type="button"` (the `Button` component in ui.jsx sets it already).
   Keep it that way when adding new ones.

When a click legitimately opens content rendered elsewhere on the page
(e.g. the prep library opening a prep above the list), scroll the opened
content into view — from the click position, "nothing happened" is what
an off-screen open looks like.

## Server

`run.bat` runs uvicorn in the user's console with
`--reload --reload-dir api --reload-dir src`. Editing `api/` or `src/`
restarts it: never do so while a live recording is running or a prep job
is running (`GET /api/jobs?kind=prep`). `data/`, `tests/`, `web/`, `.env`
are safe anytime. Never kill the console.

**Recording check, in this order:**

1. Server up: `GET /api/live/recording-active` → `{"active": true|false}`.
   That IS the heartbeat (refreshed by every ~8s chunk, 150s TTL) — trust
   it over any file-based guess.
2. Server down: treat a recording as live if the newest file in EITHER
   `data/live_sessions/` OR `data/transcripts/` was touched <5 min ago.
   On 18 Aug 2026 a gate that watched only `live_sessions/` declared
   "clear" while a meeting was heartbeating through `data/transcripts/`;
   the mid-meeting reload, pytest run and verification probe that
   followed dropped that meeting's audio (MACHINE BUSY banner).

Heavy CPU work (full pytest, cold Notion index builds, verification
probes) competes with Whisper for cores even without a reload — gate it
exactly like an `api/` edit.

**A reload kills EVERY in-memory job, not just preps.** Felix's live scan
alone runs 5-10+ minutes (raw crawl of ~35k Notion pages, rate-limited);
five runs died to reloads on 18 Aug 2026. Before editing `api/` or
`src/`, check `GET /api/jobs` for ANY `status: "running"` job and wait it
out. Treat pytest runs the same way while a job is live: suspected reload
triggers include `__pycache__` writes under watched dirs and OneDrive
sync touching `src/` (two reloads that night had no edit at all — the
uvicorn console's "WatchFiles detected changes in …" line right before a
restart names the actual trigger; capture it before theorizing).

## Tests

- Backend: `.venv/Scripts/python.exe -m pytest -q` (from `weybourne/`).
- Frontend: `npx vitest run --pool=threads` (from `weybourne/web/`; the
  default pool hangs on this machine — retry once on a no-tests flake).
- No emoji in UI. Teal/navy/paper palette, mono-uppercase microlabels,
  brass for notable findings.
