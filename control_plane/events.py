"""Persistent Slack event idempotency store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable


class EventStore:
    def __init__(self, runtime_root: Path):
        self.path = Path(runtime_root) / "events.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS processed_events ("
                "event_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)"
            )
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def process_once(self, event_id: str, action: Callable[[], dict]) -> tuple[dict, bool]:
        if not event_id or len(event_id) > 256:
            raise ValueError("invalid event_id")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT result_json FROM processed_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is not None:
                conn.commit()
                return json.loads(row[0]), True
            result = action()
            conn.execute(
                "INSERT INTO processed_events(event_id, result_json) VALUES (?, ?)",
                (event_id, json.dumps(result, ensure_ascii=False, sort_keys=True)),
            )
            conn.commit()
            return result, False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
