"""MessageBus — civilisation-internal pub/sub message passing.

Usage example::

    bus = MessageBus()
    bus.subscribe("task_done", lambda m: print(m))
    bus.publish("task_done", "agent-1", {"result": "ok"})
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("CollabMessageBus")


class MessageBus:
    """Topic-based message bus for inter-agent communication."""

    def __init__(self) -> None:
        self._messages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

    # ── public API ──

    def publish(
        self, msg_type: str, sender_id: str, payload: Dict[str, Any]
    ) -> None:
        """Publish *payload* from *sender_id* under *msg_type*."""
        envelope = {"msg_type": msg_type, "sender_id": sender_id, "payload": payload, "ts": time.time()}
        self._messages[msg_type].append(envelope)
        for handler in list(self._subscribers[msg_type]):
            try:
                handler(envelope)
            except Exception as exc:
                log.warning("CollabMessageBus: subscriber error — %s", exc)

    def subscribe(self, msg_type: str, handler: Callable) -> None:
        """Register *handler* for messages of *msg_type*."""
        self._subscribers[msg_type].append(handler)

    def get_messages(
        self, msg_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return messages filtered by *msg_type*, or all if None."""
        if msg_type is None:
            return [m for msgs in self._messages.values() for m in msgs]
        return list(self._messages.get(msg_type, []))

    def broadcast(self, payload: Dict[str, Any]) -> None:
        """Send *payload* to all subscribers regardless of msg_type."""
        for msg_type in list(self._subscribers.keys()):
            self.publish(msg_type, "broadcast", payload)
