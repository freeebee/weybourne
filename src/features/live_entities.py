"""Live entity cards: who is that name they just mentioned?

The read loop (src/features/transcription.py, READ_SCHEMA's "entities") flags
people, companies and funds whose mention carried weight in the meeting. This
module answers "what does the firm already know about them", in two stages:

Stage 1 — ``build_entity_card``: local only, no model call. Manager threads,
the Notion RAM caches (matched through dedupe.NameIndex), meeting notes,
recent mail, past live transcripts, and any web-research dossier already on
disk. Tens of milliseconds of CPU plus one bounded network wait, because it
runs while a meeting is being transcribed on this same machine and whisper
owns the cores (see the 17 Aug 2026 freeze notes in src/features/stt.py).

Stage 2 — ``request_quick_news``: one light web-search call (the
felix/enrich.research_contact shape, not the minutes-scale
web_research.gather_dossier) in a background thread, cached under
data/research/quick/. At most ONE runs at a time machine-wide, and excess
demand is dropped rather than queued — the client re-asks later if it still
cares. The call rides the DEFAULT CLI pool, so it queues behind preps and
Felix and can never occupy the reserved live-tidy/live-read lanes.

The quick cache is deliberately a SEPARATE directory from data/research/: a
quick blob written under the main store would satisfy web_research.
get_dossier's freshness check and silently starve prep of a real dossier
gather for RESEARCH_TTL_DAYS.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

from src import config
from src.features import dedupe, managers, transcript_library
from src.features.dedupe import (
    DUPLICATE_THRESHOLD,
    REVIEW_THRESHOLD,
    NameIndex,
    name_score,
    normalize_name,
    prepare_name,
    prepared_match,
)
from src.features.meeting_prep import _name_matches
from src.features.web_research import (
    age_days,
    is_fresh,
    load_dossier,
    research_key,
    save_dossier,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Name indexes over the Notion RAM caches
# --------------------------------------------------------------------------- #

# One NameIndex per collection, keyed by the identity of the list object the
# Notion connector returned: its list cache hands back the SAME object until
# the 600s TTL expires, so an identity change is exactly a cache-generation
# change. Holding `src` in the tuple keeps that id() from being reused.
_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[int, NameIndex, list]] = {}
# (id(src), [(note, normalized_name, normalized_excerpt)], src)
_NOTES_CACHE: Optional[tuple[int, list, list]] = None

_LISTERS = {
    "contacts": lambda notion: notion.list_contacts(),
    "companies": lambda notion: notion.list_companies(),
    "funds": lambda notion: notion.list_funds(),
}


def get_index(kind: str, notion, *, allow_stale: bool = False) -> Optional[NameIndex]:
    """The NameIndex for one collection, or None when it cannot be had cheaply.

    ``allow_stale=True`` is the mid-meeting mode: return whatever is cached
    WITHOUT touching ``list_*`` (whose delta sync is a network pull and a
    parse), and return None when nothing is cached yet — the caller skips
    that collection for this card rather than building a ~9k-name index
    beside a live transcription. The warm hook at recording start is what
    makes the None case rare.
    """
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(kind)
    if allow_stale:
        return cached[1] if cached else None
    src = _LISTERS[kind](notion)
    if cached and cached[0] == id(src):
        return cached[1]
    index = NameIndex((r.name, r) for r in src if getattr(r, "name", ""))
    with _INDEX_LOCK:
        _INDEX_CACHE[kind] = (id(src), index, src)
    return index


def get_prepared_notes(notion, *, allow_stale: bool = False) -> Optional[list]:
    """Notes with their matchable strings prenormalized, same staleness rules
    as get_index — per-card note matching is then pure string ops."""
    global _NOTES_CACHE
    with _INDEX_LOCK:
        cached = _NOTES_CACHE
    if allow_stale:
        return cached[1] if cached else None
    src = notion.list_notes()
    if cached and cached[0] == id(src):
        return cached[1]
    prepared = [(n, normalize_name(n.name), normalize_name(n.excerpt)) for n in src]
    with _INDEX_LOCK:
        _NOTES_CACHE = (id(src), prepared, src)
    return prepared


def warm_indexes(notion) -> None:
    """Build all four caches now — called from /api/live/warm's background
    thread at recording start, before audio is flowing, so no card ever pays
    the ~27k prepare_name build (or a Notion delta sync) mid-meeting.
    Best-effort, same contract as the other warmers."""
    for kind in _LISTERS:
        try:
            get_index(kind, notion)
        except Exception:  # noqa: BLE001
            logger.warning("entity index warm failed for %s", kind, exc_info=True)
    try:
        get_prepared_notes(notion)
    except Exception:  # noqa: BLE001
        logger.warning("entity notes warm failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Stage 1 — the card, assembled from what the firm already holds
# --------------------------------------------------------------------------- #

_MAX_NOTES = 5
_MAX_EMAILS = 5
_MAX_TRANSCRIPTS = 3
_MAX_RELATED_FUNDS = 3
_MAX_THREAD_HISTORY = 6
_EXCERPT_CHARS = 200
_DESCRIPTION_CHARS = 600
# Display window around a note's first mention of the entity, weighted aft:
# what was said about a name usually follows it.
_MENTION_BEFORE = 60
_MENTION_AFTER = 150
# The wider slice stage 2b's one-liner call reads — never shown raw.
_CONTEXT_BEFORE = 250
_CONTEXT_AFTER = 450


def _trim(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _trim_sentence(text: str, limit: int) -> str:
    """Whole sentences only: a description hard-cut mid-clause ("…drive
    value creation through…") reads as broken, not summarised (user,
    21 Aug 2026). The plain trim stays the fallback for text with no
    sentence end inside the limit."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 0 else _trim(text, limit)


