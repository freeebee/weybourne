"""The judgment layer — one schema-constrained model call.

Every count and status is computed in derive.py and handed in as fact; this
module is only ever asked to interpret, never to tally. Model output is
filtered before it's trusted: real fund names/statuses are re-attached from
Notion rather than restated by the model, and any source URL the model
didn't actually see is dropped — a hallucinated citation never reaches the
page.
"""
from __future__ import annotations

import json

from src.config import REASONING_MODEL

from . import derive

# Bump whenever SYSTEM_PROMPT changes. Both this and REASONING_MODEL are
# written into every stored review's provenance, so a review that reads
# differently months from now can be explained by exactly which model and
# prompt produced it.
PROMPT_VERSION = "2026-08-a"

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "kebab-case slug"},
        "title": {"type": "string", "description": "sentence case, max 90 chars"},
        "meta": {"type": "string",
                 "description": "e.g. '3 August · GP meeting · Japan buyout'"},
        "wide": {"type": "boolean", "description": "full width; at most two per week"},
        "badge": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "max 16 chars"},
                "tone": {"type": "string",
                         "enum": ["neutral", "field", "brass", "positive",
                                  "caution", "critical"]},
            },
            "required": ["label", "tone"], "additionalProperties": False,
        },
        "paragraphs": {"type": "array", "minItems": 1, "maxItems": 3,
                       "items": {"type": "string",
                                 "description": "**bold** is the only markup permitted"}},
        "quote": {"type": ["string", "null"],
                  "description": "verbatim from the note, no quote marks; null unless genuine"},
        "note": {
            "type": ["object", "null"],
            "properties": {
                "kind": {"type": "string", "enum": ["risk", "watch", "good", "next"]},
                "label": {"type": "string", "description": "max 14 chars"},
                "body": {"type": "string"},
            },
            "required": ["kind", "label", "body"], "additionalProperties": False,
        },
        "sources": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                "required": ["label", "url"], "additionalProperties": False,
            },
        },
    },
    "required": ["id", "title", "meta", "wide", "badge", "paragraphs",
                "quote", "note", "sources"],
    "additionalProperties": False,
}

