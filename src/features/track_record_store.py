"""Parsed track records, kept rather than thrown away.

``analyse_file`` (src/features/track_record.py) normalises an uploaded
spreadsheet or PDF into a ``TrackRecord``, and until now the API returned it and
discarded it. The factor-correlation view needs those return series to persist:
correlating a manager against a market factor takes a dozen-plus aligned months,
which no single email supplies.

Stored at ``data/track_records/<slug>.json``, one file per fund, holding the
**whole** record rather than just its returns. ``caveats``, ``currency``,
``fee_basis`` and ``vehicle_type`` are what let the dashboard say what a number
actually is — a gross figure, a restated one, a backtested period — instead of
presenting every series as though it were the same kind of thing.

Deliberately not ``fact_table``. That table belongs to the quarterly-PDF
pipeline, its ``FinancialMetric`` validator requires ``YYYY-Qn`` periods (these
are monthly ``YYYY-MM``), and writing return rows there would make a stray
metric appear in the Fund data page's dropdown.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from src import config
from src.features.managers import slug
from src.features.track_record import TrackRecord

RECORDS_DIR = config.BASE_DIR / "data" / "track_records"

# Monthly period keys the correlation view can use. Quarterly records parse and
# store fine — they are simply not correlatable against monthly factor series,
# and are reported as excluded rather than silently resampled.
_MONTHLY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _dir(base: Optional[Path] = None) -> Path:
    return base or RECORDS_DIR


def record_key(record: TrackRecord) -> str:
    """Identity for a stored record — the same rule ``to_fact_rows`` uses."""
    return record.fund or record.manager or record.source_file or "unnamed"


def save(record: TrackRecord, base: Optional[Path] = None) -> Path:
    """Store a parsed record, replacing any earlier parse of the same fund.

    Replacing rather than appending is the right default: a manager sending an
    updated track record is restating the same series, not adding a second one,
    and keeping both would double-count the fund in every aggregate.
    """
    d = _dir(base)
    d.mkdir(parents=True, exist_ok=True)
    key = record_key(record)
    path = d / f"{slug(key)}.json"
    payload = record.model_dump(mode="json")
    payload["_key"] = key
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def list_all(base: Optional[Path] = None) -> list[dict]:
    d = _dir(base)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def monthly_series(record: dict) -> dict[str, float]:
    """``{"YYYY-MM": return_pct}`` for the months this record actually reports.

    Keyed by month rather than positional, because real records start and end
    wherever the manager's history does — no two share a window, so alignment
    against a factor series has to happen by date, not by index.
    """
    out: dict[str, float] = {}
    for p in record.get("periods") or []:
        period = str(p.get("period") or "").strip()
        value = p.get("return_pct")
        if value is None or not _MONTHLY_RE.match(period):
            continue
        try:
            out[period] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def quarterly_only(record: dict) -> bool:
    """Whether a record reports returns, but none of them monthly."""
    periods = record.get("periods") or []
    has_returns = any(p.get("return_pct") is not None for p in periods)
    return has_returns and not monthly_series(record)


def display_name(record: dict) -> str:
    return record.get("fund") or record.get("manager") or record.get("_key") or "unnamed"
