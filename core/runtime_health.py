import os
import threading
import time
from typing import Any, Dict, Optional


class RuntimeHealth:
    """Lightweight runtime health monitor with cached snapshots."""

    def __init__(self, runtime_manager: Any, snapshot_interval_seconds: float = 5.0) -> None:
        self._runtime = runtime_manager
        self._snapshot_interval_seconds = snapshot_interval_seconds
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._last_snapshot_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self, force: bool = False) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if not force and self._last_snapshot is not None and (now - self._last_snapshot_at) < self._snapshot_interval_seconds:
                return self._last_snapshot

            diagnostics = self._runtime.get_diagnostics()
            services = self._runtime.get_runtime_services()
            modules = self._runtime.get_runtime_modules()
            threads = self._runtime.get_runtime_threads()
            events = self._runtime.get_runtime_events(limit=200)
            queue_depth = int(self._runtime.task_queue.pending_count()) if hasattr(self._runtime, "task_queue") else 0
            dependency_validation = self._runtime.get_dependency_validation()
            startup_warnings = list(self._runtime.get_startup_warnings())

            snapshot = {
                "status": self._derive_status(dependency_validation, services, modules, startup_warnings),
                "runtime_state": diagnostics.get("runtime_state", "unknown"),
                "service_count": len(services.get("services", {})),
                "module_count": modules.get("module_count", 0),
                "thread_count": len(threads.get("threads", [])),
                "queue_depth": queue_depth,
                "failed_module_count": len(modules.get("failed", [])),
                "warning_count": len(startup_warnings),
                "dependency_validation": dependency_validation,
                "services": services.get("services", {}),
                "modules": modules,
                "threads": threads,
                "events": events,
                "resource_usage": {
                    "memory_mb": self._collect_memory_usage(),
                    "cpu_percent": self._collect_cpu_usage(),
                },
                "startup_warnings": startup_warnings,
            }
            self._last_snapshot = snapshot
            self._last_snapshot_at = now
            return snapshot

    @staticmethod
    def _derive_status(dependency_validation: Dict[str, Any], services: Dict[str, Any], modules: Dict[str, Any], startup_warnings: list) -> str:
        if dependency_validation.get("status") == "failed":
            return "degraded"
        if any(service.get("status") == "degraded" for service in services.get("services", {}).values()):
            return "degraded"
        if modules.get("failed") or startup_warnings:
            return "warning"
        return "healthy"

    @staticmethod
    def _collect_memory_usage() -> Optional[float]:
        try:
            import psutil  # type: ignore

            process = psutil.Process(os.getpid())
            return round(process.memory_info().rss / (1024 * 1024), 2)
        except Exception:
            return None

    @staticmethod
    def _collect_cpu_usage() -> Optional[float]:
        try:
            import psutil  # type: ignore

            process = psutil.Process(os.getpid())
            return round(process.cpu_percent(interval=None), 2)
        except Exception:
            return None
