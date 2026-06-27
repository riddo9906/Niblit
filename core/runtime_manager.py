#!/usr/bin/env python3
"""
core/runtime_manager.py — Top-level runtime coordinator for Niblit.

The RuntimeManager owns the shared EventBus, TaskQueue, and Orchestrator
instances.  It exposes a simple facade so the rest of the system never needs
to import from multiple ``core/`` sub-modules.

Architecture role (Phase 1)
---------------------------

    niblit_core.py  (or any entry point)
           │
           ▼
    RuntimeManager.start()
           │
      ┌────┴────┐
      │         │
   EventBus  TaskQueue
      │         │
      └────┬────┘
           │
       Orchestrator
           │
        Agents…

Usage::

    from core.runtime_manager import RuntimeManager

    rm = RuntimeManager()
    rm.register_agent("research", my_research_handler)
    rm.submit_task("research", payload={"topic": "neural nets"}, priority="high")
    rm.dispatch_pending()   # or run rm.start_loop() in a background thread
"""

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import Event, EventBus, EventType
from core.orchestrator import Orchestrator
from core.task_queue import Priority, Task, TaskQueue

log = logging.getLogger("RuntimeManager")

_PRIORITY_MAP: Dict[str, Priority] = {
    "low": Priority.LOW,
    "normal": Priority.NORMAL,
    "high": Priority.HIGH,
    "critical": Priority.CRITICAL,
}

# Process-wide guard: only one core↔modules event bridge on the singleton module bus.
_RUNTIME_BRIDGES_INSTALLED = False
_RUNTIME_BRIDGES_LOCK = threading.Lock()


