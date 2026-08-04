"""Central configuration for the Weybourne Investment Connector.

Historically this module only configured the PDF-extraction pipeline. It now
also holds the settings for the connector app (Microsoft 365 / Outlook, Notion,
and the feature modules built on top of them).

Everything is env-driven with sensible defaults. Crucially, the connectors run
in a **mock/demo mode** whenever their credentials are absent, so the whole app
launches and every screen is demonstrable without any live secrets. Provide the
relevant env vars to switch a connector to live mode.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# PDF extraction pipeline (existing)
# --------------------------------------------------------------------------- #

# Where source PDFs live (the "watched folder"). New quarterly drops go here.
PDF_FOLDER = Path(os.environ.get("PDF_FOLDER", BASE_DIR / "data" / "pdfs"))

# SQLite database file backing both the pipeline and the Streamlit dashboard.
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "dashboard.db"))

# Claude models used for OCR (vision) and structured extraction.
VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-opus-4-8")
EXTRACTION_MODEL = os.environ.get("CLAUDE_EXTRACTION_MODEL", "claude-opus-4-8")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Model used by the connector feature modules (screening, drafting, meeting
# prep). Kept separate so the reasoning model can be tuned independently of the
# extraction model.
REASONING_MODEL = os.environ.get("CLAUDE_REASONING_MODEL", "claude-opus-4-8")

# Fast model for mechanical classification (inbox triage, scan flags) — a
# fraction of the latency of the reasoning model, ample for the task.
FAST_MODEL = os.environ.get("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")

# Live-meeting model (30-second reads, question sharpening): needs real
# reasoning sharpness but must land within the read cadence — Sonnet sits
# between Haiku's speed and Opus's depth and fits both constraints.
LIVE_MODEL = os.environ.get("CLAUDE_LIVE_MODEL", "claude-sonnet-5")

# Shared web-research pass (src/features/web_research.py). Gathering facts and
# citing them is not the reasoning model's work — the screen and the briefing
# do the reasoning downstream from what this returns.
RESEARCH_MODEL = os.environ.get("CLAUDE_RESEARCH_MODEL", LIVE_MODEL)

# How long a gathered dossier stays usable. Long enough that preparing the
# screen and the briefing days apart costs one set of searches; short enough
# that a fundraise or a departure does not go unnoticed.
RESEARCH_TTL_DAYS = float(os.environ.get("RESEARCH_TTL_DAYS", "14"))

# --------------------------------------------------------------------------- #
# Model backend
# --------------------------------------------------------------------------- #
# Which billing rail the AI calls run on:
#   claude_cli (default) -- the Claude Code CLI, i.e. your **Claude account**
#                           (whatever `claude login` established). No API key.
#   api                  -- anthropic.Anthropic(), billed to ANTHROPIC_API_KEY.
#
# The CLI backend needs Claude Code installed and logged in on the machine
# running the app, so it suits local use rather than unattended hosting.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "claude_cli")

CLAUDE_CLI_PATH = os.environ.get("CLAUDE_CLI_PATH", "claude")
CLAUDE_CLI_TIMEOUT = int(os.environ.get("CLAUDE_CLI_TIMEOUT", "600"))
# Empty directory the CLI runs from, so it doesn't auto-load an unrelated
# CLAUDE.md / .mcp.json / hooks into every call. See src/llm.py.
CLAUDE_CLI_SCRATCH_DIR = os.environ.get("CLAUDE_CLI_SCRATCH_DIR")

# Page render resolution for scanned pages sent to vision OCR.
PAGE_RENDER_ZOOM = float(os.environ.get("PAGE_RENDER_ZOOM", "2.0"))

# If a document's assembled markdown exceeds this many characters, split it
# into per-page-range sections and run extraction per section instead of
# a single call.
MAX_DOC_CHARS_PER_CALL = int(os.environ.get("MAX_DOC_CHARS_PER_CALL", "40000"))

# Minimum characters of text on a page before it's considered a "text" page
# rather than a scanned/image page needing OCR.
MIN_TEXT_LAYER_CHARS = int(os.environ.get("MIN_TEXT_LAYER_CHARS", "20"))

# --------------------------------------------------------------------------- #
# Microsoft 365 / Microsoft Graph (Outlook mail + calendar)
# --------------------------------------------------------------------------- #
# Live mode requires an Azure AD app registration. When these are unset the
# Graph connector serves representative sample data instead (mock mode).

MS_TENANT_ID = os.environ.get("MS_TENANT_ID")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
# The mailbox to operate on (defaults to the signed-in user in delegated flows).
MS_USER = os.environ.get("MS_USER", "Jinghan.Chen@weybourneholdings.com")
GRAPH_BASE_URL = os.environ.get("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")

# --------------------------------------------------------------------------- #
# Inbox triage scope
# --------------------------------------------------------------------------- #
# Triage only reads the **top-level Inbox** — mail already filed into a subfolder
# (research, fund managers, etc.) has been dealt with and is not re-triaged.
# Both Focused and Other are included, since cold intros often land in Other.
#
# How far back to look, as a rolling window (not calendar days). Adjustable in
# the UI for catching up after time away.
TRIAGE_LOOKBACK_DAYS = int(os.environ.get("TRIAGE_LOOKBACK_DAYS", "3"))
# Upper bound on messages fetched in one scan, so a busy period can't fan out
# into an unbounded number of model calls.
TRIAGE_MAX_MESSAGES = int(os.environ.get("TRIAGE_MAX_MESSAGES", "25"))


def graph_configured() -> bool:
    return bool(MS_TENANT_ID and MS_CLIENT_ID and MS_CLIENT_SECRET)


# --------------------------------------------------------------------------- #
# "What's new" briefing
# --------------------------------------------------------------------------- #
# The Investments shared mailbox condensed in part two of What's new.
SHARED_MAILBOX = os.environ.get("SHARED_MAILBOX", "wbinvestments@weybourne.co.uk")
# Rolling window for all three What's-new sections.
WHATS_NEW_LOOKBACK_DAYS = int(os.environ.get("WHATS_NEW_LOOKBACK_DAYS", "7"))


# --------------------------------------------------------------------------- #
# Notion
# --------------------------------------------------------------------------- #
# Live mode requires a Notion integration token and the four main database IDs.
# When NOTION_TOKEN is unset the Notion connector serves sample data (mock mode).

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
NOTION_BASE_URL = os.environ.get("NOTION_BASE_URL", "https://api.notion.com/v1")

# Main database IDs (data source IDs). Fill these in from the workspace.
NOTION_FUNDS_DB = os.environ.get("NOTION_FUNDS_DB")
NOTION_COMPANIES_DB = os.environ.get("NOTION_COMPANIES_DB")
NOTION_CONTACTS_DB = os.environ.get("NOTION_CONTACTS_DB")
NOTION_NOTES_DB = os.environ.get("NOTION_NOTES_DB")
# Optional intake DB used by the existing "To Be Intelligenced" workflow.
NOTION_INTAKE_DB = os.environ.get("NOTION_INTAKE_DB")
# FI execution monitoring dashboard — operational items surfaced in What's new.
NOTION_EXECUTION_DB = os.environ.get("NOTION_EXECUTION_DB")

# CHAO investment-preference pages. These IDs are the canonical Weybourne
# preference pages referenced by the CHAO agent; the screening feature loads
# them the same way CHAO does (General + Learnings always, plus the relevant
# strategy sleeve).
CHAO_PAGES = {
    "chao": os.environ.get("CHAO_PAGE_ID", "3218387e-c92d-80d2-8e65-d87c27419f1e"),
    "general": os.environ.get("CHAO_GENERAL_PAGE_ID", "646766a4-fa24-4220-8fe4-e31f37df8c14"),
    "learnings": os.environ.get("CHAO_LEARNINGS_PAGE_ID", "3118387e-c92d-8096-9ece-f17626b43083"),
    "private_growth": os.environ.get("CHAO_PRIVATE_PAGE_ID", "4027959f-fae4-40b8-9a76-dbf2b2ae147e"),
    "public_growth": os.environ.get("CHAO_PUBLIC_PAGE_ID", "5b8a8e33-81c8-4895-ac73-d5e31acca14a"),
    "diversifiers": os.environ.get("CHAO_DIVERSIFIERS_PAGE_ID", "6cdcde71-b2b4-498f-ad19-f13fba4dd6bb"),
}


def notion_configured() -> bool:
    return bool(NOTION_TOKEN)


def anthropic_configured() -> bool:
    return bool(ANTHROPIC_API_KEY)