def _mention_span(text: str, name: str) -> Optional[tuple[int, int]]:
    """Where lower-cased ``text`` first names the entity, or None. The full
    name is tried first, then its distinguishing tokens longest-first —
    notes say plain "Advantage", not "Advantage Partners" — always at word
    boundaries, so "advantage" never anchors inside "disadvantageous" and
    a noise token like "partners" never anchors at all."""
    hay = (text or "").lower()
    tokens = re.findall(r"\w+", (name or "").lower())
    if not hay or not tokens:
        return None
    patterns = [r"\W+".join(re.escape(t) for t in tokens)]
    patterns += [re.escape(t) for t in
                 sorted((t for t in tokens
                         if t not in dedupe._NOISE_TOKENS and len(t) >= 4),
                        key=len, reverse=True)]
    for pat in patterns:
        m = re.search(rf"\b{pat}\b", hay)
        if m:
            return m.start(), m.end()
    return None


def _around(text: str, span: tuple[int, int], before: int, after: int) -> str:
    lo = max(0, span[0] - before)
    hi = min(len(text), span[1] + after)
    return (("…" if lo > 0 else "") + text[lo:hi].strip()
            + ("…" if hi < len(text) else ""))


def _note_entry(note, name: str) -> dict:
    """One PRIOR CONTACT line. When the note's text names the entity, both
    excerpts anchor on that first mention — the card's job is what was said
    about THEM, and a note's opening 200 characters describe the meeting it
    records (user, 21 Aug 2026). Relation-only matches, where the entity is
    never named, keep the opening."""
    text = " ".join((note.excerpt or "").split())
    span = _mention_span(text, name)
    if span:
        excerpt = _around(text, span, _MENTION_BEFORE, _MENTION_AFTER)
        context = _around(text, span, _CONTEXT_BEFORE, _CONTEXT_AFTER)
    else:
        excerpt = _trim(text, _EXCERPT_CHARS)
        context = _trim(text, _CONTEXT_BEFORE + _CONTEXT_AFTER)
    return {"date": note.date, "title": note.name, "note_type": note.note_type,
            "excerpt": excerpt, "mention_context": context}


# Displaying a wrong record mid-meeting is worse than displaying none, so the
# bare similarity route needs more than dedupe's review band: "Zephyr Crest
# Partners" scores 0.76 against "Harvest Partners" on nothing but the shared
# noise token. prepared_match's OTHER routes (equality, acronym, token-
# stripped equality) carry their own evidence and keep the 0.72 floor — that
# is what lets "EIP" still find Enhanced Investment Products, and a whisper
# mishearing ("Brookfeld") still clear 0.85 comfortably on true similarity.
_SIMILARITY_DISPLAY_FLOOR = 0.85


