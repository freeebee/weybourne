"""Extracted correspondence, one file per organisation.

``data/inbox_signal/voices/<slug>.json`` holds everything the extractor found in
one manager's letters, across every sampled window:

    {"org": "Albizia",
     "letters": [
       {"message_id": "...", "period": "p0", "date": "2025-09-05",
        "person": "CR", "stance": "cautious", "themes": ["asean"],
        "subject": "Albizia ASEAN Monthly - August 2025",
        "source": "August 2025 monthly letter",
        "quotes": [{"quote": "...", "context": "..."}],
        "reported_returns": [{"month": "2025-08", "pct": -1.9, "fund": "Opportunities Fund"}]}
     ]}

Grouping by organisation rather than by message is what makes the dashboard's
central question cheap to answer: *how has this manager's stance moved across
the five windows*. A message-keyed store would need a full scan and a regroup
for every view; this shape is one file read per manager.

Follows the file-store idiom already used by ``src/features/managers.py`` —
including its ``base`` injection, so tests never touch real data. It reuses that
module's ``slug`` helper deliberately: the two features are unrelated (that one
is a CRM contact store, this one is investment correspondence) but a slug is a
slug, and a second copy would be a second thing to keep in step.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src import config
from src.features.managers import slug

VOICES_DIR = config.BASE_DIR / "data" / "inbox_signal" / "voices"


def _dir(base: Optional[Path] = None) -> Path:
    return base or VOICES_DIR


def _path(org: str, base: Optional[Path] = None) -> Path:
    return _dir(base) / f"{slug(org)}.json"


def load(org: str, base: Optional[Path] = None) -> dict:
    """One organisation's record, or a blank one."""
    p = _path(org, base)
    if not p.exists():
        return {"org": org, "letters": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"org": org, "letters": []}
    data.setdefault("org", org)
    data.setdefault("letters", [])
    return data


def save(data: dict, base: Optional[Path] = None) -> None:
    d = _dir(base)
    d.mkdir(parents=True, exist_ok=True)
    _path(data["org"], base).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def add_letter(org: str, letter: dict, base: Optional[Path] = None) -> None:
    """Record one extracted letter, replacing any earlier take on that message.

    Keying on ``message_id`` makes re-extraction idempotent. The manifest should
    already prevent a second pass, but a store that quietly accumulated
    duplicates would inflate every count on the dashboard — belt and braces on
    the one invariant the whole feature's honesty rests on.
    """
    data = load(org, base)
    mid = letter.get("message_id")
    data["letters"] = [x for x in data["letters"] if x.get("message_id") != mid]
    data["letters"].append(letter)
    data["letters"].sort(key=lambda x: (x.get("date") or "", x.get("message_id") or ""))
    save(data, base)


def list_all(base: Optional[Path] = None) -> list[dict]:
    """Every organisation's record, alphabetical."""
    d = _dir(base)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("org"):
            data.setdefault("letters", [])
            out.append(data)
    return out


def all_letters(base: Optional[Path] = None) -> list[dict]:
    """Every letter from every organisation, flattened, with ``org`` attached.

    The natural input for the correspondence log and for the cross-manager
    passes (themes, conflicts), which care about what was said and when rather
    than who filed it.
    """
    out = []
    for rec in list_all(base):
        for letter in rec.get("letters", []):
            out.append({**letter, "org": rec["org"]})
    out.sort(key=lambda x: x.get("date") or "")
    return out


def counts(base: Optional[Path] = None) -> dict:
    """Orgs and letters held, per period — feeds the sampled-window header."""
    per_period: dict[str, dict] = {}
    for letter in all_letters(base):
        p = letter.get("period") or "?"
        slot = per_period.setdefault(p, {"letters": 0, "orgs": set()})
        slot["letters"] += 1
        slot["orgs"].add(letter.get("org", ""))
    return {
        p: {"letters": v["letters"], "orgs": len(v["orgs"] - {""})}
        for p, v in per_period.items()
    }
