from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.event_bus import Event, EventBus, EventType


class SimulationHarness:
    """Minimal event generator and replay harness for lightweight simulation."""

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self._event_bus = event_bus or EventBus(history_limit=100)
        self._events: List[Event] = []

    def generate_event(self, event_type: str | EventType, payload: Optional[Dict[str, Any]] = None, source: str = "simulation") -> Event:
        event = Event(
            type=event_type,
            payload=payload or {},
            source=source,
            source_module="simulation",
            event_category="simulation",
            event_priority="normal",
        )
        self._events.append(event)
        self._event_bus.publish(event)
        return event

    def replay_events(self) -> List[Event]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