def _best_match(index: Optional[NameIndex], q) -> Optional[tuple[float, object]]:
    if index is None:
        return None
    best: Optional[tuple[float, object]] = None
    for _pos, prepared, payload in index.candidates(q, floor=REVIEW_THRESHOLD):
        score, reason = prepared_match(q, prepared, floor=REVIEW_THRESHOLD)
        if reason == "name similarity" and score < _SIMILARITY_DISPLAY_FLOOR:
            continue
        if score >= REVIEW_THRESHOLD and (best is None or score > best[0]):
            best = (score, payload)
    return best


def build_entity_card(
    name: str,
    kind: str = "",
    *,
    notion,
    graph,
    context: str = "",
    session_id: str = "",
    allow_stale_index: bool = False,
    managers_base: Optional[Path] = None,
    live_dir: Optional[Path] = None,
    lib_dir: Optional[Path] = None,
    quick_store: Optional[Path] = None,
    email_timeout: float = 2.5,
) -> dict:
    """Everything the firm already knows about one mentioned name.

    Every section is independently best-effort — a card with an empty section
    beats no card, and nothing here may raise past the endpoint. ``kind`` is a
    display hint from the detector, not a search restriction: a "company"
    mention is looked up in all three collections regardless, because the
    manager of a fund lives in whichever database someone filed them in.
    """
    q = prepare_name(name)
    card: dict = {
        "name": name,
        "kind": kind if kind in ("person", "company", "fund") else "company",
        "matched": {"contact": None, "company": None, "fund": None},
        "related_funds": [],
        "manager_thread": None,
        "notes": [],
        "emails": [],
        "transcripts": [],
        "dossier": None,
        "news": None,
        "news_status": "none",
        "no_record": False,
    }

    # Mail first, on its own thread, so the one network wait overlaps all the
    # local work below. A plain daemon thread rather than an executor: an
    # executor's shutdown would wait out a slow Graph call we already gave up on.
    email_result: dict = {}

    def _fetch_mail():
        try:
            email_result["messages"] = graph.messages_with(name, top=_MAX_EMAILS, days=180)
        except Exception:  # noqa: BLE001
            email_result["messages"] = []

    mail_thread = threading.Thread(target=_fetch_mail, daemon=True)
    mail_thread.start()

    # Manager thread: the curated relationship timeline, 44 small files.
    thread = None
    try:
        thread = managers.find(name, base=managers_base)
    except Exception:  # noqa: BLE001
        logger.warning("entity card: managers.find failed for %r", name, exc_info=True)
    if thread:
        history = list(thread.get("history") or [])[-_MAX_THREAD_HISTORY:]
        card["manager_thread"] = {
            "entity": thread.get("entity", ""),
            "company_name": thread.get("company_name", ""),
            "fund_name": thread.get("fund_name", ""),
            "contact_name": thread.get("contact_name", ""),
            "email": thread.get("email", ""),
            "history": [
                {k: _trim(str(v)) for k, v in h.items()} for h in history
            ],
        }

    # Notion, through the prebuilt indexes. A collection whose index is not
    # warm is SKIPPED while recording, never built (see get_index).
    matched_ids: set[str] = set()
    for coll, field, shape in (
        ("contacts", "contact",
         lambda r, s: {"id": r.id, "name": r.name, "email": r.email,
                       "title": r.title, "company": r.company, "score": round(s, 2)}),
        ("companies", "company",
         lambda r, s: {"id": r.id, "name": r.name,
                       "description": _trim_sentence(r.description,
                                                     _DESCRIPTION_CHARS),
                       "city": r.city, "country": r.country, "score": round(s, 2)}),
        ("funds", "fund",
         lambda r, s: {"id": r.id, "name": r.name, "status": r.status,
                       "asset_class": list(r.asset_class),
                       "strategy_description": _trim_sentence(
                           r.strategy_description, _DESCRIPTION_CHARS),
                       "company": r.company, "score": round(s, 2)}),
    ):
        try:
            index = get_index(coll, notion, allow_stale=allow_stale_index)
            best = _best_match(index, q)
            if best:
                score, record = best
                card["matched"][field] = shape(record, score)
                if record.id:
                    matched_ids.add(record.id)
        except Exception:  # noqa: BLE001
            logger.warning("entity card: %s match failed for %r", coll, name,
                           exc_info=True)

    # Funds this name is the OWNER of — a relationship no similarity score
    # finds ("Albizia" vs "Albizia ASEAN Opportunities Fund").
    try:
        funds_index = get_index("funds", notion, allow_stale=allow_stale_index)
        if funds_index is not None and q.normalised:
            matched_fund_id = (card["matched"]["fund"] or {}).get("id")
            for _pos, _prep, rec in funds_index.starting_with(q.normalised.split()):
                if rec.id and rec.id != matched_fund_id:
                    card["related_funds"].append(
                        {"id": rec.id, "name": rec.name, "status": rec.status})
                if len(card["related_funds"]) >= _MAX_RELATED_FUNDS:
                    break
    except Exception:  # noqa: BLE001
        logger.warning("entity card: related funds failed for %r", name, exc_info=True)

    # Meeting notes: related by id to anything matched above, or naming the
    # entity in their own title/excerpt (relations are often never filled in).
    try:
        prepared_notes = get_prepared_notes(notion, allow_stale=allow_stale_index)
        if prepared_notes and q.normalised:
            hits = []
            for note, name_norm, excerpt_norm in prepared_notes:
                related = matched_ids & (set(note.attendee_ids)
                                         | set(note.company_ids) | set(note.fund_ids))
                if related or _name_matches(q.normalised, name_norm) \
                        or _name_matches(q.normalised, excerpt_norm):
                    hits.append(note)
            hits.sort(key=lambda n: n.date or "", reverse=True)
            card["notes"] = [_note_entry(n, name) for n in hits[:_MAX_NOTES]]
    except Exception:  # noqa: BLE001
        logger.warning("entity card: notes match failed for %r", name, exc_info=True)

    # Past live meetings. `who` may be a raw email address, so match on title.
    try:
        summaries = transcript_library.list_all(live_dir=live_dir, lib_dir=lib_dir)
        for t in summaries:
            if t.get("id") == session_id:
                continue
            title = t.get("title") or ""
            if name_score(name, title) >= REVIEW_THRESHOLD \
                    or _name_matches(q.normalised, normalize_name(title)):
                card["transcripts"].append({"id": t.get("id"), "title": title,
                                            "started": t.get("started", "")})
            if len(card["transcripts"]) >= _MAX_TRANSCRIPTS:
                break
    except Exception:  # noqa: BLE001
        logger.warning("entity card: transcript match failed for %r", name,
                       exc_info=True)

    # What was actually SAID about them before — verbatim from past meeting
    # transcripts, the context the card's footer leads with.
    try:
        card["said_before"] = said_before(name, live_dir=live_dir,
                                          lib_dir=lib_dir,
                                          exclude_id=session_id)
    except Exception:  # noqa: BLE001
        card["said_before"] = []
        logger.warning("entity card: said-before scan failed for %r", name,
                       exc_info=True)

    # A research dossier already on disk. Any age: for a live card a stale
    # dossier beats nothing, and the age is stated rather than hidden —
    # which is why this is load_dossier, not get_dossier(gather=False)
    # (fresh-only, would hide a 15-day-old dossier entirely).
    company_hint = ((card["matched"]["company"] or {}).get("name")
                    or (card["manager_thread"] or {}).get("company_name")
                    or (card["matched"]["fund"] or {}).get("company") or "")
    try:
        key = research_key(name, company_hint)
        dossier = load_dossier(key) if key else None
        if dossier:
            card["dossier"] = {
                "firm": _trim(dossier.get("firm", ""), 400),
                "recent": list(dossier.get("recent") or [])[:3],
                "gathered_on": dossier.get("gathered_on", ""),
                "age_days": int(age_days(dossier)),
            }
    except Exception:  # noqa: BLE001
        logger.warning("entity card: dossier read failed for %r", name, exc_info=True)

    # Quick news already gathered (or being gathered) for this key.
    status, news = news_status(name, company_hint, quick_store=quick_store)
    card["news_status"] = status
    card["news"] = news
    card["company_hint"] = company_hint

    mail_thread.join(timeout=email_timeout)
    messages = email_result.get("messages") or []
    card["emails"] = [{"received": m.received, "subject": m.subject,
                       "sender": m.sender_name or m.sender_email}
                      for m in messages[:_MAX_EMAILS]]

    card["no_record"] = not (
        any(card["matched"].values()) or card["related_funds"]
        or card["manager_thread"] or card["notes"] or card["emails"]
        or card["transcripts"] or card["dossier"]
    )

    # Haiku one-liners for the prior-contact lines — cache READ only here;
    # stage-1 stays local. The endpoint triggers the gather on "none".
    try:
        apply_mention_summaries(card, name, quick_store=quick_store)
    except Exception:  # noqa: BLE001
        card["summaries"] = "none"
        logger.warning("entity card: summary apply failed for %r", name,
                       exc_info=True)
    return card


