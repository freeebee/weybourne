# Handoff — Weybourne Investment Connector

Repo: `c:\Users\Jinghan.Chen\OneDrive - Weybourne Holdings\Desktop\test\weybourne`
Branch: `claude/build-request-n91p2q` (up to date with `origin`, working tree clean)
Last commit: `a05a02a` — "Live meeting reads see the whole transcript, and the question queue is capped at 20"
Remote: `https://github.com/freeebee/weybourne.git`

## Who this is for
Jinghan Chen, Senior Investment Manager at Weybourne family office. This is a real internal tool
(real Notion/Outlook/Claude backends), not a demo.

## Standing constraints (do not relitigate these)
- **Weybourne Design System**: no emoji anywhere in the UI; teal/navy/paper palette; Newsreader
  serif headings, Hanken Grotesk sans body, IBM Plex Mono for labels/mono UI. Tokens live in
  `web/src/theme.css` (`--ink-800`, `--paper-050`, `--teal-700`, `var(--serif)`/`var(--sans)`/`var(--mono)`).
- British English throughout.
- **Never kill the user's server console.** `run.bat` runs uvicorn in the foreground with
  `--reload`; the user runs it themselves in their own terminal. Don't background/kill it.
- Always commit **and push** to `claude/build-request-n91p2q` after verified work.
- No double quotes inside git commit messages (heredoc quoting issue in this environment).
- No em dashes in drafted email replies.
- **Email sending is live**, not draft-only. The user explicitly authorized real sending; it's
  gated behind a confirm dialog in `Triage.jsx` ("Send now") and backed by
  `POST /api/drafts/send` in `api/main.py` + `send_reply()` in `src/connectors/graph.py`. Do not
  revert this to draft-only without the user asking.
- Run the three-tier verification before calling anything done: `pytest -q` (backend),
  `npm run build` / vitest in `web/` (frontend), Playwright in `web/e2e/` where relevant.

## Architecture quick reference
- **Backend**: FastAPI, `api/main.py`. Business logic under `src/features/*`. Connectors under
  `src/connectors/*` (Notion, Outlook/Graph, Claude CLI).
- **Frontend**: React + Vite + HashRouter, `web/src/`. Pages in `web/src/pages/`. Module-scope
  stores (`liveStore.js`, `felixStore.js`, `triageStore.js`, `uiStore.js`) hold state that
  survives navigation — this is the established idiom for anything long-running (jobs, live
  meeting sessions, poll loops).
- **LLM backend**: every model call shells out to a real `claude` CLI subprocess
  (`src/llm.py`, `ClaudeCodeClient`). This has real process-startup overhead (~10-18s measured)
  independent of model latency — relevant any time something "feels slow."
  - Concurrency is gated by semaphores in `src/llm.py`: `_cli_slot` (background jobs, env
    `CLAUDE_CLI_MAX_CONCURRENT`, default 3), and two **separate** live-meeting lanes,
    `_live_tidy_slot` / `_live_read_slot` (env `CLAUDE_CLI_LIVE_CONCURRENT`, default 1 each).
    Do not merge these two lanes back into one — that caused a real starvation bug earlier
    (tidy fires every ~8s and starved read for minutes).
- **Microsoft 365**: `_mcp_mail_action()` in `api/main.py` shells a headless `claude -p` with
  `--allowedTools` as the real mechanism behind drafts/deletes/forwards/sends — independent of
  Graph API creds, which remain unconfigured (`_graph.live` is False; mock mode).

## Features that exist and are built (not just planned)
- **Meeting prep** (`src/features/meeting_prep.py`, `Prep.jsx`): briefing + preference screen,
  booking-tool-aware internal/external detection (Calendly-style "Customer Info" body parsing),
  deals ledger table, downloadable HTML kit (`src/features/templates/weybourne-brief-kit.html`
  via `brief_builder.py`).
- **Live note-taker** (`Live.jsx`, `liveStore.js`, `src/features/transcription.py`): live
  transcription + tidy + recap + live-questions, tabbed panel (Questions / Meeting prep / Deck),
  system-audio-only capture (screen share stops immediately after the picker consent), question
  queue capped at 20 with a dynamic per-read budget, reads now see the **full** transcript (not
  a truncated tail — this was the root cause of a quality-degradation bug on longer calls).
