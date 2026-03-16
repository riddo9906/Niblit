"""ContainerManager — simulated container lifecycle management.

No Docker required — uses in-memory state to simulate container operations.

Usage example::

    cm = ContainerManager()
    container = cm.create("web-1", "python:3.11-slim")
    print(cm.get_status("web-1"))
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("ContainerManager")


class ContainerManager:
    """Simulates container lifecycle without Docker."""

    def __init__(self) -> None:
        self._containers: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def create(
        self,
        container_id: str,
        image: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create and start a simulated container; return its metadata."""
        container = {
            "container_id": container_id,
            "image": image,
            "config": config or {},
            "status": "running",
            "created_at": time.time(),
        }
        self._containers[container_id] = container
        log.info("ContainerManager: created %s (%s)", container_id, image)
        return dict(container)

    def stop(self, container_id: str) -> bool:
        """Stop *container_id*; return True if found."""
        entry = self._containers.get(container_id)
        if entry:
            entry["status"] = "stopped"
            log.info("ContainerManager: stopped %s", container_id)
            return True
        return False

    def list_running(self) -> List[str]:
        """Return IDs of running containers."""
        return [cid for cid, c in self._containers.items() if c["status"] == "running"]

    def get_status(self, container_id: str) -> str:
        """Return status string or 'not_found'."""
        entry = self._containers.get(container_id)
        return entry["status"] if entry else "not_found"

    def remove(self, container_id: str) -> bool:
        """Remove *container_id*; return True if found."""
        if container_id in self._containers:
            del self._containers[container_id]
            log.info("ContainerManager: removed %s", container_id)
            return True
        return False
