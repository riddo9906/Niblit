#!/usr/bin/env python3
"""modules/event_bus.py — Lightweight Pub/Sub Event Bus for Niblit SDAL.

Extends the immutable audit trail from ``modules/event_sourcing.py`` with a
fast in-process pub/sub layer that decouples SDAL components without
requiring direct object references between modules.

All SDAL advisors emit typed events and the DecisionEngine subscribes to
aggregate them.  Any other module may also publish or subscribe.

Public API
----------
``NiblitEvent``
    Dataclass carrying ``type``, ``source``, ``payload``, and ``timestamp``.

``EventBus``
    Thread-safe pub/sub hub.

    * ``subscribe(event_type, handler)``  — register callable
    * ``unsubscribe(event_type, handler)`` — deregister callable
    * ``publish(event)``                  — dispatch to all handlers
    * ``last_event(event_type)``          — most recent event of a type
    * ``stats()``                         — publish counts by type

``get_event_bus() → EventBus``
    Process-level singleton.

Well-known event type constants
---------------------------------
``EVENT_MEMORY_RECALLED``     = ``"memory.recalled"``
``EVENT_REASONING_COMPLETE``  = ``"reasoning.complete"``
``EVENT_GOAL_UPDATED``        = ``"goal.updated"``
``EVENT_LEARNING_COMPLETE``   = ``"learning.cycle.complete"``
``EVENT_DECISION_MADE``       = ``"decision.made"``
``EVENT_RESPONSE_COMPLETE``   = ``"response.complete"``
``EVENT_EVOLUTION_OUTCOME``   = ``"evolution.outcome"``
``EVENT_CONTEXT_MISMATCH``    = ``"context.mismatch"``
``EVENT_INTENT_DRIFT``        = ``"intent.drift"``
``EVENT_SYSTEM_MIRRORED``     = ``"system.mirrored"``
``EVENT_SYSTEM_RESONANCE``    = ``"system.resonance"``

Design
------
* Thread-safe — all mutations are lock-protected.
* Never raises — handler errors are caught and logged at DEBUG level.
* Pure stdlib — no extra dependencies.
* Additive — does not modify ``modules/event_sourcing.py``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("NiblitEventBus")

# ── Well-known event type constants ───────────────────────────────────────────

EVENT_MEMORY_RECALLED    = "memory.recalled"
EVENT_REASONING_COMPLETE = "reasoning.complete"
EVENT_GOAL_UPDATED       = "goal.updated"
EVENT_LEARNING_COMPLETE  = "learning.cycle.complete"
EVENT_DECISION_MADE      = "decision.made"
EVENT_RESPONSE_COMPLETE  = "response.complete"
EVENT_META_ANALYSIS_COMPLETE = "meta.analysis.complete"
EVENT_POLICY_OPTIMIZED   = "policy.optimized"
EVENT_EVOLUTION_OUTCOME  = "evolution.outcome"   # Phase 6: emitted by feedback_learner
EVENT_CONTEXT_MISMATCH   = "context.mismatch"    # Phase 8: emitted by context_guard
EVENT_INTENT_DRIFT       = "intent.drift"         # Phase 8.5: emitted by intent_anchor_engine
EVENT_MODE_LOCKED        = "stability.mode_locked" # Phase 9: emitted by stability_controller
EVENT_AGENT_OBSERVATION  = "agent.observation"      # Phase 15: emitted by background worker agents
EVENT_SYSTEM_MIRRORED   = "system.mirrored"         # Phase 16: emitted by system_interface_layer after mirror_system()
EVENT_SYSTEM_RESONANCE  = "system.resonance"        # Phase 16: emitted by system_interface_layer
# after establish_resonance()
EVENT_GOVERNANCE_ADAPTED = "governance.adapted"     # Phase 18: emitted by governance_evolution_engine
# after parameter adaptation

# Phase 21: Cognitive Execution Layer
EVENT_INTENT_CLASSIFIED  = "intent.classified"      # Phase 21: emitted by intent_engine after classify()
EVENT_COGNITIVE_ROUTED   = "cognitive.routed"       # Phase 21: emitted by cognitive_router after route()
EVENT_EXECUTION_COMPLETE = "execution.complete"     # Phase 21: emitted by execution_graph after run()
EVENT_SELF_MODEL_UPDATED = "self_model.updated"     # Phase 21: emitted by self_model after update
EVENT_PLAN_SELECTED      = "plan.selected"          # Phase 21: emitted by deliberative_planner after plan()

# Phase Ω: Unified Intelligence Convergence
EVENT_STATE_UPDATED        = "state.updated"           # Phase Ω: emitted by unified_cognitive_state on every set()
EVENT_REFLECTION_COMPLETE  = "reflection.complete"     # Phase Ω: emitted by reflection_engine after reflect()
EVENT_WORLD_MODEL_UPDATED  = "world_model.updated"     # Phase Ω: emitted by predictive_world_model after forecast()
EVENT_RESOURCE_ADAPTED     = "resource.adapted"        # Phase Ω: emitted by autonomic_runtime_manager after assess()
EVENT_IDENTITY_UPDATED     = "identity.updated"        # Phase Ω: emitted by niblit_identity after snapshot update
EVENT_CONSTITUTION_CHECKED = "constitution.checked"    # Phase Ω: emitted by constitutional_layer after validate()

# Phase Ω.5: Cognitive Coherence & Recursive Stability
EVENT_COHERENCE_EVALUATED      = "coherence.evaluated"
EVENT_RECURSION_GOVERNED       = "recursion.governed"
EVENT_REALITY_VALIDATED        = "reality.validated"
EVENT_META_GOVERNANCE_EVALUATED = "meta_governance.evaluated"
EVENT_COGNITIVE_THREAT_DETECTED = "cognitive.threat.detected"
EVENT_TEMPORAL_CAUSAL_UPDATED   = "temporal.causal.updated"
EVENT_EMERGENCE_DETECTED        = "emergence.detected"
EVENT_GLOBAL_METRICS_UPDATED    = "global.metrics.updated"

# Phase Ω.5 required canonical events
EVENT_COHERENCE_ANALYZED        = "coherence.analyzed"
EVENT_RECURSION_STABILIZED      = "recursion.stabilized"
EVENT_RECURSIVE_WARNING         = "recursion.warning"
EVENT_IDENTITY_DRIFT            = "identity.drift"
EVENT_IDENTITY_VALIDATED        = "identity.validated"
EVENT_META_GOVERNANCE_UPDATED   = "meta_governance.updated"
EVENT_GOVERNANCE_CAPTURE_WARNING = "governance.capture.warning"
EVENT_SUBSYSTEM_QUARANTINED     = "subsystem.quarantined"
EVENT_COHERENCE_RESTORED        = "coherence.restored"
EVENT_CAUSAL_CHAIN_UPDATED      = "causal_chain.updated"
EVENT_TEMPORAL_CONTRADICTION    = "temporal.contradiction"
EVENT_GLOBAL_COGNITIVE_UPDATE   = "global.cognitive.update"
EVENT_AGENT_COALITION           = "agent.coalition"
EVENT_DEBATE_RECORDED           = "debate.recorded"
EVENT_COLLECTIVE_ALIGNMENT      = "collective.alignment"

# Phase Ω.6: Attention Economy & Cognitive Resource Allocation
EVENT_SALIENCE_SCORED           = "salience.scored"
EVENT_COGNITIVE_BUDGET_ENFORCED = "cognitive_budget.enforced"
EVENT_ATTENTION_ALLOCATED       = "attention.allocated"

# Phase Ω.7: Cross-Repo Cognitive Execution Protocol
EVENT_EXECUTION_ENVELOPE_PUBLISHED = "execution_envelope.published"   # schema-v2 envelope written to disk
EVENT_TRADE_REFLECTION_INGESTED    = "trade_reflection.ingested"       # reflection JSONL record ingested
EVENT_MARKET_EPISODE_INGESTED      = "market_episode.ingested"         # market episode JSONL record ingested
EVENT_RUNTIME_MODE_CHANGED         = "runtime_mode.changed"            # governance mode transition

# Knowledge-Gap Cognition Layer
EVENT_COGNITION_GAP_DETECTED       = "cognition.gap.detected"           # gap signal escalated
EVENT_COGNITION_SYNTHESIS_COMPLETE = "cognition.synthesis.complete"     # Llama3 synthesis produced


@dataclass
class NiblitEvent:
    """A single pub/sub event carrying typed payload.

    Attributes
    ----------
    type:      Dot-namespaced event type string (e.g. ``"goal.updated"``).
    source:    Name of the module that emitted this event.
    payload:   Arbitrary dict of event-specific data.
    timestamp: UNIX timestamp of emission (auto-set on creation).
    """

    type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# Handler callable type alias
_Handler = Callable[[NiblitEvent], None]


class EventBus:
    """Thread-safe in-process pub/sub event bus.

    Multiple handlers may be registered per event type.  When ``publish``
    is called, all handlers receive the event synchronously in the calling
    thread.  Errors in individual handlers are isolated and logged.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[_Handler]] = {}
        self._last: dict[str, NiblitEvent] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()
        log.info("[EventBus] Initialised")

    # ── Subscribe / Unsubscribe ───────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: _Handler) -> None:
        """Register *handler* to be called whenever *event_type* is published.

        Registering the same handler twice for the same event type is a no-op.
        """
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)
        log.debug(
            "[EventBus] subscribed: %s → %s",
            event_type,
            getattr(handler, "__qualname__", repr(handler)),
        )

    def unsubscribe(self, event_type: str, handler: _Handler) -> None:
        """Remove *handler* from *event_type* subscriptions (silent if absent)."""
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(self, event: NiblitEvent) -> None:
        """Dispatch *event* to all handlers subscribed to its type.

        Each handler is called sequentially.  A handler that raises an
        exception does not prevent subsequent handlers from running.
        """
        with self._lock:
            handlers = list(self._handlers.get(event.type, []))
            self._last[event.type] = event
            self._counts[event.type] = self._counts.get(event.type, 0) + 1

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                log.debug(
                    "[EventBus] handler error for %s in %s: %s",
                    event.type,
                    getattr(handler, "__qualname__", repr(handler)),
                    exc,
                )

    # ── Query ─────────────────────────────────────────────────────────────────

    def last_event(self, event_type: str) -> NiblitEvent | None:
        """Return the most recently published event of *event_type*, or None."""
        with self._lock:
            return self._last.get(event_type)

    def stats(self) -> dict[str, Any]:
        """Return a copy of publish-count statistics keyed by event type."""
        with self._lock:
            return dict(self._counts)


# ── Singleton ─────────────────────────────────────────────────────────────────

_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-level :class:`EventBus` singleton."""
    global _bus  # pylint: disable=global-statement
    with _bus_lock:
        if _bus is None:
            _bus = EventBus()
        return _bus


if __name__ == "__main__":
    bus = get_event_bus()

    received: list = []

    def _handle(e: NiblitEvent) -> None:
        received.append(e)
        print(f"Received: {e.type} from {e.source} — {e.payload}")

    bus.subscribe(EVENT_GOAL_UPDATED, _handle)
    bus.publish(NiblitEvent(type=EVENT_GOAL_UPDATED, source="test",
                            payload={"topic": "transformers"}))
    assert len(received) == 1
    print("EventBus OK")
    print("Stats:", bus.stats())
