"""Live-meeting transcript persistence.

A recording session exists only in the browser's memory, which makes a closed
tab or a crash unrecoverable. Two disk-backed layers fix that:

* **Autosave** — while recording, the note taker posts its running state every
  few seconds and it lands in ``data/live_sessions/<id>.json``. A crash
  mid-meeting now loses at most a few seconds.
* **Library** — pressing Stop finalises the session into ``data/transcripts/``,
  the permanent transcript library, and removes the autosave file. Any autosave
  left behind by a crash still shows up in the library listing, flagged
  unfinished, so nothing silently disappears.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.config import BASE_DIR

LIVE_DIR = BASE_DIR / "data" / "live_sessions"
LIB_DIR = BASE_DIR / "data" / "transcripts"


def _safe_id(sid: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "", str(sid))[:60] or "session"


def _prepare(record: dict) -> dict:
    rec = dict(record)
    rec["id"] = _safe_id(rec.get("id", ""))
    rec["title"] = (rec.get("who") or "").strip() or "Untitled meeting"
    rec["words"] = len((rec.get("transcript") or "").split())
    rec["saved_at"] = datetime.now().isoformat(timespec="seconds")
    return rec


def autosave(record: dict, live_dir: Path = None) -> Path:
    live_dir = live_dir or LIVE_DIR
    live_dir.mkdir(parents=True, exist_ok=True)
    rec = _prepare(record)
    path = live_dir / f"{rec['id']}.json"
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return path


def finish(record: dict, live_dir: Path = None, lib_dir: Path = None) -> dict:
    """Move a session into the permanent library; idempotent per id."""
    live_dir, lib_dir = live_dir or LIVE_DIR, lib_dir or LIB_DIR
    lib_dir.mkdir(parents=True, exist_ok=True)
    rec = _prepare(record)
    (lib_dir / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    stray = live_dir / f"{rec['id']}.json"
    if stray.exists():
        stray.unlink()
    return {"id": rec["id"], "title": rec["title"], "words": rec["words"]}


def _summary(path: Path, unfinished: bool) -> dict | None:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt file must not hide the rest
        return None
    return {
        "id": rec.get("id", path.stem),
        "title": rec.get("title") or rec.get("who") or "Untitled meeting",
        "started": rec.get("started", ""),
        "saved_at": rec.get("saved_at", ""),
        "words": rec.get("words", 0),
        "goal": rec.get("goal", ""),
        "unfinished": unfinished,
    }


def list_all(live_dir: Path = None, lib_dir: Path = None) -> list[dict]:
    """Library entries plus crash-orphaned autosaves, newest first."""
    live_dir, lib_dir = live_dir or LIVE_DIR, lib_dir or LIB_DIR
    out, seen = [], set()
    if lib_dir.exists():
        for p in lib_dir.glob("*.json"):
            s = _summary(p, unfinished=False)
            if s:
                out.append(s)
                seen.add(s["id"])
    if live_dir.exists():
        for p in live_dir.glob("*.json"):
            if p.stem in seen:
                continue
            s = _summary(p, unfinished=True)
            if s:
                out.append(s)
    out.sort(key=lambda s: s.get("started") or s.get("saved_at") or "", reverse=True)
    return out


def load(sid: str, live_dir: Path = None, lib_dir: Path = None) -> dict | None:
    live_dir, lib_dir = live_dir or LIVE_DIR, lib_dir or LIB_DIR
    for base in (lib_dir, live_dir):
        path = base / f"{_safe_id(sid)}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
    return None
