"""One web-research pass per counterparty, shared by everything that needs it.

The preference screen and the briefing are two readings of the same firm. They
were researching independently — the briefing inline during synthesis, the
screen not at all — so preparing both meant paying for the same searches twice,
and preparing them an hour apart meant paying again.

Research is gathered once into a dossier, written to ``data/research/``, and
handed to whichever consumer asks. A second consumer within RESEARCH_TTL_DAYS
reads the file instead of searching: the screen you run today reuses the
searches the briefing ran last week, and vice versa.

What is cached is the *external* picture of a firm — what it is, who runs it,
what it has raised, what has been written about it. Nothing deck-specific and
nothing from our own records goes in, so the dossier stays valid across
meetings, decks and consumers.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import BASE_DIR, RESEARCH_MODEL, RESEARCH_TTL_DAYS
from src.features.dedupe import normalize_name

STORE_DIR = BASE_DIR / "data" / "research"

DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "entity": {"type": "string",
                   "description": "The firm as it names itself, with any former name"},
        "firm": {"type": "string",
                 "description": "What the firm is: founded, ownership, "
                                "headquarters, size, what it invests in. Two to "
                                "five sentences of fact, no assessment."},
        "people": {
            "type": "array",
            "description": "Named principals found in public sources",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "note": {"type": "string",
                             "description": "Background, tenure, prior firms, or "
                                            "'No meaningful public record found' "
                                            "where a search returned nothing"},
                },
                "required": ["name", "role", "note"],
                "additionalProperties": False,
            },
        },
        "vehicles": {"type": "string",
                     "description": "Funds raised and current fundraising status, "
                                    "with sizes, dates and closes where public"},
        "recent": {
            "type": "array",
            "description": "Material developments, newest first",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "detail": {"type": "string"},
                    "date": {"type": "string", "description": "As published"},
                    "url": {"type": "string"},
                },
                "required": ["headline", "detail", "date", "url"],
                "additionalProperties": False,
            },
        },
        "flags": {
            "type": "array",
            "description": "Litigation, regulatory action, departures, criticism. "
                           "Empty where searches found none.",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "detail": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["topic", "detail", "url"],
                "additionalProperties": False,
            },
        },
        "collisions": {"type": "string",
                       "description": "Same-named but unrelated firms or people "
                                      "that a reader could confuse with this one. "
                                      "Empty if none."},
        "not_found": {"type": "string",
                      "description": "What you searched for and did not find. This "
                                     "is a finding: state it rather than omitting it."},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "note": {"type": "string", "description": "What it supports"},
                },
                "required": ["title", "url", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entity", "firm", "people", "vehicles", "recent", "flags",
                 "collisions", "not_found", "sources"],
    "additionalProperties": False,
}

DOSSIER_SYSTEM_PROMPT = """You are gathering public facts about an investment firm for a \
family office. You are not writing the analysis — a later call does that from what you return. \
Your job is that the later call never has to search for itself.

Use WebSearch and WebFetch. Search before you write anything.

Cover: what the firm is and who owns it; its principals and their backgrounds; funds raised and \
current fundraising status with sizes and dates; developments since its own materials would have \
been written; and anything adverse — litigation, regulatory action, senior departures, \
substantive criticism.

Discipline:
- Every fact carries the source that supports it. Never state something you did not find.
- Search each named principal alongside criticism, controversy and litigation. Where a person \
has no meaningful public record, say exactly that — absence of information is not a clean bill \
of health, and the later call must not read silence as endorsement.
- Watch for name collisions: unrelated firms sharing a name, often in another geography. Say \
which entity each finding refers to, and record the confusion in 'collisions'.
- What you looked for and did not find belongs in 'not_found'. It is as useful as what you did \
find, and it stops the next call repeating the search.
- Report facts, not judgements. No recommendation, no fit assessment, no adjectives the sources \
do not support.

