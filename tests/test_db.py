from src.db import (
    delete_facts_and_notes_for_doc,
    get_connection,
    get_manifest_entry,
    init_db,
    insert_flag,
    insert_metrics,
    insert_notes,
    log_ingestion,
    upsert_manifest_entry,
)
from src.schemas import FinancialMetric, NarrativeNote


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert {"fact_table", "notes_table", "manifest_table", "flagged_table", "ingestion_log"} <= tables


def test_manifest_upsert_and_get(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        upsert_manifest_entry(conn, "doc.pdf", "hash1", "2026-Q1", "2026-01-01T00:00:00")
        entry = get_manifest_entry(conn, "doc.pdf")
        assert entry["file_hash"] == "hash1"

        # Reprocessing updates the existing row rather than creating a duplicate.
        upsert_manifest_entry(conn, "doc.pdf", "hash2", "2026-Q2", "2026-04-01T00:00:00")
        entry = get_manifest_entry(conn, "doc.pdf")
        assert entry["file_hash"] == "hash2"
        assert entry["period"] == "2026-Q2"

        count = conn.execute("SELECT COUNT(*) c FROM manifest_table").fetchone()["c"]
        assert count == 1


def test_insert_and_delete_facts_and_notes(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    metric = FinancialMetric(
        fund_id="Fund I", metric_name="AUM", value=100.0, unit="USD",
        period="2026-Q1", source_doc="doc.pdf",
    )
    note = NarrativeNote(
        entity_id="Fund I", period="2026-Q1", note_text="hello",
        topic_tag="outlook", source_doc="doc.pdf",
    )

    with get_connection(db_path) as conn:
        insert_metrics(conn, [metric], extracted_date="2026-01-01T00:00:00")
        insert_notes(conn, [note])

        assert conn.execute("SELECT COUNT(*) c FROM fact_table").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM notes_table").fetchone()["c"] == 1

        delete_facts_and_notes_for_doc(conn, "doc.pdf")

        assert conn.execute("SELECT COUNT(*) c FROM fact_table").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM notes_table").fetchone()["c"] == 0


def test_insert_flag_and_log_ingestion(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        insert_flag(conn, "doc.pdf", "invalid_json", "{bad", "2026-01-01T00:00:00")
        log_ingestion(conn, "2026-01-01T00:00:00", "doc.pdf", "failed", "invalid_json")

        flags = conn.execute("SELECT * FROM flagged_table").fetchall()
        logs = conn.execute("SELECT * FROM ingestion_log").fetchall()

    assert len(flags) == 1
    assert flags[0]["reason"] == "invalid_json"
    assert len(logs) == 1
    assert logs[0]["status"] == "failed"
