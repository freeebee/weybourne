"""Shared helpers for the Streamlit pages: clients, caching, status, styling."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.connectors.graph import GraphConnector  # noqa: E402
from src.connectors.notion_client import NotionConnector  # noqa: E402

CARD_CSS = """
<style>
  .wb-hero { padding: .5rem 0 1.25rem 0; }
  .wb-hero h1 { margin-bottom: .25rem; font-size: 2rem; }
  .wb-hero p { color: #6b7280; margin: 0; }
  div[data-testid="stVerticalBlockBorderWrapper"] h4 { margin: 0 0 .35rem 0; font-size: 1.05rem; }
  div[data-testid="stVerticalBlockBorderWrapper"] p { color: #6b7280; font-size: .88rem; margin: 0 0 .6rem 0; }
  .wb-pill { display:inline-block; padding:.12rem .5rem; border-radius:999px;
             font-size:.72rem; font-weight:600; margin-right:.3rem; }
  .wb-live { background:#dcfce7; color:#166534; }
  .wb-mock { background:#fef3c7; color:#92400e; }
  .wb-soon { background:#e5e7eb; color:#374151; }
</style>
"""


def page_setup(title: str, icon: str = "📊", layout: str = "wide") -> None:
    st.set_page_config(page_title=f"{title} · Weybourne", page_icon=icon, layout=layout)
    st.markdown(CARD_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_graph() -> GraphConnector:
    return GraphConnector()


@st.cache_resource
def get_notion() -> NotionConnector:
    return NotionConnector()


@st.cache_resource
def get_claude():
    """Anthropic client, or None when no API key is configured.

    Feature modules accept ``None`` and fall back to deterministic behaviour
    where they can, so the app stays usable without a key.
    """
    if not config.anthropic_configured():
        return None
    import anthropic

    return anthropic.Anthropic()


def connection_status() -> list[tuple[str, bool, str]]:
    """(label, is_live, detail) for each dependency, for the status strip."""
    graph = get_graph()
    from src.connectors.graph import CALENDAR_SNAPSHOT, INBOX_SNAPSHOT

    if graph.live:
        outlook_detail = "live (Microsoft Graph)"
    elif INBOX_SNAPSHOT.exists() or CALENDAR_SNAPSHOT.exists():
        outlook_detail = "snapshot (via Claude connector)"
    else:
        outlook_detail = "sample data"

    return [
        ("Outlook", graph.live or INBOX_SNAPSHOT.exists(), outlook_detail),
        ("Notion", get_notion().live, "live" if get_notion().live else "sample data"),
        ("Claude", config.anthropic_configured(), "live" if config.anthropic_configured() else "no API key"),
    ]


def render_status_strip() -> None:
    cols = st.columns(3)
    for col, (label, ok, detail) in zip(cols, connection_status()):
        col.markdown(
            f"**{label}** <span class='wb-pill {'wb-live' if ok else 'wb-mock'}'>"
            f"{'connected' if ok else 'demo'}</span><br>"
            f"<span style='color:#6b7280;font-size:.8rem'>{detail}</span>",
            unsafe_allow_html=True,
        )


def require_claude() -> object | None:
    """Return the Claude client, or render a friendly notice and return None."""
    client = get_claude()
    if client is None:
        st.info(
            "**Demo mode** — no `ANTHROPIC_API_KEY` is set, so AI analysis is unavailable. "
            "Set the key in `.env` to run real triage, screening and drafting. "
            "Deterministic fallbacks are used where they exist."
        )
    return client
