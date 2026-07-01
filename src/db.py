"""SQLite schema + read/write helpers shared by the pipeline and the dashboard."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import DB_PATH
from src.schemas import FinancialMetric, NarrativeNote

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest_table (
    filename        TEXT PRIMARY KEY,
    file_hash       TEXT NOT NULL,
    period          TEXT,
    processed_date  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_table (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id         TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL NOT NULL,
    unit            TEXT NOT NULL,
    period          TEXT NOT NULL,
    source_doc      TEXT NOT NULL,
    extracted_date  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes_table (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   TEXT NOT NULL,
    period      TEXT NOT NULL,
    note_text   TEXT NOT NULL,
    topic_tag   TEXT NOT NULL,
    source_doc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flagged_table (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_doc    TEXT NOT NULL,
    reason        TEXT NOT NULL,
    raw_content   TEXT,
    flagged_date  TEXT NOT NULL,
    resolved      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_metric ON fact_table(metric_name, fund_id, period);
CREATE INDEX IF NOT EXISTS idx_notes_entity ON notes_table(entity_id, period);
"""


@contextmanager
def get_connection(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def get_manifest_entry(conn: sqlite3.Connection, filename: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM manifest_table WHERE filename = ?", (filename,))
    return cur.fetchone()


def upsert_manifest_entry(
    conn: sqlite3.Connection, filename: str, file_hash: str, period: str | None, processed_date: str
) -> None:
    conn.execute(
        """
        INSERT INTO manifest_table (filename, file_hash, period, processed_date)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            file_hash = excluded.file_hash,
            period = excluded.period,
            processed_date = excluded.processed_date
        """,
        (filename, file_hash, period, processed_date),
    )


def delete_facts_and_notes_for_doc(conn: sqlite3.Connection, source_doc: str) -> None:
    """Remove prior rows for a document before re-inserting (handles reprocessing a changed file)."""
    conn.execute("DELETE FROM fact_table WHERE source_doc = ?", (source_doc,))
    conn.execute("DELETE FROM notes_table WHERE source_doc = ?", (source_doc,))


def insert_metrics(conn: sqlite3.Connection, metrics: list[FinancialMetric], extracted_date: str) -> None:
    conn.executemany(
        """
        INSERT INTO fact_table (fund_id, metric_name, value, unit, period, source_doc, extracted_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (m.fund_id, m.metric_name, m.value, m.unit, m.period, m.source_doc, extracted_date)
            for m in metrics
        ],
    )


def insert_notes(conn: sqlite3.Connection, notes: list[NarrativeNote]) -> None:
    conn.executemany(
        """
        INSERT INTO notes_table (entity_id, period, note_text, topic_tag, source_doc)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(n.entity_id, n.period, n.note_text, n.topic_tag, n.source_doc) for n in notes],
    )


def insert_flag(conn: sqlite3.Connection, source_doc: str, reason: str, raw_content: str, flagged_date: str) -> None:
    conn.execute(
        "INSERT INTO flagged_table (source_doc, reason, raw_content, flagged_date) VALUES (?, ?, ?, ?)",
        (source_doc, reason, raw_content, flagged_date),
    )


def log_ingestion(conn: sqlite3.Connection, run_date: str, filename: str, status: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO ingestion_log (run_date, filename, status, detail) VALUES (?, ?, ?, ?)",
        (run_date, filename, status, detail),
    )
