"""Notion extraction for the weekly review — facts only, no interpretation.

The single most important detail: a note's "Thoughts / Considerations"
property is empty on a large minority of real notes while the actual
write-up sits in the page body. Reading only the property silently drops
those meetings from the review, and it fails quietly — a shorter, blander
page and no error. fetch_week always reads both.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

# Bounded concurrency: bodies are the slow part of a fetch (one block-tree
# walk per note), so they're pulled in parallel rather than one at a time,
# capped so a big week doesn't fan out into dozens of simultaneous requests
# against the shared per-integration rate limit.
_BODY_FETCH_CONCURRENCY = 5


def _fetch_bodies(notion, notes: list[dict]) -> dict[str, str]:
    def one(note: dict) -> tuple[str, str]:
        try:
            return note["id"], notion.get_page_text(note["id"], max_depth=2)
        except Exception:  # noqa: BLE001 - a missing body is not fatal to the week
            return note["id"], ""

    if not notes:
        return {}
    with ThreadPoolExecutor(max_workers=min(_BODY_FETCH_CONCURRENCY, len(notes))) as pool:
        return dict(pool.map(one, notes))


def fetch_week(notion, window: dict) -> dict:
    """{window, notes, funds, contacts} — the raw material derive.py and
    summarise.py work from. Every list is already mock-mode-safe (the
    connector methods themselves degrade to sample data with no token)."""
    notes = notion.list_notes_in_window(window["start"], window["end"])
    bodies = _fetch_bodies(notion, notes)
    notes = [{**n, "body": bodies.get(n["id"], "")} for n in notes]
    funds = notion.list_funds_touched(window["start"], window["end"])
    contacts = notion.list_contacts_created(window["start"], window["end"])
    return {"window": window, "notes": notes, "funds": funds, "contacts": contacts}
