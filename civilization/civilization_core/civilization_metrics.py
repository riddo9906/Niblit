"""CivilizationMetrics — records and summarises per-cycle civilisation metrics.

Usage example::

    metrics = CivilizationMetrics()
    metrics.record_cycle({"agents": 10, "tasks_completed": 5})
    print(metrics.get_summary())
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

log = logging.getLogger("CivilizationMetrics")


class CivilizationMetrics:
    """Tracks civilisation cycle data."""

    def __init__(self) -> None:
        self._history: List[Dict[str, Any]] = []

    # ── public API ──

    def record_cycle(self, cycle_data: Dict[str, Any]) -> None:
        """Append *cycle_data* to history."""
        self._history.append({**cycle_data, "recorded_at": time.time()})
        log.debug("CivilizationMetrics: recorded cycle %d", len(self._history))

    def get_cycle_history(self) -> List[Dict[str, Any]]:
        """Return full cycle history."""
        return list(self._history)

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregate statistics across all recorded cycles."""
        if not self._history:
            return {"total_cycles": 0, "avg_agents": 0.0, "avg_tasks": 0.0}
        agents = [c.get("agents", c.get("agents_active", 0)) for c in self._history]
        tasks = [c.get("tasks_completed", 0) for c in self._history]
        return {
            "total_cycles": len(self._history),
            "avg_agents": round(sum(agents) / len(agents), 2),
            "avg_tasks": round(sum(tasks) / len(tasks), 2),
        }

    def export(self) -> Dict[str, Any]:
        """Return full metrics payload."""
        return {"history": self._history, "summary": self.get_summary()}


if __name__ == "__main__":
    print('Running civilization_metrics.py')