# How many recent transcripts a card scans for earlier mentions, and how
# much verbatim context each quote carries. Disk reads only — never a model.
_SAID_SCAN_LIMIT = 20
_SAID_MAX = 3
_SAID_BEFORE_CHARS = 100
_SAID_AFTER_CHARS = 140


def said_before(name: str, *, live_dir=None, lib_dir=None,
                exclude_id: str = "") -> list[dict]:
    """Verbatim moments from past transcripts where this name came up.

    Newest first, capped, each entry {title, date, excerpt}. The excerpt is
    the sentence-neighbourhood of the first occurrence — what the room
    actually said, not a summary of it.
    """
    needle = (name or "").strip().lower()
    if not needle:
        return []
    out: list[dict] = []
    for t in transcript_library.list_all(live_dir=live_dir,
                                         lib_dir=lib_dir)[:_SAID_SCAN_LIMIT]:
        if t.get("id") == exclude_id:
            continue
        rec = transcript_library.load(t["id"], live_dir=live_dir,
                                      lib_dir=lib_dir) or {}
        text = rec.get("transcript") or ""
        idx = text.lower().find(needle)
        if idx < 0:
            continue
        start = max(0, idx - _SAID_BEFORE_CHARS)
        end = min(len(text), idx + len(needle) + _SAID_AFTER_CHARS)
        excerpt = text[start:end].strip()
        out.append({
            "title": rec.get("title") or t.get("title") or "",
            "date": (rec.get("started") or "")[:10],
            "excerpt": ("…" if start > 0 else "") + excerpt
                       + ("…" if end < len(text) else ""),
        })
        if len(out) >= _SAID_MAX:
            break
    return out


