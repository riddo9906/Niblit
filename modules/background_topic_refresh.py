#!/usr/bin/env python3
"""
modules/background_topic_refresh.py — Periodic autonomous topic refresh via threading.

Provides :func:`background_topic_refresh_loop`, a daemon-thread target that
periodically calls :class:`~modules.dynamic_topic_manager.DynamicTopicManager`
to generate fresh topics and then injects them into the Autonomous Learning
Engine (ALE) or any agent that exposes ``update_research_topics()``.

Typical integration in the orchestrator / NiblitCore::

    import threading
    from modules.background_topic_refresh import background_topic_refresh_loop

    t = threading.Thread(
        target=background_topic_refresh_loop,
        kwargs=dict(
            dtm=self.dynamic_topic_manager,
            ale=self.autonomous_engine,
            interval_secs=600,          # refresh every 10 minutes
            stop_event=self._stop_event,
        ),
        daemon=True,
        name="BackgroundTopicRefresh",
    )
    t.start()

The thread respects a :class:`threading.Event` for clean shutdown:
pass ``stop_event`` and set it to stop the loop gracefully.
"""

import logging
import threading
import time
from typing import Any, List, Optional

log = logging.getLogger("BackgroundTopicRefresh")

# Default refresh interval (seconds).  Override via `interval_secs` kwarg.
DEFAULT_REFRESH_INTERVAL: int = 600  # 10 minutes


def _inject_topics(ale: Any, new_topics: List[str]) -> bool:
    """Inject *new_topics* into *ale* if it supports the required method.

    Tries:
    1. ``ale.update_research_topics(new_topics)`` — preferred public API.
    2. Directly extend ``ale.research_topics`` list as a fallback.

    Returns ``True`` if topics were injected, ``False`` otherwise.
    """
    if ale is None:
        return False

    if hasattr(ale, "update_research_topics"):
        try:
            ale.update_research_topics(new_topics)
            log.info("[BackgroundTopicRefresh] Injected %d topics via update_research_topics()",
                     len(new_topics))
            return True
        except Exception as exc:
            log.warning("[BackgroundTopicRefresh] update_research_topics() failed: %s", exc)

    # Fallback: extend the list directly
    if hasattr(ale, "research_topics") and isinstance(ale.research_topics, list):
        try:
            before = len(ale.research_topics)
            # Append only truly new topics
            existing = set(ale.research_topics)
            for t in new_topics:
                if t not in existing:
                    ale.research_topics.append(t)
                    existing.add(t)
            added = len(ale.research_topics) - before
            log.info("[BackgroundTopicRefresh] Extended research_topics list (+%d topics)", added)
            return True
        except Exception as exc:
            log.warning("[BackgroundTopicRefresh] Direct research_topics extension failed: %s",
                        exc)

    log.debug("[BackgroundTopicRefresh] ALE has no compatible topic-injection API")
    return False


def background_topic_refresh_loop(
    dtm: Any,
    ale: Any = None,
    interval_secs: int = DEFAULT_REFRESH_INTERVAL,
    batch_size: int = 10,
    stop_event: Optional[threading.Event] = None,
    initial_delay_secs: int = 60,
) -> None:
    """Daemon-thread target: periodically refresh ALE's research topics.

    Parameters
    ----------
    dtm:
        A :class:`~modules.dynamic_topic_manager.DynamicTopicManager` (or any
        object with a ``propose_new_topics(batch_size)`` method).
    ale:
        The Autonomous Learning Engine instance (or any agent that exposes
        ``update_research_topics()``).  May be ``None`` if topic injection is
        handled elsewhere.
    interval_secs:
        Seconds between refresh cycles.  Default: 600 (10 minutes).
    batch_size:
        Number of fresh topics to propose per refresh cycle.
    stop_event:
        A :class:`threading.Event` that, when set, causes the loop to exit
        cleanly.  If ``None`` the loop runs until the process exits (daemon
        thread behaviour).
    initial_delay_secs:
        Seconds to wait before the first refresh (gives the system time to
        fully initialise before the first topic injection).
    """
    if stop_event is None:
        stop_event = threading.Event()

    log.info(
        "[BackgroundTopicRefresh] Thread started — interval=%ds, batch=%d, initial_delay=%ds",
        interval_secs, batch_size, initial_delay_secs,
    )

    # Initial delay: let the rest of the system come up before the first run.
    if initial_delay_secs > 0:
        if stop_event.wait(timeout=initial_delay_secs):
            log.info("[BackgroundTopicRefresh] Stop requested during initial delay — exiting")
            return

    while not stop_event.is_set():
        try:
            if not hasattr(dtm, "propose_new_topics"):
                log.warning("[BackgroundTopicRefresh] dtm has no propose_new_topics() — sleeping")
            else:
                new_topics = dtm.propose_new_topics(batch_size=batch_size)
                if new_topics:
                    _inject_topics(ale, new_topics)
                    log.info("[BackgroundTopicRefresh] Refresh cycle complete (%d new topics)",
                             len(new_topics))
                else:
                    log.debug("[BackgroundTopicRefresh] No new topics proposed this cycle")
        except Exception as exc:
            log.warning("[BackgroundTopicRefresh] Refresh cycle error: %s", exc)

        # Sleep in small chunks so we respond quickly to stop_event
        remaining = interval_secs
        chunk = min(30, remaining)
        while remaining > 0 and not stop_event.is_set():
            stop_event.wait(timeout=chunk)
            remaining -= chunk
            chunk = min(30, remaining)

    log.info("[BackgroundTopicRefresh] Thread exiting cleanly")


def start_background_refresh(
    dtm: Any,
    ale: Any = None,
    interval_secs: int = DEFAULT_REFRESH_INTERVAL,
    batch_size: int = 10,
    stop_event: Optional[threading.Event] = None,
    initial_delay_secs: int = 60,
) -> threading.Thread:
    """Convenience wrapper: create, start, and return the refresh thread.

    Parameters are passed directly to :func:`background_topic_refresh_loop`.

    Returns
    -------
    threading.Thread
        The started daemon thread.
    """
    t = threading.Thread(
        target=background_topic_refresh_loop,
        kwargs=dict(
            dtm=dtm,
            ale=ale,
            interval_secs=interval_secs,
            batch_size=batch_size,
            stop_event=stop_event,
            initial_delay_secs=initial_delay_secs,
        ),
        daemon=True,
        name="BackgroundTopicRefresh",
    )
    t.start()
    log.info("[BackgroundTopicRefresh] Background thread started (tid=%s)", t.ident)
    return t
