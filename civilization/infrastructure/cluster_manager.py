"""ClusterManager — manages logical compute clusters for the civilisation.

Usage example::

    cm = ClusterManager()
    cm.add_cluster("research-cluster", {"region": "us-east"})
    print(cm.list_clusters())
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("ClusterManager")


class ClusterManager:
    """Tracks logical clusters and their configuration."""

    def __init__(self) -> None:
        self._clusters: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def add_cluster(
        self, cluster_id: str, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Register *cluster_id* with *config*."""
        self._clusters[cluster_id] = {"cluster_id": cluster_id, "config": config or {}}
        log.info("ClusterManager: added cluster %s", cluster_id)

    def remove_cluster(self, cluster_id: str) -> None:
        """Deregister *cluster_id*."""
        self._clusters.pop(cluster_id, None)
        log.info("ClusterManager: removed cluster %s", cluster_id)

    def list_clusters(self) -> List[str]:
        """Return cluster IDs."""
        return list(self._clusters.keys())

    def get_cluster(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """Return cluster config or None."""
        return self._clusters.get(cluster_id)

    def cluster_count(self) -> int:
        """Return total cluster count."""
        return len(self._clusters)


if __name__ == "__main__":
    print('Running cluster_manager.py')
