"""
niblit_sqlite_db.py — SQLite-backed persistent storage for Niblit.

Provides a drop-in companion to the existing JSON-based LocalDB.
All public methods are thread-safe.

Schema
------
facts          – key/value store for agent facts
events         – append-only event log
interactions   – chat history
meta           – single-row metadata / stats

Usage::

    from niblit_sqlite_db import NiblitSQLiteDB
    db = NiblitSQLiteDB("niblit_data.sqlite")
    db.add_fact("greeting", "hello world")
    print(db.list_facts())
"""

import sqlite3
import threading
import json
import shutil
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("NiblitSQLiteDB")


class NiblitSQLiteDB:
    """SQLite-backed persistent store for Niblit."""

    # ------------------------------------------------------------------
    # Construction / schema
    # ------------------------------------------------------------------

    def __init__(self, db_path: str = "niblit_data.sqlite") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        # Use a single shared connection (check_same_thread=False) protected
        # by a mutex.  This works correctly for both file-based and
        # in-memory (':memory:') databases.
        self._conn_obj = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        self._conn_obj.row_factory = sqlite3.Row
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return self._conn_obj

    def _init_schema(self) -> None:
        """Create tables if they do not already exist."""
        conn = self._conn()
        with self._lock:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS facts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    key        TEXT    NOT NULL,
                    value      TEXT    NOT NULL,
                    category   TEXT    DEFAULT '',
                    created_at TEXT    DEFAULT (datetime('now','utc')),
                    updated_at TEXT    DEFAULT (datetime('now','utc'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_key ON facts(key);

                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT    NOT NULL,
                    payload    TEXT    DEFAULT '{}',
                    created_at TEXT    DEFAULT (datetime('now','utc'))
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    role       TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    created_at TEXT    DEFAULT (datetime('now','utc'))
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    def add_fact(self, key: str, value: Any, category: str = "") -> None:
        """Insert or update a fact by key."""
        serialised = value if isinstance(value, str) else json.dumps(value)
        now = _utc_now()
        conn = self._conn()
        with self._lock:
            conn.execute(
                """
                INSERT INTO facts (key, value, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    category   = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (key, serialised, category, now, now),
            )
            conn.commit()

    def get_fact(self, key: str) -> Optional[str]:
        """Return the value for *key*, or ``None`` if not found."""
        conn = self._conn()
        row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def list_facts(self, limit: int = 200, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return a list of fact dicts, newest first."""
        conn = self._conn()
        if category is not None:
            rows = conn.execute(
                "SELECT key, value, category, created_at FROM facts "
                "WHERE category = ? ORDER BY id DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, category, created_at FROM facts "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_fact(self, key: str) -> bool:
        """Delete a fact by key. Returns True if a row was removed."""
        conn = self._conn()
        with self._lock:
            cur = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def log_event(self, event_type: str, payload: Optional[Dict] = None) -> None:
        """Append an event to the event log."""
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT INTO events (event_type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(payload or {}), _utc_now()),
            )
            conn.commit()

    def list_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict]:
        """Return recent events, newest first."""
        conn = self._conn()
        if event_type:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def add_interaction(self, role: str, content: str) -> None:
        """Record a chat interaction (role: 'user' or 'assistant')."""
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT INTO interactions (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, _utc_now()),
            )
            conn.commit()

    def list_interactions(self, limit: int = 50) -> List[Dict]:
        """Return recent interactions, newest first."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT role, content, created_at FROM interactions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: Any) -> None:
        """Set a metadata key."""
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
            conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        """Get a metadata value."""
        conn = self._conn()
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup(self, dest_path: str) -> str:
        """Copy the database file to *dest_path* and return the path."""
        if self.db_path == ":memory:":
            raise ValueError("Cannot back up an in-memory database to a file.")
        # Flush WAL before copying
        conn = self._conn()
        with self._lock:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(self.db_path, dest_path)
        log.info("Database backed up to %s", dest_path)
        return dest_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the shared database connection."""
        with self._lock:
            if self._conn_obj:
                self._conn_obj.close()
                self._conn_obj = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
