"""ExperimentScheduler — priority queue for scheduled experiments.

Usage example::

    sched = ExperimentScheduler()
    eid = sched.schedule_experiment({"name": "NAS trial"}, priority=8)
    next_exp = sched.next_experiment()
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("ExperimentScheduler")


class ExperimentScheduler:
    """Priority-based experiment scheduling queue."""

    def __init__(self) -> None:
        self._queue: List[Dict[str, Any]] = []

    # ── public API ──

    def schedule_experiment(self, exp: Dict[str, Any], priority: int = 5) -> str:
        """Enqueue *exp* with *priority* (higher = sooner); return schedule_id."""
        sid = str(uuid.uuid4())
        self._queue.append({
            "schedule_id": sid,
            "experiment": exp,
            "priority": priority,
            "scheduled_at": time.time(),
            "status": "queued",
        })
        self._queue.sort(key=lambda x: x["priority"], reverse=True)
        log.debug("ExperimentScheduler: queued %s prio=%d", sid, priority)
        return sid

    def get_queue(self) -> List[Dict[str, Any]]:
        """Return current queue ordered by priority."""
        return [e for e in self._queue if e["status"] == "queued"]

    def next_experiment(self) -> Optional[Dict[str, Any]]:
        """Pop and return the highest-priority pending experiment or None."""
        for entry in self._queue:
            if entry["status"] == "queued":
                entry["status"] = "dispatched"
                log.info("ExperimentScheduler: dispatched %s", entry["schedule_id"])
                return entry
        return None
