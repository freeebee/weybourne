"""Ingestion pipeline: manifest diff -> triage -> OCR -> extraction -> SQLite write.

Run via update.py. Designed to be safe to re-run: only new/changed files
(per the manifest) are processed, and reprocessing a changed file replaces
its prior fact/note rows rather than duplicating them.
"""
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config import PDF_FOLDER
from src.db import (
    delete_facts_and_notes_for_doc,
    get_connection,
    init_db,
    insert_flag,
    insert_metrics,
    insert_notes,
    log_ingestion,
    upsert_manifest_entry,
)
from src.extraction import extract_document
from src.llm import get_client
from src.manifest import diff_against_manifest, hash_file, scan_pdfs
from src.ocr import assemble_document_markdown
from src.triage import triage_pages

FILENAME_PERIOD_RE = re.compile(r"(\d{4})[-_]?[qQ]([1-4])")


def period_from_filename(filename: str) -> str | None:
    match = FILENAME_PERIOD_RE.search(filename)
    if not match:
        return None
    return f"{match.group(1)}-Q{match.group(2)}"


@dataclass
class RunSummary:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    metrics_written: int = 0
    notes_written: int = 0
    flags_written: int = 0


def process_file(
    conn: sqlite3.Connection,
    client,
    path: Path,
    file_hash: str,
    default_period: str | None,
) -> tuple[int, int, int]:
    """Process a single PDF end to end; returns (metrics, notes, flags) written."""
    period = period_from_filename(path.name) or default_period
    pages = triage_pages(path)
    markdown = assemble_document_markdown(client, path, pages)
    outcome = extract_document(client, markdown, source_doc=path.name, fallback_period=period)

    now = datetime.now(timezone.utc).isoformat()
    delete_facts_and_notes_for_doc(conn, path.name)
    insert_metrics(conn, outcome.metrics, extracted_date=now)
    insert_notes(conn, outcome.notes)
    for reason, raw in outcome.flagged:
        insert_flag(conn, source_doc=path.name, reason=reason, raw_content=raw, flagged_date=now)
    upsert_manifest_entry(conn, filename=path.name, file_hash=file_hash, period=period, processed_date=now)

    return len(outcome.metrics), len(outcome.notes), len(outcome.flagged)


def run(
    folder: Path = PDF_FOLDER,
    default_period: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> RunSummary:
    init_db()
    summary = RunSummary()
    client = get_client()
    if client is None:
        raise RuntimeError(
            "No model backend available. Run `claude login` for the Claude account "
            "backend, or set LLM_BACKEND=api with an ANTHROPIC_API_KEY."
        )
    run_date = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        files = scan_pdfs(folder)
        diff = diff_against_manifest(conn, files)
        summary.skipped = [p.name for p in diff.unchanged_files]

        to_process = diff.to_process
        if limit is not None:
            to_process = to_process[:limit]

        if dry_run:
            summary.processed = [p.name for p in to_process]
            return summary

        for path in to_process:
            file_hash = hash_file(path)
            try:
                n_metrics, n_notes, n_flags = process_file(conn, client, path, file_hash, default_period)
                summary.processed.append(path.name)
                summary.metrics_written += n_metrics
                summary.notes_written += n_notes
                summary.flags_written += n_flags
                log_ingestion(conn, run_date, path.name, status="processed",
                               detail=f"{n_metrics} metrics, {n_notes} notes, {n_flags} flagged")
            except Exception as e:  # noqa: BLE001 - one bad doc shouldn't kill the batch
                summary.failed.append((path.name, str(e)))
                log_ingestion(conn, run_date, path.name, status="failed", detail=str(e))

    return summary
