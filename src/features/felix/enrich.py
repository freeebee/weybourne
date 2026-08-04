"""Filling the gaps the deterministic rules cannot: who someone works for,
what a fund invests in, who was in a meeting.

Every function here is evidence-first. Linked notes and attachments are read
before the web is touched, because the workspace's own record of a meeting
beats anything a search engine infers. When the web IS used, the source is
named and travels with the proposal.

Nothing here writes to Notion. Each function returns proposals that the run
records for the reviewer to approve, and relation proposals return NAMES which
the run resolves against the real scan — the model never supplies a page id.
"""
from __future__ import annotations

import json

from src.config import LIVE_MODEL
from src.features.dedupe import _name_score

# A proposed name has to be this close to an existing record before it is
# treated as that record. Below it, the name is either created (companies,
# with a confident source) or left for the reviewer — never guessed onto the
# nearest match, because a wrong relation is silent and hard to spot later.
MATCH_STRONG = 0.88
MATCH_NEAR = 0.72


def resolve_name(name: str, cards: list[dict]) -> dict:
    """Match a proposed name against scanned records.

    Returns {"match": card|None, "near": card|None, "score": float}. A strong
    match is safe to link; a near match means "probably this, but a human
    should look" and blocks creating a new record.
    """
    best, best_score = None, 0.0
    for c in cards:
        if c.get("archived"):
            continue
        score = _name_score(name or "", c.get("name") or "")
        if score > best_score:
            best, best_score = c, score
    if best is not None and best_score >= MATCH_STRONG:
        return {"match": best, "near": None, "score": round(best_score, 3)}
    if best is not None and best_score >= MATCH_NEAR:
        return {"match": None, "near": best, "score": round(best_score, 3)}
    return {"match": None, "near": None, "score": round(best_score, 3)}

# Sonnet across this module: these are judgement calls on messy evidence
# (is this the same firm, is this the right LinkedIn profile, who was actually
# in the room), where the cheap model's misreads cost more than the tokens.
ENRICH_MODEL = LIVE_MODEL

_CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "employer": {"type": "string",
                     "description": "The company they work for, exactly as it "
                                    "would be written as a company name. Empty "
                                    "if not established."},
        "title": {"type": "string", "description": "Their job title. Empty if "
                                                   "not established."},
        "description": {"type": "string",
                        "description": "One or two factual sentences on who "
                                       "they are professionally. Empty if not "
                                       "established."},
        "linkedin_url": {"type": "string",
                         "description": "Their LinkedIn profile URL, ONLY if "
                                        "you are confident it is this person"},
        "photo_url": {"type": "string",
                      "description": "Direct URL to their profile photo, only "
                                     "if you actually found an image URL. Never "
                                     "guess one."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "string",
                     "description": "What you relied on, naming the source "
                                    "(the linked note, or the site)"},
        "used_web": {"type": "boolean",
                     "description": "True if you used a web search rather than "
                                    "the supplied workspace evidence"},
    },
    "required": ["employer", "title", "description", "linkedin_url",
                 "photo_url", "confidence", "evidence", "used_web"],
    "additionalProperties": False,
}

_CONTACT_SYSTEM = """You identify a business contact so a family office's CRM \
record can be completed. You are given what the workspace already holds, \
including the text of any meeting notes they appear in.

Order of evidence:
1. The supplied workspace evidence (meeting notes, email domain) comes first. \
If a note says who someone works for, that beats anything online.
2. Only then search the web. Prefer LinkedIn, the employer's own team page, \
and reputable press.

Rules:
- Identify the RIGHT person. A name match alone is not identification: it must \
be consistent with the email domain, the meeting context, or the sector. If \
several people share the name and you cannot tell them apart, return empty \
fields with confidence "low". A wrong contact record is worse than a blank one.
- The employer is the company name as an organisation would write it, not a \
description ("Axeleo Capital", not "a French VC firm").
- Only give linkedin_url when you are confident the profile is this exact \
person. Only give photo_url when you genuinely found an image URL; never \
construct or guess one.
- confidence "high" means the identification itself is established beyond \
reasonable doubt, not that you found something plausible.
- Name your sources in evidence."""


_NO_WEB = ("\n\nFOR THIS CALL: do NOT search the web. Use only the supplied "
           "workspace evidence. If it does not establish an answer, return "
           "empty fields with confidence \"low\" — saying so is the useful "
           "answer, and the user will decide whether to spend a search on it.")