# --------------------------------------------------------------------------- #
# Stage 2 — one light web look, bounded hard
# --------------------------------------------------------------------------- #

QUICK_DIR = config.BASE_DIR / "data" / "research" / "quick"
QUICK_TTL_DAYS = 3.0   # news staler than a structural dossier — 14 days would
                       # serve dead headlines

# ONE quick look at a time, machine-wide, acquired non-blocking: excess demand
# is DROPPED (status "none"), never queued. The client may re-ask on a later
# poll; an unbounded queue is how the 17 Aug transcript died.
_QUICK_SEMAPHORE = threading.BoundedSemaphore(1)
_QUICK_INFLIGHT: set[str] = set()
_QUICK_GUARD = threading.Lock()

QUICK_NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string",
                    "description": "Two or three factual sentences on who or what "
                                   "this is. Empty when nothing reliable was found."},
        "news": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "date": {"type": "string",
                             "description": "As the source states it, or a recency "
                                            "like 'this month'"},
                    "url": {"type": "string"},
                },
                "required": ["headline", "date", "url"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "not_found": {"type": "boolean"},
    },
    "required": ["summary", "news", "confidence", "not_found"],
    "additionalProperties": False,
}

QUICK_NEWS_SYSTEM_PROMPT = """You are a fast lookup for a name mentioned moments ago in a \
live meeting at Weybourne, a single family office. The user is still in the meeting: speed \
beats depth. Run one or two web searches at most, then answer.

Rules:
- Use the supplied meeting context to pick the right entity. If several same-named people or \
firms cannot be separated quickly, return empty fields with not_found true and confidence \
"low" — a wrong identification is worse than none.
- "summary" is the ONLY text the user sees, in the meeting, at a glance. Two or three \
sentences: who they are, and what any notable recent coverage actually SAYS about them \
("EQT agreed in July to sell Quantios to Vista"), woven into the prose — never "see the \
news items below", never a headline restated verbatim. No speculation, no adjectives of \
judgement.
- "news" is machine-side citation only (at most three items, newest first, with the \
source's own date and URL) — the user is never shown these links, so everything that \
matters must already be in the summary. Nothing notable is a normal answer: an empty list.
- Never present the absence of coverage as a finding about the entity itself.
- Confidence reflects the identification, not the amount found."""


