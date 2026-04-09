#!/usr/bin/env python3
"""
core/notification_queue.py — Thread-safe notification queue for background job feedback.

All background agents, loops, and daemon threads push their output here via
:func:`push`.  The main shell loop calls :func:`pop_all` **after** the user
presses Enter (i.e. after ``input()`` returns), so background activity is
never printed while the user is typing.

This module also provides :class:`NotificationQueueHandler`, a
``logging.Handler`` subclass that silently captures log records from any
background thread and routes them into the notification queue instead of
writing them directly to stderr/stdout.

Usage::

    # In background workers
    from core.notification_queue import notif_queue
    notif_queue.push("Research cycle complete: 5 new topics found")

    # In the main shell loop (after input() returns)
    from core.notification_queue import notif_queue
    msgs = notif_queue.pop_all()
    if msgs:
        print("\\n--- Background Notifications ---")
        for m in msgs:
            print(">", m)

    # Install the logging handler once at startup to silence background logs
    from core.notification_queue import install_queue_log_handler
    install_queue_log_handler(level=logging.INFO)

The module exposes a process-wide singleton ``notif_queue`` so all modules
share the same queue without circular imports.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Thread-safe notification queue
# ─────────────────────────────────────────────────────────────────────────────

class NotificationQueue:
    """Thread-safe, bounded FIFO queue for background notification messages.

    Parameters
    ----------
    maxlen:
        Maximum number of messages to retain.  Oldest messages are discarded
        when the queue is full (same semantics as ``collections.deque``).
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._q: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────

    def push(self, msg: str) -> None:
        """Append *msg* to the notification queue (thread-safe)."""
        with self._lock:
            self._q.append(str(msg))

    def pop_all(self) -> List[str]:
        """Return all pending notifications and clear the queue (thread-safe)."""
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def peek_all(self) -> List[str]:
        """Return all pending notifications WITHOUT clearing the queue."""
        with self._lock:
            return list(self._q)

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton shared across the whole process
# ─────────────────────────────────────────────────────────────────────────────

#: Global notification queue singleton.  Import and use this everywhere.
notif_queue: NotificationQueue = NotificationQueue(maxlen=200)


# ─────────────────────────────────────────────────────────────────────────────
# Custom logging handler — routes log records into the notification queue
# instead of printing them to stderr/stdout during user input.
# ─────────────────────────────────────────────────────────────────────────────

