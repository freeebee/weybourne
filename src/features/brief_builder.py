"""Full pre-meeting DD briefing — the HTML deliverable.

Implements docs/meeting_prep_instructions.md for the local app: a structured
Claude call produces the section content, and Python fills the supplied brief
kit (src/features/templates/weybourne-brief-kit.html — the user's own design
system) by replacing only the content between its FILL markers. The style block
is never touched and the model never writes HTML.

Source rules from the instructions are enforced in the prompt: Teams chat is
never an admissible source, and a fact with no admissible source is dropped.
"""
from __future__ import annotations

import base64
import html
import json
import re
from datetime import date
from pathlib import Path

from src.config import REASONING_MODEL
from src.features.meeting_prep import PrepContext
from src.features.web_research import research_block

KIT_PATH = Path(__file__).resolve().parent / "templates" / "weybourne-brief-kit.html"

_QUESTION = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "src": {"type": "string", "description": "One-line source anchor, e.g. 'Deck p.12 vs Preqin 2025 median'"},
    },
    "required": ["q", "src"],
    "additionalProperties": False,
}

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "entity": {"type": "string"},
        "descriptor": {"type": "string", "description": "One-line strategy descriptor for the cover"},
        "is_manager": {"type": "boolean", "description": "False for non-manager relationships; deals are then omitted"},
        "relationship": {"type": "string", "description": "'New relationship — first meeting' or a one-liner on the existing relationship"},
        "vehicle": {"type": "string", "description": "Fund, vintage, status — empty if not applicable"},
        "meetings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "title": {"type": "string"},
                    "attendees": {"type": "string"},
                    "format": {"type": "string", "description": "e.g. 'London, in person' or 'Video call'"},
                    "summary": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["date", "title", "attendees", "format", "summary", "source"],
                "additionalProperties": False,
            },
        },
        "no_meetings_text": {
            "type": "string",
            "description": "Only when there are no qualifying meetings: plain statement + what the section is built around",
        },
        "other_mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "date": {"type": "string"},
                    "context": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["source", "date", "context", "text"],
                "additionalProperties": False,
            },
        },
        "landscape_md": {"type": "string", "description": "Sector & market landscape, markdown paragraphs/bullets"},
        "manager_bg_md": {"type": "string", "description": "Manager background, markdown"},
        "red_flags_md": {"type": "string", "description": "Red flags, markdown; state plainly where nothing was found"},
        "strategy_md": {"type": "string", "description": "Strategy section, markdown"},
        "questions_a": {"type": "array", "items": _QUESTION, "description": "Strategy & direction, 5-8"},
        "questions_b": {"type": "array", "items": _QUESTION, "description": "Manager-level & structural, 4-6"},
        "deals_omit_text": {"type": "string", "description": "Non-managers only: why the deal section is omitted"},
        "ledger": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "fund_sector": {"type": "string"},
                    "entry": {"type": "string"},
                    "cost": {"type": "string"},
                    "ownership": {"type": "string"},
                    "moic": {"type": "string"},
                    "irr": {"type": "string"},
                    "description": {"type": "string"},
                    "hot": {"type": "boolean", "description": "Shade: drives reported performance or flagged below"},
                },
                "required": ["company", "fund_sector", "entry", "cost", "ownership",
                             "moic", "irr", "description", "hot"],
                "additionalProperties": False,
            },
        },
        "deal_cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "figs": {"type": "string", "description": "e.g. '$12.0m cost · 64% · 3.4x · 41% IRR'"},
                    "business": {"type": "string"},
                    "actions": {"type": "string"},
                    "newsflow": {"type": "string"},
                    "questions": {"type": "array", "items": _QUESTION},
                    "key_flag": {"type": "string", "description": "Empty string for clean/immaterial positions"},
                },
                "required": ["name", "figs", "business", "actions", "newsflow", "questions", "key_flag"],
                "additionalProperties": False,
            },
        },
        "standouts_md": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "Notion / Outlook / Deck / External"},
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entity", "descriptor", "is_manager", "relationship", "vehicle",
                 "meetings", "no_meetings_text", "other_mentions", "landscape_md",
                 "manager_bg_md", "red_flags_md", "strategy_md", "questions_a",
                 "questions_b", "deals_omit_text", "ledger", "deal_cards",
                 "standouts_md", "sources"],
    "additionalProperties": False,
}

