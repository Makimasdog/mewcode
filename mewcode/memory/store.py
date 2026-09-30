from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


VALID_TYPES = {"user", "feedback", "project", "reference"}
VALID_STATUSES = {"pending", "active", "archived", "rejected"}


@dataclass(frozen=True)
class MemoryItem:
    id: str
    scope: str
    type: str
    content: str
    summary: str = ""
    tags: tuple[str, ...] = ()
    status: str = "active"
    confidence: float = 1.0
    source_session_id: str = ""
    source_message_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""
    expires_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def make_memory_id(scope: str, type_: str, content: str) -> str:
    key = f"{scope}\0{type_}\0{_canonical(content)}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:32]


class MemoryStore:
    """Small SQLite repository for structured memories.

    The repository has no third-party dependency and deliberately exposes a
    narrow API so the existing Markdown-based MemoryManager can remain the
    compatibility facade during rollout.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            # Read-only filesystems and some SQLite builds do not allow WAL.
            pass
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    type TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source_session_id TEXT NOT NULL DEFAULT '',
                    source_message_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT,
                    UNIQUE(scope, type, canonical_key)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope_status
                    ON memory_items(scope, status);
                CREATE INDEX IF NOT EXISTS idx_memory_updated
                    ON memory_items(updated_at DESC);
                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    actor TEXT NOT NULL DEFAULT 'mewcode',
                    created_at TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
                    "USING fts5(id UNINDEXED, content, summary, tags)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO memory_fts(id, content, summary, tags) "
                    "SELECT id, content, summary, tags_json FROM memory_items"
                )
                self._has_fts = True
            except sqlite3.DatabaseError:
                self._has_fts = False

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryItem:
        try:
            tags = tuple(json.loads(row["tags_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            tags = ()
        try:
            source_ids = tuple(json.loads(row["source_message_ids_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            source_ids = ()
        return MemoryItem(
            id=row["id"],
            scope=row["scope"],
            type=row["type"],
            content=row["content"],
            summary=row["summary"],
            tags=tags,
            status=row["status"],
            confidence=float(row["confidence"]),
            source_session_id=row["source_session_id"],
            source_message_ids=source_ids,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            expires_at=row["expires_at"],
        )

    def upsert(self, item: MemoryItem, *, actor: str = "mewcode") -> MemoryItem:
        if item.type not in VALID_TYPES:
            raise ValueError(f"unknown memory type: {item.type}")
        if item.status not in VALID_STATUSES:
            raise ValueError(f"unknown memory status: {item.status}")
        content = item.content.strip()
        if not content:
            raise ValueError("memory content must not be empty")
        now = _now()
        item_id = item.id or make_memory_id(item.scope, item.type, content)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM memory_items WHERE scope = ? AND type = ? "
                "AND canonical_key = ?",
                (item.scope, item.type, _canonical(content)),
            ).fetchone()
            if existing is not None:
                return self._from_row(existing)
            conn.execute(
                """INSERT INTO memory_items (
                    id, scope, type, canonical_key, content, summary, tags_json,
                    status, confidence, source_session_id, source_message_ids_json,
                    created_at, updated_at, last_used_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    item.scope,
                    item.type,
                    _canonical(content),
                    content,
                    item.summary.strip(),
                    json.dumps(list(item.tags), ensure_ascii=False),
                    item.status,
                    max(0.0, min(1.0, item.confidence)),
                    item.source_session_id,
                    json.dumps(list(item.source_message_ids), ensure_ascii=False),
                    item.created_at or now,
                    now,
                    item.last_used_at,
                    item.expires_at,
                ),
            )
            conn.execute(
                "INSERT INTO memory_events(memory_id, action, new_value, created_at) "
                "VALUES (?, 'create', ?, ?)",
                (item_id, json.dumps(item.content, ensure_ascii=False), now),
            )
            if getattr(self, "_has_fts", False):
                conn.execute(
                    "INSERT OR REPLACE INTO memory_fts(id, content, summary, tags) "
                    "VALUES (?, ?, ?, ?)",
                    (item_id, content, item.summary, " ".join(item.tags)),
                )
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row is not None
            return self._from_row(row)

    def list(
        self,
        scope: str | None = None,
        statuses: Iterable[str] = ("active",),
        limit: int = 200,
    ) -> list[MemoryItem]:
        statuses = tuple(statuses)
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        params: list[object] = list(statuses)
        where = f"status IN ({placeholders})"
        if scope:
            where += " AND scope = ?"
            params.append(scope)
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_items WHERE {where} "
                "ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, memory_id: str) -> MemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (memory_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def search(
        self, query: str, scope: str | None = None, limit: int = 20
    ) -> list[MemoryItem]:
        query = query.strip()
        if not query:
            return self.list(scope=scope, limit=limit)
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows: list[sqlite3.Row] = []
            if getattr(self, "_has_fts", False):
                terms = [re.sub(r'[^\w\-]+', "", part) for part in query.split()]
                terms = [term for term in terms if term]
                match = " AND ".join(terms)
                if match:
                    sql = (
                        "SELECT m.* FROM memory_items m JOIN memory_fts f ON f.id = m.id "
                        "WHERE m.status = 'active' AND memory_fts MATCH ?"
                    )
                    params: list[object] = [match]
                    if scope:
                        sql += " AND m.scope = ?"
                        params.append(scope)
                    sql += " ORDER BY m.updated_at DESC LIMIT ?"
                    params.append(limit)
                    rows = conn.execute(sql, params).fetchall()
                else:
                    rows = []
            if not rows:
                pattern = f"%{query}%"
                sql = (
                    "SELECT * FROM memory_items WHERE status = 'active' "
                    "AND (content LIKE ? OR summary LIKE ? OR tags_json LIKE ?)"
                )
                params = [pattern, pattern, pattern]
                if scope:
                    sql += " AND scope = ?"
                    params.append(scope)
                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def set_status(self, memory_id: str, status: str, *, actor: str = "mewcode") -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown memory status: {status}")
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE memory_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, memory_id),
            )
            conn.execute(
                "INSERT INTO memory_events(memory_id, action, old_value, new_value, actor, created_at) "
                "VALUES (?, 'status', ?, ?, ?, ?)",
                (memory_id, row["status"], status, actor, now),
            )
        return True

    def delete(self, memory_id: str, *, actor: str = "mewcode") -> bool:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
            conn.execute(
                "INSERT INTO memory_events(memory_id, action, old_value, actor, created_at) "
                "VALUES (?, 'delete', ?, ?, ?)",
                (memory_id, json.dumps(dict(row), ensure_ascii=False), actor, now),
            )
            if getattr(self, "_has_fts", False):
                conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
        return True

    def clear(self, scope: str | None = None, *, actor: str = "mewcode") -> int:
        now = _now()
        with self._connect() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT id FROM memory_items WHERE scope = ?", (scope,)
                ).fetchall()
                conn.execute("DELETE FROM memory_items WHERE scope = ?", (scope,))
            else:
                rows = conn.execute("SELECT id FROM memory_items").fetchall()
                conn.execute("DELETE FROM memory_items")
            for row in rows:
                conn.execute(
                    "INSERT INTO memory_events(memory_id, action, actor, created_at) "
                    "VALUES (?, 'clear', ?, ?)",
                    (row["id"], actor, now),
                )
            if getattr(self, "_has_fts", False):
                if scope:
                    ids = [row["id"] for row in rows]
                    for memory_id in ids:
                        conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
                else:
                    conn.execute("DELETE FROM memory_fts")
        return len(rows)
