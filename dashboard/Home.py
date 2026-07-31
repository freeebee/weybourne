"""Weybourne Investment Connector — home.

A hub of buttons, one per capability. Run with:

    streamlit run dashboard/Home.py

Every screen works without credentials (sample data); connect Notion, Outlook
and an Anthropic key to run it for real. See README for the access model.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import page_setup, render_status_strip  # noqa: E402

page_setup("Home", icon="🧭")

st.markdown(
    """
    <div class="wb-hero">
      <h1>Weybourne Investment Connector</h1>
      <p>Outlook and Notion, joined up — inbox triage, meeting prep, track records and live meetings.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

render_status_strip()
st.divider()

FEATURES = [
    {
        "page": "pages/1_Inbox_triage.py",
        "icon": "📥",
        "title": "Inbox triage",
        "blurb": "Scan the inbox for investment-relevant mail, check it against Notion for "
                 "duplicates, screen it against our preferences and draft a reply.",
        "label": "Open inbox triage",
        "state": "ready",
    },
    {
        "page": "pages/2_Meeting_prep.py",
        "icon": "🗂️",
        "title": "Meeting prep",
        "blurb": "Pick an upcoming meeting, type a manager's name or attach a deck — get a "
                 "full brief on who you're meeting and what to probe.",
        "label": "Prepare for a meeting",
        "state": "ready",
    },
    {
        "page": "pages/3_Track_records.py",
        "icon": "📈",
        "title": "Track record analysis",
        "blurb": "Turn a manager's Excel or PDF track record into one common format — "
                 "private and public markets alike — then compare and chart it.",
        "label": "Analyse a track record",
        "state": "ready",
    },
    {
        "page": "pages/4_Live_meeting.py",
        "icon": "🎙️",
        "title": "Live meeting",
        "blurb": "Follow a meeting transcript as it happens and get the questions worth "
                 "asking next, tracked so nothing is repeated or missed.",
        "label": "Start a live meeting",
        "state": "preview",
    },
    {
        "page": "pages/5_Fund_data.py",
        "icon": "📊",
        "title": "Fund data",
        "blurb": "The time-series dashboard over everything ingested from quarterly "
                 "reports and statements.",
        "label": "Open fund data",
        "state": "ready",
    },
]

_PILL = {
    "ready": "",
    "preview": "<span class='wb-pill wb-soon'>preview</span>",
}

cols = st.columns(3, gap="medium")
for i, feature in enumerate(FEATURES):
    with cols[i % 3]:
        with st.container(border=True):
            st.markdown(
                f"#### {feature['icon']} {feature['title']} {_PILL[feature['state']]}",
                unsafe_allow_html=True,
            )
            st.markdown(f"<p>{feature['blurb']}</p>", unsafe_allow_html=True)
            st.page_link(feature["page"], label=feature["label"], icon=feature["icon"])

st.divider()
with st.expander("How this connects to Outlook and Notion"):
    st.markdown(
        """
**Notion** connects directly with an internal integration token — set `NOTION_TOKEN`
and the four database IDs in `.env`, and share the databases with the integration.
No admin approval needed.

**Outlook** has two routes:

1. **Via Claude's Microsoft 365 connector** (today) — Claude fetches your real mail and
   calendar and writes `data/inbox_snapshot.json` / `data/calendar_snapshot.json`, which
   this app reads. Run `python scripts/refresh_outlook_snapshot.py --help` for the format.
2. **Directly via Microsoft Graph** (later) — needs an Entra ID app registration
   (`MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`), which usually requires IT to
   consent to the mail/calendar scopes. Only needed for the app to reach Outlook on its
   own, unattended.

Nothing is ever sent or written without you confirming it: replies are created as
**drafts** in Outlook, and Notion pages are created only after you approve them.
        """
    )
