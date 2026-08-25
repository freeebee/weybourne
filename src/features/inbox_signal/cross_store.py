"""Verdicts from the cross-document pass, so no pair is ever judged twice.

``views.py`` recomputes on every page load, which is why everything in it is
counting rather than reasoning. The two views that genuinely need a model —
a manager reversing their position across windows, and two managers answering
the same question oppositely — therefore need somewhere to put an answer once
it has been paid for. This is that place.

The rule mirrors ``manifest.py``: **a key present here is never sent to a model
again.** In particular a *negative* verdict is stored like any other. "These two
letters are not actually a reversal" costs exactly as much to establish as the
positive case, and a cache that only remembered the hits would re-buy every
near-miss on every run — which, since most candidate pairs are near-misses, is
where nearly all the money would go.

Stored at ``data/inbox_signal/cross.json``. ``base`` is injectable throughout so
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

CROSS_DIR = config.BASE_DIR / "data" / "inbox_signal"
CROSS_NAME = "cross.json"

REVERSAL = "reversal"
CONFLICT = "conflict"

_lock = threading.Lock()


def _path(base: Optional[Path] = None) -> Path:
    return (base or CROSS_DIR) / CROSS_NAME


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _blank() -> dict:
    return {"verdicts": {}, "runs": []}


def load(base: Optional[Path] = None) -> dict:
    """The stored verdicts, or an empty set. A corrupt file is treated as empty.

    As with the manifest, unreadable JSON costs a re-judge rather than wedging
    the feature shut — re-judging is only ever a cost, never a correctness
    problem, because a verdict is a function of the two letters alone.
    """
    p = _path(base)
    if not p.exists():
        return _blank()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    data.setdefault("verdicts", {})
    data.setdefault("runs", [])
    return data


def save(data: dict, base: Optional[Path] = None) -> None:
    """Write atomically — a half-written file would re-judge every pair."""
    p = _path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def judged(data: dict, key: str) -> bool:
    """Whether this pair already has a verdict, positive or negative."""
    return key in data.get("verdicts", {})


def record(data: dict, key: str, verdict: dict) -> None:
    data.setdefault("verdicts", {})[key] = {**verdict, "at": _now()}


def held(data: dict, kind: str) -> list[dict]:
    """Confirmed findings of one kind, newest first.

    Only findings the model affirmed AND that carry both of their quotes. A
    reversal shown without the two lines that make it one is an assertion about
    a named person with nothing behind it, which is precisely what this feature
    exists not to do.
    """
    out = [
        {**v, "key": k} for k, v in data.get("verdicts", {}).items()
        if v.get("kind") == kind and v.get("found") and v.get("quotes")
    ]
    out.sort(key=lambda v: v.get("sort_date") or "", reverse=True)
    return out


def record_run(data: dict, summary: dict) -> None:
    """Append a run summary, keeping the last few for the UI's cost display."""
    data.setdefault("runs", []).append({"at": _now(), **summary})
    data["runs"] = data["runs"][-10:]


def stats(data: dict) -> dict:
    verdicts = data.get("verdicts", {})
    found = {REVERSAL: 0, CONFLICT: 0}
    for v in verdicts.values():
        if v.get("found") and v.get("quotes") and v.get("kind") in found:
            found[v["kind"]] += 1
    return {
        "pairs_judged": len(verdicts),
        "reversals": found[REVERSAL],
        "conflicts": found[CONFLICT],
        "last_run": (data.get("runs") or [{}])[-1],
    }


class Cross:
    """Load-mutate-save wrapper, held under a module lock for the whole block.

    Same reasoning as ``manifest.Manifest``: the pass runs on a background
    thread while API reads happen on request threads, and the atomic write
    above protects the file but not a read-modify-write race.
    """

    def __init__(self, base: Optional[Path] = None):
        self.base = base
        self.data: dict = {}

    def __enter__(self) -> "Cross":
        _lock.acquire()
        self.data = load(self.base)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                save(self.data, self.base)
        finally:
            _lock.release()
