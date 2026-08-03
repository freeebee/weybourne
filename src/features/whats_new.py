"""What's new — the weekly catch-up briefing, in three parts.

1. **Team** — Notion activity over the window: investment side (meetings taken,
   key insights from the notes) and operational side (FI execution monitoring
   dashboard additions / completions).
2. **Inbox** — what people are saying: the Investments shared mailbox
   condensed into themes and notables.
3. **Portfolio** — news across portfolio positions. Placeholder until the
   position list exists; see ``portfolio_whats_new``.
"""
from __future__ import annotations

import json

from src.config import REASONING_MODEL, SHARED_MAILBOX, WHATS_NEW_LOOKBACK_DAYS

TEAM_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string",
                     "description": "Two or three sentences on the week — what happened "
                                    "and what it means, not a table of contents"},
        "operational_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "movement": {"type": "string", "enum": ["new", "completed", "in progress"]},
                    "detail": {"type": "string"},
                },
                "required": ["item", "movement", "detail"],
                "additionalProperties": False,
            },
        },
        "key_insights": {
            "type": "array",
            "items": {"type": "string"},
            "description": "4-7 substantive cross-meeting insights on the investments "
                           "side: patterns, shifts in view, where conviction moved and "
                           "why, capacity/pricing signals. Each MUST open with the key "
                           "point in markdown bold — '**Asia venture pricing is "
                           "resetting.** ' — followed by two or three full sentences of "
                           "substance with figures and names kept. Synthesis, not a "
                           "restatement.",
        },
        "meeting_highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Meeting / note title"},
                    "date": {"type": "string"},
                    "highlight": {"type": "string",
                                  "description": "Why this one is interesting: the claim, "
                                                 "figure, or judgement that stood out and "
                                                 "what it implies. Three to five full "
                                                 "sentences with the specifics kept."},
                },
                "required": ["title", "date", "highlight"],
                "additionalProperties": False,
            },
            "description": "The MOST INTERESTING meetings of the week, chosen not listed "
                           "— a striking figure, a contrarian view, a capacity signal, a "
                           "relationship development. Skip routine catch-ups.",
        },
    },
    "required": ["headline", "operational_updates", "key_insights",
                 "meeting_highlights"],
    "additionalProperties": False,
}

TEAM_SYSTEM_PROMPT = """You prepare the weekly "what's going on in the team" digest for \
Weybourne's Financial Investments team. The reader missed the week entirely — this brief \
must genuinely catch them up, not gesture at what happened. Err towards MORE substance: \
every figure, name, fund term, date and geography in the source material that matters \
should survive into the digest.

From the supplied Notion activity, produce:
- headline: two or three sentences that say what actually happened this week and what it \
means for the pipeline — not a list of section names.
- operational_updates: from the execution dashboard items, classify each as new, completed \
or in progress. Keep detail to one line.
- key_insights: step back from the individual meetings and synthesise what the week says on \
the investments side — recurring themes across managers, where the team's conviction moved, \
capacity or pricing signals, anything that changes how the pipeline should be read. Open \
each with the key point in **markdown bold** (a short, declarative claim), then two or \
three full sentences of substance grounded in the specifics. These must add something the \
meeting highlights don't already say.
- meeting_highlights: choose the genuinely interesting meetings — a striking figure, a \
contrarian claim, a capacity opening, a relationship development — and for each write three \
to five sentences: what was discussed, the notable specifics, and why it matters to us. \
Skip routine internal catch-ups and administrative notes; choosing well is the point.

Voice: measured, precise, plain financial English, sentence case, no hype, no emoji. \
British English. Never invent an item not present in the input."""


