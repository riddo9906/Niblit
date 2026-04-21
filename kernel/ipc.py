"""
kernel/ipc.py — Inter-process communication bus.

Provides a lightweight publish/subscribe + named-queue message bus so
kernel subsystems and NiblitCore modules can exchange messages without
tight coupling.

Features
--------
- Named channels (queues) — any producer/consumer can push/pop messages
- Pub/sub topics — broadcast to all subscribers of a topic
- Thread-safe — uses :class:`queue.Queue` internally
- No external dependencies
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("NiblitOSKernel.IPC")

__all__ = ["IPCMessage", "IPCBus"]


@dataclass
class IPCMessage:
    """A single message envelope."""

    topic: str
    payload: Any
    sender: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: hex(id(object()))[2:])


class IPCBus:
    """
    Central message bus for inter-module communication.

    Named channels (queues)
    ~~~~~~~~~~~~~~~~~~~~~~~
    ``push(channel, payload, sender)``   — enqueue a message
    ``pop(channel, timeout)``            — dequeue (blocks up to *timeout*s)
    ``drain(channel)``                   — return all pending messages

    Pub/sub topics
    ~~~~~~~~~~~~~~
    ``subscribe(topic, callback)``       — register a callback
    ``publish(topic, payload, sender)``  — call all topic subscribers
    ``unsubscribe(topic, callback)``     — remove a callback
    """

    def __init__(self) -> None:
        self._channels: dict[str, queue.Queue] = {}
        self._subscribers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    # ──────────────────────────────────────────── named-channel (queue) API ──

    def _get_channel(self, name: str) -> queue.Queue:
        with self._lock:
            if name not in self._channels:
                self._channels[name] = queue.Queue()
            return self._channels[name]

    def push(self, channel: str, payload: Any, sender: str = "unknown") -> None:
        """Enqueue a message on *channel*."""
        msg = IPCMessage(topic=channel, payload=payload, sender=sender)
        self._get_channel(channel).put(msg)
        log.debug("[IPC] push → %s from %s", channel, sender)

    def pop(
        self, channel: str, timeout: float | None = None
    ) -> IPCMessage | None:
        """
        Dequeue the next message from *channel*.

        Returns None if the queue is empty within *timeout* seconds.
        Pass ``timeout=None`` for a non-blocking check (default).
        """
        q = self._get_channel(channel)
        try:
            block = timeout is not None and timeout > 0
            return q.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def drain(self, channel: str) -> list[IPCMessage]:
        """Return all currently queued messages from *channel* (non-blocking)."""
        q = self._get_channel(channel)
        messages: list[IPCMessage] = []
        while True:
            try:
                messages.append(q.get_nowait())
            except queue.Empty:
                break
        return messages

    def channel_size(self, channel: str) -> int:
        """Return the number of pending messages in *channel*."""
        return self._get_channel(channel).qsize()

    # ───────────────────────────────────────────────────── pub/sub topic API ──

    def subscribe(self, topic: str, callback: Callable[[IPCMessage], None]) -> None:
        """Register *callback* to be called when *topic* is published."""
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)
        log.debug("[IPC] subscribe %s → %s", topic, getattr(callback, "__name__", repr(callback)))

    def unsubscribe(self, topic: str, callback: Callable) -> bool:
        """Remove *callback* from *topic* subscribers.  Returns True if found."""
        with self._lock:
            subs = self._subscribers.get(topic, [])
            try:
                subs.remove(callback)
                return True
            except ValueError:
                return False

    def publish(self, topic: str, payload: Any, sender: str = "unknown") -> int:
        """
        Deliver *payload* to all subscribers of *topic*.

        Also enqueues the message on the same-named channel so consumers
        using :meth:`pop` / :meth:`drain` can also receive it.
        Returns the number of subscriber callbacks invoked.
        """
        msg = IPCMessage(topic=topic, payload=payload, sender=sender)
        self._get_channel(topic).put(msg)

        with self._lock:
            callbacks = list(self._subscribers.get(topic, []))

        count = 0
        for cb in callbacks:
            try:
                cb(msg)
                count += 1
            except Exception as exc:
                log.warning("[IPC] subscriber error on topic %r: %s", topic, exc)
        log.debug("[IPC] publish %s → %d subscriber(s)", topic, count)
        return count

    # ────────────────────────────────────────────────────────────── status ────

    def status(self) -> dict:
        with self._lock:
            channels = {
                name: q.qsize() for name, q in self._channels.items()
            }
            topics = {
                topic: len(cbs) for topic, cbs in self._subscribers.items()
            }
        return {
            "channels": channels,
            "subscriptions": topics,
        }

    def shutdown(self) -> None:
        """Drain all channels and clear subscribers."""
        with self._lock:
            self._channels.clear()
            self._subscribers.clear()
        log.debug("[IPC] Bus shut down.")


if __name__ == "__main__":
    print('Running ipc.py')
