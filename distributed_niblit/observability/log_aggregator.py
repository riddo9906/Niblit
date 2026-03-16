"""LogAggregator — centralised structured log collection.

Usage example::

    agg = LogAggregator()
    agg.log("INFO", "agent-1", "Task completed", {"task_id": "t1"})
    recent = agg.tail(10)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("LogAggregator")

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class LogAggregator:
    """Stores structured log entries with source and level filtering."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._max_entries = max_entries

    # ── public API ──

    def log(
        self,
        level: str,
        source: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a structured log entry."""
        entry: Dict[str, Any] = {
            "level": level.upper(),
            "source": source,
            "message": message,
            "context": context or {},
            "ts": time.time(),
        }
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

    def get_logs(
        self,
        source: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return entries filtered by *source* and/or *level*."""
        results = list(self._entries)
        if source is not None:
            results = [e for e in results if e["source"] == source]
        if level is not None:
            results = [e for e in results if e["level"] == level.upper()]
        return results

    def tail(self, n: int = 100) -> List[Dict[str, Any]]:
        """Return the last *n* log entries."""
        return self._entries[-n:]

    def clear(self) -> None:
        """Remove all stored entries."""
        self._entries.clear()
        log.info("LogAggregator: cleared all entries")
