"""What has already been read, so it is never read twice.

This is the module that makes the sweep safe to run automatically. The sweep
fires on app open, and every message it processes costs a model call; without a
record of what has already been done, each launch would re-extract the entire
sampled year. The rule is simple and absolute: **a message id present here is
never sent to a model again.**

It also tracks attachments, which have a third state beyond done and skipped.
Claude's Microsoft 365 connector cannot return attachment bytes, so a track
record arriving pre-Entra is recorded as ``pending``: known about, visible on
the watchlist, and queued so that the backlog parses itself the moment live
Graph access exists. ``pending`` is the one status that is *not* terminal —
everything else is a promise never to look again.

Stored at ``data/inbox_signal/manifest.json``. ``base`` is injectable
throughout so tests never touch the real file.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path
from typing import Optional

from src import config

MANIFEST_DIR = config.BASE_DIR / "data" / "inbox_signal"
MANIFEST_NAME = "manifest.json"

# Terminal message states — seen() treats these as "do not touch again".
DONE = "extracted"
SKIPPED = "skipped"
FAILED = "failed"

# Attachment states. PENDING is the only non-terminal one.
PARSED = "parsed"
PENDING = "pending"
IGNORED = "ignored"

_lock = threading.Lock()


def _path(base: Optional[Path] = None) -> Path:
    return (base or MANIFEST_DIR) / MANIFEST_NAME


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load(base: Optional[Path] = None) -> dict:
    """The manifest, or an empty one. A corrupt file is treated as empty.

    Treating unreadable JSON as empty means a damaged manifest costs a re-sweep
    rather than wedging the feature shut — the extractors are idempotent, so
    redoing work is only ever a cost, never a correctness problem.
    """
    p = _path(base)
    if not p.exists():
        return {"messages": {}, "sweeps": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"messages": {}, "sweeps": []}
    if not isinstance(data, dict):
        return {"messages": {}, "sweeps": []}
    data.setdefault("messages", {})
    data.setdefault("sweeps", [])
    return data


def save(data: dict, base: Optional[Path] = None) -> None:
    """Write atomically — a half-written manifest would re-extract everything."""
    p = _path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def seen(data: dict, message_id: str) -> bool:
    """Whether this message has already been handled, however it turned out.

    A failed extraction counts as seen. Retrying automatically on every app
    open would spend a model call per launch on a message that has already
    proven it cannot be parsed; clearing the entry by hand is the way to retry.
    """
    return message_id in data.get("messages", {})


def attachment_key(name: str, size: int, attachment_id: str = "") -> str:
    """Stable key for an attachment.

    Graph supplies an id; the connector bridge does not, so name+size stands in.
    That pair is not globally unique, but it only has to be unique *within one
    message*, which it is in practice.
    """
    return attachment_id or f"{name}:{size}"


def record_message(data: dict, message_id: str, *, status: str, period: str = "",
                   org: str = "", subject: str = "", reason: str = "",
                   attachments: Optional[dict] = None) -> None:
    data.setdefault("messages", {})[message_id] = {
        "status": status,
        "period": period,
        "org": org,
        "subject": subject[:160],
        "reason": reason,
        "at": _now(),
        "attachments": attachments or {},
    }


def pending_attachments(data: dict) -> list[dict]:
    """Every attachment awaiting bytes, newest message first.

    Feeds two things: the watchlist entry that says a track record arrived but
    could not be read, and the post-Entra backfill that clears the queue.
    """
    out = []
    for msg_id, rec in data.get("messages", {}).items():
        for key, att in (rec.get("attachments") or {}).items():
            if att.get("status") == PENDING:
                out.append({
                    "message_id": msg_id,
                    "key": key,
                    "name": att.get("name", ""),
                    "org": rec.get("org", ""),
                    "period": rec.get("period", ""),
                    "at": rec.get("at", ""),
                })
    out.sort(key=lambda a: a["at"], reverse=True)
    return out


def record_sweep(data: dict, summary: dict) -> None:
    """Append a sweep summary, keeping the last few for the UI's cost display."""
    data.setdefault("sweeps", []).append({"at": _now(), **summary})
    data["sweeps"] = data["sweeps"][-10:]


def stats(data: dict) -> dict:
    """Counts for the dashboard header and the sweep's own reporting."""
    msgs = data.get("messages", {})
    by_status: dict[str, int] = {}
    for rec in msgs.values():
        by_status[rec.get("status", "?")] = by_status.get(rec.get("status", "?"), 0) + 1
    return {
        "messages_seen": len(msgs),
        "by_status": by_status,
        "attachments_pending": len(pending_attachments(data)),
        "last_sweep": (data.get("sweeps") or [{}])[-1],
    }


class Manifest:
    """Load-mutate-save wrapper, so the sweep does not juggle the raw dict.

    Held under a module lock for the whole ``with`` block: the sweep runs on a
    background thread while API reads happen on request threads, and the atomic
    write above protects the file but not a read-modify-write race.
    """

    def __init__(self, base: Optional[Path] = None):
        self.base = base
        self.data: dict = {}

    def __enter__(self) -> "Manifest":
        _lock.acquire()
        self.data = load(self.base)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                save(self.data, self.base)
        finally:
            _lock.release()