class RuntimeManager:
    """
    Facade that wires together EventBus, TaskQueue, and Orchestrator.

    Args:
        history_limit:  Maximum events kept in the event bus history.
        queue_max_size: Maximum pending tasks (0 = unlimited).
    """

    def __init__(
        self,
        history_limit: int = 1000,
        queue_max_size: int = 0,
    ) -> None:
        self.runtime_id = f"runtime-{uuid.uuid4().hex[:12]}"
        self.event_bus = EventBus(history_limit=history_limit)
        self.task_queue = TaskQueue(max_size=queue_max_size)
        self.orchestrator = Orchestrator(self.event_bus, self.task_queue)
        self._module_bus = None
        self._module_bus_attached = False
        self._service_registry: Dict[str, Any] = {}
        self._service_statuses: Dict[str, Dict[str, Any]] = {}

        self._running = False
        self._loop_thread: Optional[threading.Thread] = None
        self._attach_runtime_bridges()

        # Publish system-started event
        self.event_bus.publish(Event(
            type=EventType.SYSTEM_STARTED,
            payload={"time": time.time()},
            source="runtime_manager",
            runtime_id=self.runtime_id,
            source_module="runtime_manager",
            event_category="runtime",
            event_priority="high",
        ))

    # ── agent registration ────────────────────────────────────────────────────

    def register_agent(
        self,
        task_type: str,
        handler: Callable[[Task, EventBus], Any],
    ) -> None:
        """Register an agent handler for a task type."""
        self.orchestrator.register_agent(task_type, handler)

    # ── task submission ───────────────────────────────────────────────────────

    def submit_task(
        self,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        source: str = "runtime_manager",
    ) -> Task:
        """
        Create and enqueue a task.

        Args:
            task_type: Type string matched to an agent handler.
            payload:   Dict of task parameters.
            priority:  One of ``"low"``, ``"normal"``, ``"high"``, ``"critical"``.
            source:    Identifying label for the submitter.

        Returns:
            The enqueued Task object.
        """
        pri = _PRIORITY_MAP.get(priority.lower(), Priority.NORMAL)
        return self.task_queue.enqueue_simple(
            task_type=task_type,
            payload=payload or {},
            priority=pri,
            source=source,
        )

    # ── dispatch ──────────────────────────────────────────────────────────────

    def dispatch_pending(self, max_tasks: int = 0) -> int:
        """
        Dispatch all pending tasks (or up to *max_tasks*).

        Returns:
            Number of tasks dispatched.
        """
        dispatched = 0
        while True:
            if max_tasks and dispatched >= max_tasks:
                break
            result = self.orchestrator.dispatch_next()
            if result is None and self.task_queue.pending_count() == 0:
                break
            dispatched += 1
        return dispatched

    # ── background loop ───────────────────────────────────────────────────────

    def start_loop(self, poll_interval: float = 0.5) -> None:
        """Start the background dispatch loop in a daemon thread."""
        if self._running:
            return
        self._running = True
        self._loop_thread = threading.Thread(
            target=self._loop, args=(poll_interval,), daemon=True, name="RuntimeLoop"
        )
        self._loop_thread.start()
        log.info("[RuntimeManager] background loop started")

    def stop_loop(self) -> None:
        """Signal the background loop to stop."""
        self._running = False
        self.event_bus.publish(Event(
            type=EventType.SYSTEM_STOPPING,
            payload={},
            source="runtime_manager",
        ))
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)
        log.info("[RuntimeManager] background loop stopped")

    def _loop(self, poll_interval: float) -> None:
        while self._running:
            try:
                self.dispatch_pending(max_tasks=10)
            except Exception as exc:
                log.warning("[RuntimeManager] dispatch error: %s", exc)
            time.sleep(poll_interval)

    # ── stats / introspection ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "runtime_id": self.runtime_id,
            "orchestrator": self.orchestrator.get_stats(),
            "event_history": len(self.event_bus.get_history()),
            "event_diagnostics": self.event_bus.observability_report(),
            "services": self.get_diagnostics().get("services", {}),
        }

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Shortcut to subscribe an event handler via the runtime."""
        self.event_bus.subscribe(event_type, handler)

    def _set_service_status(self, name: str, status: str, detail: Optional[str] = None) -> None:
        entry = self._service_statuses.get(name, {})
        entry["status"] = status
        if detail is not None:
            entry["detail"] = detail
        self._service_statuses[name] = entry

    def _get_or_create_service(self, name: str, factory: Callable[[], Any]) -> Any:
        service = self._service_registry.get(name)
        if service is not None:
            return service
        try:
            service = factory()
        except Exception as exc:
            self._set_service_status(name, "degraded", str(exc))
            raise
        self._service_registry[name] = service
        self._bind_module_singleton(name, service)
        self._set_service_status(name, "ready")
        return service

    def _bind_module_singleton(self, name: str, service: Any) -> None:
        if name == "memory_graph":
            try:
                import modules.memory_graph as memory_graph_module

                memory_graph_module._graph_singleton = service
            except Exception:
                pass
            return
        if name == "reasoning_engine":
            try:
                import modules.reasoning_engine as reasoning_engine_module

                reasoning_engine_module._INSTANCE = service
            except Exception:
                pass
            return
        if name == "knowledge_comprehension":
            try:
                import modules.knowledge_comprehension as comprehension_module

                comprehension_module._comprehension_singleton = service
            except Exception:
                pass

    def get_knowledge_db(self) -> Any:
        """Return the shared KnowledgeDB instance owned by the runtime."""
        try:
            from modules.storage import KnowledgeDB

            return self._get_or_create_service("knowledge_db", lambda: KnowledgeDB())
        except Exception as exc:
            self._set_service_status("knowledge_db", "degraded", str(exc))
            raise

    def get_memory_graph(self) -> Any:
        """Return the shared MemoryGraph instance owned by the runtime."""
        try:
            from modules.memory_graph import get_memory_graph

            return self._get_or_create_service(
                "memory_graph",
                lambda: get_memory_graph(),
            )
        except Exception as exc:
            self._set_service_status("memory_graph", "degraded", str(exc))
            raise

    def get_reasoning_engine(self) -> Any:
        """Return the shared ReasoningEngine instance owned by the runtime."""
        try:
            from modules.reasoning_engine import get_reasoning_engine

            knowledge_db = self.get_knowledge_db()
            memory_graph = self.get_memory_graph()
            engine = self._get_or_create_service(
                "reasoning_engine",
                lambda: get_reasoning_engine(knowledge_db=knowledge_db, memory_graph=memory_graph),
            )
            if knowledge_db is not None:
                engine.db = knowledge_db
            if memory_graph is not None:
                engine.memory_graph = memory_graph
                if hasattr(engine, "_sync_graph_from_memory_graph"):
                    engine._sync_graph_from_memory_graph()
            return engine
        except Exception as exc:
            self._set_service_status("reasoning_engine", "degraded", str(exc))
            raise

    def get_knowledge_comprehension(self) -> Any:
        """Return the shared KnowledgeComprehension instance owned by the runtime."""
        try:
            from modules.knowledge_comprehension import get_knowledge_comprehension

            knowledge_db = self.get_knowledge_db()
            memory_graph = self.get_memory_graph()
            comprehension = self._get_or_create_service(
                "knowledge_comprehension",
                lambda: get_knowledge_comprehension(
                    knowledge_db=knowledge_db,
                    memory_graph=memory_graph,
                ),
            )
            if knowledge_db is not None:
                comprehension.knowledge_db = knowledge_db
            if memory_graph is not None:
                comprehension.memory_graph = memory_graph
            return comprehension
        except Exception as exc:
            self._set_service_status("knowledge_comprehension", "degraded", str(exc))
            raise

    def get_diagnostics(self) -> Dict[str, Any]:
        """Expose lightweight runtime diagnostics, including service health."""
        services = {}
        for name in [
            "knowledge_db",
            "memory_graph",
            "reasoning_engine",
            "knowledge_comprehension",
        ]:
            if name in self._service_registry:
                services[name] = {
                    "status": self._service_statuses.get(name, {}).get("status", "ready"),
                    "detail": self._service_statuses.get(name, {}).get("detail"),
                    "object_type": type(self._service_registry[name]).__name__,
                }
            elif name in self._service_statuses:
                services[name] = dict(self._service_statuses[name])
            else:
                services[name] = {"status": "unknown"}
        return {
            "runtime_id": self.runtime_id,
            "running": self._running,
            "services": services,
        }

    def _attach_runtime_bridges(self) -> None:
        """Best-effort bridge into the canonical modules event stream + UI runtime."""
        global _RUNTIME_BRIDGES_INSTALLED  # pylint: disable=global-statement
        try:
            from modules.event_bus import get_event_bus

            self._module_bus = get_event_bus()
            with _RUNTIME_BRIDGES_LOCK:
                if _RUNTIME_BRIDGES_INSTALLED:
                    self._module_bus_attached = True
                    log.debug(
                        "[RuntimeManager] module event bridge already installed — "
                        "skipping duplicate subscriptions"
                    )
                    return
                self._module_bus.subscribe_all(self._mirror_modules_event)
                self.event_bus.subscribe_all(self._mirror_core_event)
                _RUNTIME_BRIDGES_INSTALLED = True
                self._module_bus_attached = True
        except Exception as exc:
            log.debug("[RuntimeManager] module event bridge unavailable: %s", exc)

    def _lineage_payload(self, payload: Dict[str, Any] | None, event_type: str, source: str) -> Dict[str, Any]:
        data = dict(payload or {})
        data.setdefault("trace_id", data.get("trace_id") or f"{self.runtime_id}:{event_type}:{int(time.time() * 1000)}")
        data.setdefault("runtime_id", self.runtime_id)
        data.setdefault("cognition_id", data.get("cognition_id", ""))
        data.setdefault("source_module", source)
        data.setdefault("event_category", data.get("event_category") or self._categorize(event_type))
        data.setdefault("event_priority", data.get("event_priority", "normal"))
        return data

    @staticmethod
    def _categorize(event_type: str) -> str:
        etype = str(event_type or "").lower()
        if "provider" in etype:
            return "provider"
        if "memory" in etype or "knowledge" in etype:
            return "memory"
        if "reflect" in etype or "cognition" in etype:
            return "cognition"
        if "learn" in etype or "train" in etype:
            return "learning"
        if "metric" in etype or "telemetry" in etype:
            return "telemetry"
        if "task" in etype or "plan" in etype:
            return "orchestration"
        return "runtime"

    @staticmethod
    def _core_to_module_event_type(event_type: str) -> str:
        mapping = {
            EventType.LEARNING_CYCLE_COMPLETED.value: "learning.cycle.complete",
            EventType.REFLECTION_COMPLETED.value: "reflection.complete",
            EventType.KNOWLEDGE_UPDATED.value: "knowledge.updated",
            EventType.TASK_CREATED.value: "task.created",
            EventType.TASK_COMPLETED.value: "task.completed",
            EventType.TASK_FAILED.value: "task.failed",
            EventType.SYSTEM_STARTED.value: "runtime.system.started",
            EventType.SYSTEM_STOPPING.value: "runtime.system.stopping",
            EventType.ERROR_OCCURRED.value: "runtime.error",
            EventType.METRIC_RECORDED.value: "telemetry.metric.recorded",
        }
        return mapping.get(event_type, event_type.replace("_", "."))

    @staticmethod
    def _module_to_core_event_type(event_type: str) -> EventType | str:
        mapping = {
            "learning.cycle.complete": EventType.LEARNING_CYCLE_COMPLETED,
            "reflection.complete": EventType.REFLECTION_COMPLETED,
            "knowledge.updated": EventType.KNOWLEDGE_UPDATED,
            "task.created": EventType.TASK_CREATED,
            "task.completed": EventType.TASK_COMPLETED,
            "task.failed": EventType.TASK_FAILED,
            "runtime.system.started": EventType.SYSTEM_STARTED,
            "runtime.system.stopping": EventType.SYSTEM_STOPPING,
            "runtime.error": EventType.ERROR_OCCURRED,
            "telemetry.metric.recorded": EventType.METRIC_RECORDED,
        }
        return mapping.get(event_type, event_type)

    def _emit_to_unified_runtime(self, event_type: str, source: str, payload: Dict[str, Any]) -> None:
        try:
            from modules.unified_runtime import get_unified_runtime

            runtime = get_unified_runtime()
            if hasattr(runtime, "ingest_external_event"):
                runtime.ingest_external_event(event_type=event_type, source=source, payload=payload)
        except Exception:
            return

    def _mirror_core_event(self, event: Event) -> None:
        if getattr(event, "bridge_origin", "") == "modules":
            return
        payload = self._lineage_payload(event.payload, event.type_name, event.source)
        payload["_bridge_origin"] = "core"
        module_event_type = self._core_to_module_event_type(event.type_name)
        if self._module_bus is not None:
            try:
                from modules.event_bus import NiblitEvent

                self._module_bus.publish(
                    NiblitEvent(
                        type=module_event_type,
                        source=event.source,
                        payload=payload,
                    )
                )
            except Exception:
                pass
        self._emit_to_unified_runtime(module_event_type, event.source, payload)

    def _mirror_modules_event(self, event: Any) -> None:
        payload = dict(getattr(event, "payload", {}) or {})
        if payload.get("_bridge_origin") == "core":
            return
        event_type = str(getattr(event, "type", "event"))
        source = str(getattr(event, "source", "modules"))
        lineage = self._lineage_payload(payload, event_type, source)
        try:
            self.event_bus.publish(
                Event(
                    type=self._module_to_core_event_type(event_type),
                    payload={**lineage, "_bridge_origin": "modules"},
                    source=source,
                    runtime_id=self.runtime_id,
                    trace_id=str(lineage.get("trace_id", "")),
                    cognition_id=str(lineage.get("cognition_id", "")),
                    source_module=str(lineage.get("source_module", source)),
                    event_category=str(lineage.get("event_category", self._categorize(event_type))),
                    event_priority=str(lineage.get("event_priority", "normal")),
                    bridge_origin="modules",
                )
            )
        except Exception:
            pass
        self._emit_to_unified_runtime(event_type, source, lineage)


if __name__ == "__main__":
    print('Running runtime_manager.py')
