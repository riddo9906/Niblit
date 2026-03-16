"""MessageBus — in-memory publish/subscribe system for distributed Niblit nodes.

Provides topic-based message routing between components without external
message broker dependencies.

Usage example::

    bus = MessageBus()
    bus.subscribe("tasks", lambda m: print(m))
    bus.publish("tasks", {"action": "run", "payload": "hello"})
    messages = bus.get_messages("tasks")
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List

log = logging.getLogger("MessageBus")


class MessageBus:
    """In-memory pub/sub message bus.

    Args:
        max_history: Maximum messages retained per topic.
    """

    def __init__(self, max_history: int = 1000) -> None:
        self._max_history = max_history
        self._messages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

    # ── public API ──

    def publish(self, topic: str, message: Dict[str, Any]) -> None:
        """Publish *message* to *topic* and notify subscribers."""
        envelope = {"topic": topic, "message": message, "ts": time.time()}
        store = self._messages[topic]
        store.append(envelope)
        if len(store) > self._max_history:
            store.pop(0)
        log.debug("MessageBus: published to topic %s", topic)
        for handler in list(self._subscribers[topic]):
            try:
                handler(envelope)
            except Exception as exc:
                log.warning("MessageBus: subscriber error on %s — %s", topic, exc)

    def subscribe(self, topic: str, handler: Callable) -> None:
        """Register *handler* callable to receive messages on *topic*."""
        self._subscribers[topic].append(handler)
        log.debug("MessageBus: new subscriber on topic %s", topic)

    def get_messages(self, topic: str) -> List[Dict[str, Any]]:
        """Return all stored messages for *topic*."""
        return list(self._messages.get(topic, []))

    def clear(self) -> None:
        """Clear all stored messages and subscribers."""
        self._messages.clear()
        self._subscribers.clear()
        log.info("MessageBus: cleared all messages and subscribers")
