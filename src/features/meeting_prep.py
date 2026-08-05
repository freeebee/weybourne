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
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import REASONING_MODEL
from src.connectors.notion_client import NotionConnector, page_title
from src.features.dedupe import normalize_name
from src.features.web_research import research_block
from src.schemas import Attendee, CalendarEvent, MeetingPrep

INTERNAL_DOMAIN = "weybourneholdings.com"

# Weybourne's own people, across every domain the group uses. A meeting with
# only these is an internal one: there is no counterparty to research and no
# preferences to screen against, so prep works off what we have said to each
# other instead. Override with WEYBOURNE_INTERNAL_DOMAINS (comma-separated).
INTERNAL_DOMAINS = tuple(
    d.strip().lower() for d in os.environ.get(
        "WEYBOURNE_INTERNAL_DOMAINS",
        "weybourneholdings.com,weybourne.co.uk,weybournepartners.com,"
        "weybourne.com,tarenna.com,tarenna.co.uk",
    ).split(",") if d.strip()
)
# Some invitations carry a name and no address. These read as internal.
INTERNAL_NAME_TOKENS = ("weybourne", "tarenna")


def is_internal(email: str = "", name: str = "") -> bool:
    """Is this attendee one of ours?

    Matched on the email domain first — the reliable signal — and on the name
    only when there is no address to go on.
    """
    addr = (email or "").strip().lower()
    if "@" in addr:
        domain = addr.rsplit("@", 1)[1].strip(" ;,<>")
        return any(domain == d or domain.endswith("." + d) for d in INTERNAL_DOMAINS)
    if addr:
        return any(tok in addr for tok in INTERNAL_NAME_TOKENS)
    return any(tok in (name or "").lower() for tok in INTERNAL_NAME_TOKENS)

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
    # A meeting with our own people. There is nothing to research and nothing
    # to screen; the prep is built from what we have been mailing each other.
    internal: bool = False
    email_context: str = ""
    sources: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


# --------------------------------------------------------------------------- #
# Counterparty resolution
# --------------------------------------------------------------------------- #

_CUSTOMER_INFO_RE = re.compile(r"customer\s*info", re.IGNORECASE)
_BOOKING_NAME_RE = re.compile(r"^\s*name\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_BOOKING_EMAIL_RE = re.compile(r"^\s*email\s*:\s*(\S+@\S+?)\s*$", re.IGNORECASE | re.MULTILINE)


def booking_customer(body: str) -> Optional[Attendee]:
    """The real counterparty from a Calendly-style booking confirmation.

    Some invitations come through a scheduling tool: the calendar's own
    attendee list is just the shared booking mailbox (e.g. Tarenna@...), and
    the person who actually booked the meeting is typed into the event
    description instead, as a "Customer Info / Name: ... / Email: ..." block.
    Missing this reads a genuinely external meeting as internal, because the
    only address Graph exposes as an attendee is our own booking inbox.
    """
    header = _CUSTOMER_INFO_RE.search(body or "")
    if not header:
        return None
    # The block is a few lines long — Name, Email, Time Zone — well before
    # any later section (Booking Info, Custom Fields) could contribute a
    # stray "Name:"/"Email:" line of its own.
    window = body[header.end():header.end() + 400]
    name_m = _BOOKING_NAME_RE.search(window)
    email_m = _BOOKING_EMAIL_RE.search(window)
    if not (name_m or email_m):
        return None
    return Attendee(name=name_m.group(1).strip() if name_m else "",
                    email=email_m.group(1).strip().rstrip(".,;") if email_m else "")


def external_attendees(event: CalendarEvent, internal_domain: str = INTERNAL_DOMAIN) -> list:
    """Attendees who are not internal to Weybourne.

    Includes the booking-confirmation customer (see booking_customer) when
    the structured attendee list doesn't already name them — a booking-tool
    invite would otherwise look like it has no outside party at all.
    """
    out = []
    for a in event.attendees:
        if not (a.email or "") and not a.name:
            continue
        if is_internal(a.email or "", a.name or ""):
            continue
        out.append(a)
    booked = booking_customer(event.body_preview)
    if booked and not is_internal(booked.email, booked.name):
        already = any(booked.email and a.email
                      and a.email.lower() == booked.email.lower() for a in out)
        if not already:
            out.insert(0, booked)
    return out


def event_is_internal(event: CalendarEvent) -> bool:
    """A meeting with no outside attendee at all.

    An invitation with no attendee list is NOT called internal: a calendar
    entry someone typed for themselves ("GP meeting — Old Well Labs") is the
    commonest way a prep gets requested, and the name in the subject is the
    counterparty. A booking-confirmation invite is not called internal
    either, even when every structured attendee is one of ours — see
    external_attendees, which already folds the booking customer in.
    """
    return bool(event.attendees) and not external_attendees(event)


def counterparty_from_event(event: CalendarEvent) -> tuple[str, str]:
    """Return (name, email) of whoever the prep is about.

    Normally the outside party. For an internal meeting there is no outside
    party, so it returns the colleague — the prep is then built from what we
    have already said to each other rather than from research.
    """
    externals = external_attendees(event)
    if externals:
        return externals[0].name or externals[0].email, externals[0].email
    if event.attendees:
        a = event.attendees[0]
        return (a.name or a.email or "", a.email or "")
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
    notion: NotionConnector, counterparty: str, company: str, max_notes: int = 12
) -> tuple[str, list[str]]:
    """Pull any matching Funds / Companies / Contacts records, plus every
    meeting note linked to (or naming) them, as context text.

    Matching a Company/Fund/Contact record used to be where this stopped —
    the actual meeting history sitting in the Notes database was never
    looked at, so "no prior record" got reported for counterparties we had
    met a dozen times. A note counts as relevant if it's related (Attendees /
    Companies / Fund) to something matched below, OR its own title/summary
    names the counterparty/company directly — the latter catches notes whose
    relations were never filled in.
    """
    lines: list[str] = []
    sources: list[str] = []
    target_names = {normalize_name(n) for n in (counterparty, company) if n}

    def _hits(value: str) -> bool:
        v = normalize_name(value)
        return bool(v) and any(t and (t in v or v in t) for t in target_names)

    matched_contact_ids: set[str] = set()
    matched_company_ids: set[str] = set()
    matched_fund_ids: set[str] = set()

    try:
        for c in notion.list_contacts():
            if _hits(c.name) or (c.company and _hits(c.company)):
                lines.append(f"Contact: {c.name} — {c.title or 'unknown title'} "
                             f"({c.type or 'no type'}), {c.email or 'no email'}")
                sources.append(f"Notion Contacts: {c.name}")
                if c.id:
                    matched_contact_ids.add(c.id)
        for co in notion.list_companies():
            if _hits(co.name):
                lines.append(f"Company: {co.name} — {co.description or 'no description'} "
                             f"[{co.city}, {co.country}]".strip())
                sources.append(f"Notion Companies: {co.name}")
                if co.id:
                    matched_company_ids.add(co.id)
        for f in notion.list_funds():
            if _hits(f.name) or (f.company and _hits(f.company)):
                lines.append(
                    f"Fund: {f.name} — status '{f.status or 'unknown'}', "
                    f"asset class {', '.join(f.asset_class) or 'n/a'}, "
                    f"geography {', '.join(f.geographic_focus) or 'n/a'}. "
                    f"{f.strategy_description}"
                )
                sources.append(f"Notion Funds: {f.name}")
                if f.id:
                    matched_fund_ids.add(f.id)

        notes = [
            n for n in notion.list_notes()
            if matched_contact_ids & set(n.attendee_ids)
            or matched_company_ids & set(n.company_ids)
            or matched_fund_ids & set(n.fund_ids)
            or _hits(n.name) or _hits(n.excerpt)
        ]
        notes.sort(key=lambda n: n.date, reverse=True)
        if len(notes) > max_notes:
            sources.append(f"({len(notes) - max_notes} older matching note(s) omitted)")
        for n in notes[:max_notes]:
            lines.append(f"Meeting note ({n.date or 'undated'}"
                         f"{', ' + n.note_type if n.note_type else ''}): "
                         f"{n.name} — {n.excerpt or 'no summary recorded'}")
            sources.append(f"Notion Notes: {n.name}")

        # Anything else in the workspace mentioning the name — deal memos,
        # wiki pages, ad hoc docs — that live outside the three curated
        # databases and the Notes database. This is Notion's own search, not
        # a connected-sources search: it will not surface SharePoint/Outlook
        # content, only Notion pages actually shared with the integration.
        seen_ids = (matched_contact_ids | matched_company_ids | matched_fund_ids
                    | {n.id for n in notes[:max_notes] if n.id})
        query = (company or counterparty or "").strip()
        if query:
            for hit in notion.search(query, page_size=8):
                pid = hit.get("id", "")
                if not pid or pid in seen_ids:
                    continue
                title = page_title(hit)
                if not title or not _hits(title):
                    continue
                seen_ids.add(pid)
                url = hit.get("url", "")
                lines.append(f"Notion page: {title}" + (f" ({url})" if url else ""))
                sources.append(f"Notion search: {title}")
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


