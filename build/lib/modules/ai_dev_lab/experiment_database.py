#!/usr/bin/env python3
"""
modules/ai_dev_lab/experiment_database.py

Store and retrieve SEADL experiment results in a SQLite database.

Schema::

    CREATE TABLE experiments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis TEXT,
        architecture TEXT,
        code_version TEXT,
        performance_score REAL,
        benchmark_json TEXT,
        timestamp TEXT
    )

Usage::

    from modules.ai_dev_lab.experiment_database import ExperimentDatabase
    db = ExperimentDatabase()
    db.store(hypothesis=h, architecture=a, code=c, benchmark_results=r)
    recent = db.recent(limit=10)
    best = db.best(top_n=5)
"""

import json
import logging
import os
import sqlite3
import tempfile
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("ExperimentDatabase")

_DEFAULT_DB_PATH = os.environ.get("AI_DEV_LAB_DB_PATH") or os.path.join(
    os.getcwd() if os.access(os.getcwd(), os.W_OK) else tempfile.gettempdir(),
    "ai_dev_lab.db",
)
_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis        TEXT,
    architecture      TEXT,
    code_version      TEXT,
    performance_score REAL,
    benchmark_json    TEXT,
    timestamp         TEXT
);
CREATE INDEX IF NOT EXISTS idx_perf ON experiments(performance_score DESC);
"""


class ExperimentDatabase:
    """
    Persistent SQLite store for SEADL experiment results.

    Args:
        db_path: Path to the SQLite file.  Defaults to ``ai_dev_lab.db`` in cwd.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    # ── public API ────────────────────────────────────────────────────────────

    def store(
        self,
        hypothesis: Dict[str, Any],
        architecture: Dict[str, Any],
        code: str = "",
        benchmark_results: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Persist an experiment record.

        Returns the row id.
        """
        perf = float((benchmark_results or {}).get("performance", 0.0))
        row = {
            "hypothesis": json.dumps(hypothesis),
            "architecture": json.dumps(architecture),
            "code_version": code[:2000] if code else "",
            "performance_score": perf,
            "benchmark_json": json.dumps(benchmark_results or {}),
            "timestamp": self._ts(),
        }
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "INSERT INTO experiments "
                    "(hypothesis, architecture, code_version, performance_score, "
                    "benchmark_json, timestamp) "
                    "VALUES (:hypothesis, :architecture, :code_version, "
                    ":performance_score, :benchmark_json, :timestamp)",
                    row,
                )
                row_id = cur.lastrowid or 0
                log.debug("ExperimentDatabase: stored experiment id=%d perf=%.3f", row_id, perf)
                return row_id
        except Exception as exc:  # noqa: BLE001
            log.warning("ExperimentDatabase.store: %s", exc)
            return -1

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the *limit* most recent experiments."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM experiments ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("ExperimentDatabase.recent: %s", exc)
            return []

    def best(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """Return the *top_n* highest-performing experiments."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM experiments ORDER BY performance_score DESC LIMIT ?", (top_n,)
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("ExperimentDatabase.best: %s", exc)
            return []

    def count(self) -> int:
        try:
            with self._conn() as conn:
                return conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        except Exception:  # noqa: BLE001
            return 0

    def clear(self) -> None:
        """Remove all experiment records (used in tests)."""
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM experiments")
        except Exception as exc:  # noqa: BLE001
            log.warning("ExperimentDatabase.clear: %s", exc)

    # ── internals ─────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            with self._conn() as conn:
                for stmt in _CREATE_SQL.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            log.warning("ExperimentDatabase._init_db: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _ts() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        keys = ["id", "hypothesis", "architecture", "code_version",
                "performance_score", "benchmark_json", "timestamp"]
        d = dict(zip(keys, row))
        # Deserialize JSON fields
        for field in ("hypothesis", "architecture", "benchmark_json"):
            try:
                d[field] = json.loads(d[field]) if d.get(field) else {}
            except Exception:  # noqa: BLE001
                pass
        return d


if __name__ == "__main__":
    print('Running experiment_database.py')
