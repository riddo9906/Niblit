#!/usr/bin/env python3
"""
nibblebots/learning_loop_bridge.py — Phase 6 SDAL / MetaEngine Bridge

Connects the code evolution loop to the existing Niblit runtime intelligence
system (SDAL).  After each ``feedback_learner.record_outcome()`` call the
evolution outcome is already published to the EventBus as
``EVENT_EVOLUTION_OUTCOME``.  This module provides the *subscriber* side:

  * Subscribes to ``EVENT_EVOLUTION_OUTCOME`` on the process-level EventBus.
  * Translates evolution outcomes into MetaEngine ``record_meta_insight()``
    calls so the runtime intelligence learns from code evolution history.
  * Optionally logs a human-readable summary for debugging.

This closes the loop between the code evolution agent and the runtime
intelligence system — they share knowledge.

Usage
-----
Call ``wire()`` once at application startup (e.g. in ``niblit_core.py``
after the MetaEngine is initialised).  The bridge is entirely passive after
that — it reacts to events as the evolution agent runs.

For standalone / test use::

    from nibblebots.learning_loop_bridge import wire, unwire
    wire()   # subscribe
    ...
    unwire() # unsubscribe

Public API
----------
``wire(meta_engine=None)``    — subscribe to EventBus
``unwire()``                   — unsubscribe from EventBus
``_handle_evolution_outcome(event)``  — handler (exposed for testing)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

log = logging.getLogger("NiblitLearningLoopBridge")

# Lazily resolved references so this module imports cleanly even when the
# SDAL modules are not installed.
_meta_engine: Optional[Any] = None
_subscribed: bool = False
_handler_ref: Optional[Callable] = None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _handle_evolution_outcome(event: Any) -> None:
    """Translate an evolution outcome event into a MetaEngine meta-insight.

    Expected event.payload keys (all optional):
        fix_types, tests_passed, ci_delta, impact_net_score, commit_sha
    """
    payload = event.payload if hasattr(event, "payload") else {}

    fix_types = payload.get("fix_types", [])
    tests_passed = payload.get("tests_passed")
    ci_delta = payload.get("ci_delta", 0)
    net_score = payload.get("impact_net_score")
    commit_sha = payload.get("commit_sha", "")[:8]

    # Build a human-readable insight string
    status = "✅ pass" if tests_passed else ("⚠ fail" if tests_passed is False else "? unknown")
    insight_text = (
        f"Evolution commit {commit_sha}: {', '.join(fix_types) or 'unknown'} — "
        f"CI {status}, ci_delta={ci_delta:+d}"
        + (f", net_score={net_score:.3f}" if net_score is not None else "")
    )

    log.debug("[LearningLoopBridge] %s", insight_text)

    # Forward to MetaEngine if available
    if _meta_engine is not None:
        try:
            _meta_engine.record_meta_insight(  # type: ignore[attr-defined]
                patterns=[insight_text],
                slope=float(net_score) if net_score is not None else 0.0,
                quality_avg=float(tests_passed) if tests_passed is not None else 0.5,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("[LearningLoopBridge] record_meta_insight failed: %s", exc)
    else:
        log.debug("[LearningLoopBridge] MetaEngine not wired — insight not forwarded.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wire(meta_engine: Optional[Any] = None) -> bool:
    """Subscribe to ``EVENT_EVOLUTION_OUTCOME`` on the process EventBus.

    Parameters
    ----------
    meta_engine : optional MetaEngine instance.  When None, the bridge
                  attempts to resolve the singleton at handler call time.

    Returns True if subscription succeeded, False otherwise.
    """
    global _meta_engine, _subscribed, _handler_ref  # pylint: disable=global-statement

    if _subscribed:
        return True   # already wired

    _meta_engine = meta_engine

    # Attempt to auto-resolve MetaEngine singleton if not provided
    if _meta_engine is None:
        try:
            from modules.meta_engine import get_meta_engine  # type: ignore[import] # noqa: PLC0415
            _meta_engine = get_meta_engine()
        except Exception:  # noqa: BLE001
            pass

    try:
        from modules.event_bus import get_event_bus, EVENT_EVOLUTION_OUTCOME  # noqa: PLC0415
        bus = get_event_bus()
        bus.subscribe(EVENT_EVOLUTION_OUTCOME, _handle_evolution_outcome)
        _handler_ref = _handle_evolution_outcome
        _subscribed = True
        log.info("[LearningLoopBridge] Subscribed to %s", EVENT_EVOLUTION_OUTCOME)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("[LearningLoopBridge] wire() failed (EventBus unavailable): %s", exc)
        return False


def unwire() -> bool:
    """Unsubscribe from the EventBus.  Returns True if unsubscription succeeded."""
    global _subscribed, _handler_ref  # pylint: disable=global-statement

    if not _subscribed or _handler_ref is None:
        return True

    try:
        from modules.event_bus import get_event_bus, EVENT_EVOLUTION_OUTCOME  # noqa: PLC0415
        bus = get_event_bus()
        bus.unsubscribe(EVENT_EVOLUTION_OUTCOME, _handler_ref)
        _subscribed = False
        _handler_ref = None
        log.info("[LearningLoopBridge] Unsubscribed from %s", EVENT_EVOLUTION_OUTCOME)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("[LearningLoopBridge] unwire() failed: %s", exc)
        return False


if __name__ == "__main__":
    print('Running learning_loop_bridge.py')
