"""Meeting prep — from a calendar entry, a typed name, or an attached deck."""
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import get_graph, get_notion, page_setup, require_claude  # noqa: E402

from src.features.meeting_prep import (  # noqa: E402
    build_context,
    counterparty_from_event,
    synthesize_prep,
)

page_setup("Meeting prep", icon="🗂️")
st.title("🗂️ Meeting prep")
st.caption("Who you're meeting, what they do, our history with them, and what to probe.")

graph = get_graph()
notion = get_notion()
client = require_claude()

tab_cal, tab_name, tab_doc = st.tabs(
    ["From my calendar", "By manager name", "From an attachment"]
)

selection = {}

with tab_cal:
    events = graph.upcoming_events(days=21)
    if not events:
        st.info("No upcoming meetings found.")
    else:
        labels = [f"{e.start[:16].replace('T', ' ')} — {e.subject}" for e in events]
        idx = st.selectbox("Upcoming meetings", range(len(events)),
                           format_func=lambda i: labels[i])
        event = events[idx]
        name, email = counterparty_from_event(event)
        st.caption(f"Counterparty detected: **{name}**" + (f" ({email})" if email else ""))
        if st.button("Prepare me", type="primary", key="prep-cal"):
            selection = {"name": name, "email": email, "event": event}

with tab_name:
    typed_name = st.text_input("Manager or firm name", placeholder="e.g. Old Well Labs")
    typed_company = st.text_input("Company (optional)")
    if st.button("Prepare me", type="primary", key="prep-name", disabled=not typed_name):
        selection = {"name": typed_name, "company": typed_company}

with tab_doc:
    upload = st.file_uploader("Attach a deck or tearsheet (PDF)", type=["pdf"])
    doc_name = st.text_input("Counterparty name (optional — helps matching)",
                             key="doc-name")
    if st.button("Prepare me", type="primary", key="prep-doc", disabled=upload is None):
        tmp = Path(tempfile.gettempdir()) / upload.name
        tmp.write_bytes(upload.getbuffer())
        selection = {"name": doc_name or upload.name.rsplit(".", 1)[0], "pdf": tmp}

if selection:
    if client is None:
        st.warning("An `ANTHROPIC_API_KEY` is required to write the brief.")
        st.stop()

    def research(query: str) -> str:
        """Background research hook.

        Left unwired deliberately: the app has no search backend of its own, and
        inventing one would risk fabricated background. Wire a search API here,
        or run the prep through Claude (which has web search) instead.
        """
        return ""

    with st.spinner("Gathering context…"):
        ctx = build_context(
            notion,
            counterparty_name=selection["name"],
            counterparty_email=selection.get("email", ""),
            company_name=selection.get("company", ""),
            event=selection.get("event"),
            pdf_path=selection.get("pdf"),
            research=research,
        )
    with st.spinner("Writing the brief…"):
        prep = synthesize_prep(client, ctx)

    st.divider()
    st.subheader(prep.counterparty_name or selection["name"])
    if prep.counterparty_title or prep.company_name:
        st.caption(" · ".join(x for x in (prep.counterparty_title, prep.company_name) if x))

    st.markdown(prep.prep_markdown)

    if prep.diligence_questions:
        st.markdown("### Questions to ask")
        for q in prep.diligence_questions:
            st.markdown(f"- {q}")

    if prep.sources:
        with st.expander("Sources used"):
            st.markdown("\n".join(f"- {s}" for s in prep.sources))

    st.download_button(
        "Download brief (markdown)",
        f"# Meeting prep — {prep.counterparty_name}\n\n{prep.prep_markdown}\n\n"
        "## Questions to ask\n" + "\n".join(f"- {q}" for q in prep.diligence_questions),
        file_name=f"meeting-prep-{prep.counterparty_name or 'brief'}.md",
    )
