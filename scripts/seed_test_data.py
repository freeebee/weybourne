#!/usr/bin/env python3
"""Seed the SQLite database with static sample data.

Lets you wire up and test the Streamlit dashboard before running the real
ingestion pipeline against actual PDFs, per the suggested build order.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_connection, init_db, insert_flag, insert_metrics, insert_notes, log_ingestion, upsert_manifest_entry  # noqa: E402
from src.schemas import FinancialMetric, NarrativeNote  # noqa: E402

FUNDS = ["Fund I", "Fund II", "Fund III"]
PERIODS = ["2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]

METRICS = [
    ("AUM", "USD"),
    ("IRR", "%"),
    ("Distributions", "USD"),
]


def build_sample_metrics() -> list[FinancialMetric]:
    metrics = []
    base_values = {"Fund I": 500, "Fund II": 300, "Fund III": 150}
    for fund in FUNDS:
        for i, period in enumerate(PERIODS):
            for metric_name, unit in METRICS:
                growth = 1 + 0.05 * i
                if metric_name == "IRR":
                    value = round(8 + i * 0.7, 2)
                else:
                    value = round(base_values[fund] * growth, 2)
                metrics.append(
                    FinancialMetric(
                        fund_id=fund,
                        metric_name=metric_name,
                        value=value,
                        unit=unit,
                        period=period,
                        source_doc=f"{fund.replace(' ', '_')}_{period}.pdf",
                    )
                )
    return metrics


def build_sample_notes() -> list[NarrativeNote]:
    samples = [
        ("Fund I", "2026-Q1", "leadership change", "CFO transition completed; new CFO started April 1."),
        ("Fund II", "2026-Q1", "market commentary", "Portfolio company revenue growth outpaced sector average."),
        ("Fund III", "2026-Q2", "litigation", "Minor contract dispute settled out of court, no material impact."),
        ("Fund I", "2026-Q2", "outlook", "Management expects continued distributions through year-end."),
    ]
    return [
        NarrativeNote(
            entity_id=entity,
            period=period,
            note_text=text,
            topic_tag=topic,
            source_doc=f"{entity.replace(' ', '_')}_{period}.pdf",
        )
        for entity, period, topic, text in samples
    ]


def main() -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        metrics = build_sample_metrics()
        notes = build_sample_notes()
        insert_metrics(conn, metrics, extracted_date=now)
        insert_notes(conn, notes)

        seen_docs = {m.source_doc for m in metrics} | {n.source_doc for n in notes}
        for doc in sorted(seen_docs):
            upsert_manifest_entry(conn, filename=doc, file_hash="seed", period=None, processed_date=now)
            log_ingestion(conn, now, doc, status="seeded", detail="static sample data")

        insert_flag(
            conn,
            source_doc="Fund_II_2026-Q1.pdf",
            reason="invalid_metric: value could not be parsed as a number",
            raw_content='{"fund_id": "Fund II", "metric_name": "NAV", "value": "n/a"}',
            flagged_date=now,
        )

    print(f"Seeded {len(metrics)} metrics, {len(notes)} notes, 1 flagged record.")


if __name__ == "__main__":
    main()
