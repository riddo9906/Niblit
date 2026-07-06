#!/usr/bin/env python3
"""
core/event_bus.py — Pub/sub event bus for inter-agent communication.

Agents publish typed events to the bus; other agents subscribe to event types
they care about.  Handlers are called synchronously in the order they were
registered.

Example::

    from core.event_bus import EventBus, Event, EventType

    bus = EventBus()

    def on_research(event: Event):
        print(f"Got research request: {event.payload['topic']}")

    bus.subscribe(EventType.RESEARCH_REQUEST, on_research)
    bus.publish(Event(EventType.RESEARCH_REQUEST, payload={"topic": "neural nets"}))

Architecture role (Phase 1)
---------------------------
Agents communicate exclusively through the event bus; they never call each
other's methods directly.  This decouples the system and makes it easy to
add, remove, or replace individual agents without touching their consumers.
"""

import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("EventBus")


class EventType(str, Enum):
    """All event types understood by the Niblit runtime."""

    # ── Research / knowledge ──────────────────────────────────────────────────
    RESEARCH_REQUEST = "research_request"
    RESEARCH_COMPLETED = "research_completed"
    KNOWLEDGE_UPDATED = "knowledge_updated"

    # ── Code generation ────────────────────────────────────────────────────────
    CODE_GENERATION_REQUEST = "code_generation_request"
    CODE_GENERATION_COMPLETED = "code_generation_completed"
    CODE_COMPILATION_REQUESTED = "code_compilation_requested"
    CODE_COMPILATION_DONE = "code_compilation_done"
    CODE_REFACTOR_REQUESTED = "code_refactor_requested"

    # ── Testing / validation ────────────────────────────────────────────────────
    TEST_RUN_REQUESTED = "test_run_requested"
    TEST_RUN_COMPLETED = "test_run_completed"
    TEST_FAILED = "test_failed"

    # ── Reflection / learning ──────────────────────────────────────────────────
    REFLECTION_REQUESTED = "reflection_requested"
    REFLECTION_COMPLETED = "reflection_completed"
    LEARNING_CYCLE_STARTED = "learning_cycle_started"
    LEARNING_CYCLE_COMPLETED = "learning_cycle_completed"
    # Additive: gap detection and contradiction signals
    KNOWLEDGE_GAP_DETECTED = "knowledge_gap_detected"
    CONTRADICTION_DETECTED = "contradiction_detected"

    # ── Architecture / self-evolution ─────────────────────────────────────────
    ARCHITECTURE_ANALYSIS_REQUESTED = "architecture_analysis_requested"
    ARCHITECTURE_ANALYSIS_DONE = "architecture_analysis_done"
    REFACTOR_PLAN_GENERATED = "refactor_plan_generated"
    EVOLUTION_STEP_COMPLETED = "evolution_step_completed"

    # ── Planning ───────────────────────────────────────────────────────────────
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    PLAN_GENERATED = "plan_generated"

    # ── System ─────────────────────────────────────────────────────────────────
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPING = "system_stopping"
    ERROR_OCCURRED = "error_occurred"
    METRIC_RECORDED = "metric_recorded"

    # ── Multi-repository boot sequence ─────────────────────────────────────────
    LAYER_INITIALIZED = "layer.initialized"
    LAYER_DEGRADED = "layer.degraded"
    LAYER_FAILED = "layer.failed"
    LAYER_RETRYING = "layer.retrying"
    RUNTIME_READY = "runtime.ready"
    REPO_DISCOVERED = "repo.discovered"
    REPO_UNAVAILABLE = "repo.unavailable"
    REPO_REGISTERED = "repo.registered"


@dataclass
class Event:
    """
    An immutable event object passed between agents via the bus.

    Attributes:
        type:      Enum value identifying the event type.
        payload:   Arbitrary dict of event data.
        source:    Name of the agent / component that published the event.
        timestamp: Unix timestamp (set automatically).
        event_id:  Auto-incrementing integer ID.
    """

    type: EventType | str
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    event_id: int = field(default=0)
    trace_id: str = ""
    runtime_id: str = ""
    cognition_id: str = ""
    source_module: str = ""
    event_category: str = ""
    event_priority: str = "normal"
    bridge_origin: str = ""
    # Unified multi-repository envelope fields
    source_repository: str = "niblit"
    correlation_id: str = ""
    parent_event_id: int = 0
    destination: str = ""
    intent: str = ""

    def __post_init__(self) -> None:
        if not self.source_module:
            self.source_module = self.source
        if not self.event_category:
            self.event_category = _categorize_event_type(self.type_name)
        if not self.trace_id:
            seed = f"{self.type_name}:{self.source}:{self.timestamp}"
            self.trace_id = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:16]

    @property
    def type_name(self) -> str:
        try:
            raw = self.type
            if isinstance(raw, EventType):
                return raw.value
            return str(raw)
        except Exception:
            return "unknown"

    def __repr__(self) -> str:
        return (
            f"Event(type={self.type_name!r}, source={self.source!r}, "
            f"payload_keys={list(self.payload.keys())})"
        )