def quick_look(client, name: str, company: str = "", context: str = "") -> dict:
    """One bounded search-and-summarise call. The felix research_contact
    shape: LIVE_MODEL, small budget, schema-constrained, web tools offered
    when the backend takes them."""
    import time

    user = (
        f"NAME: {name}\n"
        f"Likely organisation: {company or '(unknown)'}\n"
        f"MEETING CONTEXT (what was being discussed when they came up)\n"
        f"{context or '(none supplied)'}"
    )
    kwargs = {
        "model": config.LIVE_MODEL,
        "max_tokens": 1200,
        "system": QUICK_NEWS_SYSTEM_PROMPT,
        "output_config": {"format": {"type": "json_schema", "schema": QUICK_NEWS_SCHEMA}},
        "messages": [{"role": "user", "content": user}],
    }
    try:
        response = client.messages.create(
            **kwargs, extra_allowed_tools=["WebSearch", "WebFetch"])
    except TypeError:
        # The Anthropic SDK backend takes no extra_allowed_tools kwarg — run
        # without web tools rather than not at all (same fallback as
        # web_research.gather_dossier).
        response = client.messages.create(**kwargs)
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    data = json.loads(raw)
    data["news"] = list(data.get("news") or [])[:3]
    now = time.time()
    data["gathered_at"] = now
    data["gathered_on"] = time.strftime("%d %b %Y", time.localtime(now))
    data["subject"] = name
    return data


def news_status(name: str, company: str = "",
                quick_store: Optional[Path] = None) -> tuple[str, Optional[dict]]:
    """Where stage 2 stands for this entity: ("cached", payload) when a fresh
    quick look is on disk, ("pending", None) while one is being gathered,
    ("none", None) otherwise. Read-only — polling this can never spawn work."""
    key = research_key(name, company)
    if not key:
        return "none", None
    store = quick_store or QUICK_DIR
    data = load_dossier(key, store_dir=store)
    if data and is_fresh(data, ttl_days=QUICK_TTL_DAYS):
        return "cached", data
    with _QUICK_GUARD:
        if key in _QUICK_INFLIGHT:
            return "pending", None
    return "none", None


def request_quick_news(name: str, company: str, context: str, client_factory,
                       quick_store: Optional[Path] = None) -> str:
    """Start a quick look if capacity allows. Returns the resulting status.

    ``client_factory`` is a zero-arg callable producing the LLM client — the
    endpoint passes a lambda over llm.get_client so this module (and its
    tests) never import the CLI plumbing.
    """
    key = research_key(name, company)
    if not key:
        return "none"
    store = quick_store or QUICK_DIR
    cached = load_dossier(key, store_dir=store)
    if cached and is_fresh(cached, ttl_days=QUICK_TTL_DAYS):
        return "cached"
    with _QUICK_GUARD:
        if key in _QUICK_INFLIGHT:
            return "pending"
        if not _QUICK_SEMAPHORE.acquire(blocking=False):
            # At capacity: drop, don't queue. The client's poll may re-ask.
            return "none"
        _QUICK_INFLIGHT.add(key)
    threading.Thread(target=_gather_quick,
                     args=(key, name, company, context, client_factory, store),
                     daemon=True).start()
    return "pending"


