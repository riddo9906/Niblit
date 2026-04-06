#!/usr/bin/env python3
"""
modules/llm_chat_memory.py — Persistent chat-history store for the LLM
inference provider.

This module solves two problems:

1. **Cross-session memory**: Every user ↔ assistant exchange is persisted to
   SQLite so the LLM sees the full conversation history even after Niblit
   restarts.  The inference provider receives the last *N* turns as ``messages``
   in each API call, giving it continuity across sessions.

2. **Pause / Resume**: When the LLM is toggled off (``toggle-llm off``) the
   conversation state is preserved.  When toggled back on the full history is
   reloaded and injected into the next LLM request — nothing is lost.

Usage::

    from modules.llm_chat_memory import get_llm_chat_memory

    mem = get_llm_chat_memory()           # singleton
    mem.add("user", "Hello!")
    mem.add("assistant", "Hi there!")
    messages = mem.load_messages(limit=30) # → list of {role, content, ts}
    mem.save_session_marker("paused")      # mark the current pause point

The SQLite database lives at the path controlled by
``NIBLIT_LLM_CHAT_DB_PATH`` (defaults to ``llm_chat_history.sqlite``
next to the main Niblit data directory).
"""

import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("LLMChatMemory")


# ── helpers ───────────────────────────────────────────────────────────────────

def _writable_path(default_name: str, env_var: str) -> str:
    """Return the path from *env_var* or fall back to *default_name* in the
    first writable candidate directory."""
    from_env = os.getenv(env_var, "").strip()
    if from_env:
        return from_env
    candidates = [
        os.path.join(os.getcwd(), default_name),
        os.path.join(os.path.expanduser("~"), default_name),
        os.path.join("/tmp", default_name),
    ]
    for path in candidates:
        parent = os.path.dirname(path) or "."
        if os.access(parent, os.W_OK):
            return path
    return candidates[0]


_DEFAULT_DB_PATH = _writable_path(
    "llm_chat_history.sqlite", "NIBLIT_LLM_CHAT_DB_PATH"
)

# Maximum number of messages returned by default.  This caps the context
# window sent to the inference provider so we don't exceed token limits.
_DEFAULT_CONTEXT_LIMIT: int = 40


# ── LLMChatMemory ────────────────────────────────────────────────────────────

class LLMChatMemory:
    """SQLite-backed persistent chat history for the LLM inference provider.

    Every ``add()`` call writes a row immediately (autocommit) so data
    survives unexpected shutdowns.  ``load_messages()`` returns the last *N*
    turns in chronological order, ready to be injected as the ``messages``
    list in any OpenAI-compatible chat-completions call.
    """

    _CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS chat_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role       TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            ts         REAL    NOT NULL,
            session_id TEXT    DEFAULT ''
        );
    """

    _CREATE_MARKERS_SQL = """
        CREATE TABLE IF NOT EXISTS session_markers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            marker     TEXT    NOT NULL,
            ts         REAL    NOT NULL,
            metadata   TEXT    DEFAULT ''
        );
    """

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._session_id = f"s-{int(time.time())}"
        self._paused = False
        try:
            with self._connect() as conn:
                conn.execute(self._CREATE_SQL)
                conn.execute(self._CREATE_MARKERS_SQL)
        except Exception as exc:
            log.warning("[LLMChatMemory] DB init failed: %s", exc)

    # ── connection ────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.isolation_level = None  # autocommit
        return conn

    # ── public API ────────────────────────────────────────────────────────────

    def add(self, role: str, content: str) -> None:
        """Persist a single chat message.

        Args:
            role:    ``"user"`` or ``"assistant"`` (also accepts ``"system"``).
            content: The message text.
        """
        if not content or not content.strip():
            return
        role = role if role in ("user", "assistant", "system") else "user"
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO chat_history (role, content, ts, session_id) "
                        "VALUES (?, ?, ?, ?)",
                        (role, content.strip(), time.time(), self._session_id),
                    )
            except Exception as exc:
                log.debug("[LLMChatMemory] add failed: %s", exc)

    def load_messages(
        self,
        limit: int = _DEFAULT_CONTEXT_LIMIT,
    ) -> List[Dict[str, str]]:
        """Return the most recent *limit* messages in chronological order.

        Each entry is ``{"role": "...", "content": "..."}``, ready for
        direct injection into an OpenAI-compatible ``messages`` list.
        """
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT role, content FROM chat_history "
                        "ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                # rows are newest-first; reverse to chronological order
                return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
            except Exception as exc:
                log.debug("[LLMChatMemory] load_messages failed: %s", exc)
                return []

    def message_count(self) -> int:
        """Return total number of stored messages."""
        with self._lock:
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM chat_history"
                    ).fetchone()
                    return row[0] if row else 0
            except Exception:
                return 0

    # ── session markers (pause / resume) ──────────────────────────────────────

    def save_session_marker(self, marker: str, metadata: str = "") -> None:
        """Record a session event (e.g. ``"paused"`` or ``"resumed"``)."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO session_markers (marker, ts, metadata) "
                        "VALUES (?, ?, ?)",
                        (marker, time.time(), metadata),
                    )
            except Exception as exc:
                log.debug("[LLMChatMemory] save_session_marker failed: %s", exc)

    def pause(self) -> None:
        """Mark the session as paused — all history is preserved."""
        self._paused = True
        self.save_session_marker("paused")
        log.info("[LLMChatMemory] Session paused — chat history preserved (%d messages)",
                 self.message_count())

    def resume(self) -> None:
        """Resume the session — history is fully reloaded on next load_messages()."""
        self._paused = False
        # Start a new session ID so new messages are distinguishable
        self._session_id = f"s-{int(time.time())}"
        self.save_session_marker("resumed")
        count = self.message_count()
        log.info("[LLMChatMemory] Session resumed — %d messages available for context", count)

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── housekeeping ──────────────────────────────────────────────────────────

    def trim(self, keep: int = 200) -> int:
        """Delete old messages, keeping the most recent *keep* rows.

        Returns the number of rows deleted.
        """
        with self._lock:
            try:
                with self._connect() as conn:
                    total = conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
                    if total <= keep:
                        return 0
                    to_delete = total - keep
                    conn.execute(
                        "DELETE FROM chat_history WHERE id IN "
                        "(SELECT id FROM chat_history ORDER BY id ASC LIMIT ?)",
                        (to_delete,),
                    )
                    log.info("[LLMChatMemory] Trimmed %d old messages (kept %d)", to_delete, keep)
                    return to_delete
            except Exception as exc:
                log.debug("[LLMChatMemory] trim failed: %s", exc)
                return 0

    def clear(self) -> None:
        """Delete all chat history."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM chat_history")
                    conn.execute("DELETE FROM session_markers")
                log.info("[LLMChatMemory] All chat history cleared")
            except Exception as exc:
                log.debug("[LLMChatMemory] clear failed: %s", exc)

    def status(self) -> Dict[str, Any]:
        """Return a summary of the chat memory state."""
        count = self.message_count()
        return {
            "message_count": count,
            "session_id": self._session_id,
            "paused": self._paused,
            "db_path": self._db_path,
        }


# ── singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[LLMChatMemory] = None


def get_llm_chat_memory(db_path: str = "") -> LLMChatMemory:
    """Return (and lazily create) the process-level LLMChatMemory singleton."""
    global _instance  # pylint: disable=global-statement
    if _instance is None:
        _instance = LLMChatMemory(db_path=db_path)
    return _instance
