# PDF Extraction → Time-Series Dashboard

Turns a folder of mixed scanned/text PDFs (financial figures + narrative notes)
into a structured SQLite dataset and a Streamlit dashboard, reprocessing only
new/changed files on each run.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
```

Drop PDFs into `data/pdfs/` (or point `PDF_FOLDER` elsewhere).

## Try the dashboard with sample data first

Before pointing the pipeline at real documents, seed the DB with static
sample data to check the dashboard works end to end:

```bash
python scripts/seed_test_data.py
streamlit run dashboard/app.py
```

## Run the pipeline

```bash
# Small test batch first (recommended - see "cost estimation" below)
python update.py --limit 15

# Everything new/changed since the last run
python update.py

# Preview what would be processed without calling the API
python update.py --dry-run

# Provide a fallback period for docs where it can't be determined otherwise
python update.py --period 2026-Q2
```

Re-running `update.py` after adding new PDFs to the watched folder is the
entire quarterly update workflow — it diffs against the manifest table and
only OCRs/extracts new or changed files. The dashboard reads the same SQLite
file directly, so no redeploy is needed after a run (as long as the DB and
app share a host, or the DB is on shared/mounted storage).

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
Streamlit dashboard (dashboard/app.py) -- reads the DB directly
```

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
2. Otherwise, the model is asked to determine it from the document's own
   content, on a per-record basis (a single doc can describe more than one
   period).
3. Otherwise, the `--period` CLI fallback, if one was given.

Records where none of the above yields a valid period fail pydantic
validation and land in `flagged_table` rather than being written with a
guessed value.

## Testing

```bash
pytest
```

Tests cover manifest diffing/hashing, DB schema and writes, pydantic
validation rules, page triage classification, and extraction validation/
flagging logic (using a fake Claude client — no API calls in tests).

## Before running the full batch

- **Estimate cost on a sample first**: run `python update.py --limit 15` (or
  `--limit 20`) against a representative slice of the ~200+ doc folder and
  check token usage/cost before running the rest.
- **Confirm the exact metrics to extract** (AUM, IRR, distributions, etc.)
  and their expected units — the extraction prompt in `src/extraction.py`
  can be tightened once these are confirmed.
- **Review the flagged queue** (`flagged_table`, surfaced in the dashboard's
  "Ingestion log" tab) after each run rather than assuming 100% clean
  extraction.

## Hosting decision (confirm before deploying)

This pipeline handles PE fund/financial data. Before deploying the dashboard
anywhere:

- Confirm with IT/compliance whether a third-party host (Streamlit Community
  Cloud, Render, Railway) is acceptable, or whether this needs to run on
  internal infrastructure.
- If internal hosting is required: a small VPS or internal server running
  `streamlit run dashboard/app.py` plus the SQLite file is sufficient. Run
  `update.py` manually or via cron each quarter when new PDFs are dropped in.

## Environment variables

See `.env.example`. Key ones: `ANTHROPIC_API_KEY` (required),
`PDF_FOLDER` / `DB_PATH` (override default locations),
`CLAUDE_VISION_MODEL` / `CLAUDE_EXTRACTION_MODEL` (defaults to
`claude-opus-4-8`).
