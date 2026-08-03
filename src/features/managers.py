"""Manager threads — one persistent context per manager.

A thread is a small JSON file that follows a manager through the whole app:
triage links it to Notion records, prep stamps its latest briefing and key
questions, the note taker preloads it, and saved Notion notes land in its
history. Everything here is pure file I/O plus the dedupe name scorer — no
network, no model calls — so it is fully unit-testable.

File shape (data/managers/<slug>.json):
    {"entity": "Fife Capital", "aliases": ["FIFECAPITAL", "Allan Fife"],
     "email": "...", "company_id": "...", "company_name": "...",
     "fund_id": "...", "fund_name": "...", "contact_id": "...",
     "contact_name": "...", "questions": [{"q": ..., "src": ...}],
     "history": [{"kind": "prep|note|triage", "at": "2026-08-03", ...}],
     "updated": iso}
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from src import config
from src.features.dedupe import _name_score, normalize_name

MANAGERS_DIR = config.BASE_DIR / "data" / "managers"

# A thread's history is a running relationship timeline, not a full log.
_HISTORY_CAP = 40
_MATCH_THRESHOLD = 0.72

_ID_FIELDS = ("email", "company_id", "company_name", "fund_id", "fund_name",
              "contact_id", "contact_name")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "unnamed"


def _path(name: str, base: Path | None = None) -> Path:
    return (base or MANAGERS_DIR) / f"{slug(name)}.json"


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent or corrupt → no thread
        return None


def _save(data: dict, base: Path | None = None) -> None:
    d = base or MANAGERS_DIR
    d.mkdir(parents=True, exist_ok=True)
    _path(data["entity"], d).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _blank(name: str) -> dict:
    return {"entity": name, "aliases": [], "email": "",
            "company_id": "", "company_name": "", "fund_id": "", "fund_name": "",
            "contact_id": "", "contact_name": "",
            "questions": [], "history": [], "updated": ""}


def find(query: str, base: Path | None = None) -> dict | None:
    """The best-matching thread for a name, or None.

    Exact slug first; otherwise fuzzy over entity + aliases using the dedupe
    name scorer, plus containment so "Meeting with Fife Capital" still finds
    the "Fife Capital" thread.
    """
    d = base or MANAGERS_DIR
    if not query:
        return None
    exact = _load(_path(query, d))
    if exact:
        return exact
    if not d.exists():
        return None
    q_norm = normalize_name(query)
    best, best_score = None, 0.0
    for f in d.glob("*.json"):
        data = _load(f)
        if not data:
            continue
        for name in [data.get("entity", ""), *(data.get("aliases") or [])]:
            if not name:
                continue
            score = _name_score(query, name)
            n_norm = normalize_name(name)
            if n_norm and q_norm and (n_norm in q_norm or q_norm in n_norm):
                score = max(score, 0.95)
            if score > best_score:
                best, best_score = data, score
    return best if best and best_score >= _MATCH_THRESHOLD else None


def upsert(name: str, *, aliases: list[str] | None = None,
           questions: list[dict] | None = None,
           add_history: dict | None = None,
           base: Path | None = None, **fields) -> dict:
    """Create or update the thread for ``name``.

    Attaches to an existing thread by fuzzy match (so "FIFECAPITAL" updates
    the "Fife Capital" thread rather than spawning a twin). Non-empty
    ``fields`` overwrite; ``questions`` replaces the list only when given;
    history entries are appended newest-last and capped.
    """
    data = find(name, base) or _blank(name)

    # Track every name the manager goes by.
    for alias in [name, *(aliases or [])]:
        alias = (alias or "").strip()
        if (alias and alias.lower() != data["entity"].strip().lower()
                and alias not in data["aliases"]):
            data["aliases"].append(alias)

    for k in _ID_FIELDS:
        v = (fields.get(k) or "").strip() if isinstance(fields.get(k), str) else fields.get(k)
        if v:
            data[k] = v

    if questions is not None:
        seen, deduped = set(), []
        for q in questions:
            text = (q.get("q") or "").strip()
            if text and text not in seen:
                seen.add(text)
                deduped.append(q)
        data["questions"] = deduped

    if add_history:
        entry = {"at": dt.date.today().isoformat(), **add_history}
        data["history"].append(entry)
        data["history"] = data["history"][-_HISTORY_CAP:]

    data["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    _save(data, base)
    return data


def list_all(base: Path | None = None) -> list[dict]:
    """Thread summaries, most recently touched first — feeds the picker."""
    d = base or MANAGERS_DIR
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        data = _load(f)
        if not data:
            continue
        notes = sum(1 for h in data.get("history", []) if h.get("kind") == "note")
        preps = [h for h in data.get("history", []) if h.get("kind") == "prep"]
        out.append({
            "entity": data.get("entity", ""),
            "updated": data.get("updated", ""),
            "questions": len(data.get("questions", [])),
            "notes": notes,
            "last_prep": preps[-1].get("at", "") if preps else "",
            "company_name": data.get("company_name", ""),
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def migrate_legacy_questions(questions_dir: Path, base: Path | None = None) -> int:
    """One-time absorb of the old per-entity question files into threads.

    Idempotent: a legacy file is only imported when no thread matches its
    entity yet; the legacy file itself is left untouched.
    """
    if not questions_dir.exists():
        return 0
    imported = 0
    for f in questions_dir.glob("*.json"):
        data = _load(f)
        if not data or not data.get("entity"):
            continue
        if find(data["entity"], base):
            continue
        upsert(data["entity"], aliases=data.get("aliases") or [],
               questions=data.get("questions") or [], base=base)
        imported += 1
    return imported
