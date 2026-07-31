# Weybourne Investment Connector

Outlook and Notion, joined up. A Streamlit app whose home page is a set of
buttons, each opening one capability:

| | Feature | What it does |
|---|---|---|
| 📥 | **Inbox triage** | Flags investment-relevant mail, checks it against Notion for duplicates, screens it against our investment preferences, and drafts a reply |
| 🗂️ | **Meeting prep** | Turns a calendar entry, a manager's name, or an attached deck into a briefing on who you're meeting and what to probe |
| 📈 | **Track records** | Normalises a manager's Excel/PDF track record into one common format — private and public markets alike |
| 🎙️ | **Live meeting** *(preview)* | Follows a meeting transcript and suggests the questions worth asking next |
| 📊 | **Fund data** | The time-series dashboard over everything ingested by the PDF pipeline |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
claude login                  # runs the AI on your Claude account (no API key)
streamlit run dashboard/Home.py
```

**It runs with no credentials at all.** Every connector falls back to
representative sample data, so you can click through all five screens
immediately. Add credentials to make each one real.

The AI runs on **your Claude account** by default via the Claude Code CLI — see
[Claude](#claude--needed-for-any-ai-analysis) below. Copy `.env.example` to `.env`
when you're ready to connect Notion and Outlook.

## Connecting things up

There are three independent connections, and you can enable them one at a time.

### Claude — needed for any AI analysis

**By default this runs on your Claude account, not an API key.** The app calls the
Claude Code CLI, which uses whatever `claude login` established:

```bash
claude login        # once, in a terminal
```

That's the whole setup — no `ANTHROPIC_API_KEY` required. Verify with the status
strip on the home page, which should read *Claude account · connected*.

To use an Anthropic API account instead, set `LLM_BACKEND=api` and
`ANTHROPIC_API_KEY` in `.env`.

Two things worth knowing about the Claude-account route:

- **It needs Claude Code installed and logged in on the machine running the app**,
  so it suits running locally rather than an unattended hosted deployment.
- **The cost is your usage limit, not dollars.** Each call carries a few seconds of
  CLI startup, and inbox triage deliberately makes one call per message so each is
  reasoned about in isolation — so triaging a full inbox is noticeably slower and
  uses more of your limit than a single batched call would. If limits become a
  problem, batching triage is the first lever to pull.

The two backends are separate billing rails and the app never silently switches
between them: if you're not logged in, or you hit your usage limit, it says so and
stops rather than quietly falling back to an API key.

### Notion — self-serve, no admin needed

1. Create an internal integration at <https://www.notion.so/profile/integrations>
2. Share the **Funds**, **Companies**, **Contacts** and **Notes** databases with it
3. Put the token and the four database IDs in `.env`

The app then reads your real databases for duplicate checking and creates pages
in them (only after you approve each one).

### Outlook — two routes

**Route 1 — via Claude's Microsoft 365 connector (no Entra registration).**
Claude reads your mail and calendar through its own connector and writes:

```
data/inbox_snapshot.json
data/calendar_snapshot.json
```

which the app picks up automatically. Run
`python scripts/refresh_outlook_snapshot.py --format` to see the expected shape,
`--sample` to write example files, or `--validate` to check existing ones.

**Route 2 — directly via Microsoft Graph (needs Entra).** For the standalone app
to reach Outlook on its own, unattended, register an app in Entra ID (Azure AD)
with `Mail.Read`, `Mail.ReadWrite` and `Calendars.Read`, and set `MS_TENANT_ID` /
`MS_CLIENT_ID` / `MS_CLIENT_SECRET`. Those scopes normally require tenant-admin
consent, so this is usually an IT request. An **Azure subscription is not
required** — that is only relevant if you later host the app on Azure.

`GraphConnector` presents the same interface in all three modes, so switching is
a matter of environment variables; no code changes.

## Safety model

Nothing leaves the app without you approving it:

- Replies are created as **drafts** in Outlook. Nothing is ever sent.
- Notion pages are created only after you tick them in the UI. Entities that
  merely *resemble* an existing record are held back for review rather than
  written.
- Connectors expose reads and draft creation only.

## How duplicate checking works

Following the workspace's Property Guidebook:

- **Contacts** — Email is the unique key. An exact email match is a definite
  duplicate; a matching *name* alone never is, since two people can share a name.
- **Companies** — an exact web-domain match is a duplicate, otherwise names are
  compared after normalisation.
- **Funds** — names are normalised (legal suffixes dropped, roman numerals
  converted) before comparison, and a differing vintage number rules out a
  duplicate: *Fund VII* is not *Fund VI*.

Matches above 90% are treated as duplicates, 72–90% are surfaced for review, and
anything below that is treated as new.

## Preference screening

The screening step mirrors the workspace's CHAO agent: it loads the *General
preferences* and *Learnings* pages plus the relevant strategy sleeve page
(Private Growth, Public Growth or Diversifiers) and judges fit against them,
separating genuine fits from non-fits and listing the questions that would most
change the conclusion. The non-fits are what the pass-reply drafts are built on,
so a decline cites a real reason rather than a platitude.

---

# PDF extraction pipeline

The connector app sits on top of an existing pipeline that turns a folder of
mixed scanned/text PDFs into a structured SQLite dataset, reprocessing only
new/changed files on each run.

## Run the pipeline

```bash
python update.py --limit 15      # small test batch first (see cost note below)
python update.py                 # everything new/changed since the last run
python update.py --dry-run       # preview without calling the API
python update.py --period 2026-Q2  # fallback period for undated docs
```

Re-running `update.py` after adding new PDFs to `data/pdfs/` is the entire
quarterly update workflow — it diffs against the manifest table and only
OCRs/extracts new or changed files. The dashboard reads the same SQLite file, so
no redeploy is needed after a run.

To try the dashboard with static sample data first:

```bash
python scripts/seed_test_data.py
streamlit run dashboard/Home.py
```

## Architecture

```
data/pdfs/*.pdf
      |
      v
manifest diff (src/manifest.py)  -- hash + compare against manifest_table
      |
      v
page triage (src/triage.py)      -- pymupdf: text layer vs. scanned page
      |
      v
vision OCR (src/ocr.py)          -- Claude vision, scanned pages only -> markdown
      |
      v
structured extraction (src/extraction.py)
      -- Claude structured outputs (JSON schema) + pydantic validation
      -- invalid records are flagged for review, never silently dropped
      |
      v
SQLite (src/db.py): fact_table, notes_table, manifest_table,
                     flagged_table, ingestion_log
      |
      v
Streamlit (dashboard/) -- reads the DB directly
```

### Connector layer

```
src/llm.py          model backend: Claude Code CLI (your Claude account) or the API
src/connectors/     graph.py (Outlook), notion_client.py (Notion)
src/features/       inbox_triage, dedupe, notion_sync, preferences,
                    draft_reply, meeting_prep, track_record, transcription
dashboard/          Home.py + pages/, one page per feature
```

Every model call goes through one shape — `client.messages.create(...)` — so
`src/llm.py` can swap the backend without any feature module changing. The CLI
backend translates that call into
`claude -p --output-format json --json-schema <schema>`, which gives the same
schema-validated output the API's structured outputs provide.

### Data model

- `fact_table(fund_id, metric_name, value, unit, period, source_doc, extracted_date)`
- `notes_table(entity_id, period, note_text, topic_tag, source_doc)`
- `manifest_table(filename, file_hash, period, processed_date)`
- `flagged_table(source_doc, reason, raw_content, flagged_date, resolved)` — records
  that failed pydantic validation, for manual review instead of silent drops
- `ingestion_log(run_date, filename, status, detail)` — what was processed, when

### Period determination

`period` (e.g. `2026-Q1`) is resolved in this order:
1. Parsed from the filename if it contains a `YYYY-Qn`-shaped pattern.
2. Otherwise, the model determines it from the document's own content, per record.
3. Otherwise, the `--period` CLI fallback.

Records where none of the above yields a valid period fail validation and land in
`flagged_table` rather than being written with a guessed value.

## Testing

```bash
pytest
```

Tests cover manifest diffing/hashing, DB schema and writes, pydantic validation,
page triage, extraction flagging, dedupe matching, calendar free-slot logic,
snapshot parsing, and every feature module — using a fake Claude client, so **no
API calls are made in tests**.

## Before running the full batch

- **Estimate cost on a sample first**: run `python update.py --limit 15` against a
  representative slice and check token usage before running the rest.
- **Confirm the exact metrics to extract** (AUM, IRR, distributions, etc.) — the
  extraction prompt in `src/extraction.py` can be tightened once confirmed.
- **Review the flagged queue** after each run rather than assuming clean extraction.

## Hosting

This handles PE fund/financial data and mailbox contents. Before deploying
anywhere, confirm with IT/compliance whether a third-party host (Streamlit
Community Cloud, Render, Railway) is acceptable or whether it needs to run on
internal infrastructure. A small internal VPS running
`streamlit run dashboard/Home.py` plus the SQLite file is sufficient.

## Known gaps

- **Live meeting** is a preview: audio capture and automatic transcription are not
  wired up (they need a local microphone, so this must be run locally rather than
  in a hosted container). Everything downstream of the transcript works — paste or
  stream text in and the question generation and ledger operate normally.
- **Meeting prep** has a `research` hook for web background that is deliberately
  left unwired; the app has no search backend of its own and inventing one would
  risk fabricated background. Wire a search API there, or run the prep through
  Claude, which has web search.
- The track-record output format is a first cut (`SCHEMA_VERSION = "1.0"`) and is
  expected to be refined once real files have been run through it.
- **OCR on the Claude-account backend is clunkier than on the API.** The CLI can't
  take an inline image, so page images are written to temp files for Claude to
  read. It works, but if you run the PDF pipeline at volume, `LLM_BACKEND=api`
  is the better route for that particular job.
