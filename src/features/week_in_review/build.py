"""Orchestrator: Notion -> derive -> model -> the WeekInReview dict the
frontend renders. Deliberately dumb — the expensive parts (page-body reads,
the model call) happen once per week and the result is what api/main.py
persists via store.save_review."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.config import REASONING_MODEL

from . import derive, extract, summarise


NO_REASON = ("Recorded as declined in Notion. No reason for the decline appears "
             "in this week's notes.")


def _declined_rows(summary: dict, funds: list[dict]) -> list[dict]:
    """Every declined fund as a full row, whether or not a reason was evidenced.

    Declining a fund is something that moved — it is a decision the desk took —
    so it belongs in the same table as everything else that moved, with the
    same four fields filled in. A bare list of names told the reader a decision
    had happened while withholding what it was about.

    Only the *source* of each field differs. Name, status and url come off the
    Notion record. Focus is the model's line when it wrote one, and the fund's
    own geography and asset class when it did not. The why is the model's
    grounded sentence, or — where nothing in the notes explained the decline —
    a statement that nothing was recorded. What this never does is invent a
    rationale to fill the column, which is why ``why_evidenced`` travels with
    the row: the page can show the difference rather than flatten it.
    """
    grounded = {d["id"]: d for d in summary["declined"]}
    # A fund can be written up under "what moved" *and* be declined. Prefer the
    # decline rationale, fall back to what the model said about the move.
    also_moved = {m["id"]: m for m in summary["moved"]}
    rows = []
    for f in derive.declined_funds(funds):
        src = grounded.get(f["id"]) or also_moved.get(f["id"])
        rows.append({
            "id": f["id"], "url": f.get("url", ""), "name": f["name"],
            "status": f["status"],
            "focus": (src or {}).get("focus") or derive.focus_label(f),
            "why": (src or {}).get("why") or NO_REASON,
            "declined": True,
            "why_evidenced": bool(src and (src.get("why") or "").strip()),
        })
    return rows


def build(client, notion, window: Optional[dict] = None) -> dict:
    window = window or derive.prior_week()
    raw = extract.fetch_week(notion, window)
    stats = derive.derive_stats(raw)
    summary = summarise.summarise(client, window, stats, raw["funds"], raw["notes"])

    declined_rows = _declined_rows(summary, raw["funds"])
    declined_ids = {d["id"] for d in declined_rows}
    # One row per fund: anything already carried as declined is dropped from the
    # plain moved list rather than printed twice.
    moved = [{**m, "declined": False, "why_evidenced": True}
             for m in summary["moved"] if m["id"] not in declined_ids] + declined_rows

    return {
        "window": window,
        "window_label": derive.window_label(window),
        "ref": derive.iso_week_ref(window),
        "headline": summary["headline"],
        "standfirst": summary["standfirst"],
        "stats": stats,
        "urgent": summary.get("urgent"),
        "moved": moved,
        # Kept so a review stored under the previous shape still renders, and
        # so the header's declined summary has names to show.
        "declined": summary["declined"],
        "declined_names": derive.declined_names(raw["funds"]),
        "reads": summary["reads"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"model": REASONING_MODEL, "prompt_version": summarise.PROMPT_VERSION},
    }