British English. Figures with units and dates."""


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

# One gather per key at a time: two preps for the same firm started together
# should mean one search, with the second waiting for the first's result.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def research_key(name: str, company: str = "") -> str:
    """Cache key for a counterparty.

    Keyed on the firm, not the person and not the vintage: a prep for a contact
    and a screen of their Fund IV are asking about the same organisation, so a
    trailing fund numeral is dropped (normalize_name has already turned "III"
    into "3").
    """
    tokens = normalize_name(company or name or "").split()
    while tokens and tokens[-1].isdigit():
        tokens.pop()
    slug = " ".join(tokens)
    return "".join(ch if ch.isalnum() else "-" for ch in slug).strip("-")[:80]


def _path(key: str, store_dir: Optional[Path] = None) -> Path:
    return (store_dir or STORE_DIR) / f"{key}.json"


def load_dossier(key: str, store_dir: Optional[Path] = None) -> Optional[dict]:
    """The stored dossier for a key, whatever its age (None if never gathered)."""
    p = _path(key, store_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing or half-written file is a miss
        return None


def save_dossier(key: str, dossier: dict, store_dir: Optional[Path] = None) -> None:
    d = store_dir or STORE_DIR
    d.mkdir(parents=True, exist_ok=True)
    _path(key, d).write_text(json.dumps(dossier, indent=2), encoding="utf-8")


def age_days(dossier: dict, now: Optional[float] = None) -> float:
    """How long ago this dossier was gathered."""
    return ((now if now is not None else time.time())
            - float(dossier.get("gathered_at") or 0)) / 86400.0


def is_fresh(dossier: dict, ttl_days: float = RESEARCH_TTL_DAYS,
             now: Optional[float] = None) -> bool:
    return age_days(dossier, now) < ttl_days


# --------------------------------------------------------------------------- #
# Gathering
# --------------------------------------------------------------------------- #

def gather_dossier(client, name: str, company: str = "") -> dict:
    """Run the research pass. One model call, with the search tools."""
    subject = company or name
    user = (
        f"FIRM: {subject}\n"
        + (f"Named contact: {name}\n" if name and name != subject else "")
        + "\nResearch this firm now and return what you find."
    )
    kwargs = dict(
        model=RESEARCH_MODEL,
        max_tokens=4000,
        system=DOSSIER_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": DOSSIER_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    try:
        response = client.messages.create(
            **kwargs, extra_allowed_tools=["WebSearch", "WebFetch"])
    except TypeError:
        # API-backend clients don't take the kwarg — same call without it.
        response = client.messages.create(**kwargs)
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "")
    data = json.loads(raw)
    data["gathered_at"] = time.time()
    data["gathered_on"] = datetime.now(timezone.utc).strftime("%d %b %Y")
    data["subject"] = subject
    return data


def get_dossier(
    client,
    name: str,
    company: str = "",
    *,
    gather: bool = True,
    refresh: bool = False,
    ttl_days: float = RESEARCH_TTL_DAYS,
    store_dir: Optional[Path] = None,
) -> tuple[Optional[dict], str]:
    """The dossier for a counterparty, plus how it was obtained.

    Returns ``(dossier, origin)`` where origin is "cache", "gathered", "failed"
    or "none". ``gather=False`` means reuse-only: take a dossier if one is
    already on disk, but never spend a search — for callers on a latency
    budget, such as inbox triage.
    """
    key = research_key(name, company)
    if not key:
        return None, "none"

    if not refresh:
        cached = load_dossier(key, store_dir)
        if cached and is_fresh(cached, ttl_days):
            return cached, "cache"

    if not gather:
        return None, "none"

    with _lock_for(key):
        # Another thread may have gathered it while we waited on the lock.
        if not refresh:
            cached = load_dossier(key, store_dir)
            if cached and is_fresh(cached, ttl_days):
                return cached, "cache"
        try:
            dossier = gather_dossier(client, name, company)
        except Exception:  # noqa: BLE001 - research must never sink the prep
            stale = load_dossier(key, store_dir)
            # A stale dossier beats no dossier; the reader is told its age.
            return (stale, "cache") if stale else (None, "failed")
        save_dossier(key, dossier, store_dir)
        return dossier, "gathered"


# --------------------------------------------------------------------------- #
# Rendering into a prompt
# --------------------------------------------------------------------------- #

def dossier_text(dossier: dict) -> str:
    """The dossier as a prompt block, with its age stated."""
    if not dossier:
        return ""
    age = age_days(dossier)
    when = dossier.get("gathered_on") or "an earlier session"
    freshness = ("gathered just now" if age < 0.02 else
                 f"gathered {when} ({int(age)} day{'s' if int(age) != 1 else ''} ago)")
    out = [f"[Web research on {dossier.get('subject') or dossier.get('entity')}, "
           f"{freshness}.]", "", f"THE FIRM: {dossier.get('firm', '')}"]

    if dossier.get("vehicles"):
        out += ["", f"VEHICLES AND FUNDRAISING: {dossier['vehicles']}"]
    if dossier.get("people"):
        out += ["", "PEOPLE:"] + [f"- {p.get('name')} — {p.get('role')}. {p.get('note')}"
                                  for p in dossier["people"]]
    if dossier.get("recent"):
        out += ["", "DEVELOPMENTS:"] + [
            f"- {r.get('date')} — {r.get('headline')}: {r.get('detail')} [{r.get('url')}]"
            for r in dossier["recent"]]
    out += ["", "ADVERSE FINDINGS:"]
    out += ([f"- {f.get('topic')}: {f.get('detail')} [{f.get('url')}]"
             for f in dossier["flags"]] if dossier.get("flags")
            else ["- None found by the searches run."])
    if dossier.get("collisions"):
        out += ["", f"NAME COLLISIONS: {dossier['collisions']}"]
    if dossier.get("not_found"):
        out += ["", f"SEARCHED FOR AND NOT FOUND: {dossier['not_found']}"]
    if dossier.get("sources"):
        out += ["", "SOURCES:"] + [f"- {s.get('title')} — {s.get('url')}"
                                   for s in dossier["sources"]]
    return "\n".join(out)


def dossier_sources(dossier: dict) -> list[str]:
    """Source lines for the prep's own source list."""
    if not dossier:
        return []
    return [f"Web: {s.get('title')} — {s.get('url')}"
            for s in dossier.get("sources", []) if s.get("url")]


def research_block(web_context: str) -> str:
    """The BACKGROUND RESEARCH section of a synthesis prompt.

    Two different instructions, and getting them the wrong way round is what
    made briefings apologise for tooling they had: with a dossier the searches
    are done and repeating them is waste; without one, nothing is pre-gathered
    and the call must search for itself.
    """
    if web_context:
        return (
            f"{web_context}\n\n"
            "[The research above was gathered for you by web search before this "
            "call, and is shared with the other passes over this counterparty. "
            "Treat those searches as done — do not repeat them. You still hold "
            "WebSearch and WebFetch: use them only for gaps the research above "
            "does not cover, or to check a specific claim in the materials.]"
        )
    return ("Nothing has been pre-gathered for you. You have the WebSearch and "
            "WebFetch tools in this session: run the searches yourself now, "
            "before writing, and cite what you find.")