def research_contact(client, card: dict, notes_text: str = "",
                     wanted: list[str] | None = None,
                     use_web: bool = True) -> dict:
    """Identify a contact and propose the missing fields.

    ``notes_text`` is the text of meeting notes they are linked to — the
    evidence that takes priority over the web. With ``use_web`` False the
    call is confined to that evidence and no search tools are offered.
    """
    wanted = wanted or ["employer", "title", "description"]
    plain = card.get("plain", {})
    known = "; ".join(f"{k}: {str(v)[:80]}" for k, v in plain.items()
                      if v and not isinstance(v, list))
    user = (
        f"CONTACT: {card.get('name', '')}\n"
        f"Email: {card.get('email') or '(none on record)'}\n"
        f"Email domain: {card.get('domain') or '(none)'}\n"
        f"Already on the record: {known or '(nothing else)'}\n"
        f"Fields needed: {', '.join(wanted)}\n\n"
        "WORKSPACE EVIDENCE (meeting notes this contact is linked to)\n"
        f"{notes_text[:6000] or '(none — this contact appears in no notes)'}"
    )
    kwargs = ({"extra_allowed_tools": ["WebSearch", "WebFetch"]}
              if use_web else {})
    response = client.messages.create(
        model=ENRICH_MODEL, max_tokens=1200,
        system=_CONTACT_SYSTEM + ("" if use_web else _NO_WEB),
        output_config={"format": {"type": "json_schema", "schema": _CONTACT_SCHEMA}},
        messages=[{"role": "user", "content": user}],
        **kwargs,
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    return json.loads(raw)


_FUND_CO_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string",
                    "description": "The manager/GP running this fund, as the "
                                   "organisation writes its own name. Empty if "
                                   "not established."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "string",
                     "description": "What established it, naming the source"},
    },
    "required": ["company", "confidence", "evidence"],
    "additionalProperties": False,
}

_FUND_CO_SYSTEM = """You identify which management company runs a named \
investment fund, so a family office's CRM can link the fund to its manager.

Use the supplied workspace evidence (meeting notes, existing fields) first, \
then the web. The answer is the firm's own name as it writes it ("Axiom Asia \
Private Capital", not "an Asian fund-of-funds").

A fund name often contains the manager's name, but confirm it rather than \
assuming: "Growth Fund IV" tells you nothing. If you cannot establish the \
manager, return an empty company with confidence "low". Name your source."""


def research_fund_company(client, card: dict, notes_text: str = "",
                          use_web: bool = True) -> dict:
    """Identify the manager behind a fund. Returns {company, confidence,
    evidence}. With ``use_web`` False, the notes alone must settle it."""
    plain = card.get("plain", {})
    known = "; ".join(f"{k}: {str(v)[:80]}" for k, v in plain.items()
                      if v and not isinstance(v, list))
    user = (
        f"FUND: {card.get('name', '')}\n"
        f"Already on the record: {known or '(nothing else)'}\n\n"
        "WORKSPACE EVIDENCE (linked meeting notes)\n"
        f"{notes_text[:6000] or '(none)'}"
    )
    kwargs = ({"extra_allowed_tools": ["WebSearch", "WebFetch"]}
              if use_web else {})
    response = client.messages.create(
        model=ENRICH_MODEL, max_tokens=800,
        system=_FUND_CO_SYSTEM + ("" if use_web else _NO_WEB),
        output_config={"format": {"type": "json_schema", "schema": _FUND_CO_SCHEMA}},
        messages=[{"role": "user", "content": user}],
        **kwargs,
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    return json.loads(raw)


_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "attendees": {
            "type": "array", "items": {"type": "string"},
            "description": "Names of people who attended, exactly as written "
                           "in the note. Only people actually present — not "
                           "everyone mentioned in passing.",
        },
        "note_type": {"type": "string",
                      "description": "One of the supplied options, or empty if "
                                     "the note does not establish it"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "string",
                     "description": "The phrase in the note that establishes "
                                    "this, quoted"},
    },
    "required": ["attendees", "note_type", "confidence", "evidence"],
    "additionalProperties": False,
}

_NOTE_SYSTEM = """You read a meeting note from a family office's workspace and \
establish who was in the meeting and what kind of meeting it was.

Rules:
- Attendees are people who were PRESENT. A note that discusses a third party, \
quotes someone, or mentions a person who was not there must not list them. If \
the note does not say who attended, return an empty list.
- Quote names exactly as the note writes them; the caller matches them against \
the contact records itself.
- note_type must be one of the supplied options verbatim, or empty. Infer it \
from what the meeting actually was, not from the title alone.
- Everything must come from the note's own text. Never infer an attendee from \
the fact that a firm was discussed.
- Quote the phrase that establishes your answer in evidence."""


def infer_note_fields(client, card: dict, note_text: str,
                      type_options: list[str] | None = None,
                      want_attendees: bool = True,
                      want_type: bool = True) -> dict:
    """Attendees and note type, read out of the note's own text."""
    opts = ", ".join(type_options or []) or "(no options supplied)"
    wanted = [w for w, on in (("attendees", want_attendees),
                              ("note_type", want_type)) if on]
    user = (
        f"NOTE TITLE: {card.get('name', '')}\n"
        f"Fields needed: {', '.join(wanted)}\n"
        f"Allowed note_type options: {opts}\n\n"
        f"NOTE TEXT\n{note_text[:8000] or '(the note body is empty)'}"
    )
    response = client.messages.create(
        model=ENRICH_MODEL, max_tokens=1000, system=_NOTE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _NOTE_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    out = json.loads(raw)
    # The model may only choose from the live options — anything else is
    # dropped in code rather than trusted.
    if type_options and out.get("note_type") not in type_options:
        out["note_type"] = ""
    return out
