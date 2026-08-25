"""What has already been triaged, so the same mail is not classified twice.

Inbox triage costs a model call per message. Without a record of what has been
done, every app open re-triages the whole lookback window — the same twenty
emails, the same twenty answers, paid for again. This is the record.

It is deliberately *not* the inbox-signal manifest. That one is absolute: an id
present there is never sent to a model again, because a manager letter's
extracted content does not change. A triaged email is different — the mailbox
moves on, a thread gets a reply, and a verdict from three weeks ago may no
longer describe the message's place in the inbox. So entries here expire.

On the expiry window: the obvious choice is a day, but that reintroduces the
exact problem it is meant to solve. ``TRIAGE_LOOKBACK_DAYS`` decides how far
back the inbox list reaches and is adjustable in the UI for catching up after
time away; if memory expires sooner than that, a message triaged on Monday is
back on Wednesday asking to be triaged again. The window therefore defaults
comfortably past any realistic lookback. Entries are three short strings and a
timestamp, so remembering longer costs effectively nothing, while remembering
too briefly costs a model call per message per app open.

Stored at ``data/triage_memory.json``. ``base`` is injectable throughout so
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

MEMORY_DIR = config.BASE_DIR / "data"
MEMORY_NAME = "triage_memory.json"

# Generous on purpose — see the module docstring. Override with
# TRIAGE_MEMORY_DAYS to make the app forget sooner.
MEMORY_DAYS = int(os.environ.get("TRIAGE_MEMORY_DAYS", "14"))

_lock = threading.Lock()


def _path(base: Optional[Path] = None) -> Path:
    return (base or MEMORY_DIR) / MEMORY_NAME


def _now() -> dt.datetime:
    return dt.datetime.now()


def load(base: Optional[Path] = None) -> dict:
    """The store, or an empty one. A corrupt file is treated as empty.

    Unreadable JSON costs a round of re-triage rather than wedging the feature:
    triage is idempotent, so redoing it is only ever a cost.
    """
    p = _path(base)
    if not p.exists():
        return {"messages": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"messages": {}}
    if not isinstance(data, dict):
        return {"messages": {}}
    data.setdefault("messages", {})
    return data


def save(data: dict, base: Optional[Path] = None) -> None:
    """Write atomically — a half-written file would re-triage everything."""
    p = _path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _age_days(stamp: str) -> float:
    """Age of an entry in days; a missing or unparseable stamp reads as ancient.

    Treating a bad timestamp as expired is the safe direction: the cost is one
    needless re-triage, where the opposite would hide a message forever.
    """
    try:
        return (_now() - dt.datetime.fromisoformat(stamp)).total_seconds() / 86400
    except (TypeError, ValueError):
        return float("inf")


def seen(data: dict, message_id: str, days: Optional[int] = None) -> bool:
    """Whether this message was triaged recently enough to skip."""
    rec = data.get("messages", {}).get(message_id)
    if not rec:
        return False
    return _age_days(rec.get("at", "")) <= (MEMORY_DAYS if days is None else days)


def record(data: dict, message_id: str, result: dict, *, subject: str = "") -> None:
    """Remember one triaged message, verdict and all.

    The whole result is kept rather than a bare "seen" marker. A skip-list
    would stop the app paying twice but would leave the row blank, so the
    reader could not tell a message that had been judged irrelevant from one
    nobody had looked at — and the only way to find out would be to triage it
    again. Storing the verdict means a remembered message comes back already
    answered.

    A result carrying an error is not stored: that is a failed attempt, not a
    verdict, and it should be retried rather than remembered.
    """
    if not isinstance(result, dict) or result.get("error"):
        return
    data.setdefault("messages", {})[message_id] = {
        "at": _now().isoformat(timespec="seconds"),
        "subject": subject[:160],
        "result": result,
    }


def result_for(data: dict, message_id: str) -> Optional[dict]:
    """The stored verdict, if it is still fresh."""
    if not seen(data, message_id):
        return None
    return (data.get("messages", {}).get(message_id) or {}).get("result")


def record_work(data: dict, message_id: str, patch: dict) -> bool:
    """Attach downstream work — reply drafts, a preference screen — to a verdict.

    Kept separate from ``record`` because it happens later and independently:
    drafts are generated after triage, sometimes minutes later, sometimes not
    at all. Each is its own model call, so remembering the verdict while
    forgetting the drafts still charges most of the cost again on the next app
    open — which is the whole thing this module exists to stop.

    Only attaches to a message already carrying a verdict. Drafts without the
    triage result they were written from are not worth restoring: the page
    needs the entity and the dedupe decision to render them at all.
    """
    rec = data.get("messages", {}).get(message_id)
    if not rec:
        return False
    work = {**(rec.get("work") or {}), **(patch or {})}
    # Never store a busy/error flag — those describe a moment, not the work.
    for transient in ("busy", "error", "notice"):
        work.pop(transient, None)
    rec["work"] = work
    return True


def work_for(data: dict, message_id: str) -> dict:
    """The stored drafts and screen for a message, or {}."""
    if not seen(data, message_id):
        return {}
    return (data.get("messages", {}).get(message_id) or {}).get("work") or {}


def triaged_at(data: dict, message_id: str) -> str:
    """When this message was triaged, or '' — lets the UI say so on the row."""
    rec = data.get("messages", {}).get(message_id)
    return (rec or {}).get("at", "") if rec and seen(data, message_id) else ""


def forget(data: dict, message_id: str) -> bool:
    """Drop one entry — the 're-triage this anyway' override."""
    return data.get("messages", {}).pop(message_id, None) is not None


def clear(data: dict) -> int:
    """Drop everything. Returns how many entries went."""
    n = len(data.get("messages", {}))
    data["messages"] = {}
    return n


def prune(data: dict, days: Optional[int] = None) -> int:
    """Drop expired entries so the file cannot grow without bound."""
    limit = MEMORY_DAYS if days is None else days
    msgs = data.get("messages", {})
    stale = [k for k, v in msgs.items() if _age_days(v.get("at", "")) > limit]
    for k in stale:
        msgs.pop(k, None)
    return len(stale)


def stats(data: dict) -> dict:
    msgs = data.get("messages", {})
    fresh = [k for k in msgs if seen(data, k)]
    return {"remembered": len(fresh), "stored": len(msgs), "days": MEMORY_DAYS}


class Memory:
    """Load-mutate-save wrapper, held under a module lock for the whole block.

    Triage jobs run on background threads while API reads happen on request
    threads; the atomic write protects the file but not a read-modify-write
    race between them.
    """

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
