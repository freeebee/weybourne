"""Preference screens already run, so the same manager is not screened twice.

The per-message work memory (``triage_memory.record_work``) already keeps a
screen alive for the message it was run on. This is the other half: a screen is
about a **firm**, not about an email. When the same manager writes again — a
follow-up, a data-room link, a second fund — the message id is new and the work
memory has nothing, so the screen is bought again at a couple of minutes and a
model call, to reach the conclusion already on file.

Keyed with ``web_research.research_key``, which is already the app's notion of
"which counterparty is this" for research dossiers: the firm, not the person and
not the vintage. A screen of Fund IV and a screen of Fund V are the same firm
against the same preference pages, and the desk reads them as one view.

**A remembered screen is always labelled as remembered, with its date.** That is
the whole basis on which reuse is honest here. Unlike a triaged email — where
the verdict is about a message that does not change — a screen is a judgement
about an opportunity we may since have learnt more about. So it is offered as
"this is what we concluded on the 3rd", never as a fresh reading, and re-running
is one click. The expiry below is a backstop, not the safeguard; the label is.

Stored at ``data/screen_memory.json``. ``base`` is injectable throughout so
tests never touch the real file.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path
from typing import Optional

from src import config
from src.features.web_research import research_key

MEMORY_DIR = config.BASE_DIR / "data"
MEMORY_NAME = "screen_memory.json"

# Longer than triage memory, because what it depends on moves more slowly: the
# CHAO preference pages (themselves cached for a week) and the desk's own view
# of a firm. Override with SCREEN_MEMORY_DAYS.
MEMORY_DAYS = int(os.environ.get("SCREEN_MEMORY_DAYS", "45"))

_lock = threading.Lock()


def _path(base: Optional[Path] = None) -> Path:
    return (base or MEMORY_DIR) / MEMORY_NAME


def _now() -> dt.datetime:
    return dt.datetime.now()


def key_for(fund_name: str = "", company_name: str = "") -> str:
    """The firm this screen is about. Empty when there is nothing to key on."""
    return research_key(fund_name or company_name or "", company_name or "")


def load(base: Optional[Path] = None) -> dict:
    """The store, or an empty one. A corrupt file is treated as empty —
    re-screening costs time, a wedged feature costs the whole workflow."""
    p = _path(base)
    if not p.exists():
        return {"screens": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"screens": {}}
    if not isinstance(data, dict):
        return {"screens": {}}
    data.setdefault("screens", {})
    return data


def save(data: dict, base: Optional[Path] = None) -> None:
    p = _path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def record(data: dict, key: str, screen: dict, *, label: str = "") -> None:
    """Keep one screen. A screen that failed is not worth remembering."""
    if not key or not screen or screen.get("error"):
        return
    data.setdefault("screens", {})[key] = {
        "at": _now().isoformat(timespec="seconds"),
        "label": label,
        # Stored without any remembered-marker of its own: that is added on the
        # way out, so a screen recalled and re-saved never accumulates them.
        "screen": {k: v for k, v in screen.items() if k != "remembered"},
    }


def _age_days(entry: dict) -> Optional[float]:
    try:
        return (_now() - dt.datetime.fromisoformat(entry["at"])).total_seconds() / 86400
    except (KeyError, ValueError, TypeError):
        return None


def screen_for(data: dict, key: str) -> Optional[dict]:
    """The remembered screen for a firm, tagged with when it was taken.

    The ``remembered`` block is the point: the caller renders it so the reader
    knows they are looking at a conclusion from a previous sitting, and can ask
    for a fresh one.
    """
    entry = (data.get("screens") or {}).get(key)
    if not entry or not entry.get("screen"):
        return None
    age = _age_days(entry)
    if age is None or age > MEMORY_DAYS:
        return None
    return {
        **entry["screen"],
        "remembered": {
            "at": entry["at"],
            "days": int(age),
            "label": entry.get("label", ""),
        },
    }


def forget(data: dict, key: str) -> bool:
    return (data.get("screens") or {}).pop(key, None) is not None


def prune(data: dict) -> int:
    """Drop expired entries. Returns how many went."""
    screens = data.get("screens") or {}
    stale = [k for k, e in screens.items()
             if (_age_days(e) or MEMORY_DAYS + 1) > MEMORY_DAYS]
    for k in stale:
        screens.pop(k, None)
    return len(stale)


def stats(data: dict) -> dict:
    return {"screens": len(data.get("screens") or {}), "days": MEMORY_DAYS}


class Memory:
    """Load-mutate-save under a module lock, as triage_memory does — the triage
    job writes from a worker thread while requests read on another."""

    def __init__(self, base: Optional[Path] = None):
        self.base = base
        self.data: dict = {}

    def __enter__(self) -> "Memory":
        _lock.acquire()
        self.data = load(self.base)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                save(self.data, self.base)
        finally:
            _lock.release()