BRIEFING_SYSTEM_PROMPT = """You produce a pre-meeting due-diligence briefing for Weybourne, \
a single family office. Work autonomously from the supplied context; state assumptions inline \
rather than asking questions.

SOURCE RULES (absolute):
- Microsoft Teams chat is never an admissible source. If any supplied context appears to come \
from Teams, disregard it entirely — do not use, quote or mention it. If excluding it leaves a \
fact unsupported, drop the fact. If it leaves the relationship with no internal record, say so \
plainly in the meetings section.
- Admissible internal sources: Notion records, Outlook, SharePoint. Everything else is external \
research. Anchor every question with a one-line source reference.

EXTERNAL RESEARCH (mandatory — you have the WebSearch tool; USE IT before writing):
- Run real web searches on the entity and its principals. Prioritise the diff: post-deck \
developments, other vehicles, current fundraising status, personnel and leadership changes, \
ownership and governance changes, competitive landscape, and anything material the manager's \
own materials do not disclose.
- Background-check every named individual: search "[Name]" together with criticism OR \
controversy OR litigation. Report findings plainly and proportionately; where a person has no \
meaningful public record, say so explicitly — absence of information is not a clean bill of \
health.
- Watch for name collisions (same-named but unrelated firms in other geographies) and say \
which entity a finding refers to.
- For each portfolio position in a deck, look for the most recent public newsflow since entry \
(funding rounds, filings, hiring, customer wins, leadership changes, expansion or contraction \
signals) and read it lightly against the deck's narrative.
- Cite searched facts in the sources list as kind "External" with enough detail to find them \
again. Never invent a search result.
- The tools ARE available to you in this session. Never write that web verification was \
unavailable, that you could not access the internet, or that research could not be performed: \
run the searches. If a specific search genuinely returns nothing useful, say what you looked \
for and what was not found — that is a finding, not an apology for the tooling.

CLASSIFICATION:
- A fund manager gets the full briefing including deals. A non-manager relationship (a \
government body, another allocator, a service provider) gets is_manager=false, an explicit \
deals_omit_text, and empty ledger/deal_cards.

SECTION STANDARDS:
- Meetings: qualifying meetings reverse-chronologically, only those directly with or \
substantively about the entity. Always include other mentions. If there are none of either, \
say so plainly in no_meetings_text.
- Background research: complete even without a deck. Tie every landscape factor to this \
manager's strategy. Red flags stated plainly and proportionately; where nothing concerning is \
found, say so — and where a person has no public record, say that explicitly rather than \
treating absence as a clean bill of health.
- Questions: 10-14 total across the two blocks. Diff, don't extract — build from gaps between \
the deck and third-party context, not facts supporting the manager's narrative. \
Defend-your-own-numbers: cite the deck figure and the contradicting data point and ask them to \
reconcile. No manufactured-absence questions. Block A tests whether the stated edge is real, \
differentiated and repeatable at scale (sourcing, entry price, value creation, consistency, \
scaling, team, realised vs paper proof). Block B covers fundraise status, concentration, GP \
commitment, fees and carry including offsets, co-invest, governance, ownership, conflicts.
- Deals (managers only): ledger sorted by gross MoIC descending, hot=true only where a \
position materially drives reported performance or carries a flag. Cards: where the deck gives \
no detail on value creation, say so rather than inventing it; key_flag only where the deal \
warrants a deeper look, empty otherwise. Then standouts.
- Where the supplied context is thin (demo data, no deck), produce the best briefing the \
context supports and say plainly what is missing — never pad or invent.

VOICE: measured, precise, quietly confident; institutional "we"; sentence case; precise \
figures with explicit units and an "as at" date where known; plain financial English; no hype, \
no exclamation marks, no emoji. British English. Markdown fields may use short paragraphs and \
hyphen bullets only."""


INTERNAL_BRIEFING_NOTE = """THIS IS AN INTERNAL MEETING. The other person works at \
Weybourne, so there is no counterparty to assess.

- Do NOT run any web search, and do not write anything about the person's background, \
their firm, or a strategy. There is no firm and no strategy: this is a colleague.
- Build the briefing from the mail history below and from our own records. What have the \
two of you been discussing, what was promised, what is outstanding, what decision is \
waiting on whom.
- The questions should be the things worth raising with THIS colleague at THIS meeting: \
open threads, decisions needed, work you are waiting on. Not diligence questions.
- Where the mail history is thin, say so plainly and keep the briefing short. A two-line \
briefing that is true beats a page of padding."""