class NotificationQueueHandler(logging.Handler):
    """A ``logging.Handler`` that silently captures records into
    :data:`notif_queue` instead of writing to a stream.

    Only records emitted from **non-main** threads are captured; records from
    the main thread are left to propagate normally so that explicit
    ``io.out()`` / ``print()`` calls in the command loop still work.

    Parameters
    ----------
    queue:
        The :class:`NotificationQueue` instance to push messages into.
        Defaults to the module-level :data:`notif_queue` singleton.
    main_thread_id:
        The OS thread ID of the interactive main thread.  Records originating
        from this thread are not captured (allowed to propagate).  Defaults to
        the current thread's ident at the time the handler is created.
    """

    def __init__(
        self,
        queue: Optional[NotificationQueue] = None,
        main_thread_id: Optional[int] = None,
    ) -> None:
        super().__init__()
        self._queue = queue if queue is not None else notif_queue
        # Record the main thread so we can let main-thread logs through
        self._main_thread_id: int = (
            main_thread_id
            if main_thread_id is not None
            else threading.main_thread().ident or threading.current_thread().ident or 0
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Capture *record* into the notification queue."""
        try:
            # Only capture records from background (non-main) threads
            if threading.current_thread().ident == self._main_thread_id:
                # Let main-thread records propagate to the original handlers
                return
            msg = self.format(record)
            self._queue.push(f"[{record.levelname}][{record.name}] {record.getMessage()}")
        except Exception:
            # Never crash the calling thread due to a logging problem
            self.handleError(record)


# ─────────────────────────────────────────────────────────────────────────────
# Filter: pass only main-thread log records (used on stream handlers)
# ─────────────────────────────────────────────────────────────────────────────

class _MainThreadOnlyFilter(logging.Filter):
    """Logging filter that passes records from the main thread only.

    Applied to existing StreamHandler(s) so that background-thread log output
    no longer appears on stderr/stdout mid-typing.  The records are still
    captured by :class:`NotificationQueueHandler`.
    """

    def __init__(self, main_thread_id: Optional[int] = None) -> None:
        super().__init__()
        self._main_thread_id = (
            main_thread_id
            if main_thread_id is not None
            else (threading.main_thread().ident or threading.current_thread().ident or 0)
        )

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        return threading.current_thread().ident == self._main_thread_id


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: install the queue handler on the root logger
# ─────────────────────────────────────────────────────────────────────────────

_handler_installed: bool = False

# Third-party libraries that produce noisy console output during model
# loading, HTTP requests, or progress bars.  Their loggers are set to
# WARNING (or ERROR) so only genuine problems reach the console.
_NOISY_THIRD_PARTY_LOGGERS = (
    "transformers",
    "sentence_transformers",
    "safetensors",
    "huggingface_hub",
    "tqdm",
    "urllib3",
    "requests",
    "filelock",
    "torch",
    "tensorflow",
)

# Reference to the shared _MainThreadOnlyFilter so apply_filter_to_handler()
# can use it without re-creating one each time.
_shared_filter: Optional[_MainThreadOnlyFilter] = None


def apply_filter_to_handler(handler: logging.Handler) -> None:
    """Apply the :class:`_MainThreadOnlyFilter` to *handler* if applicable.

    Call this on any :class:`logging.StreamHandler` that is created **after**
    :func:`install_queue_log_handler` has run.  It is safe to call even before
    installation (it will be a no-op).

    This is the public API that other modules should use when they create
    their own StreamHandler instances.
    """
    if not _handler_installed or _shared_filter is None:
        return
    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, NotificationQueueHandler):
        # Avoid adding the same filter twice
        if _shared_filter not in handler.filters:
            handler.addFilter(_shared_filter)


def _suppress_noisy_loggers() -> None:
    """Set noisy third-party library loggers to WARNING or higher.

    These libraries produce verbose INFO/DEBUG output (connection banners,
    download progress, load reports, tokenizer info) that floods the console
    during normal Niblit operation.  Genuine warnings and errors still appear.
    """
    for name in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _apply_filter_to_all_stream_handlers(
    filt: logging.Filter,
) -> None:
    """Walk the entire logger hierarchy and apply *filt* to every
    :class:`logging.StreamHandler` that doesn't already have it.

    This catches StreamHandlers created on child loggers (e.g. by
    :class:`~modules.structured_logging.StructuredLogger`) — not just
    on the root logger.
    """
    visited: set = set()

    def _apply(logger: logging.Logger) -> None:
        lid = id(logger)
        if lid in visited:
            return
        visited.add(lid)
        for h in list(logger.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, NotificationQueueHandler):
                if filt not in h.filters:
                    h.addFilter(filt)

    # Root logger
    _apply(logging.getLogger())

    # All registered child loggers
    manager = logging.Logger.manager
    # manager.loggerDict values are either Logger or PlaceHolder instances
    for _, logger_ref in list(manager.loggerDict.items()):
        if isinstance(logger_ref, logging.Logger):
            _apply(logger_ref)


def install_queue_log_handler(
    level: int = logging.INFO,
    queue: Optional[NotificationQueue] = None,
) -> NotificationQueueHandler:
    """Install :class:`NotificationQueueHandler` on the root logger (idempotent).

    After calling this function, all ``logging.info`` / ``logging.warning``
    etc. calls from **background threads** will be silently captured in
    *queue* (default: :data:`notif_queue`) rather than writing to the
    terminal mid-typing.

    Main-thread log records are unaffected and continue to propagate to
    whatever handlers were already installed (e.g. the ``basicConfig``
    StreamHandler).

    Additionally:
    - Noisy third-party library loggers (transformers, safetensors, tqdm,
      etc.) are set to WARNING level so their verbose INFO output is
      suppressed.
    - The :class:`_MainThreadOnlyFilter` is applied to **all** existing
      StreamHandlers across the entire logger hierarchy — not just the root
      logger — so that child-logger StreamHandlers created by modules like
      :class:`~modules.structured_logging.StructuredLogger` are also covered.

    Parameters
    ----------
    level:
        Minimum log level to capture.  Records below this level are ignored.
    queue:
        Target queue.  Defaults to :data:`notif_queue`.

    Returns
    -------
    NotificationQueueHandler
        The handler that was added (or the one that was already installed).
    """
    global _handler_installed, _shared_filter
    root = logging.getLogger()

    # Idempotent: don't add the handler twice
    for h in root.handlers:
        if isinstance(h, NotificationQueueHandler):
            _handler_installed = True
            return h  # type: ignore[return-value]

    handler = NotificationQueueHandler(queue=queue)
    handler.setLevel(level)
    root.addHandler(handler)

    # Suppress background-thread log output on ALL existing stream handlers
    # across the whole logger hierarchy so they no longer write to the
    # terminal while the user is typing.  Records from background threads
    # will appear in the notification queue instead (surfaced after Enter).
    _shared_filter = _MainThreadOnlyFilter()
    _apply_filter_to_all_stream_handlers(_shared_filter)

    # Suppress noisy third-party library loggers
    _suppress_noisy_loggers()

    _handler_installed = True
    return handler


if __name__ == "__main__":
    print('Running notification_queue.py')
