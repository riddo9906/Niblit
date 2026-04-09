"""ExperimentManager — lifecycle management for civilisation experiments.

Usage example::

    manager = ExperimentManager()
    exp_id = manager.create("Will adding attention improve accuracy?")
    manager.start(exp_id)
    manager.complete(exp_id, {"accuracy": 0.92})
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("ExperimentManager")


class ExperimentManager:
    """Tracks experiment lifecycle: created → running → completed/failed."""

    def __init__(self) -> None:
        self._experiments: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def create(
        self,
        hypothesis: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a new experiment; return exp_id."""
        exp_id = str(uuid.uuid4())
        self._experiments[exp_id] = {
            "exp_id": exp_id,
            "hypothesis": hypothesis,
            "config": config or {},
            "status": "created",
            "created_at": time.time(),
        }
        log.info("ExperimentManager: created %s", exp_id)
        return exp_id

    def start(self, exp_id: str) -> None:
        """Transition *exp_id* to running status."""
        if exp_id in self._experiments:
            self._experiments[exp_id]["status"] = "running"
            self._experiments[exp_id]["started_at"] = time.time()
            log.info("ExperimentManager: started %s", exp_id)

    def complete(self, exp_id: str, results: Dict[str, Any]) -> None:
        """Mark *exp_id* as completed with *results*."""
        if exp_id in self._experiments:
            self._experiments[exp_id]["status"] = "completed"
            self._experiments[exp_id]["results"] = results
            self._experiments[exp_id]["completed_at"] = time.time()
            log.info("ExperimentManager: completed %s", exp_id)

    def fail(self, exp_id: str, reason: str) -> None:
        """Mark *exp_id* as failed with *reason*."""
        if exp_id in self._experiments:
            self._experiments[exp_id]["status"] = "failed"
            self._experiments[exp_id]["failure_reason"] = reason
            log.warning("ExperimentManager: %s failed — %s", exp_id, reason)

    def get(self, exp_id: str) -> Optional[Dict[str, Any]]:
        """Return experiment metadata or None."""
        return self._experiments.get(exp_id)

    def list_active(self) -> List[str]:
        """Return exp_ids with status 'running' or 'created'."""
        return [
            exp_id
            for exp_id, e in self._experiments.items()
            if e["status"] in ("created", "running")
        ]


if __name__ == "__main__":
    print('Running experiment_manager.py')
