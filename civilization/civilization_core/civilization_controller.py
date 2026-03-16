"""CivilizationController — top-level orchestrator for the Niblit civilization loop.

Usage example::

    controller = CivilizationController()
    controller.start()
    result = controller.run_cycle()
    print(controller.get_status())
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger("CivilizationController")


class CivilizationController:
    """Coordinates a single iteration of the civilization life-cycle."""

    def __init__(self) -> None:
        self._running: bool = False
        self._cycle_count: int = 0
        self._started_at: Optional[float] = None

    # ── public API ──

    def start(self) -> None:
        """Activate the running flag."""
        self._running = True
        self._started_at = time.time()
        log.info("CivilizationController: started")

    def stop(self) -> None:
        """Deactivate the running flag."""
        self._running = False
        log.info("CivilizationController: stopped after %d cycles", self._cycle_count)

    def run_cycle(self) -> Dict[str, Any]:
        """Execute one civilisation cycle; return results dict."""
        self._cycle_count += 1
        log.info("CivilizationController: cycle %d begin", self._cycle_count)
        start = time.time()
        results: Dict[str, Any] = {
            "cycle": self._cycle_count,
            "agents_active": 0,
            "tasks_completed": 0,
            "elapsed_ms": 0.0,
        }
        results["elapsed_ms"] = round((time.time() - start) * 1000, 2)
        log.info("CivilizationController: cycle %d done in %.1f ms", self._cycle_count, results["elapsed_ms"])
        return results

    def get_status(self) -> Dict[str, Any]:
        """Return current controller status."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "started_at": self._started_at,
        }

    def get_cycle_count(self) -> int:
        """Return total completed cycles."""
        return self._cycle_count
