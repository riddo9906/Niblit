#!/usr/bin/env python3
"""Runtime awareness for NiblitDevAgent using existing runtime systems."""

from __future__ import annotations

import os
import threading
from typing import Any


class RuntimeAwareness:
    """Read runtime topology and state without introducing global state silos."""

    def __init__(
        self,
        core: Any | None = None,
        runtime_manager: Any | None = None,
        event_bus: Any | None = None,
        telemetry: Any | None = None,
        local_brain: Any | None = None,
    ) -> None:
        self._core = core
        self._runtime_manager = runtime_manager
        self._event_bus = event_bus
        self._telemetry = telemetry
        self._local_brain = local_brain

    @staticmethod
    def _deployment_mode() -> str:
        if os.getenv("VERCEL"):
            return "vercel"
        if os.getenv("FLY_APP_NAME"):
            return "fly"
        if os.getenv("TERMUX_VERSION"):
            return "termux"
        if os.getenv("WSL_DISTRO_NAME"):
            return "wsl"
        if os.getenv("NIBLIT_RUNTIME_PROFILE"):
            return str(os.getenv("NIBLIT_RUNTIME_PROFILE"))
        return "local"

    def _local_brain_status(self) -> dict[str, Any]:
        lb = self._local_brain
        if lb is None and self._core is not None:
            lb = getattr(self._core, "local_brain", None)
        if lb is not None and hasattr(lb, "status"):
            try:
                return dict(lb.status())
            except Exception:
                return {}
        return {}

    def _runtime_manager_stats(self) -> dict[str, Any]:
        rm = self._runtime_manager or (getattr(self._core, "runtime_manager", None) if self._core else None)
        if rm is not None and hasattr(rm, "get_stats"):
            try:
                return dict(rm.get_stats())
            except Exception:
                return {}
        return {}

    def _event_bus_stats(self) -> dict[str, Any]:
        bus = self._event_bus
        if bus is None:
            rm = self._runtime_manager or (getattr(self._core, "runtime_manager", None) if self._core else None)
            bus = getattr(rm, "event_bus", None)
        if bus is None:
            return {"available": False}

        history_count = None
        if hasattr(bus, "get_history"):
            try:
                history_count = len(bus.get_history(limit=200))
            except Exception:
                history_count = None

        return {
            "available": True,
            "history_count": history_count,
        }

    def _memory_systems(self) -> list[str]:
        if self._core is None:
            return []
        loaded = []
        for attr in (
            "db",
            "memory",
            "memory_store",
            "memory_loop",
            "vector_store",
            "governed_qdrant_memory",
            "fused_memory",
        ):
            if getattr(self._core, attr, None) is not None:
                loaded.append(attr)
        return loaded

    def _runtime_mode(self) -> str:
        if self._core is None:
            return "normal"
        coordinator = getattr(self._core, "runtime_coordinator", None)
        if coordinator is None or not hasattr(coordinator, "status"):
            return "normal"
        try:
            status = coordinator.status()
        except Exception:
            return "normal"
        if not isinstance(status, dict):
            return "normal"
        return str(status.get("runtime_mode", "normal"))

    def get_runtime_snapshot(self) -> dict[str, Any]:
        threads = list(threading.enumerate())
        thread_info = {
            "count": len(threads),
            "active": [
                {
                    "name": t.name,
                    "daemon": bool(t.daemon),
                    "alive": bool(t.is_alive()),
                }
                for t in threads[:50]
            ],
        }

        event_bus_stats = self._event_bus_stats()
        local_status = self._local_brain_status()
        runtime_manager_stats = self._runtime_manager_stats()

        return {
            "deployment_mode": self._deployment_mode(),
            "runtime_topology": {
                "runtime_manager_available": bool(runtime_manager_stats),
                "event_bus_available": bool(event_bus_stats.get("available")),
                "telemetry_available": self._telemetry is not None,
                "router_v2_available": True,
                "local_brain_available": bool(local_status),
                "runtime_mode": self._runtime_mode(),
            },
            "runtime_manager": runtime_manager_stats,
            "event_bus": event_bus_stats,
            "telemetry": {"available": self._telemetry is not None},
            "local_brain": local_status,
            "active_threads": thread_info,
            "loaded_memory_systems": self._memory_systems(),
        }
