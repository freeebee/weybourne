"""Give already-extracted quotes the themes of the passage rather than the letter.

Every letter read before per-quote themes existed stored themes at the letter
level only. The correspondence log and the theme drawer then printed the
*letter's* subjects under each quote, which reads as a claim about the quote:
RPD's May letter ranged over AI, semiconductors, the Gulf and degrossing, so a
passage about ZoomInfo's guidance reset was tagged Iran & Hormuz; QSP's July
risk report carried the same four tags onto a passage about single-stock
decorrelation, putting it under Semiconductors.

``views.py`` and the log already distinguish the two cases and say which they
are showing. This pass is the other half: it repairs the data instead of
captioning it, so the distinction stops mattering.

What keeps it cheap and safe:

* **The letter body is never re-read.** The input is the stored quotes and the
  letter's own theme list — a few hundred tokens against the several thousand a
  re-extraction would cost, and it runs at ``EFFORT_EXTRACTION`` because the
  model is filling in a schema rather than reasoning.
* **Themes are chosen, never coined.** The reply is filtered to the letter's
  existing theme ids. A backfill that could mint new ids would quietly rewrite
  the vocabulary the whole theme drawer is built on.
* **Nothing is invented and nothing is lost.** Quote text, context, order and
  every other field are untouched; only the ``themes`` key is added. A quote
  the model does not rule on keeps inheriting, exactly as before.
* **It is resumable and idempotent.** A quote carrying its own themes is never
  sent again, so the cost is bounded by what remains and an interrupted run
  loses only the letter in flight.

Tests inject a fake client exposing ``messages.create``, as the other feature
modules do, so no model calls happen in CI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.config import EXTRACTION_MODEL

from . import store
from .taxonomy import THEMES, normalise_theme

SYSTEM_PROMPT = (
    "You attribute themes to individual passages from investor letters. You are "
    "given the themes already recorded for a whole letter and the passages "
    "extracted from it. For each passage, say which of those themes the passage "
    "is actually about.\n\n"
    "A letter's themes are not a passage's themes. A letter may range across AI, "
    "semiconductors and the Gulf while a given passage is about one company's "
    "guidance and belongs to none of them. Returning an empty list is the right "
    "answer far more often than returning everything, and is always better than "
    "a theme the passage merely sits near.\n\n"
    "Choose only from the ids you are given. Never invent one."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "passages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The number printed beside the passage.",
                    },
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The ids from the letter's list that THIS passage "
                                       "is about — usually one, often none. Empty when the "
                                       "passage is about something the list does not cover.",
                    },
                },
                "required": ["index", "themes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["passages"],
    "additionalProperties": False,
}


def quotes_needing_themes(letter: dict) -> list[int]:
    """Positions of quotes with no themes of their own.

    ``None`` and a missing key mean "never asked"; an empty list means the model
    was asked and said none of them, which is an answer and is not re-bought.
    """
    out = []
    for i, q in enumerate(letter.get("quotes") or []):
        if isinstance(q, dict) and q.get("themes") is None:
            out.append(i)
    return out


def pending(letters: list[dict]) -> list[dict]:
    """Letters still carrying quotes that inherit, with how many each."""
    out = []
    for letter in letters:
        positions = quotes_needing_themes(letter)
        # A letter with no themes of its own has nothing to choose from, and a
        # letter with no quotes has nothing to attribute.
        if positions and (letter.get("themes") or []):
            out.append({
                "org": letter.get("org", ""),
                "message_id": letter.get("message_id", ""),
                "date": letter.get("date", ""),
                "source": letter.get("source", ""),
                "quotes": len(positions),
                "themes": list(letter.get("themes") or []),
            })
    return out


def stats(letters: list[dict]) -> dict:
    """How much of the archive still inherits — the honest coverage line."""
    own = inherit = 0
    for letter in letters:
        for q in letter.get("quotes") or []:
            if isinstance(q, dict) and q.get("themes") is None:
                inherit += 1
            else:
                own += 1
    return {"quotes": own + inherit, "attributed": own, "inheriting": inherit,
            "letters_pending": len(pending(letters))}


def _numbered(quotes: list[dict], positions: list[int]) -> str:
    return "\n\n".join(
        f"[{i}] {(quotes[i] or {}).get('quote', '')}" for i in positions)


def _theme_list(ids: list[str]) -> str:
    return "\n".join(f"- {t} ({THEMES.get(t, t)})" for t in ids)


def attribute(client, letter: dict) -> dict[int, list[str]]:
    """Ask which of the letter's themes each un-attributed passage is about.

    Returns position -> theme ids. Never raises on model trouble: a letter that
    cannot be read keeps inheriting, which is where it already was.
    """
    positions = quotes_needing_themes(letter)
    allowed = list(letter.get("themes") or [])
    if not positions or not allowed:
        return {}

    user = (
        f"Themes recorded for this letter ({letter.get('source') or 'letter'}"
        f"{', ' + letter['date'] if letter.get('date') else ''}):\n"
        f"{_theme_list(allowed)}\n\n"
        f"Passages extracted from it:\n\n"
        f"{_numbered(letter.get('quotes') or [], positions)}\n\n"
        f"For each numbered passage, which of the ids above is it about?"
    )

    try:
        response = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=900,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
        if getattr(response, "stop_reason", None) == "refusal":
            return {}
        raw = next((b.text for b in response.content
                    if getattr(b, "type", None) == "text"), "")
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 - a failed backfill must never lose a letter
        return {}
    if not isinstance(parsed, dict):
        return {}

    wanted = set(positions)
    allowed_set = set(allowed)
    out: dict[int, list[str]] = {}
    for row in parsed.get("passages") or []:
        if not isinstance(row, dict):
            continue
        i = row.get("index")
        if not isinstance(i, int) or isinstance(i, bool) or i not in wanted:
            continue
        # Subset of the letter's own ids, order preserved, deduplicated. The
        # model choosing an id nobody recorded for this letter would put a
        # theme on the page that the letter was never read for.
        seen: list[str] = []
        for t in row.get("themes") or []:
            # Normalised the same way the extractor normalises, so a reply of
            # "AI" matches the stored id rather than being discarded as unknown.
            norm = normalise_theme(t)
            if norm in allowed_set and norm not in seen:
                seen.append(norm)
        out[i] = seen
    return out


def apply_to_letter(client, letter: dict, base: Optional[Path] = None) -> int:
    """Attribute one letter's quotes and write them back. Returns quotes fixed.

    The stored record is re-read and matched by ``message_id`` rather than
    written from the in-memory copy, so a concurrent sweep that added a letter
    to the same organisation is not clobbered.
    """
    attributed = attribute(client, letter)
    if not attributed:
        return 0

    org = letter.get("org") or ""
    mid = letter.get("message_id")
    data = store.load(org, base)
    target = next((x for x in data.get("letters") or []
                   if x.get("message_id") == mid), None)
    if target is None:
        return 0

    quotes = target.get("quotes") or []
    fixed = 0
    for i, themes in attributed.items():
        if 0 <= i < len(quotes) and isinstance(quotes[i], dict):
            quotes[i]["themes"] = themes
            fixed += 1
    if fixed:
        store.save(data, base)
    return fixed


def run(client, limit: int = 0, base: Optional[Path] = None,
        on_progress=None, check_cancel=None) -> dict:
    """Work through the letters that still inherit, oldest first.

    ``limit`` caps letters per run so the cost is chosen by the caller rather
    than by however much history happens to be on disk. What was left is
    reported rather than implied.

    Each letter is written back as it is finished, so cancelling keeps
    everything already paid for.

    Serial on purpose. The store keeps one file per organisation, and
    ``apply_to_letter`` re-reads it before saving; two letters from the same
    manager running at once would race on that file and one would lose its
    attribution. At roughly nine seconds a letter the wait is tolerable for a
    one-off repair, where a lost write would not be.
    """
    letters = store.all_letters(base)
    todo = pending(letters)
    by_id = {(x.get("org", ""), x.get("message_id")): x for x in letters}

    taken = todo[:limit] if limit and limit > 0 else todo
    quotes_fixed = letters_done = examined = 0
    for row in taken:
        if check_cancel and check_cancel():
            break
        if on_progress:
            on_progress(examined, len(taken), row.get("org", ""))
        examined += 1
        letter = by_id.get((row["org"], row["message_id"]))
        if letter is None:
            continue
        fixed = apply_to_letter(client, letter, base)
        if fixed:
            letters_done += 1
            quotes_fixed += fixed
    if on_progress:
        on_progress(examined, len(taken), "")

    return {
        "letters_examined": examined,
        "letters_updated": letters_done,
        "quotes_attributed": quotes_fixed,
        "letters_remaining": max(0, len(todo) - examined),
    }
