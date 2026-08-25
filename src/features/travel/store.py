"""Durable, transaction-safe storage for travel plans and side effects."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src import config
from .models import TravelTrip


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
  id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trip_id TEXT NOT NULL, action_key TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_travel_actions_trip ON action_log(trip_id, created_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TravelStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or config.TRAVEL_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(1, ?)",
                (utcnow(),),
            )

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, trip: TravelTrip) -> TravelTrip:
        trip.updated_at = utcnow()
        payload = trip.model_dump_json()
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO trips(id,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (trip.id, payload, trip.updated_at),
            )
        return trip

    def get(self, trip_id: str) -> TravelTrip | None:
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM trips WHERE id=?", (trip_id,)).fetchone()
        return TravelTrip.model_validate_json(row["payload"]) if row else None

    def list(self) -> list[TravelTrip]:
        with self.connection() as conn:
            rows = conn.execute("SELECT payload FROM trips ORDER BY updated_at DESC").fetchall()
        return [TravelTrip.model_validate_json(row["payload"]) for row in rows]

    def delete(self, trip_id: str) -> bool:
        with self.connection() as conn:
            cur = conn.execute("DELETE FROM trips WHERE id=?", (trip_id,))
        return bool(cur.rowcount)

    def action_once(self, trip_id: str, key: str, action: str, payload: dict) -> bool:
        """Record an irreversible action; False means it was already performed."""
        try:
            with self.connection() as conn:
                conn.execute(
                    "INSERT INTO action_log(trip_id,action_key,action,payload,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (trip_id, key, action, json.dumps(payload), utcnow()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def actions(self, trip_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT action_key,action,payload,created_at FROM action_log "
                "WHERE trip_id=? ORDER BY id", (trip_id,),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