def _gather_quick(key: str, name: str, company: str, context: str,
                  client_factory, store: Path) -> None:
    """The background worker. A failure caches nothing — the card simply
    stays firm-data-only, never an error surface. The ``finally`` is the
    contract that matters: a failed gather MUST free its slot."""
    try:
        client = client_factory()
        data = quick_look(client, name, company, context)
        save_dossier(key, data, store_dir=store)
    except Exception:  # noqa: BLE001
        logger.warning("quick news gather failed for %r", name, exc_info=True)
    finally:
        with _QUICK_GUARD:
            _QUICK_INFLIGHT.discard(key)
        _QUICK_SEMAPHORE.release()


# --------------------------------------------------------------------------- #
# Stage 2b — one Haiku line per prior-contact item
# --------------------------------------------------------------------------- #
# A raw note excerpt clipped at 200 characters is the note talking, not an
# answer: the user asked "what was said about THIS entity", got a pitch
# paragraph cut mid-sentence, and said so (18 Aug 2026). One cheap Haiku
# call per card rewrites every prior-contact line as a single sentence about
# the mentioned entity. Same discipline as the news look: one subprocess
# machine-wide (the SAME semaphore), non-blocking drop, cached on disk.

SUMMARY_TTL_DAYS = 7.0   # notes and past transcripts do not change under us

MENTION_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string",
                            "description": "The item's ref, copied verbatim"},
                    "line": {"type": "string",
                             "description": "ONE sentence, at most ~22 words, "
                                            "stating what this item said about "
                                            "the entity"},
                },
                "required": ["ref", "line"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summaries"],
    "additionalProperties": False,
}

MENTION_SUMMARY_SYSTEM_PROMPT = (
    "You summarise what our own meeting notes and transcripts said about ONE "
    "specific entity, for a card shown during a live meeting.\n\n"
    "For each item return one plain sentence (at most ~22 words) stating what "
    "was said about the entity — the fact, view or terms discussed, not the "
    "meeting logistics. Write the fact directly (\"Pitched a listed "
    "daily-liquidity AI fund at a flat 2.5% fee, no carry\"), never \"the "
    "note says\". Item text may be a window cut from a longer note ('…' "
    "marks the cuts), often from a meeting with a DIFFERENT firm — state "
    "what it says about the entity, never what the meeting itself was "
    "about. If an item only mentions the entity in passing, say in a "
    "few words what it was mentioned for. Return every ref you were given.")


def _summary_key(name: str) -> str:
    """Entity slug + suffix. research_key's second argument is a COMPANY
    override, not a namespace — passing "mention-lines" there gave every
    entity the same key, so each gather overwrote the previous entity's
    lines. The suffix keeps the key clear of the entity's news dossier,
    which shares QUICK_DIR under the bare slug."""
    key = research_key(name)
    return f"{key}--mention-lines" if key else ""


def _summary_ref(kind: str, date: str, title: str) -> str:
    return f"{kind}:{date}:{title}"[:120]


def summary_items(card: dict) -> list[dict]:
    """The items a card wants one-liners for, with refs stable across
    rebuilds (kind + date + title)."""
    items = []
    for n in card.get("notes") or []:
        # The wider mention window, not the two-line display excerpt: a
        # one-liner about the entity needs the sentences where the entity
        # actually comes up.
        items.append({"ref": _summary_ref("note", n.get("date", ""), n.get("title", "")),
                      "kind": "note", "title": n.get("title", ""),
                      "date": n.get("date", ""),
                      "text": n.get("mention_context") or n.get("excerpt", "")})
    for sb in card.get("said_before") or []:
        items.append({"ref": _summary_ref("said", sb.get("date", ""), sb.get("title", "")),
                      "kind": "transcript", "title": sb.get("title", ""),
                      "date": sb.get("date", ""), "text": sb.get("excerpt", "")})
    return [it for it in items if (it["text"] or "").strip()]


