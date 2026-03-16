"""WorkloadBalancer — distributes tasks across infrastructure nodes.

Usage example::

    balancer = WorkloadBalancer()
    node_id = balancer.assign({"type": "research"}, ["node-1", "node-2"])
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

log = logging.getLogger("InfraWorkloadBalancer")


class WorkloadBalancer:
    """Assigns tasks and tracks node load."""

    def __init__(self) -> None:
        self._load: Dict[str, int] = defaultdict(int)
        self._completed: Dict[str, int] = defaultdict(int)

    # ── public API ──

    def assign(self, task: Dict[str, Any], nodes: List[Any]) -> str:
        """Assign *task* to the least-loaded node from *nodes*."""
        if not nodes:
            log.warning("InfraWorkloadBalancer: no nodes available")
            return ""
        node_ids = [n if isinstance(n, str) else n.get("node_id", str(n)) for n in nodes]
        chosen = min(node_ids, key=lambda n: self._load[n])
        self._load[chosen] += 1
        log.debug("InfraWorkloadBalancer: assigned %s to %s", task.get("type", "?"), chosen)
        return chosen

    def report_completion(self, node_id: str, task_id: str) -> None:
        """Decrement load counter for *node_id*."""
        self._load[node_id] = max(0, self._load[node_id] - 1)
        self._completed[node_id] += 1

    def get_load(self, node_id: str) -> int:
        """Return current active task count for *node_id*."""
        return self._load[node_id]

    def get_utilization(self) -> Dict[str, Any]:
        """Return load and completion stats for all nodes."""
        return {
            nid: {"active_tasks": self._load[nid], "completed": self._completed[nid]}
            for nid in set(list(self._load.keys()) + list(self._completed.keys()))
        }
