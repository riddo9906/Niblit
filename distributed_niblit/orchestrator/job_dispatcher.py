"""JobDispatcher — dispatches and tracks jobs sent to nodes.

Usage example::

    dispatcher = JobDispatcher()
    job_id = dispatcher.queue_job({"type": "research", "topic": "AI"})
    status = dispatcher.get_job_status(job_id)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("JobDispatcher")

_TERMINAL_STATES = {"completed", "failed", "cancelled"}


class JobDispatcher:
    """Queues and dispatches jobs to nodes."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._queue: List[str] = []

    # ── public API ──

    def dispatch(self, job: Dict[str, Any], node_id: str) -> Dict[str, Any]:
        """Immediately dispatch *job* to *node_id* and return result stub."""
        job_id = job.get("job_id", str(uuid.uuid4()))
        self._jobs[job_id] = {
            "job_id": job_id,
            "job": job,
            "node_id": node_id,
            "status": "dispatched",
            "dispatched_at": time.time(),
        }
        log.info("JobDispatcher: dispatched %s to %s", job_id, node_id)
        self._jobs[job_id]["status"] = "completed"
        return {"job_id": job_id, "status": "completed", "node_id": node_id}

    def queue_job(self, job: Dict[str, Any]) -> str:
        """Enqueue *job* and return its job_id."""
        job_id = str(uuid.uuid4())
        job["job_id"] = job_id
        self._jobs[job_id] = {
            "job_id": job_id,
            "job": job,
            "status": "queued",
            "queued_at": time.time(),
        }
        self._queue.append(job_id)
        log.debug("JobDispatcher: queued %s", job_id)
        return job_id

    def get_job_status(self, job_id: str) -> str:
        """Return status string for *job_id* or 'not_found'."""
        entry = self._jobs.get(job_id)
        return entry["status"] if entry else "not_found"


if __name__ == "__main__":
    print('Running job_dispatcher.py')