def summarize_mentions(client, name: str, items: list[dict]) -> dict:
    """One FAST_MODEL call over all of a card's prior-contact items."""
    import time

    blocks = [f"[{it['ref']}] ({it['kind']}, {it['date'] or 'undated'}) "
              f"{it['title']}\n{it['text']}" for it in items]
    user = f"ENTITY: {name}\n\nITEMS\n" + "\n\n".join(blocks)
    response = client.messages.create(
        model=config.FAST_MODEL, max_tokens=700,
        system=MENTION_SUMMARY_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema",
                                  "schema": MENTION_SUMMARY_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next((b.text for b in response.content
                if getattr(b, "type", None) == "text"), "{}")
    data = json.loads(raw)
    lines = {}
    for item in data.get("summaries") or []:
        ref = item.get("ref") or ""
        line = " ".join((item.get("line") or "").split())
        if ref and line:
            lines[ref] = line[:220]
    now = time.time()
    return {"subject": name, "lines": lines,
            "refs": sorted(it["ref"] for it in items),
            "gathered_at": now,
            "gathered_on": time.strftime("%d %b %Y", time.localtime(now))}


def apply_mention_summaries(card: dict, name: str,
                            quick_store: Optional[Path] = None) -> None:
    """Swap verbatim excerpts for cached Haiku lines. Disk read only.

    Sets card["summaries"]: "ready" when applied (or nothing to summarise),
    "pending" while a gather runs, "none" when the endpoint should trigger
    one. A cache missing any CURRENT ref counts as stale — a new note or
    transcript re-earns its one-liner."""
    items = summary_items(card)
    if not items:
        card["summaries"] = "ready"
        return
    key = _summary_key(name)
    store = quick_store or QUICK_DIR
    data = load_dossier(key, store_dir=store) if key else None
    lines = (data or {}).get("lines") or {}
    if (data and is_fresh(data, ttl_days=SUMMARY_TTL_DAYS)
            and all(it["ref"] in lines for it in items)):
        for n in card.get("notes") or []:
            ref = _summary_ref("note", n.get("date", ""), n.get("title", ""))
            if lines.get(ref):
                n["excerpt"] = lines[ref]
        for sb in card.get("said_before") or []:
            ref = _summary_ref("said", sb.get("date", ""), sb.get("title", ""))
            if lines.get(ref):
                sb["excerpt"] = lines[ref]
        card["summaries"] = "ready"
        return
    with _QUICK_GUARD:
        card["summaries"] = "pending" if key in _QUICK_INFLIGHT else "none"


def summaries_status(name: str, quick_store: Optional[Path] = None) -> str:
    """Read-only poll: "ready" when a fresh cache exists, "pending" while a
    gather runs, "none" otherwise. Never spawns work."""
    key = _summary_key(name)
    if not key:
        return "none"
    data = load_dossier(key, store_dir=quick_store or QUICK_DIR)
    if data and is_fresh(data, ttl_days=SUMMARY_TTL_DAYS):
        return "ready"
    with _QUICK_GUARD:
        if key in _QUICK_INFLIGHT:
            return "pending"
    return "none"


def request_mention_summaries(name: str, items: list[dict], client_factory,
                              quick_store: Optional[Path] = None) -> str:
    """Start a summary gather if capacity allows — request_quick_news's
    exact shape, sharing its one-subprocess semaphore."""
    key = _summary_key(name)
    if not items:
        return "ready"
    if not key:
        return "none"
    store = quick_store or QUICK_DIR
    cached = load_dossier(key, store_dir=store)
    if (cached and is_fresh(cached, ttl_days=SUMMARY_TTL_DAYS)
            and all(it["ref"] in (cached.get("lines") or {}) for it in items)):
        return "ready"
    with _QUICK_GUARD:
        if key in _QUICK_INFLIGHT:
            return "pending"
        if not _QUICK_SEMAPHORE.acquire(blocking=False):
            return "none"
        _QUICK_INFLIGHT.add(key)
    threading.Thread(target=_gather_summaries,
                     args=(key, name, items, client_factory, store),
                     daemon=True).start()
    return "pending"


def _gather_summaries(key: str, name: str, items: list[dict],
                      client_factory, store: Path) -> None:
    """Background worker — the ``finally`` frees the shared slot."""
    try:
        client = client_factory()
        data = summarize_mentions(client, name, items)
        save_dossier(key, data, store_dir=store)
    except Exception:  # noqa: BLE001
        logger.warning("mention summary gather failed for %r", name, exc_info=True)
    finally:
        with _QUICK_GUARD:
            _QUICK_INFLIGHT.discard(key)
        _QUICK_SEMAPHORE.release()