- **Inbox triage** (`Triage.jsx`, `triageStore.js`, `src/features/inbox_triage.py`,
  `src/features/draft_reply.py`): draft generation, preference-screen-driven reply option
  appending (not replacing), real send.
- **Fix-it Felix** (`src/features/felix/` — `detect.py`, `adjudicate.py`, `execute.py`,
  `undo.py`, `run.py`, `store.py`, `models.py`, `enrich.py`, `research.py`; `FixItFelix.jsx`,
  `felixStore.js`; pixel-office game scene in `PixelOffice.jsx`): autonomous Notion clean-up
  agent (dedupe, missing-info fills, dangling relations, formatting) with dry-run/live modes,
  full change log + undo, presented as an incremental-game tab. **This is already built**, not
  a pending plan — despite a stale plan file surfacing it as future work (see below).
- **Contact Creator** (`ContactCard.jsx`): business-card capture → vision extraction → prefilled
  editable Notion contact with dedupe + best-effort LinkedIn photo match. Already built.

## Stale artifact to be aware of
There is a plan file at
`C:\Users\Jinghan.Chen\.claude\plans\read-this-workspace-and-lexical-llama.md` describing
Fix-it Felix + Contact Creator as if they were still to be built from scratch. **They already
exist** (see above) — confirmed by directory listing (`src/features/felix/*.py` all present,
`ContactCard.jsx` present) on 2026-08-05. Don't rebuild them; if picking up loose threads there,
diff the plan's spec against the actual code first to find any genuinely-missing piece (e.g. the
plan mentions specific endpoints/config knobs — worth spot-checking `api/main.py` for
`/api/felix/*` routes and `.env.example` for `FELIX_*` vars if the user references something
that isn't there).

## Recent bug fixes worth knowing the root cause of (in case symptoms resurface)
- **Live question/recap quality dropping on long calls**: `TranscriptBuffer.recent_text(max_chars=6000)`
  was silently truncating to ~10 minutes of speech. Fixed by switching to `buffer.full_text()`.
- **7-minute gaps between live reads**: self-inflicted — tidy and read shared one semaphore.
  Fixed by splitting into `_live_tidy_slot` / `_live_read_slot` (see above). If gaps come back,
  check `CLAUDE_CLI_LIVE_CONCURRENT` and confirm the two lanes are still separate.
- **Meeting prep misclassifying external meetings as internal**: booking-tool invites (Calendly
  etc.) put the real counterparty in the event body, not the structured attendee list. Fixed via
  `booking_customer()` in `meeting_prep.py`, which parses "Customer Info / Name: / Email:" blocks.
- **Preference screen missing context the briefing found**: `start_prep_job` was passing the raw
  (usually empty) `company` form field into research/dedupe instead of the derived
  `ctx.company_name`. Fixed in `api/main.py` (three call sites) and `/api/prep`.
- **Prep timeout under concurrent load**: no global cap on concurrent Claude CLI subprocesses.
  Fixed with `_cli_slot` / `CLAUDE_CLI_MAX_CONCURRENT`.

## Verification state as of this handoff
- `pytest -q`: 388 passed, 2 known-flaky (`tests/test_llm.py::TestErrorsAreLoud::test_real_runner_maps_missing_binary_to_unavailable`
  and `TestBackendSelection::test_preflight_reports_a_missing_cli`) — both pass cleanly in
  isolation every time they've been checked; they only flake under full-suite system load. Not
  caused by recent changes. If they show up again, rerun just those two before worrying.
- `npm run build` (in `web/`): clean, 4.47s, no errors (last verified 2026-08-05, after the
  `liveStore.js` question-cap change that hadn't been re-verified post-edit — now confirmed).
- Playwright/vitest: last run clean; a couple of transient vitest worker-timeout failures
  occurred earlier in the session and resolved on immediate retry (system-load related, not code).

## No pending tasks
The most recent explicit user request (re-query full transcript every read, cap open questions
at 20 with a dynamic budget) is fully implemented, tested, committed, and pushed. Nothing is
mid-flight. Wait for the user's next request.
