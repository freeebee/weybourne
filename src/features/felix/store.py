"""Felix's disk persistence under data/felix/.

    runs/<run_id>.json        RunRecord
    changes/<run_id>.json     list[ChangeRecord] for the run
    snapshots/<change_id>.json  RAW Notion payloads (before / planned after;
                                merges: both full pages + inbound relations).
                                The authoritative undo source — undo REFUSES
                                without it rather than reconstructing values
                                from display text.
    config.json               live_enabled, auto-run settings

Change ids are FLX-<yyyymmdd>-<run6>-<seq4>: sortable, unique, greppable.
All functions take an optional base dir so tests run against tmp paths.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import BASE_DIR
from src.features.felix.models import ChangeRecord, RunRecord

FELIX_DIR = BASE_DIR / "data" / "felix"


def _dirs(base: Optional[Path]) -> tuple[Path, Path, Path]:
    root = base or FELIX_DIR
    return root / "runs", root / "changes", root / "snapshots"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def change_id_for(run_id: str, seq: int, when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    return f"FLX-{when:%Y%m%d}-{run_id[:6]}-{seq:04d}"


# -- runs ------------------------------------------------------------------- #

def save_run(run: RunRecord, base: Optional[Path] = None) -> None:
    runs, _, _ = _dirs(base)
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run.run_id}.json").write_text(
        run.model_dump_json(indent=1), encoding="utf-8")


def load_run(run_id: str, base: Optional[Path] = None) -> Optional[RunRecord]:
    runs, _, _ = _dirs(base)
    path = runs / f"{run_id}.json"
    if not path.exists():
        return None
    return RunRecord(**json.loads(path.read_text(encoding="utf-8")))


def list_runs(base: Optional[Path] = None, limit: int = 50) -> list[RunRecord]:
    runs, _, _ = _dirs(base)
    if not runs.exists():
        return []
    out = []
    for p in sorted(runs.glob("*.json"), key=lambda p: p.stat().st_mtime,
                    reverse=True)[:limit]:
        try:
            out.append(RunRecord(**json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001 - one corrupt file must not hide the rest
            continue
    return out


# -- changes ---------------------------------------------------------------- #

def save_changes(run_id: str, changes: list[ChangeRecord],
                 base: Optional[Path] = None) -> None:
    _, ch, _ = _dirs(base)
    ch.mkdir(parents=True, exist_ok=True)
    (ch / f"{run_id}.json").write_text(
        json.dumps([c.model_dump() for c in changes], indent=1),
        encoding="utf-8")


def load_changes(run_id: str, base: Optional[Path] = None) -> list[ChangeRecord]:
    _, ch, _ = _dirs(base)
    path = ch / f"{run_id}.json"
    if not path.exists():
        return []
    return [ChangeRecord(**c)
            for c in json.loads(path.read_text(encoding="utf-8"))]


def append_change(change: ChangeRecord, base: Optional[Path] = None) -> None:
    changes = load_changes(change.run_id, base)
    changes = [c for c in changes if c.change_id != change.change_id] + [change]
    save_changes(change.run_id, changes, base)


def find_change(change_id: str, base: Optional[Path] = None) -> Optional[ChangeRecord]:
    _, ch, _ = _dirs(base)
    if not ch.exists():
        return None
    # The run prefix is embedded in the id — try the matching file first.
    prefix = change_id.split("-")[2] if change_id.count("-") >= 3 else ""
    files = sorted(ch.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files.sort(key=lambda p: 0 if p.stem.startswith(prefix) else 1)
    for path in files:
        try:
            for c in json.loads(path.read_text(encoding="utf-8")):
                if c.get("change_id") == change_id:
                    return ChangeRecord(**c)
        except Exception:  # noqa: BLE001
            continue
    return None


def update_change(change_id: str, patch: dict, base: Optional[Path] = None) -> bool:
    _, ch, _ = _dirs(base)
    if not ch.exists():
        return False
    for path in ch.glob("*.json"):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        hit = False
        for c in rows:
            if c.get("change_id") == change_id:
                c.update(patch)
                hit = True
        if hit:
            path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
            return True
    return False


def list_all_changes(base: Optional[Path] = None, status: str = "",
                     review: str = "", db: str = "", change_type: str = "",
                     run_id: str = "", limit: int = 200,
                     offset: int = 0) -> list[ChangeRecord]:
    """Newest-run-first flat list with filters — feeds the review UI."""
    _, ch, _ = _dirs(base)
    if not ch.exists():
        return []
    files = ([ch / f"{run_id}.json"] if run_id
             else sorted(ch.glob("*.json"), key=lambda p: p.stat().st_mtime,
                         reverse=True))
    out: list[ChangeRecord] = []
    for path in files:
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for c in reversed(rows):
            if status and c.get("execution_status") != status:
                continue
            if review and c.get("review_status") != review:
                continue
            if db and c.get("database") != db:
                continue
            if change_type and c.get("change_type") != change_type:
                continue
            out.append(ChangeRecord(**c))
    return out[offset:offset + limit]


# -- snapshots -------------------------------------------------------------- #

def save_snapshot(change_id: str, payload: dict, base: Optional[Path] = None) -> Path:
    _, _, snaps = _dirs(base)
    snaps.mkdir(parents=True, exist_ok=True)
    path = snaps / f"{change_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def load_snapshot(change_id: str, base: Optional[Path] = None) -> Optional[dict]:
    _, _, snaps = _dirs(base)
    path = snaps / f"{change_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt snapshot = no snapshot
        return None


# -- resolved duplicate pairs ----------------------------------------------- #
# Once a pair is decided — by the user clearing a possible-duplicate flag, or
# by confident web research — future runs neither re-flag it nor spend another
# web search on it.

def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a or "", b or "")))


def load_resolved_pairs(base: Optional[Path] = None) -> dict:
    root = base or FELIX_DIR
    path = root / "resolved_pairs.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("pairs", {})
    except Exception:  # noqa: BLE001
        return {}


def resolve_pair(a: str, b: str, decision: str,
                 base: Optional[Path] = None) -> None:
    root = base or FELIX_DIR
    root.mkdir(parents=True, exist_ok=True)
    pairs = load_resolved_pairs(base)
    pairs[pair_key(a, b)] = {"decision": decision,
                             "at": datetime.now().isoformat(timespec="seconds")}
    (root / "resolved_pairs.json").write_text(
        json.dumps({"pairs": pairs}, indent=1), encoding="utf-8")


# -- config ----------------------------------------------------------------- #

_DEFAULT_CONFIG = {
    "live_enabled": False,           # dry-run until the user flips this in the UI
    "auto_run_enabled": True,
    "auto_run_hour": 7,              # local time
    "last_auto_run_date": "",
}


def load_config(base: Optional[Path] = None) -> dict:
    root = base or FELIX_DIR
    path = root / "config.json"
    cfg = dict(_DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return cfg


def save_config(cfg: dict, base: Optional[Path] = None) -> None:
    root = base or FELIX_DIR
    root.mkdir(parents=True, exist_ok=True)
    merged = load_config(base)
    merged.update(cfg)
    (root / "config.json").write_text(json.dumps(merged, indent=1),
                                      encoding="utf-8")


# -- stats ------------------------------------------------------------------ #

def stats(base: Optional[Path] = None) -> dict:
    """All-time counts for the game HUD, aggregated from the run change logs."""
    from datetime import date

    today = date.today().isoformat()
    out = {"applied_total": 0, "applied_today": 0, "undone": 0, "failed": 0,
           "recommendations": 0, "by_db": {}, "by_type": {}, "runs": 0,
           "last_run": None}
    for run in list_runs(base, limit=1000):
        out["runs"] += 1
        if out["last_run"] is None:
            out["last_run"] = {"run_id": run.run_id, "started": run.started,
                               "status": run.status, "dry_run": run.dry_run,
                               "counts": run.counts}
    for c in list_all_changes(base, limit=100000):
        if c.execution_status == "Applied":
            out["applied_total"] += 1
            if c.timestamp[:10] == today:
                out["applied_today"] += 1
            out["by_db"][c.database] = out["by_db"].get(c.database, 0) + 1
            out["by_type"][c.change_type] = out["by_type"].get(c.change_type, 0) + 1
        elif c.execution_status == "Undone":
            out["undone"] += 1
        elif c.execution_status == "Failed":
            out["failed"] += 1
        if c.change_type == "recommendation":
            out["recommendations"] += 1
    return out