WEEK_IN_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "sentence case, max 60 chars, no full stop"},
        "standfirst": {"type": "string", "description": "two or three sentences framing the week"},
        "urgent": {
            "type": ["object", "null"],
            "description": "only when a note contains a decision with a deadline "
                           "inside or near the window; otherwise null",
            "properties": {
                "badge_label": {"type": "string"},
                "title": {"type": "string"},
                "paragraphs": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
            },
            "required": ["badge_label", "title", "paragraphs"], "additionalProperties": False,
        },
        "moved": {
            "type": "array", "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "fund_id": {"type": "string", "description": "must be an id from the supplied fund list"},
                    "focus": {"type": "string",
                              "description": "short uppercase label, e.g. 'JAPAN BUYOUT', no emoji"},
                    "why": {"type": "string", "description": "one or two sentences"},
                },
                "required": ["fund_id", "focus", "why"], "additionalProperties": False,
            },
        },
        "declined": {
            "type": "array", "maxItems": 20,
            "description": "One entry per fund whose status ends '(Declined)' AND whose "
                           "decline reason is actually evidenced in the notes. Omit a "
                           "declined fund entirely rather than guess at why.",
            "items": {
                "type": "object",
                "properties": {
                    "fund_id": {"type": "string", "description": "must be an id from the "
                               "supplied fund list, and that fund's status must already "
                               "be '(Declined)' — never propose declining one here"},
                    "focus": {"type": "string",
                              "description": "short uppercase label, e.g. 'JAPAN BUYOUT', no emoji"},
                    "why": {"type": "string",
                            "description": "one or two sentences on why it was declined, "
                                          "grounded in the notes"},
                },
                "required": ["fund_id", "focus", "why"], "additionalProperties": False,
            },
        },
        "reads": {"type": "array", "minItems": 6, "maxItems": 16, "items": READ_SCHEMA},
    },
    "required": ["headline", "standfirst", "urgent", "moved", "declined", "reads"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write the weekly investment review for Weybourne, the Dyson family office.

VOICE
Measured, precise, quietly confident — a senior steward briefing trusted readers, never selling.
Sentence case for headings. Institutional "we" for the firm. No hype, no superlatives, no
exclamation marks, no start-up register. Never use emoji or decorative symbols; the only marks
permitted are · — § †. Short, complete sentences. Prefer a clean figure plus one line of context
to a paragraph of narrative.

WHAT MAKES A GOOD READ
A read is a judgment, not a summary. It earns its place by doing one of these:
  - naming what a meeting established that changes a position;
  - surfacing a claim that was made and not evidenced, and saying what would evidence it;
  - connecting two meetings that bear on each other;
  - recording a manager standing down, or contradicting themselves usefully.
Rank by consequence, not chronology. Mark at most two as wide — the ones that would change a
decision. Prefer specifics: figures, names, mechanics. A read with no number and no name in it is
usually a read not worth printing.

EVIDENCE DISCIPLINE
Distinguish what a manager asserted from what was evidenced. Where a figure is manager-reported,
say so. Never state a number that is not in the source text. Never infer a status — statuses are
supplied. If a note's own text flags that its transcript was partial or poor, do not present its
characterisations as established fact.

QUOTES
Only quote text that appears verbatim in the source. If you cannot find it verbatim, omit the
quote field rather than paraphrasing into quotation marks.

CONSTRAINTS
Every read must cite at least one source URL drawn from the supplied notes. Use only URLs given
to you. **bold** is the only markup allowed in paragraphs."""


def notes_for_prompt(notes: list[dict]) -> list[dict]:
    """Deduped (drop the empty half of a duplicate pair, keep the keeper),
    non-empty, date-sorted — the exact set of notes the model is shown."""
    dup_sets = derive.find_duplicate_sets(notes)
    keeper_ids = {s["keeper"]["id"] for s in dup_sets}
    dropped_ids = {n["id"] for s in dup_sets for n in s["notes"]} - keeper_ids
    kept = [n for n in notes if n["id"] not in dropped_ids and derive.content_length(n) > 0]
    return sorted(kept, key=lambda n: n.get("date") or "")


def _render_funds(funds: list[dict], window_start: str) -> str:
    lines = []
    for f in funds:
        age = "new this week" if (f.get("created_time") or "")[:10] >= window_start else "existing"
        lines.append(
            f"{f['id']} | {f['name']} | {f.get('status') or '—'} | {f.get('quality') or '—'} | "
            f"{', '.join(f.get('asset_class') or [])} | {', '.join(f.get('geographic_focus') or [])} | {age}"
        )
    return "\n".join(lines)


def _render_notes(notes: list[dict]) -> str:
    parts = []
    for n in notes:
        parts.append(
            f"### {n['title']}\n"
            f"date: {n.get('date')} · type: {n.get('note_type') or 'untyped'} · url: {n.get('url')}\n\n"
            f"{derive.note_content(n)}"
        )
    return "\n\n---\n\n".join(parts)


def build_user_message(window: dict, stats: dict, funds: list[dict], notes: list[dict]) -> str:
    prompt_notes = notes_for_prompt(notes)
    return (
        f"WINDOW: {window['start']} to {window['end']}\n\n"
        f"COMPUTED FACTS — treat as given, do not recompute or contradict:\n"
        f"{json.dumps(stats, indent=2)}\n\n"
        f"FUNDS TOUCHED (id | name | status | quality | asset class | geography | age):\n"
        f"{_render_funds(funds, window['start'])}\n\n"
        f"NOTES:\n{_render_notes(prompt_notes)}\n\n"
        "Produce the week's review. Choose the reads that matter — the judgments a partner "
        "would want to carry into next week — and the funds worth listing under \"what moved\", "
        "using only fund ids above. Separately, for every fund above whose status ends "
        "'(Declined)': if the notes actually evidence why, add it under \"declined\" with a "
        "short, grounded reason; if nothing in the notes explains the decline, leave that "
        "fund out of \"declined\" rather than inventing a reason — a declined fund with no "
        "evidenced reason is still reported elsewhere, just without a why."
    )


def _reattach_funds(moved: list[dict], funds: list[dict]) -> list[dict]:
    """Real name/url/status from the actual fund record, never the model's
    restatement of them. Drops anything that doesn't resolve to a real,
    status-bearing fund."""
    by_id = {f["id"]: f for f in funds}
    out = []
    for m in moved:
        f = by_id.get(m.get("fund_id"))
        if not f or not f.get("status"):
            continue
        out.append({"id": f["id"], "url": f.get("url", ""), "name": f["name"],
                    "status": f["status"], "focus": m.get("focus", ""),
                    "why": m.get("why", "")})
    return out[:10]


def _reattach_declined(declined: list[dict], funds: list[dict]) -> list[dict]:
    """Same contract as _reattach_funds, plus a defensive check the model
    cannot route around: the real fund record must actually carry a
    '(Declined)' status. A fund the model mislabels — or a hallucinated
    fund_id — never reaches the page just because the model asserted it."""
    by_id = {f["id"]: f for f in funds}
    out = []
    for d in declined:
        f = by_id.get(d.get("fund_id"))
        if not f or not f.get("status") or not derive.DECLINED_RE.search(f["status"]):
            continue
        out.append({"id": f["id"], "url": f.get("url", ""), "name": f["name"],
                    "status": f["status"], "focus": d.get("focus", ""),
                    "why": d.get("why", "")})
    return out[:20]


def _drop_invented_sources(reads: list[dict], notes: list[dict]) -> list[dict]:
    """Filters every read's sources to URLs that are actually in this week's
    notes, then drops any read left with none — a hallucinated citation
    never reaches the page."""
    valid_urls = {n["url"] for n in notes if n.get("url")}
    out = []
    for r in reads:
        sources = [s for s in (r.get("sources") or []) if s.get("url") in valid_urls]
        if not sources:
            continue
        out.append({**r, "sources": sources})
    return out


def summarise(client, window: dict, stats: dict, funds: list[dict], notes: list[dict]) -> dict:
    user = build_user_message(window, stats, funds, notes)
    response = client.messages.create(
        model=REASONING_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": WEEK_IN_REVIEW_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    raw = next(b.text for b in response.content if getattr(b, "type", None) == "text")
    out = json.loads(raw)
    out["moved"] = _reattach_funds(out.get("moved") or [], funds)
    out["declined"] = _reattach_declined(out.get("declined") or [], funds)
    out["reads"] = _drop_invented_sources(out.get("reads") or [], notes)
    return out
