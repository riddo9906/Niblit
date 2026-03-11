#!/usr/bin/env python3
"""
Event Sourcing - Immutable event log

Everything that happens is recorded as an event.
State is derived by replaying events.

Benefits:
- Full audit trail
- Time travel debugging
- State recovery
- Event-driven architecture
"""

import logging
import json
from typing import Any, List, Dict, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path

log = logging.getLogger("EventSourcing")


class EventType(str, Enum):
    """All possible event types."""
    COMMAND_RECEIVED = "command_received"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_FAILED = "command_failed"
    STATE_CHANGED = "state_changed"
    ERROR_OCCURRED = "error_occurred"
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    SLSA_STARTED = "slsa_started"
    SLSA_STOPPED = "slsa_stopped"
    LEARNING_TRIGGERED = "learning_triggered"


@dataclass
class Event:
    """Immutable event record."""
    timestamp: float
    event_type: EventType
    source: str
    data: Dict[str, Any]
    correlation_id: str
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            **asdict(self),
            "event_type": self.event_type.value,
        }
    
    def to_json(self) -> str:
        """Convert event to JSON."""
        data = self.to_dict()
        data["timestamp"] = datetime.fromtimestamp(self.timestamp).isoformat()
        return json.dumps(data)


class EventStore:
    """
    Immutable event store with replay capability.
    
    Stores events and can rebuild state by replaying.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.events: List[Event] = []
        self.storage_path = storage_path or Path("./events.jsonl")
        self.subscribers: Dict[EventType, List[Callable]] = {}
        self._load_from_disk()
        log.debug("EventStore initialized")
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to event type."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
        log.debug(f"Subscribed to {event_type}")
    
    def append_event(self, event: Event) -> None:
        """
        Append immutable event to store.
        
        Args:
            event: Event to append
        """
        self.events.append(event)
        log.debug(f"Event appended: {event.event_type}")
        
        # Persist to disk
        self._persist_event(event)
        
        # Notify subscribers
        if event.event_type in self.subscribers:
            for callback in self.subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception as e:
                    log.error(f"Callback error: {e}")
    
    def _persist_event(self, event: Event) -> None:
        """Persist event to disk (append-only)."""
        try:
            with open(self.storage_path, "a") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            log.error(f"Failed to persist event: {e}")
    
    def _load_from_disk(self) -> None:
        """Load events from disk on startup."""
        if not self.storage_path.exists():
            return
        
        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        # Reconstruct event (simplified)
                        log.debug(f"Loaded event: {data.get('event_type')}")
        except Exception as e:
            log.error(f"Failed to load events: {e}")
    
    def get_events(
        self,
        event_type: Optional[EventType] = None,
        correlation_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[Event]:
        """
        Query events with filters.
        
        Perfect for debugging - grep-like functionality for events.
        """
        results = self.events
        
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        
        if correlation_id:
            results = [e for e in results if e.correlation_id == correlation_id]
        
        if start_time:
            results = [e for e in results if e.timestamp >= start_time]
        
        if end_time:
            results = [e for e in results if e.timestamp <= end_time]
        
        return results
    
    def get_state_at(self, timestamp: float) -> Dict[str, Any]:
        """
        Rebuild state at specific point in time.
        
        By replaying all events up to timestamp.
        """
        state: Dict[str, Any] = {
            "commands_executed": 0,
            "errors": 0,
            "slsa_running": False,
        }
        
        for event in self.get_events(end_time=timestamp):
            if event.event_type == EventType.COMMAND_EXECUTED:
                state["commands_executed"] += 1
            elif event.event_type == EventType.ERROR_OCCURRED:
                state["errors"] += 1
            elif event.event_type == EventType.SLSA_STARTED:
                state["slsa_running"] = True
            elif event.event_type == EventType.SLSA_STOPPED:
                state["slsa_running"] = False
        
        return state
    
    def get_stats(self) -> Dict[str, Any]:
        """Get event store statistics."""
        by_type = {}
        for event in self.events:
            by_type[event.event_type.value] = by_type.get(event.event_type.value, 0) + 1
        
        return {
            "total_events": len(self.events),
            "by_type": by_type,
            "storage_path": str(self.storage_path),
        }


# Example usage
if __name__ == "__main__":
    import uuid
    
    store = EventStore()
    
    # Emit some events
    correlation_id = str(uuid.uuid4())
    
    store.append_event(Event(
        timestamp=datetime.now().timestamp(),
        event_type=EventType.COMMAND_RECEIVED,
        source="user",
        data={"command": "help"},
        correlation_id=correlation_id,
    ))
    
    store.append_event(Event(
        timestamp=datetime.now().timestamp(),
        event_type=EventType.COMMAND_EXECUTED,
        source="core",
        data={"command": "help", "result": "Help text..."},
        correlation_id=correlation_id,
    ))
    
    # Query events
    events = store.get_events(correlation_id=correlation_id)
    print(f"Events: {len(events)}")
    
    # Get state at time
    state = store.get_state_at(datetime.now().timestamp())
    print(f"State: {state}")
    
    # Stats
    print(f"Stats: {store.get_stats()}")