def synthesize_briefing(client, ctx: PrepContext) -> dict:
    """Produce the structured briefing content for the kit."""
    user = (
        f"MEETING\nSubject: {ctx.meeting_subject or '(not from a calendar entry)'}\n"
        f"Time: {ctx.meeting_time or '(unspecified)'}\n"
        + (f"Colleague: {ctx.counterparty_name} <{ctx.counterparty_email}>\n\n"
           f"{INTERNAL_BRIEFING_NOTE}\n\n"
           f"MAIL HISTORY WITH THEM\n{ctx.email_context or '(none found)'}\n\n"
           if ctx.internal else
           f"Counterparty: {ctx.counterparty_name} <{ctx.counterparty_email}>\n"
           f"Company: {ctx.company_name or '(unknown)'}\n\n")
        + f"OUR NOTION RECORDS\n{ctx.notion_context}\n\n"
        # Either a shared dossier is attached (searches done — don't repeat
        # them) or nothing is, in which case this call holds the tools and must
        # search. "(none gathered)" used to read as "the web was unavailable to
        # you", and briefings came back apologising for not verifying anything.
        + ("" if ctx.internal else
           f"BACKGROUND RESEARCH\n{research_block(ctx.web_context)}\n\n")
        + f"ATTACHED DOCUMENT (deck)\n{ctx.document_text or '(none)'}\n\n"
        + "KNOWN SOURCE LIST\n" + "\n".join(f"- {s}" for s in ctx.sources)
    )
    kwargs = dict(
        model=REASONING_MODEL,
        max_tokens=8000,
        system=BRIEFING_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": BRIEFING_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    if ctx.internal:
        # No tools at all for an internal meeting: there is nothing to look up
        # about a colleague, and handing the model a search tool is an
        # invitation to use it on a Weybourne employee's name.
        response = client.messages.create(**kwargs)
    else:
        try:
            # The CLI backend can actually run web searches during synthesis —
            # this is what fills the background-research and newsflow sections
            # with post-deck reality instead of restating the deck.
            response = client.messages.create(
                **kwargs, extra_allowed_tools=["WebSearch", "WebFetch"])
        except TypeError:
            # API-backend clients don't take the kwarg — same call without it.
            response = client.messages.create(**kwargs)
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return json.loads(raw)


# --------------------------------------------------------------------------- #
# Rendering — fill the kit's FILL regions in document order
# --------------------------------------------------------------------------- #

_FILL_RE = re.compile(r"<!-- FILL[^>]*?-->.*?<!-- /FILL -->", re.DOTALL)


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _md_to_html(text: str) -> str:
    """Minimal markdown → HTML for prose fields: paragraphs, hyphen bullets, bold."""
    out: list[str] = []
    bullets: list[str] = []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for block in re.split(r"\n\s*\n", (text or "").strip()):
        for ln in (ln.strip() for ln in block.splitlines() if ln.strip()):
            body = _esc(ln[2:].strip()) if ln.startswith("- ") else _esc(ln)
            body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
            if ln.startswith("- "):
                bullets.append(body)
            else:
                flush()
                out.append(f"<p>{body}</p>")
        flush()
    return "\n".join(out) or "<p>(nothing to report)</p>"


def _meta_row(dt: str, dd: str) -> str:
    return f"<dt>{_esc(dt)}</dt><dd>{dd}</dd>"


def _qlist(items: list) -> str:
    lis = "".join(
        f"<li>{_esc(q['q'])}<span class=\"src\">{_esc(q['src'])}</span></li>"
        for q in items
    ) or "<li>(no admissible basis for questions in the supplied context)</li>"
    return f'<ol class="qlist">{lis}</ol>'


def render_briefing(data: dict, pdf_bytes: bytes | None = None,
                    deck_name: str = "") -> str:
    """Fill the user's brief kit with the structured briefing content."""
    tpl = KIT_PATH.read_text(encoding="utf-8")
    today = date.today().isoformat()
    entity = data["entity"]

    # Non-managers: delete both deal pages, leave a single note (per the kit's
    # own instruction comment).
    if not data.get("is_manager"):
        deal_zone = re.compile(
            r"<!-- =+ 5\. DEAL SUMMARY -->.*?(?=<!-- =+ 6\. SOURCES -->)", re.DOTALL
        )
        omit = (
            '<section class="page">\n'
            '  <div class="lockup lockup--sm">Weybourne</div>\n'
            '  <hr class="rule--brass" style="margin-top:14px">\n'
            '  <p class="eyebrow">Section five</p>\n'
            "  <h2>Deals</h2>\n"
            f'  <p class="note">{_esc(data.get("deals_omit_text") or "Omitted: the relationship is not an investment manager or fund.")}</p>\n'
            f'  <div class="page__foot"><span>Deals</span><span>{_esc(entity)}</span></div>\n'
            "</section>\n\n"
        )
        tpl = deal_zone.sub(omit, tpl)

    # ---- build the FILL replacements, in document order ---- #
    fills: list[str] = []

    # 1. cover entity
    fills.append(
        '<p class="eyebrow">Pre-meeting briefing · Private &amp; confidential</p>\n'
        f'  <h1 class="display">{_esc(entity)}</h1>\n'
        f'  <p class="dek">{_esc(data["descriptor"])}</p>'
    )

    # 2. cover meta
    meta = [
        _meta_row("Status", _esc(data["relationship"])),
        _meta_row("Date", _esc(data.get("meeting_details") or "(see calendar)")),
        _meta_row("Counterparty", _esc(data.get("counterparty_line") or entity)),
    ]
    if data.get("vehicle"):
        meta.append(_meta_row("Vehicle", _esc(data["vehicle"])))
    meta.append(_meta_row(
        "Source deck",
        f'<a href="#source-pdf">{_esc(deck_name)}</a>' if pdf_bytes else "None provided",
    ))
    fills.append('<dl class="meta">' + "".join(meta) + "</dl>")

    # 3. qualifying meetings
    if data.get("meetings"):
        fills.append("".join(
            '<article class="entry">'
            '<div class="entry__head">'
            f"<h3>{_esc(m['title'])}</h3>"
            f'<span class="entry__date">{_esc(m["date"])}</span></div>'
            f'<p class="entry__meta">{_esc(m["format"])} · {_esc(m["attendees"])}</p>'
            f'<div class="prose"><p>{_esc(m["summary"])}</p>'
            f'<p class="src">{_esc(m["source"])}</p></div>'
            "</article>"
            for m in data["meetings"]
        ))
    else:
        fills.append(f'<div class="prose"><p>{_esc(data.get("no_meetings_text") or "No qualifying meetings on record.")}</p></div>')

    # 4. other mentions
    if data.get("other_mentions"):
        fills.append("".join(
            '<article class="entry">'
            '<div class="entry__head">'
            f"<h3>{_esc(mn['source'])}</h3>"
            f'<span class="entry__date">{_esc(mn["date"])}</span></div>'
            f'<p class="entry__meta">{_esc(mn["context"])}</p>'
            f'<div class="prose"><p>{_esc(mn["text"])}</p></div>'
            "</article>"
            for mn in data["other_mentions"]
        ))
    else:
        fills.append('<p class="note">No other mentions found in admissible sources.</p>')

    # 5. background research (one FILL spanning the three blocks)
    fills.append(
        "<h3>Sector &amp; market landscape</h3>\n"
        f'  <div class="prose">{_md_to_html(data["landscape_md"])}</div>\n'
        '  <hr class="rule">\n'
        "  <h3>Manager background</h3>\n"
        f'  <div class="prose">{_md_to_html(data["manager_bg_md"])}</div>\n'
        '  <hr class="rule">\n'
        "  <h3>Potential red flags</h3>\n"
        f'  <div class="prose">{_md_to_html(data["red_flags_md"])}</div>'
    )

    # 6. strategy
    fills.append(f'<div class="prose">{_md_to_html(data["strategy_md"])}</div>')

    # 7 + 8. question blocks
    fills.append(_qlist(data.get("questions_a", [])))
    fills.append(_qlist(data.get("questions_b", [])))

    if data.get("is_manager"):
        # 9. ledger
        rows = "".join(
            f'<tr{" class=\"is-flagged\"" if r["hot"] else ""}>'
            f"<td>{_esc(r['company'])}</td><td>{_esc(r['fund_sector'])}</td>"
            f'<td class="fig">{_esc(r["entry"])}</td>'
            f'<td class="num">{_esc(r["cost"])}</td><td class="num">{_esc(r["ownership"])}</td>'
            f'<td class="num">{_esc(r["moic"])}</td><td class="num">{_esc(r["irr"])}</td>'
            f'<td class="desc">{_esc(r["description"])}</td></tr>'
            for r in data.get("ledger", [])
        ) or '<tr><td colspan="8">No position data disclosed in the supplied context.</td></tr>'
        fills.append(
            '<table class="ledger">'
            f"<caption>All positions, gross of fees. As at {today}.</caption>"
            "<thead><tr>"
            '<th style="width:24mm">Company</th><th style="width:26mm">Fund · sector</th>'
            '<th style="width:17mm">Entry</th><th class="num" style="width:17mm">Cost</th>'
            '<th class="num" style="width:14mm">Own.</th><th class="num" style="width:14mm">MoIC</th>'
            '<th class="num" style="width:14mm">IRR</th><th>Business</th>'
            f"</tr></thead><tbody>{rows}</tbody></table>"
            '<p class="note">Shaded rows materially influence reported performance or carry a flag overleaf.</p>'
        )

        # 10. deal cards
        cards = ""
        for c in data.get("deal_cards", []):
            flag = (f'<div class="flag"><b>Key flag</b>{_esc(c["key_flag"])}</div>'
                    if c.get("key_flag") else "")
            cards += (
                '<article class="card">'
                '<div class="card__head">'
                f"<h3>{_esc(c['name'])}</h3>"
                f'<span class="card__figs">{_esc(c["figs"])}</span></div>'
                f'<p class="card__label">Business</p><p>{_esc(c["business"])}</p>'
                f'<p class="card__label">What the manager did</p><p>{_esc(c["actions"])}</p>'
                f'<p class="card__label">Latest newsflow</p><p>{_esc(c["newsflow"])}</p>'
                f'<p class="card__label">Questions</p>{_qlist(c.get("questions", []))}'
                f"{flag}</article>"
            )
        fills.append(cards or '<p class="note">No deal-level detail disclosed.</p>')

        # 11. standouts
        fills.append(f'<div class="prose">{_md_to_html(data.get("standouts_md", ""))}</div>')

    # 12. sources
    src_items = "".join(
        f'<li><span class="k">{_esc(s["kind"])}</span>{_esc(s["text"])}</li>'
        for s in data.get("sources", [])
    ) or "<li>No sources beyond the supplied context.</li>"
    fills.append(f'<ul class="srclist">{src_items}</ul>')

    # ---- apply, positionally ---- #
    it = iter(fills)

    def replace(_m):
        try:
            return next(it)
        except StopIteration:
            return ""

    tpl = _FILL_RE.sub(replace, tpl)

    # ---- global tokens ---- #
    tpl = (tpl
           .replace("__TITLE__", _esc(entity))
           .replace("__ENTITY__", _esc(entity))
           .replace("__DATE__", today)
           .replace("__Fund I__ · deal-by-deal", "Deal-by-deal"))

    # ---- deck embed (the PDF SWAP pattern) ---- #
    if pdf_bytes:
        tpl = (tpl
               .replace("__PDF__", base64.b64encode(pdf_bytes).decode("ascii"))
               .replace("__DECKFILE__", _esc(deck_name or "deck.pdf"))
               .replace("__Deck title__", _esc(deck_name or "Source deck")))
    else:
        tpl = re.sub(
            r'<a class="deck" id="source-pdf".*?</a>',
            '<p class="note" id="source-pdf">No source deck was provided for this briefing.</p>',
            tpl, flags=re.DOTALL,
        )

    # The kit's comments are editing instructions, not content — drop them from
    # the deliverable (this also removes the leftover PDF SWAP placeholder note).
    return re.sub(r"<!--.*?-->", "", tpl, flags=re.DOTALL)


def build_briefing(client, ctx: PrepContext, pdf_path: Path | None = None) -> tuple[dict, str]:
    """Synthesis + render in one call. Returns (structured data, html)."""
    data = synthesize_briefing(client, ctx)
    data["meeting_details"] = " · ".join(
        x for x in (ctx.meeting_subject, ctx.meeting_time) if x
    )
    if ctx.counterparty_name and ctx.counterparty_name != data.get("entity"):
        data["counterparty_line"] = ctx.counterparty_name
    pdf_bytes = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else None
    return data, render_briefing(data, pdf_bytes, pdf_path.name if pdf_path else "")
