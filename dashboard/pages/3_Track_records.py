"""Track record analysis — normalise Excel/PDF track records to a common format."""
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import page_setup, require_claude, run_ai  # noqa: E402

from src.features.track_record import (  # noqa: E402
    analyse_file,
    best_worst_period,
    cumulative_return_pct,
    max_drawdown_pct,
    to_fact_rows,
)

page_setup("Track records", icon="📈")
st.title("📈 Track record analysis")
st.caption(
    "Private and public market track records, however the manager formatted them, "
    "normalised into one common shape."
)

client = require_claude()

upload = st.file_uploader(
    "Track record file", type=["xlsx", "xlsm", "xls", "csv", "tsv", "pdf"]
)

if upload is not None and st.button("Analyse", type="primary", disabled=client is None):
    tmp = Path(tempfile.gettempdir()) / upload.name
    tmp.write_bytes(upload.getbuffer())
    with st.spinner("Reading and normalising…"):
        try:
            st.session_state.record = run_ai(analyse_file, client, tmp)
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not analyse the file: {e}")

record = st.session_state.get("record")
if record is None:
    st.info("Upload a manager's track record to begin.")
    st.stop()

st.divider()
st.subheader(record.fund or record.manager or upload.name)
meta = " · ".join(
    x for x in (
        record.manager, record.vehicle_type.title() + " markets" if record.vehicle_type != "unknown" else "",
        record.strategy, record.currency, f"inception {record.inception}" if record.inception else "",
    ) if x
)
st.caption(meta)

if record.caveats:
    st.warning("**Caveats**\n\n" + "\n".join(f"- {c}" for c in record.caveats))

# -- What the manager reports vs what we derive ----------------------------- #
col1, col2 = st.columns(2)
with col1:
    st.markdown("#### Reported by the manager")
    reported = [s for s in record.summary_stats if s.basis == "reported"]
    if reported:
        st.dataframe(
            pd.DataFrame([{"Statistic": s.name, "Value": s.value, "Unit": s.unit}
                          for s in reported]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("None stated.")

with col2:
    st.markdown("#### Derived from the series")
    cumulative = cumulative_return_pct(record.periods)
    drawdown = max_drawdown_pct(record.periods)
    best, worst = best_worst_period(record.periods)
    derived = []
    if cumulative is not None:
        derived.append({"Statistic": "Cumulative return", "Value": cumulative, "Unit": "%"})
    if drawdown is not None:
        derived.append({"Statistic": "Max drawdown", "Value": drawdown, "Unit": "%"})
    if best:
        derived.append({"Statistic": f"Best period ({best.period})",
                        "Value": best.return_pct, "Unit": "%"})
    if worst:
        derived.append({"Statistic": f"Worst period ({worst.period})",
                        "Value": worst.return_pct, "Unit": "%"})
    if derived:
        st.dataframe(pd.DataFrame(derived), use_container_width=True, hide_index=True)
        st.caption("Computed from the periodic series, not taken from the document.")
    else:
        st.caption("No periodic returns to compute from.")

# -- The series ------------------------------------------------------------- #
st.markdown("#### Periodic series")
if record.periods:
    df = pd.DataFrame([p.model_dump() for p in record.periods])
    df = df.dropna(axis=1, how="all")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if "return_pct" in df and df["return_pct"].notna().any():
        chart = df[["period", "return_pct"]].dropna().set_index("period")
        st.bar_chart(chart)
    if "nav" in df and df["nav"].notna().any():
        st.line_chart(df[["period", "nav"]].dropna().set_index("period"))
else:
    st.caption("No periodic data extracted.")

with st.expander("Normalised record (JSON)"):
    st.json(record.model_dump())

st.download_button(
    "Download normalised record (JSON)",
    record.model_dump_json(indent=2),
    file_name=f"track-record-{(record.fund or 'record').replace(' ', '-').lower()}.json",
)

if st.checkbox("Show rows as they would land in the fund database"):
    rows = to_fact_rows(record)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"{len(rows)} rows for `fact_table`.")
