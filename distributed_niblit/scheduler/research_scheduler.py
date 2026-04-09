"""ResearchScheduler — schedules periodic research topics.

Usage example::

    sched = ResearchScheduler()
    sid = sched.schedule_research("transformer architectures", interval_s=3600)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List

log = logging.getLogger("ResearchScheduler")


class ResearchScheduler:
    """Manages recurring research schedules."""

    def __init__(self) -> None:
        self._schedules: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def schedule_research(self, topic: str, interval_s: float = 3600) -> str:
        """Register periodic research for *topic*; return schedule_id."""
        sid = str(uuid.uuid4())
        self._schedules[sid] = {
            "schedule_id": sid,
            "topic": topic,
            "interval_s": interval_s,
            "last_run": None,
            "next_run": time.time(),
            "active": True,
        }
        log.info("ResearchScheduler: scheduled %s every %.0fs", topic[:50], interval_s)
        return sid

    def get_scheduled_topics(self) -> List[Dict[str, Any]]:
        """Return all active research schedules."""
        return [s for s in self._schedules.values() if s.get("active")]

    def trigger_now(self, topic: str) -> Dict[str, Any]:
        """Immediately trigger research for *topic*; return result stub."""
        log.info("ResearchScheduler: triggered %s", topic[:50])
        return {
            "topic": topic,
            "triggered_at": time.time(),
            "status": "triggered",
            "findings": f"Simulated findings for topic: {topic}",
        }


if __name__ == "__main__":
    print('Running research_scheduler.py')
