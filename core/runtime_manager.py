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
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.cognitive_contract import normalize_event_envelope
from core.event_bus import Event, EventBus, EventType
from core.orchestrator import Orchestrator
from core.runtime_health import RuntimeHealth
from core.task_queue import Priority, Task, TaskQueue

log = logging.getLogger("RuntimeManager")

_PRIORITY_MAP: dict[str, Priority] = {
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
        self._service_registry: dict[str, Any] = {}
        self._service_statuses: dict[str, dict[str, Any]] = {}
        self._service_load_durations_ms: dict[str, float] = {}
        self._service_init_order: list[str] = []
        self._optional_module_report: dict[str, list[str]] = {"loaded": [], "failed": []}
        self._singleton_warnings: list[str] = []
        self._lifecycle_state = "created"
        self._extension_points: dict[str, Any] = {}
        self._runtime_timeline: list[dict[str, Any]] = []
        self._startup_warnings: list[str] = []
        self._dependency_validation: dict[str, Any] = {"status": "ok", "issues": []}
        self._runtime_health: RuntimeHealth | None = None
        self._persistence_manager: Any | None = None
        self._provenance_service: Any | None = None
        self._runtime_architecture_model: Any | None = None
        self._managed_repositories: dict[str, dict[str, Any]] = {}

        self._running = False
        self._record_timeline_event("startup", "runtime_manager", "runtime", "info", 0.0, "runtime_manager_init")
        self._transition_lifecycle("created", "loaded")
        self._validate_dependencies()
        self.initialize_runtime_services()
        self._transition_lifecycle("loaded", "ready")
        self._loop_thread: threading.Thread | None = None
        self._attach_runtime_bridges()
        self._runtime_health = RuntimeHealth(self)
        self._record_timeline_event("startup", "runtime_manager", "runtime", "info", 0.0, "runtime_ready")

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
        payload: dict[str, Any] | None = None,
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

    def get_stats(self) -> dict[str, Any]:
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

    def _transition_lifecycle(self, previous: str, current: str) -> None:
        if previous != current:
            self._lifecycle_state = current

    def register_extension_point(self, name: str, payload: Any = None) -> None:
        self._extension_points[name] = payload
        self._record_timeline_event("extension", "runtime_manager", name, "info", 0.0, "extension_registered")

    def get_extension_point(self, name: str, default: Any = None) -> Any:
        return self._extension_points.get(name, default)

    def register_extension(self, name: str, interface: str, lifecycle: str = "managed", dependencies: list[str] | None = None, payload: Any = None) -> None:
        self.register_extension_point(
            name,
            {
                "interface": interface,
                "lifecycle": lifecycle,
                "dependencies": list(dependencies or []),
                "payload": payload,
            },
        )

    def update_managed_repository_status(self, repo_name: str, status: dict[str, Any]) -> None:
        self._managed_repositories[str(repo_name)] = dict(status or {})
        self._record_timeline_event("managed_repo", "runtime_manager", str(repo_name), "info", 0.0, "status_updated")

    def _record_timeline_event(self, event_type: str, module: str, service: str, severity: str, duration: float, detail: str) -> None:
        self._runtime_timeline.append(
            {
                "timestamp": time.time(),
                "module": module,
                "service": service,
                "severity": severity,
                "duration": round(duration, 3),
                "event_type": event_type,
                "detail": detail,
            }
        )
        if len(self._runtime_timeline) > 1000:
            self._runtime_timeline = self._runtime_timeline[-1000:]

    def _validate_dependencies(self) -> None:
        issues: list[str] = []
        try:
            import importlib

            importlib.import_module("core.event_bus")
            importlib.import_module("core.orchestrator")
            importlib.import_module("core.task_queue")
        except Exception as exc:
            issues.append(f"dependency-import-failed:{exc}")

        if self._service_registry:
            duplicate_services = [name for name in self._service_registry if name in self._service_registry]
            if duplicate_services:
                issues.append("duplicate-service-registration")
        if self._extension_points:
            pass
        self._dependency_validation = {
            "status": "warning" if issues else "ok",
            "issues": issues,
            "checked_at": time.time(),
        }
        self._startup_warnings = list(issues)
        if issues:
            self._record_timeline_event("validation", "runtime_manager", "runtime", "warning", 0.0, ";".join(issues))

    def get_dependency_validation(self) -> dict[str, Any]:
        return dict(self._dependency_validation)

    def get_startup_warnings(self) -> list[str]:
        return list(self._startup_warnings)

    def get_runtime_health(self) -> dict[str, Any]:
        if self._runtime_health is None:
            self._runtime_health = RuntimeHealth(self)
        return self._runtime_health.snapshot(force=True)

    def get_runtime_metrics(self) -> dict[str, Any]:
        diagnostics = self.get_diagnostics()
        services = self.get_runtime_services()
        modules = self.get_runtime_modules()
        threads = self.get_runtime_threads()
        events = self.get_runtime_events(limit=50)
        return {
            "runtime_id": self.runtime_id,
            "runtime_state": diagnostics["runtime_state"],
            "service_count": services.get("service_count", 0),
            "module_count": modules.get("module_count", 0),
            "thread_count": threads.get("thread_count", 0),
            "event_count": events.get("event_count", 0),
            "queue_depth": self.task_queue.pending_count() if hasattr(self, "task_queue") else 0,
            "failed_module_count": modules.get("failed_module_count", 0),
            "warning_count": len(self._startup_warnings),
            "resource_usage": {
                "memory_mb": self.get_runtime_health().get("resource_usage", {}).get("memory_mb"),
                "cpu_percent": self.get_runtime_health().get("resource_usage", {}).get("cpu_percent"),
            },
        }

    def get_runtime_services(self) -> dict[str, Any]:
        diagnostics = self.get_diagnostics()
        return {
            "runtime_state": diagnostics["runtime_state"],
            "service_count": len(diagnostics.get("services", {})),
            "services": diagnostics.get("services", {}),
        }

    def get_runtime_modules(self) -> dict[str, Any]:
        optional = self._optional_module_report or {"loaded": [], "failed": []}
        return {
            "runtime_state": self._lifecycle_state,
            "module_count": len(optional.get("loaded", [])) + len(optional.get("failed", [])),
            "loaded": list(optional.get("loaded", [])),
            "failed": list(optional.get("failed", [])),
            "failed_module_count": len(optional.get("failed", [])),
        }

    def get_runtime_threads(self) -> dict[str, Any]:
        threads = []
        for thread in threading.enumerate():
            threads.append({
                "name": thread.name,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            })
        return {"thread_count": len(threads), "threads": threads}

    def get_runtime_events(self, limit: int = 100) -> dict[str, Any]:
        events = list(self.event_bus.get_history(limit=limit))
        return {
            "event_count": len(events),
            "events": [
                {
                    "timestamp": getattr(event, "timestamp", None),
                    "type": getattr(event, "type_name", None) or getattr(event, "type", None),
                    "source": getattr(event, "source", None),
                    "payload": getattr(event, "payload", None),
                }
                for event in events
            ],
        }

    def get_runtime_timeline(self, limit: int = 100) -> dict[str, Any]:
        timeline = list(self._runtime_timeline[-limit:])
        return {"event_count": len(timeline), "events": timeline}

    def get_runtime_commands(self) -> dict[str, Any]:
        return {
            "runtime.status": "Returns current runtime state and service health.",
            "runtime.health": "Returns runtime health and resource usage.",
            "runtime.metrics": "Returns runtime summary metrics.",
            "runtime.services": "Returns runtime service registry information.",
            "runtime.modules": "Returns loaded and failed modules.",
            "runtime.events": "Returns recent runtime event history.",
            "runtime.workers": "Returns active runtime threads/workers.",
            "runtime.report": "Returns the runtime architecture report.",
        }

    def execute_runtime_command(self, command: str, **kwargs: Any) -> dict[str, Any]:
        command = (command or "").strip().lower()
        if command == "runtime.status":
            return self.get_runtime_services()
        if command == "runtime.health":
            return self.get_runtime_health()
        if command == "runtime.metrics":
            return self.get_runtime_metrics()
        if command == "runtime.services":
            return self.get_runtime_services()
        if command == "runtime.modules":
            return self.get_runtime_modules()
        if command == "runtime.events":
            return self.get_runtime_events(limit=kwargs.get("limit", 50))
        if command == "runtime.workers":
            return self.get_runtime_threads()
        if command == "runtime.report":
            return self.get_runtime_report()
        return {"error": "unknown_command", "command": command}

    def initialize_runtime_services(self) -> dict[str, Any]:
        """Initialize core services in a deterministic order."""
        self._service_init_order = []
        self._service_registry = {}
        self._service_statuses = {}
        self._service_load_durations_ms = {}
        self._optional_module_report = {"loaded": [], "failed": []}
        self._singleton_warnings = []

        self._initialize_service("persistence_manager", lambda: self._build_persistence_manager())
        self._initialize_service("knowledge_db", lambda: self._build_knowledge_db())
        self._initialize_service("memory_graph", lambda: self._build_memory_graph())
        self._initialize_service("memory_router", lambda: self._build_memory_router())
        self._initialize_service("cognitive_memory_layer", lambda: self._build_cognitive_memory_layer())
        self._initialize_service("local_brain", lambda: self._build_local_brain())
        self._initialize_service("knowledge_comprehension", lambda: self._build_knowledge_comprehension())
        self._initialize_service("reasoning_engine", lambda: self._build_reasoning_engine())
        self._initialize_service("cognitive_synthesis_engine", lambda: self._build_cognitive_synthesis_engine())
        self._initialize_service("provenance_service", lambda: self._build_provenance_service())
        self._initialize_service("runtime_architecture_model", lambda: self._build_runtime_architecture_model())
        self._initialize_service("cognitive_ingress", lambda: self._build_cognitive_ingress())
        self._initialize_service("foundation_architecture", lambda: self._build_foundation_architecture())
        self._initialize_service("local_brain", lambda: self._build_local_brain())
        self._load_optional_modules()
        self.register_extension(
            "cognitive_ingress",
            interface="CognitiveIngress",
            lifecycle="managed",
            dependencies=["reasoning_engine", "provenance_service", "runtime_architecture_model"],
            payload={"entry_point": "modules.cognitive_ingress.get_cognitive_ingress", "contract": "core.cognitive_contract"},
        )
        self.register_extension(
            "foundation_architecture",
            interface="FoundationArchitecture",
            lifecycle="managed",
            dependencies=["cognitive_ingress", "provenance_service", "runtime_architecture_model"],
            payload={"entry_point": "modules.foundation_architecture.FoundationArchitecture", "contract": "unified_feedback_path"},
        )
        return self.get_diagnostics()

    def _initialize_service(self, name: str, factory: Callable[[], Any]) -> Any:
        if name in self._service_registry:
            return self._service_registry[name]
        started_at = time.perf_counter()
        try:
            service = factory()
        except Exception as exc:
            self._set_service_status(name, "degraded", str(exc))
            raise
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        self._service_registry[name] = service
        self._service_load_durations_ms[name] = round(elapsed_ms, 3)
        self._service_init_order.append(name)
        self._bind_module_singleton(name, service)
        self._set_service_status(name, "ready")
        return service

    def _set_service_status(self, name: str, status: str, detail: str | None = None) -> None:
        entry = self._service_statuses.get(name, {})
        entry["status"] = status
        if detail is not None:
            entry["detail"] = detail
        self._service_statuses[name] = entry

    def _build_persistence_manager(self) -> Any:
        from niblit_memory import PersistenceManager

        manager = PersistenceManager(root_dir=str(self._resolve_project_root() / "runtime"))
        manager.initialize_runtime_assets()
        self._persistence_manager = manager
        return manager

    def get_persistence_manager(self) -> Any:
        return self._initialize_service("persistence_manager", self._build_persistence_manager)

    def _build_knowledge_db(self) -> Any:
        from modules.storage import KnowledgeDB

        return KnowledgeDB(persistence_manager=self.get_persistence_manager())

    def _build_provenance_service(self) -> Any:
        from modules.provenance_service import ProvenanceService

        service = ProvenanceService(persistence_manager=self.get_persistence_manager())
        self._provenance_service = service
        return service

    def _build_runtime_architecture_model(self) -> Any:
        from modules.runtime_architecture_model import RuntimeArchitectureModel

        model = RuntimeArchitectureModel(persistence_manager=self.get_persistence_manager())
        self._runtime_architecture_model = model
        return model

    def _build_cognitive_ingress(self) -> Any:
        from modules.cognitive_ingress import CognitiveIngress
        from niblit_memory.unified_memory_engine import get_unified_memory

        return CognitiveIngress(
            runtime_manager=self,
            persistence_manager=self.get_persistence_manager(),
            knowledge_db=self.get_knowledge_db(),
            unified_memory=get_unified_memory(),
            provenance_service=self.get_provenance_service(),
            architecture_model=self.get_runtime_architecture_model(),
        )

    def _build_foundation_architecture(self) -> Any:
        from modules.foundation_architecture import FoundationArchitecture

        foundation = FoundationArchitecture(
            runtime_id=self.runtime_id,
            persistence_manager=self.get_persistence_manager(),
            architecture_model=self.get_runtime_architecture_model(),
        )
        self.event_bus.subscribe_all(foundation.observe_event)
        try:
            local_brain = self.get_local_brain()
            active_provider = getattr(local_brain, "model_name", "")
        except Exception:
            active_provider = ""
        foundation.record_model_selection({"active_provider": active_provider})

        # Phase 2: Attach feedback loop
        try:
            feedback_loop = self._build_cognitive_feedback_loop()
            foundation.set_feedback_loop(feedback_loop)
            self._service_registry["cognitive_feedback_loop"] = feedback_loop
            self._set_service_status("cognitive_feedback_loop", "ready")
        except Exception as exc:
            self._set_service_status("cognitive_feedback_loop", "degraded", str(exc))

        # Phase 3: Attach reflection engine
        try:
            from modules.reflection_engine import get_reflection_engine
            foundation.set_reflection_engine(get_reflection_engine())
        except Exception:
            pass

        # Phase 6: Attach local brain for consultation
        try:
            foundation.set_local_brain(self.get_local_brain())
        except Exception:
            pass

        # Phase 7: Attach provenance service
        try:
            foundation.set_provenance_service(self.get_provenance_service())
        except Exception:
            pass

        # Phase 1: Register all known subsystems
        for name, svc in list(self._service_registry.items()):
            try:
                foundation.register_subsystem(
                    name,
                    role=type(svc).__name__,
                    module_path=type(svc).__module__,
                    service_ref=svc,
                )
            except Exception:
                pass

        # Phase 12: Validate unified path
        try:
            foundation.validate_unified_path()
        except Exception:
            pass

        return foundation

    def _build_cognitive_feedback_loop(self) -> Any:
        from modules.cognitive_feedback_loop import CognitiveFeedbackLoop

        return CognitiveFeedbackLoop()

    def _build_memory_graph(self) -> Any:
        from modules.memory_graph import get_memory_graph

        manager = self.get_persistence_manager()
        graph_path = str(Path(manager.root_dir) / "memory" / "knowledge_graph.json")
        return get_memory_graph(persist_path=graph_path, persistence_manager=manager)

    def _build_memory_router(self) -> Any:
        from modules.cognitive_memory_layer import MemoryRouter

        return MemoryRouter()

    def _build_cognitive_memory_layer(self) -> Any:
        from modules.cognitive_memory_layer import get_cognitive_memory_layer

        return get_cognitive_memory_layer(
            memory_graph=self.get_memory_graph(),
            persistence_manager=self.get_persistence_manager(),
        )

    def _build_knowledge_comprehension(self) -> Any:
        from modules.knowledge_comprehension import get_knowledge_comprehension

        return get_knowledge_comprehension(
            knowledge_db=self.get_knowledge_db(),
            memory_graph=self.get_memory_graph(),
            persistence_manager=self.get_persistence_manager(),
        )

    def _build_reasoning_engine(self) -> Any:
        from modules.reasoning_engine import get_reasoning_engine

        return get_reasoning_engine(
            knowledge_db=self.get_knowledge_db(),
            memory_graph=self.get_memory_graph(),
            persistence_manager=self.get_persistence_manager(),
        )

    def _build_cognitive_synthesis_engine(self) -> Any:
        from modules.cognitive_synthesis_engine import CognitiveSynthesisEngine
        from modules.graph_scoring_engine import GraphScoringEngine

        memory_graph = self.get_memory_graph()
        scoring_engine = GraphScoringEngine(memory_graph=memory_graph)
        reasoning_engine = self.get_reasoning_engine()
        if hasattr(reasoning_engine, "graph_scoring_engine"):
            reasoning_engine.graph_scoring_engine = scoring_engine
        return CognitiveSynthesisEngine(
            reasoning_engine=reasoning_engine,
            graph_scoring_engine=scoring_engine,
        )

    def _build_local_brain(self) -> Any:
        try:
            from modules.local_brain import get_local_brain

            return get_local_brain(persistence_manager=self.get_persistence_manager())
        except Exception as exc:
            self._set_service_status("local_brain", "degraded", str(exc))
            return None

    def _load_optional_modules(self) -> None:
        try:
            import module_loader

            report = module_loader.load_modules()
            self._optional_module_report = {
                "loaded": list(report.get("loaded", [])),
                "failed": list(report.get("failed", [])),
            }
        except Exception as exc:
            self._optional_module_report = {"loaded": [], "failed": [str(exc)]}
            self._singleton_warnings.append(f"optional-module-load-failed: {exc}")

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
        if name == "local_brain":
            try:
                import modules.local_brain as local_brain_module

                local_brain_module._instance = service
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
            return self._initialize_service("knowledge_db", self._build_knowledge_db)
        except Exception as exc:
            self._set_service_status("knowledge_db", "degraded", str(exc))
            raise

    def get_provenance_service(self) -> Any:
        try:
            service = self._initialize_service("provenance_service", self._build_provenance_service)
            self._provenance_service = service
            return service
        except Exception as exc:
            self._set_service_status("provenance_service", "degraded", str(exc))
            raise

    def get_runtime_architecture_model(self) -> Any:
        try:
            model = self._initialize_service("runtime_architecture_model", self._build_runtime_architecture_model)
            self._runtime_architecture_model = model
            return model
        except Exception as exc:
            self._set_service_status("runtime_architecture_model", "degraded", str(exc))
            raise

    def get_cognitive_ingress(self) -> Any:
        try:
            return self._initialize_service("cognitive_ingress", self._build_cognitive_ingress)
        except Exception as exc:
            self._set_service_status("cognitive_ingress", "degraded", str(exc))
            raise

    def get_foundation_architecture(self) -> Any:
        try:
            return self._initialize_service("foundation_architecture", self._build_foundation_architecture)
        except Exception as exc:
            self._set_service_status("foundation_architecture", "degraded", str(exc))
            raise

    def process_cognitive_request(
        self,
        text: str,
        *,
        source: str = "runtime_manager",
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        execution = self.get_cognitive_ingress().ingest(
            text,
            source=source,
            priority=priority,
            metadata=dict(metadata or {}),
        )
        return execution.to_dict() if hasattr(execution, "to_dict") else dict(execution or {})

    def get_memory_graph(self) -> Any:
        """Return the shared MemoryGraph instance owned by the runtime."""
        try:
            return self._initialize_service("memory_graph", self._build_memory_graph)
        except Exception as exc:
            self._set_service_status("memory_graph", "degraded", str(exc))
            raise

    def get_reasoning_engine(self) -> Any:
        """Return the shared ReasoningEngine instance owned by the runtime."""
        try:
            engine = self._initialize_service("reasoning_engine", self._build_reasoning_engine)
            knowledge_db = self.get_knowledge_db()
            memory_graph = self.get_memory_graph()
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

    def get_cognitive_synthesis_engine(self) -> Any:
        """Return the runtime-owned synthesis layer for final explanation building."""
        try:
            return self._initialize_service("cognitive_synthesis_engine", self._build_cognitive_synthesis_engine)
        except Exception as exc:
            self._set_service_status("cognitive_synthesis_engine", "degraded", str(exc))
            raise

    def get_knowledge_comprehension(self) -> Any:
        """Return the shared KnowledgeComprehension instance owned by the runtime."""
        try:
            comprehension = self._initialize_service("knowledge_comprehension", self._build_knowledge_comprehension)
            knowledge_db = self.get_knowledge_db()
            memory_graph = self.get_memory_graph()
            if knowledge_db is not None:
                comprehension.knowledge_db = knowledge_db
            if memory_graph is not None:
                comprehension.memory_graph = memory_graph
            return comprehension
        except Exception as exc:
            self._set_service_status("knowledge_comprehension", "degraded", str(exc))
            raise

    def get_cognitive_memory_layer(self) -> Any:
        """Return the runtime-owned semantic memory layer."""
        try:
            return self._initialize_service("cognitive_memory_layer", self._build_cognitive_memory_layer)
        except Exception as exc:
            self._set_service_status("cognitive_memory_layer", "degraded", str(exc))
            raise

    def get_memory_router(self) -> Any:
        """Return the routing service that decides which memory mode to use."""
        try:
            return self._initialize_service("memory_router", self._build_memory_router)
        except Exception as exc:
            self._set_service_status("memory_router", "degraded", str(exc))
            raise

    def get_local_brain(self) -> Any:
        """Return the shared LocalBrain instance owned by the runtime."""
        try:
            return self._initialize_service("local_brain", self._build_local_brain)
        except Exception as exc:
            self._set_service_status("local_brain", "degraded", str(exc))
            raise

    def get_diagnostics(self) -> dict[str, Any]:
        """Expose lightweight runtime diagnostics, including service health."""
        services = {}
        for name in [
            "persistence_manager",
            "knowledge_db",
            "memory_graph",
            "memory_router",
            "cognitive_memory_layer",
            "reasoning_engine",
            "cognitive_synthesis_engine",
            "knowledge_comprehension",
            "local_brain",
            "foundation_architecture",
            "cognitive_feedback_loop",
        ]:
            if name in self._service_registry:
                services[name] = {
                    "status": self._service_statuses.get(name, {}).get("status", "ready"),
                    "detail": self._service_statuses.get(name, {}).get("detail"),
                    "object_type": type(self._service_registry[name]).__name__,
                    "object_id": id(self._service_registry[name]),
                    "load_duration_ms": self._service_load_durations_ms.get(name),
                }
            elif name in self._service_statuses:
                services[name] = dict(self._service_statuses[name])
            else:
                services[name] = {"status": "unknown"}
        return {
            "runtime_id": self.runtime_id,
            "running": self._running,
            "runtime_state": self._lifecycle_state,
            "repository_root": str(Path(__file__).resolve().parent.parent),
            "resolved_project_root": str(self._resolve_project_root()),
            "python_executable": sys.executable,
            "working_directory": str(Path.cwd()),
            "sys_path_additions": self._sys_path_additions(),
            "services": services,
            "persistence": self.get_persistence_manager().get_diagnostics() if self._persistence_manager is not None else {},
            "optional_modules": self._optional_module_report,
            "failed_modules": self._optional_module_report.get("failed", []),
            "initialization_state": {
                "order": list(self._service_init_order),
                "status": {name: self._service_statuses.get(name, {}).get("status", "unknown") for name in self._service_init_order},
            },
            "runtime_ownership": {name: f"RuntimeManager:{id(self._service_registry[name])}" for name in self._service_registry},
            "duplicate_singleton_warnings": list(self._singleton_warnings),
            "service_lifecycle_states": {name: self._service_statuses.get(name, {}).get("status", "unknown") for name in self._service_statuses},
            "extension_points": dict(self._extension_points),
            "managed_repositories": dict(self._managed_repositories),
        }

    def get_runtime_report(self) -> dict[str, Any]:
        """Return a structured runtime architecture snapshot for operators and tests."""
        diagnostics = self.get_diagnostics()
        return {
            "runtime_id": diagnostics["runtime_id"],
            "runtime_state": diagnostics["runtime_state"],
            "repository_root": diagnostics["repository_root"],
            "resolved_project_root": diagnostics["resolved_project_root"],
            "python_executable": diagnostics["python_executable"],
            "working_directory": diagnostics["working_directory"],
            "services": diagnostics["services"],
            "persistence": diagnostics.get("persistence", {}),
            "initialization_state": diagnostics["initialization_state"],
            "lifecycle_model": {
                "current": diagnostics["runtime_state"],
                "transitions": [
                    {"from": "created", "to": "loaded"},
                    {"from": "loaded", "to": "ready"},
                ],
            },
            "boot_sequence": [
                {"name": "runtime_manager_init", "status": "completed"},
                {"name": "service_initialization", "status": "completed"},
                {"name": "optional_module_loading", "status": "completed"},
            ],
            "event_bridge": {
                "module_bridge_installed": bool(self._module_bus_attached),
                "core_event_bus": type(self.event_bus).__name__,
                "module_event_bus": type(self._module_bus).__name__ if self._module_bus is not None else None,
            },
            "extension_points": diagnostics["extension_points"],
            "optional_modules": diagnostics["optional_modules"],
            "failed_modules": diagnostics["failed_modules"],
        }

    def _resolve_project_root(self) -> Path:
        try:
            import module_loader

            return Path(module_loader.get_repo_root()).resolve()
        except Exception:
            return Path(__file__).resolve().parent.parent

    def _sys_path_additions(self) -> list[str]:
        root = self._resolve_project_root()
        return [str(path) for path in [root, root / "modules"] if str(path) in sys.path]

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

    def _lineage_payload(self, payload: dict[str, Any] | None, event_type: str, source: str) -> dict[str, Any]:
        data = dict(payload or {})
        trace_id = data.get("trace_id") or f"{self.runtime_id}:{event_type}:{int(time.time() * 1000)}"
        data.setdefault("trace_id", trace_id)
        data.setdefault("runtime_id", self.runtime_id)
        data.setdefault("cognition_id", data.get("cognition_id", ""))
        data.setdefault("source_module", source)
        data.setdefault("source_repository", "niblit")
        data.setdefault("correlation_id", data.get("correlation_id") or str(trace_id))
        lineage_channel = str(data.get("lineage_channel") or "runtime_manager.bridge")
        data.setdefault("lineage_channel", lineage_channel)
        lineage = list(data.get("lineage", []) or [])
        lineage.append(f"{source}:{event_type}")
        data["lineage"] = lineage[-12:]
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

    def _emit_to_unified_runtime(self, event_type: str, source: str, payload: dict[str, Any]) -> None:
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
        envelope = normalize_event_envelope(
            event_type=event.type_name,
            source=event.source,
            payload=payload,
            runtime_id=self.runtime_id,
            cognition_id=str(payload.get("cognition_id", "")),
            trace_id=str(payload.get("trace_id", "")),
            event_priority=str(payload.get("event_priority", "normal")),
        )
        payload = envelope.payload
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
        try:
            self.get_provenance_service().update(
                envelope.trace_id,
                request_id=str(payload.get("request_id", envelope.trace_id)),
                executed_function=module_event_type,
                output_summary=str(payload.get("summary") or payload.get("response") or module_event_type),
                downstream_consumers=["modules.event_bus", "unified_runtime"],
            )
            self.get_runtime_architecture_model().observe_event(
                {"type": module_event_type, "source": event.source, "payload": payload},
                lineage_channel="core_bridge",
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
        envelope = normalize_event_envelope(
            event_type=event_type,
            source=source,
            payload=lineage,
            runtime_id=self.runtime_id,
            cognition_id=str(lineage.get("cognition_id", "")),
            trace_id=str(lineage.get("trace_id", "")),
            event_priority=str(lineage.get("event_priority", "normal")),
        )
        lineage = envelope.payload
        try:
            self.event_bus.publish(
                Event(
                    type=self._module_to_core_event_type(event_type),
                    payload={**lineage, "_bridge_origin": "modules"},
                    source=source,
                    runtime_id=self.runtime_id,
                    trace_id=str(lineage.get("trace_id", "")),
                    source_repository=str(lineage.get("source_repository", "niblit")),
                    correlation_id=str(lineage.get("correlation_id", "")),
                    cognition_id=str(lineage.get("cognition_id", "")),
                    source_module=str(lineage.get("source_module", source)),
                    event_category=str(lineage.get("event_category", self._categorize(event_type))),
                    event_priority=str(lineage.get("event_priority", "normal")),
                    bridge_origin="modules",
                )
            )
        except Exception:
            pass
        try:
            self.get_provenance_service().update(
                envelope.trace_id,
                request_id=str(lineage.get("request_id", envelope.trace_id)),
                executed_function=event_type,
                output_summary=str(lineage.get("summary") or lineage.get("response") or event_type),
                downstream_consumers=["core.event_bus", "unified_runtime"],
            )
            self.get_runtime_architecture_model().observe_event(
                {"type": event_type, "source": source, "payload": lineage},
                lineage_channel="modules_bridge",
            )
        except Exception:
            pass
        self._emit_to_unified_runtime(event_type, source, lineage)


if __name__ == "__main__":
    print('Running runtime_manager.py')
