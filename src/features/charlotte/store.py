"""Snapshot and cache IO for Charlotte's Web.

The graph snapshot lives under data/ (safe to write any time — data/ is
not watched by uvicorn's reloader) and is written atomically, so a crawl
killed mid-flight leaves the previous web intact.

The built in-memory graph is memoized per file generation: the identity of
the SOURCE here is the snapshot file itself, so the memo keys on
(mtime_ns, size) of both the snapshot and the inferred cache — the same
source-identity idea as api.main._travel_directory_cached, adapted from
"same list object" to "same file bytes".
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from src.features.charlotte import graph as graphmod

_DATA = Path("data")


def snapshot_path(base: Optional[Path] = None) -> Path:
    return Path(base or _DATA) / "charlotte_graph.json"


def inferred_path(base: Optional[Path] = None) -> Path:
    return Path(base or _DATA) / "charlotte_inferred.json"


def load_snapshot(base: Optional[Path] = None) -> Optional[dict]:
    try:
        return json.loads(snapshot_path(base).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(snap: dict, base: Optional[Path] = None) -> None:
    p = snapshot_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def load_inferred(base: Optional[Path] = None) -> dict:
    try:
        return json.loads(inferred_path(base).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _enrich_from_notion_cache(snap: dict, base: Optional[Path] = None) -> None:
    """STOPGAP: snapshots crawled before 23 Aug 2026 lack asset_class /
    geography on fund nodes (weave dropped them). Join them once from the
    shared notion cache, which is keyed by the same Notion page UUIDs.
    Becomes dead weight after the next crawl — delete once every snapshot
    in the wild carries asset_class."""
    nodes = snap.get("nodes") or {}
    funds = [n for n in nodes.values() if n.get("kind") == "fund"]
    if not funds or any("asset_class" in n for n in funds):
        return
    try:
        cache = json.loads((Path(base or _DATA) / "notion_cache.json")
                           .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    records = (cache.get("funds") or {}).get("records") or {}
    if isinstance(records, list):
        records = {str(r.get("id", "")): r for r in records}

    def clean(v) -> list:
        return [s for s in (str(x).strip() for x in (v or [])) if s]

    for nid, n in nodes.items():
        if n.get("kind") != "fund":
            continue
        rec = records.get(nid) or {}
        n["asset_class"] = clean(rec.get("asset_class"))
        n["geography"] = clean(rec.get("geographic_focus"))


def _sig(p: Path):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


_CACHE: Optional[tuple] = None
_LOCK = threading.Lock()


def cached_graph(base: Optional[Path] = None) -> Optional[dict]:
    """The built graph for the current snapshot (+ inferred cache), built at
    most once per file generation. None until a crawl has produced one."""
    global _CACHE
    key = (_sig(snapshot_path(base)), _sig(inferred_path(base)))
    if key[0] is None:
        return None
    with _LOCK:
        if _CACHE and _CACHE[0] == key:
            return _CACHE[1]
        snap = load_snapshot(base)
        if not snap:
            return None
        _enrich_from_notion_cache(snap, base)
        g = graphmod.build_graph(snap, load_inferred(base))
        _CACHE = (key, g)
        return g
