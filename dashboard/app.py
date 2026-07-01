"""Streamlit dashboard reading directly from the pipeline's SQLite database.

Run with: streamlit run dashboard/app.py
Re-running update.py is enough to refresh this dashboard on next page load -
no redeploy needed as long as the DB file is on the same host as the app.
"""
import sys
from pathlib import Path

import pandas as pd
import sqlite3
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH  # noqa: E402
from src.db import init_db  # noqa: E402

st.set_page_config(page_title="Fund Data Dashboard", layout="wide")


def get_connection() -> sqlite3.Connection:
    init_db()
    return sqlite3.connect(str(DB_PATH))


def load_table(conn: sqlite3.Connection, query: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params)


conn = get_connection()

st.title("Fund Data Dashboard")

facts = load_table(conn, "SELECT * FROM fact_table")
notes = load_table(conn, "SELECT * FROM notes_table")
manifest = load_table(conn, "SELECT * FROM manifest_table")
ingestion_log = load_table(conn, "SELECT * FROM ingestion_log ORDER BY id DESC LIMIT 200")
flagged = load_table(conn, "SELECT * FROM flagged_table WHERE resolved = 0 ORDER BY id DESC")

last_updated = None
if not manifest.empty:
    last_updated = manifest["processed_date"].max()
elif not facts.empty:
    last_updated = facts["extracted_date"].max()

col1, col2, col3 = st.columns(3)
col1.metric("Last updated", last_updated or "never")
col2.metric("Documents ingested", len(manifest))
col3.metric("Flagged for review", len(flagged))

tab_metrics, tab_notes, tab_log = st.tabs(["Time-series metrics", "Narrative notes", "Ingestion log"])

with tab_metrics:
    if facts.empty:
        st.info("No financial metrics ingested yet. Run update.py to populate the database.")
    else:
        metric_names = sorted(facts["metric_name"].unique())
        selected_metric = st.selectbox("Metric", metric_names)

        metric_df = facts[facts["metric_name"] == selected_metric]
        fund_ids = sorted(metric_df["fund_id"].unique())
        selected_funds = st.multiselect("Fund / entity", fund_ids, default=fund_ids)

        filtered = metric_df[metric_df["fund_id"].isin(selected_funds)]
        if filtered.empty:
            st.warning("No data for the selected filters.")
        else:
            pivot = filtered.pivot_table(index="period", columns="fund_id", values="value", aggfunc="mean")
            pivot = pivot.sort_index()
            st.line_chart(pivot)
            st.dataframe(
                filtered[["fund_id", "period", "value", "unit", "source_doc", "extracted_date"]]
                .sort_values(["fund_id", "period"]),
                use_container_width=True,
            )

with tab_notes:
    if notes.empty:
        st.info("No narrative notes ingested yet.")
    else:
        search = st.text_input("Search note text")
        topic_options = ["(all)"] + sorted(notes["topic_tag"].unique())
        topic = st.selectbox("Topic", topic_options)
        entity_options = ["(all)"] + sorted(notes["entity_id"].unique())
        entity = st.selectbox("Entity", entity_options)

        filtered_notes = notes
        if search:
            filtered_notes = filtered_notes[filtered_notes["note_text"].str.contains(search, case=False, na=False)]
        if topic != "(all)":
            filtered_notes = filtered_notes[filtered_notes["topic_tag"] == topic]
        if entity != "(all)":
            filtered_notes = filtered_notes[filtered_notes["entity_id"] == entity]

        st.dataframe(
            filtered_notes[["entity_id", "period", "topic_tag", "note_text", "source_doc"]]
            .sort_values("period", ascending=False),
            use_container_width=True,
        )

with tab_log:
    st.subheader("Recent ingestion runs")
    if ingestion_log.empty:
        st.info("No ingestion runs logged yet.")
    else:
        st.dataframe(
            ingestion_log[["run_date", "filename", "status", "detail"]],
            use_container_width=True,
        )

    st.subheader("Flagged for manual review")
    if flagged.empty:
        st.success("No unresolved flagged extractions.")
    else:
        st.dataframe(
            flagged[["source_doc", "reason", "raw_content", "flagged_date"]],
            use_container_width=True,
        )
