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

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
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

    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    event_id: int = field(default=0)

    def __repr__(self) -> str:
        return (
            f"Event(type={self.type.value!r}, source={self.source!r}, "
            f"payload_keys={list(self.payload.keys())})"
        )


Handler = Callable[[Event], None]


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
        self._lock = Lock()

    # ── subscribe / unsubscribe ───────────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType,
        handler: Handler,
    ) -> None:
        """Register *handler* to be called whenever *event_type* is published."""
        with self._lock:
            self._handlers[event_type.value].append(handler)
        log.debug("[EventBus] subscribed %s → %s", handler.__name__, event_type.value)

    def subscribe_all(self, handler: Handler) -> None:
        """Register *handler* to receive every event regardless of type."""
        with self._lock:
            self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> bool:
        """Remove a previously registered handler. Returns True if found."""
        with self._lock:
            handlers = self._handlers[event_type.value]
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
        with self._lock:
            self._counter += 1
            event.event_id = self._counter
            handlers = list(self._handlers.get(event.type.value, []))
            wildcards = list(self._wildcard_handlers)
            # Store in history
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history.pop(0)

        called = 0
        for h in handlers + wildcards:
            try:
                h(event)
                called += 1
            except Exception as exc:
                log.warning("[EventBus] handler %s raised: %s", getattr(h, "__name__", h), exc)

        log.debug("[EventBus] published %s → %d handler(s)", event.type.value, called)
        return called

    # ── helpers ────────────────────────────────────────────────────────────────

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 50,
    ) -> List[Event]:
        """Return recent events, optionally filtered by type."""
        with self._lock:
            hist = list(self._history)
        if event_type is not None:
            hist = [e for e in hist if e.type == event_type]
        return hist[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def __repr__(self) -> str:
        return (
            f"EventBus(subscriptions={len(self._handlers)}, "
            f"history={len(self._history)})"
        )
