"""Build a meeting preparation brief.

Three entry points, per the brief:

1. **Upcoming meeting** — pick from the Outlook calendar; the counterparty is
   resolved from the external attendees (internal @weybourneholdings.com
   addresses are ignored).
2. **Typed name** — the user names the manager they are meeting.
3. **Attachment** — a PDF (deck, tearsheet) is uploaded and the counterparty is
   identified from its content.

Context is then gathered from whatever is available — the Notion Funds /
Companies / Contacts records and any prior notes, the PDF text, and background
research — and synthesised into a brief with diligence questions.

Web background research is delegated to a caller-supplied ``research`` callable
so this module stays free of any particular search implementation (the Streamlit
page passes one in; tests pass a stub).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import REASONING_MODEL
from src.connectors.notion_client import NotionConnector
from src.features.dedupe import normalize_name
from src.schemas import CalendarEvent, MeetingPrep

INTERNAL_DOMAIN = "weybourneholdings.com"

PREP_SCHEMA = {
    "type": "object",
    "properties": {
        "counterparty_name": {"type": "string"},
        "counterparty_title": {"type": "string"},
        "company_name": {"type": "string"},
        "prep_markdown": {
            "type": "string",
            "description": (
                "The full preparation brief in markdown. Use these sections: "
                "'## Who you are meeting', '## The firm', '## Strategy & how it makes money', "
                "'## Our history with them', '## What to probe', '## Watch-outs'."
            ),
        },
        "diligence_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "8-10 specific questions that test the real engine and the risks",
        },
    },
    "required": ["counterparty_name", "counterparty_title", "company_name",
                 "prep_markdown", "diligence_questions"],
    "additionalProperties": False,
}

PREP_SYSTEM_PROMPT = """You prepare a senior investment manager at Weybourne (a family office \
investing in funds across private and public markets) for a meeting with an external party.

Write the brief you would want 10 minutes before the call: who they are, what the firm does, \
how the strategy actually makes money in economic terms, our prior history with them, what to \
probe, and what to watch out for.

