# Handoff: Weybourne Investment Connector — full UI redesign

## Overview

A redesign of every screen in the Weybourne Investment Connector web app
(`web/` — React + Vite + react-router, FastAPI behind it): the app shell plus
Home, Inbox triage, Meeting prep, Track records, Live meeting, Fund data and
What's new.

The redesign changes **layout, hierarchy and information density**, not the
feature set, the routes, or the API. No endpoint, job, or store behaviour
changes. The existing `web/src/theme.css` token block stays as-is — every value
below already exists in it.

## About the design files

`Weybourne Connector.dc.html` in this bundle is a **design reference written as a
single self-contained HTML prototype**. It is not production code and should not
be copied into the app. The task is to **recreate these screens in the existing
React front-end** (`web/src/App.jsx`, `web/src/ui.jsx`, `web/src/pages/*.jsx`,
`web/src/theme.css`), keeping the current data flow, jobs polling, `liveStore`,
and component boundaries.

The prototype fakes its data with representative content drawn from
`data/inbox_snapshot.json` and `data/calendar_snapshot.json`. In the app, all of
it comes from the existing API responses.

Open the file in a browser; the left nav switches screens.

## Fidelity

**High-fidelity.** Colours, type, spacing, rules and states are final and should
be reproduced closely. All values are existing `theme.css` custom properties —
use the variables, not the hex codes.

---

## Global: app shell

Replaces the current `.shell` / `.sidebar` / `.main` in `theme.css` and the
sidebar markup in `App.jsx`.

**Grid:** `display:grid; grid-template-columns:236px minmax(0,1fr)`, min-height
100vh, canvas `--paper-050`. Body font `--sans` 15px, colour `--ink-700`.

**Sidebar** — `--ink-800`, sticky, `height:100vh`, `overflow-y:auto`,
`padding:24px 0 18px`, `display:flex; flex-direction:column; gap:28px`.

1. **Lockup** (padding 0 20px, gap 11px): `mascot`-free brand mark
   `/brand/weybourne-mark-light.png` at 24px wide, then a two-line stack —
   `WEYBOURNE` in `--serif` 13px, letter-spacing .26em, `--paper-050`; below it
   `INVESTMENT CONNECTOR` in `--mono` 9px, letter-spacing .15em, `--slate-300`
   (add `--slate-300:#93A9B4` if not present — it is in the design system).
