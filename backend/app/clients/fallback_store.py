"""SQLite store for the last good tool result per (tool, key). No FastAPI.

Rows hold facility data as JSON (domain dumps with their original fetched_at) and small
metadata; never URLs or keys. sqlite3 is blocking, so every call runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

_SCHEMA = """CREATE TABLE IF NOT EXISTS fallback (
    tool TEXT NOT NULL,
    key TEXT NOT NULL,
    items TEXT NOT NULL,
    meta TEXT NOT NULL,
    saved_at REAL NOT NULL,
    PRIMARY KEY (tool, key)
)"""


@dataclass(frozen=True)
class StoredResult:
    items: list[dict[str, Any]]
    meta: dict[str, Any]
    saved_at: float  # unix time of the save (facility age comes from each fetched_at)


class FallbackStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or settings.fallback_db)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=1.0)
        conn.execute(_SCHEMA)
        return conn

    def _save(self, tool: str, key: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO fallback VALUES (?, ?, ?, ?, ?)",
                (tool, key, json.dumps(items, ensure_ascii=False), json.dumps(meta), time.time()),
            )

    def _load(self, tool: str, key: str) -> StoredResult | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT items, meta, saved_at FROM fallback WHERE tool = ? AND key = ?", (tool, key)
            ).fetchone()
        if row is None:
            return None
        return StoredResult(json.loads(row[0]), json.loads(row[1]), row[2])

    async def save(self, tool: str, key: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save, tool, key, items, meta)

    async def load(self, tool: str, key: str) -> StoredResult | None:
        return await asyncio.to_thread(self._load, tool, key)


_shared: FallbackStore | None = None


def get_fallback_store() -> FallbackStore:
    """App-wide store (lazy): settings.fallback_db, EM_FALLBACK_DB to override."""
    global _shared
    if _shared is None:
        _shared = FallbackStore()
    return _shared


def set_fallback_store(store: FallbackStore | None) -> None:
    """Swap the app-wide store (tests use a temporary file)."""
    global _shared
    _shared = store