Standards:
- Do not take the manager's own marketing framing at face value; state what the strategy is \
really a bet on.
- Distinguish documented fact from the manager's assertion. If something is unverified, say so.
- Exclude table-stakes observations every manager would claim ("experienced team", "aligned \
interests") unless there is a specific, differentiated mechanism behind them.
- If our own records are thin or absent, say so plainly rather than padding.
- Diligence questions must be specific to this manager and test the real engine and risks — \
not generic questionnaire items.
- You have WebSearch and WebFetch in this session: use them to check the counterparty and \
anything our records assert but do not evidence. Never write that web verification was \
unavailable — run the search. If a search genuinely finds nothing, say what you looked for \
and that nothing came back.
- Be concise and concrete. British English."""


@dataclass
class PrepContext:
    """Everything gathered about a counterparty before synthesis."""
    counterparty_name: str = ""
    counterparty_email: str = ""
    company_name: str = ""
    meeting_subject: str = ""
    meeting_time: str = ""
    notion_context: str = ""
    document_text: str = ""
    web_context: str = ""
    sources: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


# --------------------------------------------------------------------------- #
# Counterparty resolution
# --------------------------------------------------------------------------- #

def external_attendees(event: CalendarEvent, internal_domain: str = INTERNAL_DOMAIN) -> list:
    """Attendees who are not internal to Weybourne."""
    out = []
    for a in event.attendees:
        email = (a.email or "").lower()
        if email and internal_domain in email:
            continue
        if not email and not a.name:
            continue
        out.append(a)
    return out


def counterparty_from_event(event: CalendarEvent) -> tuple[str, str]:
    """Return (name, email) of the most likely external counterparty."""
    externals = external_attendees(event)
    if externals:
        return externals[0].name or externals[0].email, externals[0].email
    # Fall back to parsing the subject, e.g. "GP meeting — Old Well Labs".
    subject = re.split(r"[—\-–:|]", event.subject)
    return (subject[-1].strip() if len(subject) > 1 else event.subject.strip()), ""


def company_from_email_domain(email: str) -> str:
    """Derive a rough company name from an email domain."""
    if "@" not in email:
        return ""
    domain = email.split("@", 1)[1].lower()
    if domain == INTERNAL_DOMAIN:
        return ""
    root = domain.split(".")[0]
    return root.replace("-", " ").title()


# --------------------------------------------------------------------------- #
# Context gathering
# --------------------------------------------------------------------------- #

def gather_notion_context(
    notion: NotionConnector, counterparty: str, company: str
) -> tuple[str, list[str]]:
    """Pull any matching Funds / Companies / Contacts records as context text."""
    lines: list[str] = []
    sources: list[str] = []
    target_names = {normalize_name(n) for n in (counterparty, company) if n}

    def _hits(value: str) -> bool:
        v = normalize_name(value)
        return bool(v) and any(t and (t in v or v in t) for t in target_names)

    try:
        for c in notion.list_contacts():
            if _hits(c.name) or (c.company and _hits(c.company)):
                lines.append(f"Contact: {c.name} — {c.title or 'unknown title'} "
                             f"({c.type or 'no type'}), {c.email or 'no email'}")
                sources.append(f"Notion Contacts: {c.name}")
        for co in notion.list_companies():
            if _hits(co.name):
                lines.append(f"Company: {co.name} — {co.description or 'no description'} "
                             f"[{co.city}, {co.country}]".strip())
                sources.append(f"Notion Companies: {co.name}")
        for f in notion.list_funds():
            if _hits(f.name) or (f.company and _hits(f.company)):
                lines.append(
                    f"Fund: {f.name} — status '{f.status or 'unknown'}', "
                    f"asset class {', '.join(f.asset_class) or 'n/a'}, "
                    f"geography {', '.join(f.geographic_focus) or 'n/a'}. "
                    f"{f.strategy_description}"
                )
                sources.append(f"Notion Funds: {f.name}")
    except Exception as e:  # noqa: BLE001 - context gathering must not break prep
        lines.append(f"(Could not read Notion: {e})")

    return ("\n".join(lines) if lines else "(no matching records found in Notion)"), sources


def extract_pdf_text(path: Path, max_pages: int = 20) -> str:
    """Plain text from a PDF's text layer (reuses the pipeline's pymupdf dep)."""
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        chunks = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            chunks.append(page.get_text())
        return "\n".join(chunks).strip()
    finally:
        doc.close()


def build_context(
    notion: NotionConnector,
    counterparty_name: str,
    counterparty_email: str = "",
    company_name: str = "",
    event: Optional[CalendarEvent] = None,
    pdf_path: Optional[Path] = None,
    research: Optional[Callable[[str], str]] = None,
) -> PrepContext:
    """Assemble all available context for a counterparty."""
    company = company_name or company_from_email_domain(counterparty_email)
    ctx = PrepContext(
        counterparty_name=counterparty_name,
        counterparty_email=counterparty_email,
        company_name=company,
        meeting_subject=event.subject if event else "",
        meeting_time=event.start if event else "",
    )

    ctx.notion_context, ctx.sources = gather_notion_context(notion, counterparty_name, company)

    if pdf_path is not None:
        try:
            ctx.document_text = extract_pdf_text(pdf_path)[:20000]
            ctx.sources.append(f"Attachment: {pdf_path.name}")
        except Exception as e:  # noqa: BLE001
            ctx.document_text = f"(could not read PDF: {e})"

    if research is not None:
        query = f"{company or counterparty_name} investment manager background"
        try:
            ctx.web_context = research(query)
            ctx.sources.append(f"Web research: {query}")
        except Exception as e:  # noqa: BLE001
            ctx.web_context = f"(research unavailable: {e})"

    return ctx


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #

def synthesize_prep(client, ctx: PrepContext) -> MeetingPrep:
    """Turn gathered context into a prep brief via a structured Claude call."""
    user = (
        f"MEETING\nSubject: {ctx.meeting_subject or '(not from a calendar entry)'}\n"
        f"Time: {ctx.meeting_time or '(unspecified)'}\n"
        f"Counterparty: {ctx.counterparty_name} <{ctx.counterparty_email}>\n"
        f"Company: {ctx.company_name or '(unknown)'}\n\n"
        f"OUR NOTION RECORDS\n{ctx.notion_context}\n\n"
        f"BACKGROUND RESEARCH\n{ctx.web_context or 'Nothing has been pre-gathered for you. You have the WebSearch and WebFetch tools in this session: check the counterparty and anything the records assert before writing.'}\n\n"
        f"ATTACHED DOCUMENT\n{ctx.document_text or '(none)'}"
    )
    kwargs = dict(
        model=REASONING_MODEL,
        max_tokens=4000,
        system=PREP_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": PREP_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    try:
        # The quick brief verifies too — a prep that only restates our own
        # records cannot tell you what has changed since we wrote them.
        response = client.messages.create(
            **kwargs, extra_allowed_tools=["WebSearch", "WebFetch"])
    except TypeError:
        # API-backend clients don't take the kwarg — same call without it.
        response = client.messages.create(**kwargs)
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    parsed = json.loads(raw)
    prep = MeetingPrep.model_validate(parsed)
    prep.meeting_subject = ctx.meeting_subject
    prep.meeting_time = ctx.meeting_time
    prep.sources = ctx.sources
    return prep