2. **Nav**, `flex:0 0 auto`, `gap:22px` between **groups**. Each group is a
   column with `gap:1px` and a mono group label: 9.5px, letter-spacing .18em,
   colour `--slate-500` (`#4F6D7C` family), `padding:0 20px 7px`.
   - `OVERVIEW` — Home
   - `WORKFLOW` — Inbox triage (right-aligned unread count, `--mono` 11px,
     `--teal-300`), Meeting prep, Live meeting (right-aligned 6px teal dot when a
     session is running)
   - `ANALYSIS` — Track records, Fund data, What's new
   
   Nav item: `padding:9px 20px`, `--sans` 14px, `border-left:2px solid`,
   text-align left, no radius. **Inactive** — colour `--stone-300`, transparent
   background and border. **Hover** — colour `--paper-050`. **Active** —
   background `rgba(36,150,146,.13)`, border-left `--teal-500`, colour
   `--paper-050`. (The current design's rounded filled pill is gone.)
3. **Footer strip**, `margin-top:auto`, `border-top:1px solid rgba(255,255,255,.08)`,
   `padding:14px 20px 0`. Mono label `RUNNING` (9.5px/.18em/`--slate-500`), then
   one line per running job (13px; live meeting in `--teal-300` with a teal dot,
   prep in `--stone-300` with a brass dot) — i.e. the existing `LiveChip` and
   `JobsTray`, restyled and moved here. Below a second hairline, the three
   connector rows: name left in `--stone-300` 12px, state right in `--mono`
   9.5px/.1em — `DEMO` in `--slate-500`, `LIVE` in `--teal-300`. This replaces
   the status strip that currently sits on the Home page.

**Main** — `padding:44px clamp(28px,4vw,56px) 72px; max-width:1400px`.

**Page header pattern** (every screen; replaces `PageHeader` styling): flex row,
`flex-wrap:wrap`, `align-items:flex-end`, `justify-content:space-between`,
`gap:20px 40px`, `padding-bottom:20px`, `border-bottom:1px solid --paper-200`.
Left column, max-width 640px, gap 9px:
- mono eyebrow 11px, letter-spacing .18em, `--stone-500` (`--brass-500` when the
  eyebrow is a date or an edition, `--positive-600` + dot when recording)
- `h1`: `--serif`, weight **300**, 38px (42px on Home), line-height 1.12,
  letter-spacing -.02em, `--ink-800`
- one-line description, `--sans` 15px/1.5, `--stone-600`, max-width 64ch

Right side of the header holds that screen's controls/actions.

**Two-pane pattern** (triage, prep, track records, live): a **wrapping flex row**,
`gap:32px`, `align-items:flex-start` — not a fixed grid. Each pane gets
`flex:<grow> 1 <basis>; min-width:min(100%,<n>px)` so the secondary pane drops
below the primary one on narrow viewports instead of squeezing. Bases are given
per screen below.

**Buttons** (replace `ui.jsx` `Button` styles), radius 3px, `--sans` 13.5px/500:
- primary — `padding:10px 17px`, background `--teal-600`, colour `--paper-000`;
  hover `--teal-700`
- dark/secondary-action — background `--ink-700`, colour `--paper-050`; hover
  `--ink-800`
- ghost — transparent, `1px solid --paper-300`, colour `--ink-700`; hover
  border `--stone-400`, background `--paper-000`

**Inputs / selects**: `padding:8px 10px`, `1px solid --paper-300`, background
`--paper-000`, radius 3px, `--mono` 13.5px. Labelled by a mono caption above:
10px, letter-spacing .14em, `--stone-500`.

**Cards**: background `--paper-000`, `1px solid --paper-200`, radius 3px. A
2px top border in `--teal-500` marks the primary card; `--brass-500` marks a
finished/premium artefact. **No coloured left-border accent cards anywhere**; a
2px left border in `--teal-500` is used only to mark the *selected row* in a list.

**Data rows**: prefer hairline-ruled rows over cards —
`border-top:1px solid --paper-200`, `padding:14px 0`, and a closing
`border-bottom` on the last row. Hover on a clickable row: background
`--paper-000`.

**Figures**: always `--mono`, tabular. KPI value 26px `--ink-800`; label above in
mono 10px/.14em/`--stone-500`. A KPI band is a
`repeat(auto-fit,minmax(190px,1fr))` grid enclosed top and bottom by hairlines,
each cell after the first separated by `border-left:1px solid --paper-200`.

---

## Screen 1 — Home (`pages/Home.jsx`)

**Purpose:** land, see what today holds, jump into a workspace.

Header: eyebrow is the date + office (`MONDAY · 3 AUGUST 2026 · SINGAPORE`) in
`--brass-500`; h1 is a greeting at 42px; description is one sentence naming the
day's actual load. Right side: the waving mascot (88px) then two buttons —
primary "Triage the inbox", ghost "Prepare a meeting".

Body: wrapping flex row, gap `40px 56px`.

**Left — Workspaces ledger** (`flex:1 1 520px; min-width:min(100%,440px)`).
Section head row: mono `WORKSPACES` / mono count `06`, `padding-bottom:12px`.
Then six ruled rows, each a `button` (whole row clickable):
`display:grid; grid-template-columns:38px minmax(0,1fr) auto; gap:10px 18px;
padding:18px 14px 18px 0; border-top:1px solid --paper-200`, hover background
`--paper-000`.
- col 1 — mono index `01`–`06`, 11px, `--stone-400`
- col 2 — title in `--serif` 20px `--ink-800`; optional status chip beside it
  (mono 10px/.12em; `12 NEW` = `--teal-700` on `--teal-100`, radius 2px;
  `RECORDING` = `--positive-600` with a dot, no fill); below, the existing
  one-sentence description at 14px/1.5 `--stone-600`, max-width 56ch
- col 3 — the old card eyebrow, now a mono meta link: `MAIL →`, `PREPARATION →`,
  `TRANSCRIPT →`, `PERFORMANCE →`, `PORTFOLIO →`, `BRIEFING →`, 10.5px/.12em,
  `--stone-400`, `white-space:nowrap`

Order: Inbox triage, Meeting prep, Live meeting, Track records, Fund data,
What's new. **The six equal cards are gone** — this ledger replaces them.

**Right — rail** (`flex:1 1 300px; max-width:340px; min-width:280px`), two
sections, gap 30px:
- `TODAY` — a primary card (2px `--teal-500` top border, padding `17px 17px 15px`)
  for the next meeting: mono time + mono `IN 42 MIN` on one spread row, serif 19px
  title, 13.5px context line, then a text link "Open the briefing →" that routes
  to `/prep`. Below it, the remaining events as hairline rows: mono time (42px
  wide) + title 13.5px `--stone-600`.
- `RECENT` — hairline rows: 13.5px `--ink-700` headline + mono 10.5px/.08em
  `--stone-400` meta (day + detail).

Both come from `/api/calendar` and recent job history.

## Screen 2 — Inbox triage (`pages/Triage.jsx`)

**Purpose:** scan the top-level Inbox, work one message at a time through Notion,
preferences and a draft reply.

Header controls (right): `LOOK BACK` select (3/7/14 days), `MAX` select
(25/50/100), primary "Scan inbox".

**Meta bar** below the header: mono 11px/.12em `--stone-500` on the left —
`12 MESSAGES · 9 TRIAGED · 4 INVESTMENT-RELEVANT · LAST 3 DAYS`, with the
44px filing mascot beside it; on the right, "9 of 12 selected", ghost
"Select all", dark "Triage 9 selected".

**Two panes** (wrapping flex):
- **List** — `flex:1 1 320px; min-width:min(100%,300px); max-width:440px`.
  One ruled row per message, `padding:16px 14px; gap:7px`: relevance dot (7px —
  filled `--teal-500` when investment-relevant, else 1px `--stone-300` ring),
  subject 14.5px (600 weight when selected, `--stone-600` when not relevant),
  then sender/domain/attachment line 13px `--stone-600`, then mono 10px/.1em
  `--stone-400` meta — `FRI 09:43 · NEW FUND · 92% CONFIDENCE`. Selected row:
  background `--paper-000` + `border-left:2px solid --teal-500`. Non-relevant
  rows sit at `opacity:.6`. Footer line: mono `+ 7 MORE, UNTRIAGED`.
  Checkboxes from the current design are folded into row selection state; keep
  the per-message delete action as a hover-revealed control.
- **Detail** — `flex:3 1 460px; min-width:min(100%,320px)`, a card.
  - Head block (`padding:22px 24px 18px`, hairline bottom): chip
    `INVESTMENT-RELEVANT` (mono 10px on `--teal-100`) + mono
    `NEW FUND · 92%`; serif 24px subject; 13.5px `--stone-500` sender line;
    body preview 14.5px/1.6 `--stone-600`, max-width 60ch.
  - Then **three numbered steps**, each
    `display:grid; grid-template-columns:26px minmax(0,1fr); gap:14px;
    padding:20px 0; border-bottom:1px solid --paper-200`. The marker is a 22px
    circle: done/available = `--teal-100` fill with `--teal-700` mono numeral;
    current = `--teal-600` fill with `--paper-000` numeral. Replaces the stacked
    `Banner` components.
    1. `NOTION` — right-aligned mono summary (`2 TO CREATE · 1 LINKED`); then one
       hairline row per entity: mono kind (80px, `--stone-400`) + outcome
       sentence. Dedupe outcomes read as prose: linked = `--stone-600`; new =
       `--ink-700`; held for review = the reason in `--caution-600`. Ghost button
       "Create 2 approved entries".
    2. `PREFERENCE SCREEN` — mono verdict right-aligned
       (`PARTIAL FIT · PRIVATE GROWTH`, coloured `--positive-600` /
       `--caution-600` / `--critical-600`); a 14px/1.55 summary; then a
       `repeat(auto-fit,minmax(140px,1fr))` pair — `FITS` (mono label
       `--positive-600`) and `NON-FITS` (`--critical-600`), each a single
       middot-joined 13.5px line.
    3. `REPLY · DRAFT ONLY` — three option buttons (chosen one primary, others
       ghost, 12.5px); the draft in a well: `--paper-050` background, hairline
       border, `--serif` 15px/1.65 — it reads as a letter, not a textarea, and
       becomes an editable field on focus. Then dark "Save as draft in Outlook"
       plus the demo-mode caveat at 12.5px `--stone-500`.

## Screen 3 — Meeting prep (`pages/Prep.jsx`)

Header right: the three sources as buttons instead of `Tabs` — "From my
calendar" (dark = active), "By name", "From a deck" (ghost).

**Left pane** — `flex:1 1 300px; max-width:400px`. Mono `NEXT SEVEN DAYS`, then
one row per event: `grid-template-columns:58px minmax(0,1fr); padding:14px` —
mono two-line `MON / 10:00` + title 14.5px and a 12.5px context line (Teams /
attendees / room). Selected row: `--paper-000` + 2px teal left border. Below the
list, the three output checkboxes (quick brief / full DD briefing / preference
screen) at 13.5px, then the primary "Prepare".

**Right pane** — `flex:2 1 480px`.
- **Running card** (`padding:18px 20px`): mono `RUNNING · REVA` +
  `41S ELAPSED · ~30S LEFT`; the 66px crunching mascot to the left of a stage
  list — done stages `--stone-500` with a `--positive-600` check, current stage
  `--ink-800` with a `--teal-600` `›`, pending `--stone-400` with `·`; then a 2px
  progress rail (`--paper-200` track, `--teal-500` fill). This replaces the
  spinner + stage text.
- **Result card** — 2px `--brass-500` top border, `padding:26px 28px 28px`.
  Mono `LAST BRIEF · AXIOM ASIA VII` + context; a serif **26px** conclusion-style
  headline (the brief's own judgement, not the manager's name); a serif 16.5px/1.65
  lede at max-width 64ch; a three-cell metric band on hairlines
  (`repeat(auto-fit,minmax(130px,1fr))`, mono 21px values with a 12px comparison
  line); then `QUESTIONS THAT WOULD CHANGE THE VIEW` as numbered hairline rows
  (mono index + 14px question). Footer: primary "Open full briefing", ghost
  "Save to Notion".

## Screen 4 — Track records (`pages/TrackRecords.jsx`)

Header right: primary "Add a record".

**Drop zone**: `1px dashed --paper-300`, radius 3px, background `--paper-000`,
`padding:14px 18px`, holding the 58px reading mascot, mono `DROP XLSX OR PDF`,
and a 13.5px explanation.

**KPI band** (`minmax(190px,1fr)`): Records normalised 14 · Longest history 18y ·
Flagged for review 2 (value in `--caution-600`) · Last run 31 JUL.

**Two panes**:
- **Table** — `flex:2 1 460px`. Real `<table>`, `border-collapse:collapse`,
  13.5px. Head cells: mono 10px/.14em `--stone-500`, `border-bottom:1px solid
  --stone-300`; first column left-aligned, all figures right-aligned. Body rows:
  `padding:11px 12px`, `border-bottom:1px solid --paper-200`, name in
  `--ink-800`, figures in `--mono`, missing values as an em dash `--stone-400`,
  a mono `FLAGGED` tag in `--caution-600` after the name where relevant, source
  format (`XLSX`/`PDF`) in mono 11px `--stone-400`.
- **Chart** — `flex:1 1 280px; max-width:400px`. Mono
  `CUMULATIVE NET MULTIPLE`, then a card holding an inline SVG line chart:
  hairline axes in `#E4DCCB`, one grid line in `#EFE9DC`, series at 1.75px in
  `--teal-500`, `--ink-700`, and dashed `--brass-500`; mono 9px axis labels in
  `--stone-400`. Legend below a hairline: 14×2px colour swatch + 12.5px label.
  Then a 13px `--stone-500` line explaining what is held back and why.

## Screen 5 — Live meeting (`pages/Live.jsx`)

Header eyebrow: `RECORDING · 14:22 ELAPSED` in `--positive-600` with a dot; the
description names who and what the meeting is for. Right: ghost "Stop", dark
"Write the note". The who/goal inputs move into a compact form revealed before a
session starts (they are the pre-flight state of this header).

**Control strip** — a full-width `--ink-800` bar, radius 3px,
`padding:14px 18px`: the waveform canvas at 34px tall (bars `--teal-300` for
elapsed, `--ink-500`/`--slate-500` for the remainder) beside mono 11px/.1em
counters in `--slate-300` with values in `--paper-050` — `OPEN 5`,
`ANSWERED 7`, `READS 28`, `WORDS 1,840`, and `NEXT READ 12S` in `--teal-300`.
This replaces the light canvas + status line.

**Two panes**:
- **Questions** (primary) — `flex:1.4 1 440px`. Mono
  `QUESTIONS WORTH ASKING` + `5 OPEN`. Each question is a card,
  `padding:15px 17px; gap:7px`; the newest gets a 2px `--teal-500` left border
  and a mono `NEW · FROM THE LAST 30 SECONDS` label in `--teal-700`; open ones a
  mono timestamp label in `--stone-400`. Question text 15px/1.5. Answered ones
  collapse to a single hairline-topped block: mono `ANSWERED · 7` in
  `--positive-600` + a middot-joined 13.5px summary line.
- **Transcript** — `flex:1 1 300px; max-width:420px`. Card, `max-height:420px`,
  `overflow:auto`, entries `gap:14px`: mono 10px timestamp + 13.5px/1.6 text
  (`--stone-600`, latest utterance `--ink-700`); the 46px call mascot next to a
  mono `READING THE NEW SPEECH…` line in `--teal-600` while a read is in flight.
  Below the card, the Teams-caption `textarea` under a mono label
  (`padding:11px 13px`, hairline border, `resize:vertical`).

## Screen 6 — Fund data (`pages/FundData.jsx`)

Header right: `METRIC` and `PERIOD` selects (the `Tabs` component is dropped —
narrative notes and the flagged queue now live on the same page).

**KPI band**: Documents ingested 312 · Facts extracted 4,806 · Flagged for review
7 (`--caution-600`) · Last run 29 JUL.

**Chart section**: mono `NAV BY FUND · £M` + right-aligned mono
`AS AT 30 JUN 2026`; card with `padding:22px 24px` holding a full-width inline
SVG (viewBox `0 0 900 260`): hairline axes, two `#EFE9DC` grid lines, four series
at 2 / 2 / 1.75 / 1.5px in `--teal-500`, `--ink-700`, `--brass-500`,
`--slate-500`; mono 11px axis labels. Legend row below a hairline, each entry
`swatch + name · £value`.

**Below**, a `repeat(auto-fit,minmax(320px,1fr))` pair:
- `NARRATIVE NOTES` — hairline rows: fund name 14px/600 + mono period right
  aligned, then the note at 13.5px/1.55.
- `FLAGGED FOR REVIEW` — the 42px puzzled mascot beside the mono label, count in
  `--caution-600`; each row a two-column grid (name + mono reason code
  `NO PERIOD` / `UNIT` / `OCR`) with the explanation spanning both columns at
  12.5px `--stone-500`. Closing line: nothing is written with a guessed value.

## Screen 7 — What's new (`pages/WhatsNew.jsx`)

Header eyebrow `BRIEFING · WEEK TO 31 JULY 2026` in `--brass-500`; right, ghost
"Rebuild the briefing" (the current per-part refresh buttons collapse into one).

**In short** — the 96px presenting mascot beside a `--serif` **20px**/1.6
paragraph in `--ink-800`, max-width 60ch: the week in four sentences. This is the
only place the briefing gets serif body copy.

**Two columns** (`repeat(auto-fit,minmax(300px,1fr))`, gap 36px):
- `EXECUTION MOVES` / mono `FROM NOTION` — hairline rows: name 14.5px/600 plus a
  status chip (mono 9.5px/.12em, radius 2px — `IN DILIGENCE` teal-100/teal-700,
  `DECISION DUE` caution-100/caution-600, `ONE ITEM OPEN`
  positive-100/positive-600, `MONITORING` paper-100/stone-500), then 13.5px/1.55
  detail.
- `SHARED INBOX, CONDENSED` / mono `62 MESSAGES → 5 THEMES` — rows
  `grid-template-columns:32px minmax(0,1fr)`: mono count + theme name 14px +
  13px/1.5 explanation. Closing line states that portfolio news is not wired and
  is deliberately empty.

---

## Interactions & behaviour

- **Navigation** — unchanged routes (`/`, `/triage`, `/prep`, `/track-records`,
  `/live`, `/fund-data`, `/whats-new`); the prototype fakes them with local
  state. Home's ledger rows and the rail's links route to the same paths.
- **Motion** — keep it measured: 120–360ms, `--ease` for transitions, fades and
  ≤8px translations. The existing `.fade-in` on route change stays. Hover states
  deepen one colour step or reveal a `--paper-000` row background; **no lift, no
  scale, no spring**.
- **Mascot animations** — the `wb-bob`, `wb-wave`, `wb-wiggle`, `wb-float`
  keyframes already in `theme.css`; durations 2.6–4.2s, `ease-in-out`, infinite,
  and all disabled under `prefers-reduced-motion`. Placements: waving (Home
  header, 88px, `transform-origin:60% 90%`), filing (triage meta bar, 44px),
  crunching (prep running card, 66px), reading (track-records drop zone, 58px),
  call (live transcript, 46px), confused (fund-data flagged queue, 42px),
  presenting (what's-new summary, 96px). One mascot per screen, always adjacent
  to the thing it refers to — never floating in a corner. The unused states
  (`celebrating`, `sleeping`, `coffee`, `thinking`, `avatar`, `notes`,
  `working`, `presenting`) remain available for empty states: keep the current
  behaviour of showing `coffee` before a scan and `celebrating` on an empty inbox.
- **Loading** — replace centre-stage spinners with the stage list on prep and
  skeleton hairline rows elsewhere; the sidebar `RUNNING` strip is the global
  indicator.
- **Errors** — keep `ErrorNote`, restyled as a hairline block with a
  `--critical-600` mono label; no filled alert boxes.
- **Responsive** — every two-pane screen is a wrapping flex row with
  `min-width:min(100%,Npx)` floors, so the secondary pane drops below the primary
  one rather than compressing. Nested `auto-fit` grids use floors of 130–190px so
  they cannot overflow a narrow pane. Below ~900px the sidebar should collapse to
  icons or a top bar (not designed here — ask before inventing it).

## State management

No new state beyond what the pages already hold. Three notes:

- Triage needs a **selected message** id for the detail pane (currently every
  message expands inline). Keep `results`, `selected` (checkbox set) and `busy`
  as they are; add `activeId`, defaulting to the first investment-relevant
  message once triage returns.
- Prep's source tabs become buttons over the same `tab` state.
- Fund data drops `tab`; notes and flagged records render unconditionally.

## Design tokens

All already in `web/src/theme.css` — use the variables.

Ink `--ink-900 #0A2230`, `--ink-800 #0F2E42`, `--ink-700 #16415C`,
`--ink-600 #21536F`. Paper `--paper-000 #FCFAF5`, `--paper-050 #F7F3EA`,
`--paper-100 #EFE9DC`, `--paper-200 #E4DCCB`, `--paper-300 #D3C9B4`.
Stone `--stone-600 #5F5A51`, `--stone-500 #7A7468`, `--stone-400 #9A9385`,
`--stone-300 #BDB6A6`. Teal `--teal-800 #114E4A`, `--teal-700 #176B66`,
`--teal-600 #1C807A`, `--teal-500 #249692`, `--teal-300 #84C7C2`,
`--teal-100 #DBEDEB`. Brass `--brass-700 #8A6A33`, `--brass-500 #B0894E`.
Status `--positive-600 #3C6A48`, `--positive-100 #E0EBE1`,
`--caution-600 #9A6B22`, `--caution-100 #F4E8CF`, `--critical-600 #8C3A2F`,
`--critical-100 #F1DAD3`. Add if missing: `--slate-500 #4F6D7C`,
`--slate-300 #93A9B4` (sidebar micro-labels and the fourth chart series).

Type: `--serif` Newsreader (display, headings, brief prose — weight 300 at 38px+,
400 below), `--sans` Hanken Grotesk (UI, body), `--mono` IBM Plex Mono (all
figures, eyebrows, micro-labels, tabular numerals). Sizes used: 9–11px mono
labels, 12.5–15px body, serif 19/20/24/26px sub-heads, h1 38px (42px Home), mono
21/26px figures.

Spacing: 4px grid. Section gap 26–36px; pane gap 32px; row padding 14–20px;
card padding 15–28px. Radius 3px throughout (2px on chips). Shadows: effectively
none — hairlines carry the structure; keep `--shadow-sm` only for overlays.

## Assets

- `web/public/brand/weybourne-mark-light.png` — existing, unchanged.
- `web/public/mascot/mascot-*.svg` — existing, unchanged. The redesign uses
  waving, filing, crunching, reading, call, confused, presenting.
- Charts are hand-authored inline SVG (no chart library added). Keep the existing
  `LineChart` in `FundData.jsx` and restyle it to the stroke widths and colours
  above.

## Files

- `Weybourne Connector.dc.html` — the design reference for all seven screens
  (left nav switches screens; single file, no build step).
- Target files in the app: `web/src/theme.css` (shell, nav, header, row and
  button styles), `web/src/App.jsx` (sidebar structure, groups, footer strip),
  `web/src/ui.jsx` (Button, Card, Banner, Stat, PageHeader, Mascot, Tabs),
  `web/src/pages/*.jsx` (one per screen above).