Handler = Callable[[Event], None]


def _categorize_event_type(event_type: str) -> str:
    etype = str(event_type or "").lower()
    if "task" in etype or "plan" in etype or "orchestr" in etype:
        return "orchestration"
    if "learn" in etype or "knowledge" in etype or "research" in etype:
        return "learning"
    if "reflect" in etype or "cognition" in etype:
        return "cognition"
    if "metric" in etype or "telemetry" in etype:
        return "telemetry"
    if "system" in etype or "runtime" in etype:
        return "runtime"
    if "error" in etype or "fail" in etype:
        return "error"
    return "other"


class EventBus:
    """
    Thread-safe publish/subscribe event bus.

    Attributes:
        history_limit: Maximum number of events to keep in the replay log.
    """

    def __init__(self, history_limit: int = 1000) -> None:
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._wildcard_handlers: List[Handler] = []
        self._history: List[Event] = []
        self._history_limit = history_limit
        self._counter = 0
        self._unconsumed_counts: Dict[str, int] = defaultdict(int)
        self._dropped_events = 0
        self._dead_subscribers = 0
        self._publish_timestamps: deque[float] = deque(maxlen=1024)
        self._handler_stats: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    # ── subscribe / unsubscribe ───────────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType | str,
        handler: Handler,
    ) -> None:
        """Register *handler* to be called whenever *event_type* is published.

        Registering the same handler twice for the same event type is a no-op.
        """
        event_name = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._lock:
            handlers = self._handlers[event_name]
            if handler not in handlers:
                handlers.append(handler)
            self._ensure_handler_stats(handler, event_name)
        log.debug("[EventBus] subscribed %s → %s", handler.__name__, event_name)

    def subscribe_all(self, handler: Handler) -> None:
        """Register *handler* to receive every event regardless of type."""
        with self._lock:
            if handler not in self._wildcard_handlers:
                self._wildcard_handlers.append(handler)
            self._ensure_handler_stats(handler, "*")

    def unsubscribe(self, event_type: EventType | str, handler: Handler) -> bool:
        """Remove a previously registered handler. Returns True if found."""
        event_name = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._lock:
            handlers = self._handlers[event_name]
            if handler in handlers:
                handlers.remove(handler)
                return True
        return False

    # ── publish ───────────────────────────────────────────────────────────────

    def publish(self, event: Event) -> int:
        """
        Deliver *event* to all matching subscribers.

        Returns:
            Number of handlers called.
        """
        try:
            event_name = event.type_name
        except Exception as exc:
            log.warning("[EventBus] invalid event type — skipping dispatch: %s", exc)
            return 0

        with self._lock:
            self._counter += 1
            event.event_id = self._counter
            handlers = list(self._handlers.get(event_name, []))
            wildcards = list(self._wildcard_handlers)
            # Store in history
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history.pop(0)
            self._publish_timestamps.append(time.time())

        called = 0
        for h in handlers + wildcards:
            started = time.monotonic()
            try:
                h(event)
                called += 1
                self._record_handler_delivery(
                    handler=h,
                    event_type=event_name,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    success=True,
                )
            except AttributeError as exc:
                # Common enum/string mismatch: handler used event.type.value on a str.
                self._record_handler_delivery(
                    handler=h,
                    event_type=event_name,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    success=False,
                )
                log.warning(
                    "[EventBus] handler %s event-type mismatch (%s) — continuing",
                    getattr(h, "__name__", h),
                    exc,
                )
            except Exception as exc:
                self._record_handler_delivery(
                    handler=h,
                    event_type=event_name,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    success=False,
                )
                log.warning("[EventBus] handler %s raised: %s", getattr(h, "__name__", h), exc)
        if called == 0:
            with self._lock:
                self._unconsumed_counts[event_name] += 1

        log.debug("[EventBus] published %s → %d handler(s)", event_name, called)
        return called

    # ── helpers ────────────────────────────────────────────────────────────────

    def get_history(
        self,
        event_type: Optional[EventType | str] = None,
        limit: int = 50,
    ) -> List[Event]:
        """Return recent events, optionally filtered by type."""
        with self._lock:
            hist = list(self._history)
        if event_type is not None:
            event_name = event_type.value if isinstance(event_type, EventType) else str(event_type)
            hist = [e for e in hist if e.type_name == event_name]
        return hist[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def __repr__(self) -> str:
        return (
            f"EventBus(subscriptions={len(self._handlers)}, "
            f"history={len(self._history)})"
        )

    def _ensure_handler_stats(self, handler: Handler, event_type: str) -> None:
        key = f"{event_type}:{id(handler)}"
        self._handler_stats.setdefault(
            key,
            {
                "handler_name": getattr(handler, "__name__", repr(handler)),
                "event_type": event_type,
                "events_handled": 0,
                "errors": 0,
                "consecutive_errors": 0,
                "last_latency_ms": 0.0,
                "avg_latency_ms": 0.0,
                "last_seen_ts": None,
                "dead": False,
            },
        )

    def _record_handler_delivery(
        self,
        *,
        handler: Handler,
        event_type: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        with self._lock:
            for key in (f"{event_type}:{id(handler)}", f"*:{id(handler)}"):
                stats = self._handler_stats.get(key)
                if stats is None:
                    continue
                if success:
                    stats["events_handled"] += 1
                    stats["consecutive_errors"] = 0
                    stats["last_seen_ts"] = time.time()
                    previous = float(stats.get("avg_latency_ms", 0.0))
                    handled = max(1, int(stats["events_handled"]))
                    stats["avg_latency_ms"] = round(((previous * (handled - 1)) + latency_ms) / handled, 3)
                else:
                    stats["errors"] += 1
                    stats["consecutive_errors"] += 1
                    self._dropped_events += 1
                stats["last_latency_ms"] = round(latency_ms, 3)
                stats["dead"] = stats["consecutive_errors"] >= 3
            self._dead_subscribers = sum(
                1 for stats in self._handler_stats.values() if stats.get("dead")
            )

    def observability_report(self) -> Dict[str, Any]:
        """Return event propagation diagnostics for runtime observability."""
        now = time.time()
        with self._lock:
            counts = {
                event_type: len([e for e in self._history if e.type_name == event_type])
                for event_type in set([e.type_name for e in self._history] + list(self._handlers.keys()))
            }
            subscriber_counts = {
                event_type: len(handlers)
                for event_type, handlers in self._handlers.items()
            }
            history = list(self._history)
            handler_stats = list(self._handler_stats.values())
            dropped_events = self._dropped_events
            dead_subscribers = self._dead_subscribers
            unconsumed = dict(self._unconsumed_counts)
            throughput_recent = sum(1 for ts in self._publish_timestamps if now - ts <= 60.0)
        events: List[Dict[str, Any]] = []
        for event_type in sorted(set(counts) | set(subscriber_counts) | set(unconsumed)):
            type_handlers = [
                item for item in handler_stats
                if item.get("event_type") in {event_type, "*"}
            ]
            latencies = [float(item.get("avg_latency_ms", 0.0)) for item in type_handlers if item.get("avg_latency_ms")]
            events.append(
                {
                    "event_type": event_type,
                    "emitted": counts.get(event_type, 0),
                    "subscribers": subscriber_counts.get(event_type, 0),
                    "unconsumed": unconsumed.get(event_type, 0),
                    "avg_subscriber_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                    "dead_subscribers": sum(1 for item in type_handlers if item.get("dead")),
                    "last_seen_ts": next(
                        (event.timestamp for event in reversed(history) if event.type_name == event_type),
                        None,
                    ),
                }
            )
        return {
            "total_event_types": len(events),
            "total_emissions": len(history),
            "dropped_events": dropped_events,
            "unconsumed_events": int(sum(unconsumed.values())),
            "dead_subscribers": dead_subscribers,
            "throughput_last_minute": throughput_recent,
            "events": events,
            "subscribers": handler_stats,
        }


if __name__ == "__main__":
    print('Running event_bus.py')
