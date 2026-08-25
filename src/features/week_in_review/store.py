"""data/week_in_review/ persistence — one JSON file per week, keyed by the
window's Monday date, overwritten on rebuild. A page view must not trigger a
Notion crawl plus a 16k-token generation; this is what lets a page load serve
the exact artifact that was built, permanently, rather than a regeneration
that would read slightly differently each time."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.config import BASE_DIR

WEEK_IN_REVIEW_DIR = BASE_DIR / "data" / "week_in_review"


def _path(monday_iso: str, base: Optional[Path] = None) -> Path:
    root = base or WEEK_IN_REVIEW_DIR
    return root / f"{monday_iso}.json"


def save_review(review: dict, base: Optional[Path] = None) -> Path:
    root = base or WEEK_IN_REVIEW_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = _path(review["window"]["start"], base)
    path.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_review(monday_iso: str, base: Optional[Path] = None) -> Optional[dict]:
    path = _path(monday_iso, base)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt file is no stored review
        return None