INBOX_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string",
                     "description": "One sentence on what the market is telling us this week"},
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "insight": {"type": "string",
                                "description": "The market signal, stated as a finding"},
                    "detail": {"type": "string",
                               "description": "The substance: figures, terms, names, timing"},
                    "source": {"type": "string",
                               "description": "Who said it — sender/firm and subject"},
                    "action_needed": {"type": "string",
                                      "description": "Only for time-limited opportunities; empty otherwise"},
                },
                "required": ["insight", "detail", "source", "action_needed"],
                "additionalProperties": False,
            },
        },
        "excluded_count": {"type": "integer",
                           "description": "How many messages were reporting/ops noise and ignored"},
    },
    "required": ["headline", "insights", "excluded_count"],
    "additionalProperties": False,
}

INBOX_SYSTEM_PROMPT = """You extract INVESTMENT MARKET INSIGHT from the Weybourne \
Investments shared mailbox. The reader wants what the market is saying, not what the \
back office is doing.

INCLUDE (this is the whole point): capacity openings and closings, fundraise launches and \
their terms, pricing and fee movements, managers' market views and positioning, deal flow \
and co-investment offers, performance signals with figures, personnel moves at managers, \
anything a market participant said that changes how an opportunity should be read.

EXCLUDE entirely — do not summarise, count them only in excluded_count: reporting and \
letters (quarterly letters received, statements, valuation packs), operational and admin \
traffic (chasers, filing confirmations, subscription paperwork, approvals), event \
logistics and invitations with no market content, compliance notices, IT and vendor mail.

Each insight is a finding, not a message summary: state the signal, give the substance \
with figures and names kept, attribute the source. Flag action_needed only for genuinely \
time-limited opportunities, with the deadline. Voice: measured, plain, sentence case, no \
emoji. British English. Never invent content not in the messages."""


def team_whats_new(client, notion, days: int = WHATS_NEW_LOOKBACK_DAYS) -> dict:
    """Part one: Notion activity condensed into investment + operational updates."""
    notes = notion.list_recent_notes(days=days)
    execution = notion.list_execution_items(days=days)

    notes_text = "\n\n".join(
        f"[{n['date']}] {n['title']} ({n['note_type']})"
        + (f" — attendees: {n['attendees']}" if n.get("attendees") else "")
        + (f"\n{n['excerpt']}" if n.get("excerpt") else "")
        for n in notes
    ) or "(no meeting notes in the window)"
    exec_text = "\n".join(
        f"[{i['updated']}] {i['title']} — status: {i['status']}"
        + (f" — {i['detail']}" if i.get("detail") else "")
        for i in execution
    ) or "(no execution dashboard activity in the window)"

    user = (
        f"Window: the last {days} days.\n\n"
        f"MEETING NOTES (Notion Notes database)\n{notes_text}\n\n"
        f"EXECUTION DASHBOARD (FI execution monitoring)\n{exec_text}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=4500,
        system=TEAM_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": TEAM_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    out = json.loads(raw)
    out["_sources"] = {"notes": len(notes), "execution": len(execution)}
    return out


def inbox_whats_new(client, graph, days: int = WHATS_NEW_LOOKBACK_DAYS) -> dict:
    """Part two: the shared inbox condensed into themes."""
    messages = graph.list_shared_inbox(days=days)
    msg_text = "\n\n".join(
        f"[{m.received}] From {m.sender_name} <{m.sender_email}>\n"
        f"Subject: {m.subject}\n{(m.body or m.body_preview)[:1200]}"
        for m in messages
    ) or "(no messages in the window)"

    user = (
        f"Shared mailbox: {SHARED_MAILBOX}. Window: the last {days} days, "
        f"{len(messages)} message(s).\n\n{msg_text}"
    )
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=2000,
        system=INBOX_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": INBOX_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    out = json.loads(raw)
    out["_sources"] = {"messages": len(messages)}
    return out


def portfolio_whats_new() -> None:
    """Part three: news across portfolio positions.

    Placeholder by design: the position list does not exist in the system yet.
    When it does, the shape is: load positions → run a news search per position
    (needs a search backend — deliberately unwired, same as meeting prep's
    research hook) → have Claude rank materiality and produce
    {position, headline, why_it_matters, source, date} items.
    Returns None so the page renders the placeholder state.
    """
    return None
