#!/usr/bin/env python3
"""
modules/ai_dev_lab/experiment_manager.py

Manage the lifecycle of SEADL experiments from creation to archival.

Responsibilities:
    - assign unique experiment IDs
    - track experiment status (pending → running → completed → failed)
    - store in ExperimentDatabase
    - expose summary statistics

Usage::

    from modules.ai_dev_lab.experiment_manager import ExperimentManager
    mgr = ExperimentManager()
    exp_id = mgr.create(hypothesis, architecture)
    mgr.start(exp_id)
    mgr.complete(exp_id, code=code, benchmark_results=results)
    summary = mgr.summary(exp_id)
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("ExperimentManager")


class ExperimentManager:
    """
    Manage experiment lifecycle for the SEADL.

    Args:
        db:  Optional ExperimentDatabase instance.  Created automatically
             with a temp path when not provided.
    """

    _STATUS = frozenset(["pending", "running", "completed", "failed"])

    def __init__(self, db: Optional[Any] = None) -> None:
        self._experiments: Dict[str, Dict[str, Any]] = {}
        self._db = db or self._make_db()

    # ── public API ────────────────────────────────────────────────────────────

    def create(
        self,
        hypothesis: Dict[str, Any],
        architecture: Dict[str, Any],
    ) -> str:
        """
        Register a new experiment.

        Returns a unique experiment ID.
        """
        exp_id = str(uuid.uuid4())[:8]
        self._experiments[exp_id] = {
            "id": exp_id,
            "hypothesis": hypothesis,
            "architecture": architecture,
            "status": "pending",
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "code": "",
            "benchmark": {},
        }
        log.debug("ExperimentManager: created experiment %s", exp_id)
        return exp_id

    def start(self, exp_id: str) -> None:
        """Mark experiment as running."""
        self._update(exp_id, status="running", started_at=time.time())

    def complete(
        self,
        exp_id: str,
        code: str = "",
        benchmark_results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark experiment as completed and persist results."""
        self._update(
            exp_id,
            status="completed",
            completed_at=time.time(),
            code=code,
            benchmark=benchmark_results or {},
        )
        exp = self._experiments.get(exp_id)
        if exp and self._db:
            try:
                self._db.store(
                    hypothesis=exp["hypothesis"],
                    architecture=exp["architecture"],
                    code=code,
                    benchmark_results=benchmark_results,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("ExperimentManager: DB store failed: %s", exc)

    def fail(self, exp_id: str, error: str = "") -> None:
        """Mark experiment as failed."""
        self._update(exp_id, status="failed", error=error)

    def get(self, exp_id: str) -> Optional[Dict[str, Any]]:
        return dict(self._experiments[exp_id]) if exp_id in self._experiments else None

    def list_all(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        exps = list(self._experiments.values())
        if status:
            exps = [e for e in exps if e["status"] == status]
        return exps

    def summary(self, exp_id: str) -> Optional[Dict[str, Any]]:
        exp = self._experiments.get(exp_id)
        if not exp:
            return None
        return {
            "id": exp_id,
            "status": exp["status"],
            "performance": exp.get("benchmark", {}).get("performance", 0.0),
            "hypothesis": exp["hypothesis"].get("hypothesis", "") if isinstance(exp["hypothesis"], dict) else "",
            "architecture": exp["architecture"].get("name", "") if isinstance(exp["architecture"], dict) else "",
        }

    def stats(self) -> Dict[str, int]:
        counts: Dict[str, int] = {s: 0 for s in self._STATUS}
        for exp in self._experiments.values():
            counts[exp["status"]] = counts.get(exp["status"], 0) + 1
        counts["total"] = len(self._experiments)
        return counts

    # ── internals ─────────────────────────────────────────────────────────────

    def _update(self, exp_id: str, **kwargs: Any) -> None:
        if exp_id in self._experiments:
            self._experiments[exp_id].update(kwargs)

    @staticmethod
    def _make_db() -> Optional[Any]:
        try:
            import tempfile
            import os
            from modules.ai_dev_lab.experiment_database import ExperimentDatabase  # type: ignore[import]
            path = os.path.join(tempfile.gettempdir(), "seadl_experiments.db")
            return ExperimentDatabase(db_path=path)
        except Exception:  # noqa: BLE001
            return None


if __name__ == "__main__":
    print('Running experiment_manager.py')