def format_email_history(messages: list, limit: int = 12) -> str:
    """Recent mail with one person, as prep material.

    Bodies are trimmed hard: twelve threads at full length swamps everything
    else in the prompt, and the opening of a mail carries the ask.
    """
    lines = []
    for m in messages[:limit]:
        body = " ".join((m.body or m.body_preview or "").split())[:700]
        lines.append(
            f"[{(m.received or '')[:10]}] {m.subject or '(no subject)'} "
            f"— from {m.sender_name or m.sender_email}\n{body}")
    return "\n\n".join(lines)


def build_context(
    notion: NotionConnector,
    counterparty_name: str,
    counterparty_email: str = "",
    company_name: str = "",
    event: Optional[CalendarEvent] = None,
    pdf_path: Optional[Path] = None,
    research: Optional[Callable[[str], str]] = None,
    internal: bool = False,
    emails: Optional[Callable[[str], list]] = None,
) -> PrepContext:
    """Assemble all available context for a counterparty."""
    company = company_name or company_from_email_domain(counterparty_email)
    if internal:
        company = ""      # a colleague's employer is us
    ctx = PrepContext(
        counterparty_name=counterparty_name,
        counterparty_email=counterparty_email,
        company_name=company,
        meeting_subject=event.subject if event else "",
        meeting_time=event.start if event else "",
        internal=internal,
    )

    ctx.notion_context, ctx.sources = gather_notion_context(notion, counterparty_name, company)

    # Internal meeting: the agenda is whatever is outstanding between the two
    # of you, and that lives in the mailbox rather than in a research report.
    if internal and emails is not None:
        try:
            found = emails(counterparty_email or counterparty_name)
            ctx.email_context = format_email_history(found)
            if found:
                ctx.sources.append(
                    f"Outlook: {len(found)} recent message(s) with "
                    f"{counterparty_name or counterparty_email}")
        except Exception as e:  # noqa: BLE001 - prep must not fail over its extras
            ctx.email_context = f"(could not read the mail history: {e})"

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
            if ctx.web_context:   # never log a search that returned nothing
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
        f"BACKGROUND RESEARCH\n{research_block(ctx.web_context)}\n\n"
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
