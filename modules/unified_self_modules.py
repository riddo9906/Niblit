#!/usr/bin/env python3
"""modules/unified_self_modules.py — Unified Self-Improvement Module Bundle
=========================================================================
Closes the autonomous feedback loop by wiring together all self-improvement
subsystems into a single, observable controller.

Architecture role (MSG Layer + LRN Layer bridge)
-------------------------------------------------
The ``UnifiedFeedbackController`` mediates between:

* **MetaEvaluator** (MSG)       — continuously-updated subsystem quality scores
* **SelfModel** (MSG)           — Niblit's self-image (capabilities / limitations)
* **EvolutionPlanner** (MSG)    — plan → simulate → commit evolution candidates
* **ALE** (LRN)                 — inject priority research topics for weak subsystems
* **AdaptiveLearning** (LRN)    — translate user interest into ALE topic biasing
* **NiblitRuntime** (KRN)       — level advancement driven by real-metric quality
* **EventBus** (KRN)            — publish/subscribe for decoupled cross-layer signalling

Unified Feedback Loop (closed)
--------------------------------
::

    ALE completes a learning cycle
         │  EventBus: LEARNING_CYCLE_COMPLETED
         ▼
    UnifiedFeedbackController.tick()
         │  1. MetaEvaluator.scores()  → identify weak subsystems
         │  2. SelfModel.update_confidence() per subsystem
         │  3. ALE.inject_priority_topic() for each weak subsystem
         │  4. EvolutionPlanner.propose() for critically weak ones
         │  5. EvolutionPlanner.pick_best() + commit the best candidate
         │  6. AdaptiveLearning.get_recommended_topics() → ALE
         │  7. NiblitRuntime.improve(delta) driven by MetaEvaluator avg
         ▼
    EventBus: EVOLUTION_STEP_COMPLETED  (when a candidate is committed)
         └─► loop continues ────────────────────────────────────────────

Singleton access via ``get_unified_self_modules()``.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("UnifiedSelfModules")

# ── Subsystem → research-topic mapping ────────────────────────────────────────
# Maps MetaEvaluator subsystem names to the most relevant research topics
# Niblit should study when that subsystem's quality score is low.

_SUBSYSTEM_TOPICS: Dict[str, List[str]] = {
    "ALE": [
        "autonomous learning systems",
        "curriculum learning algorithms",
        "self-improving AI architectures",
        "meta-learning techniques",
    ],
    "Kernel": [
        "operating system kernel design",
        "event-driven architecture patterns",
        "real-time task scheduling",
        "cognitive computing frameworks",
    ],
    "Trading": [
        "algorithmic trading strategies",
        "quantitative finance fundamentals",
        "technical analysis indicators",
        "market prediction models",
    ],
    "Security": [
        "cybersecurity threat detection",
        "defensive programming patterns",
        "zero-trust security architecture",
        "adversarial robustness in AI",
    ],
    "Memory": [
        "vector database design",
        "knowledge graph construction",
        "semantic memory retrieval",
        "memory-augmented neural networks",
    ],
    "Language": [
        "natural language understanding",
        "semantic parsing techniques",
        "intent recognition systems",
        "large language model reasoning",
    ],
    "Research": [
        "information retrieval methods",
        "research methodology automation",
        "structured web data extraction",
        "knowledge distillation techniques",
    ],
    "Reasoning": [
        "knowledge representation and reasoning",
        "inference under uncertainty",
        "causal reasoning in AI",
        "logic-based AI systems",
    ],
    "Evolution": [
        "evolutionary computation",
        "genetic programming and self-modification",
        "adaptive system design",
        "neural architecture search",
    ],
    "Civilization": [
        "multi-agent coordination",
        "distributed AI systems",
        "collective intelligence frameworks",
        "cooperative AI design",
    ],
}

# Score below which a subsystem is considered "weak" → priority research injected.
_WEAK_THRESHOLD: float = 0.5
# Score below which an immediate EvolutionCandidate is proposed.
_CRITICAL_THRESHOLD: float = 0.35
# Minimum seconds between feedback ticks to avoid overloading ALE.
_MIN_TICK_INTERVAL: float = 60.0
# Background loop sleep interval (seconds).
_LOOP_SLEEP: float = 300.0


# ── UnifiedFeedbackController ─────────────────────────────────────────────────


class UnifiedFeedbackController:
    """
    Closes the autonomous improvement feedback loop.

    On every :meth:`tick` (or whenever a ``LEARNING_CYCLE_COMPLETED`` event
    fires on the EventBus):

    1. Reads MetaEvaluator scores.
    2. Syncs SelfModel confidence maps with those scores.
    3. Injects priority research topics into ALE for weak subsystems.
    4. Proposes EvolutionCandidates for critically weak subsystems.
    5. Commits the best simulated candidate to record an outcome.
    6. Feeds AdaptiveLearning recommendations into ALE.
    7. Advances NiblitRuntime level based on the MetaEvaluator average.

    All subsystem references are optional; the controller degrades
    gracefully when individual modules are unavailable.
    """

    def __init__(
        self,
        *,
        ale: Optional[Any] = None,
        meta_evaluator: Optional[Any] = None,
        self_model: Optional[Any] = None,
        evolution_planner: Optional[Any] = None,
        niblit_runtime: Optional[Any] = None,
        adaptive_learning: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._ale = ale
        self._meta_evaluator = meta_evaluator
        self._self_model = self_model
        self._evolution_planner = evolution_planner
        self._niblit_runtime = niblit_runtime
        self._adaptive_learning = adaptive_learning
        self._event_bus = event_bus

        self._last_tick: float = 0.0
        self._tick_count: int = 0
        self._last_scores: Dict[str, float] = {}

        # Subscribe to EventBus events when available.
        self._subscribe_events()

    # ── EventBus subscription ─────────────────────────────────────────────────

    def _subscribe_events(self) -> None:
        """Register handlers on the EventBus for cross-layer signalling."""
        if self._event_bus is None:
            return
        try:
            from core.event_bus import EventType
            self._event_bus.subscribe(
                EventType.LEARNING_CYCLE_COMPLETED,
                self._on_learning_cycle_completed,
            )
            self._event_bus.subscribe(
                EventType.KNOWLEDGE_GAP_DETECTED,
                self._on_knowledge_gap_detected,
            )
            log.debug(
                "[UFC] Subscribed to EventBus: LEARNING_CYCLE_COMPLETED, KNOWLEDGE_GAP_DETECTED"
            )
        except Exception as exc:
            log.debug("[UFC] EventBus subscription failed: %s", exc)

    def _on_learning_cycle_completed(self, event: Any) -> None:
        """React to ALE completing a learning cycle."""
        topic = (event.payload or {}).get("topic", "")
        log.debug("[UFC] Learning cycle completed: topic=%r", topic)
        # Rate-limit: avoid re-entrant rapid-fire ticks.
        if time.time() - self._last_tick >= _MIN_TICK_INTERVAL:
            self.tick()

    def _on_knowledge_gap_detected(self, event: Any) -> None:
        """React to a knowledge-gap signal by immediately prioritising the topic."""
        topic = (event.payload or {}).get("topic", "")
        if topic and self._ale is not None:
            try:
                self._ale.inject_priority_topic(topic)
                log.debug("[UFC] Gap-driven priority topic injected: %r", topic)
            except Exception as exc:
                log.debug("[UFC] inject_priority_topic failed: %s", exc)

    # ── Core tick ─────────────────────────────────────────────────────────────

    def tick(self) -> Dict[str, Any]:
        """
        Run one complete feedback cycle.

        Returns a summary dict with counts of injected topics, proposed
        candidates, and whether the runtime level advanced.
        """
        self._last_tick = time.time()
        self._tick_count += 1

        result: Dict[str, Any] = {
            "tick": self._tick_count,
            "topics_injected": 0,
            "candidates_proposed": 0,
            "candidate_committed": None,
            "runtime_improved": False,
        }

        # Step 1 — read current subsystem scores
        scores = self._get_scores()
        if not scores:
            return result

        # Step 2 — sync SelfModel confidence maps
        self._sync_self_model(scores)

        # Step 3 — inject priority research topics for weak subsystems
        result["topics_injected"] = self._inject_topics_for_weak(scores)

        # Step 4 — propose evolution for critically weak subsystems
        result["candidates_proposed"] = self._propose_evolutions(scores)

        # Step 5 — commit the best simulated evolution candidate
        result["candidate_committed"] = self._commit_best_candidate()

        # Step 6 — feed AdaptiveLearning recommendations into ALE
        self._feed_adaptive_recommendations()

        # Step 7 — advance NiblitRuntime level based on MetaEvaluator average
        result["runtime_improved"] = self._advance_runtime(scores)

        log.info(
            "[UFC] Tick #%d: injected=%d proposed=%d committed=%s",
            self._tick_count,
            result["topics_injected"],
            result["candidates_proposed"],
            result["candidate_committed"],
        )
        self._last_scores = scores
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_scores(self) -> Dict[str, float]:
        """Return current MetaEvaluator scores (empty dict on any failure)."""
        if self._meta_evaluator is None:
            return {}
        try:
            return self._meta_evaluator.scores()
        except Exception as exc:
            log.debug("[UFC] _get_scores failed: %s", exc)
            return {}

    def _sync_self_model(self, scores: Dict[str, float]) -> None:
        """Push MetaEvaluator scores into SelfModel as per-domain confidence."""
        if self._self_model is None:
            return
        for subsystem, score in scores.items():
            try:
                self._self_model.update_confidence(subsystem.lower(), score)
            except Exception as exc:
                log.debug("[UFC] SelfModel.update_confidence failed for %s: %s", subsystem, exc)

    def _inject_topics_for_weak(self, scores: Dict[str, float]) -> int:
        """Inject priority research topics into ALE for each weak subsystem."""
        if self._ale is None:
            return 0
        injected = 0
        for subsystem, score in scores.items():
            if score < _WEAK_THRESHOLD:
                topics = _SUBSYSTEM_TOPICS.get(subsystem, [])
                for topic in topics[:2]:  # up to 2 topics per weak subsystem
                    try:
                        if self._ale.inject_priority_topic(topic):
                            injected += 1
                            log.debug(
                                "[UFC] Priority topic for weak %s (score=%.2f): %r",
                                subsystem, score, topic,
                            )
                    except Exception as exc:
                        log.debug("[UFC] inject_priority_topic error: %s", exc)
        return injected

    def _propose_evolutions(self, scores: Dict[str, float]) -> int:
        """Propose EvolutionCandidates for critically weak subsystems."""
        if self._evolution_planner is None:
            return 0
        proposed = 0
        for subsystem, score in scores.items():
            if score < _CRITICAL_THRESHOLD:
                topics = _SUBSYSTEM_TOPICS.get(subsystem, [subsystem.lower()])
                description = (
                    f"Improve {subsystem} subsystem (score={score:.2f}): "
                    f"study {topics[0]} and apply findings to strengthen this layer."
                )
                try:
                    self._evolution_planner.propose(
                        description=description,
                        target_module=subsystem.lower(),
                        expected_gain=round((_WEAK_THRESHOLD - score) * 0.8, 3),
                        risk=0.1,
                    )
                    proposed += 1
                    log.info(
                        "[UFC] Evolution candidate proposed for critical %s (score=%.2f)",
                        subsystem, score,
                    )
                except Exception as exc:
                    log.debug("[UFC] evolution_planner.propose failed: %s", exc)
        return proposed

    def _commit_best_candidate(self) -> Optional[str]:
        """Simulate pending candidates and commit the highest-scoring one."""
        if self._evolution_planner is None:
            return None
        try:
            best = self._evolution_planner.pick_best()
            if best is not None and best.simulated_score > 0.1:
                self._evolution_planner.commit(best.id)
                # Record the expected gain as initial outcome; real outcome will
                # be overwritten once the candidate is actually executed.
                self._evolution_planner.record_outcome(best.id, best.expected_gain)
                log.info(
                    "[UFC] Committed evolution candidate: %s (score=%.3f)",
                    best.description[:60], best.simulated_score,
                )
                # Publish the committed event to the EventBus so other layers react.
                self._publish_evolution_event(best)
                return best.id
        except Exception as exc:
            log.debug("[UFC] _commit_best_candidate failed: %s", exc)
        return None

    def _publish_evolution_event(self, candidate: Any) -> None:
        """Publish EVOLUTION_STEP_COMPLETED to the EventBus."""
        if self._event_bus is None:
            return
        try:
            from core.event_bus import Event, EventType
            self._event_bus.publish(Event(
                type=EventType.EVOLUTION_STEP_COMPLETED,
                payload={
                    "candidate_id": candidate.id,
                    "description": candidate.description,
                    "simulated_score": candidate.simulated_score,
                    "target_module": candidate.target_module,
                },
                source="unified_feedback_controller",
            ))
        except Exception as exc:
            log.debug("[UFC] _publish_evolution_event failed: %s", exc)

    def _feed_adaptive_recommendations(self) -> None:
        """Push AdaptiveLearning recommended topics into ALE."""
        if self._adaptive_learning is None or self._ale is None:
            return
        try:
            topics = self._adaptive_learning.get_recommended_topics(count=3)
            for topic in topics:
                if topic:
                    self._ale.add_research_topic(topic)
        except Exception as exc:
            log.debug("[UFC] adaptive_learning recommendations failed: %s", exc)

    def _advance_runtime(self, scores: Dict[str, float]) -> bool:
        """
        Advance NiblitRuntime level when MetaEvaluator average is improving.

        The delta is proportional to the improvement in mean score vs. the
        previous tick.  A floor of 0.01 ensures the runtime still grows even
        when scores are stable.
        """
        if self._niblit_runtime is None or not scores:
            return False
        try:
            avg = sum(scores.values()) / len(scores)
            if avg <= 0.5:
                return False
            prev_avg = (
                sum(self._last_scores.values()) / len(self._last_scores)
                if self._last_scores else avg
            )
            # delta_factor ∈ [0.01, 0.1]
            delta_factor = max(0.01, min(0.1, (avg - prev_avg) + 0.05))
            self._niblit_runtime.improve(delta=round(delta_factor * 0.1, 4))
            return True
        except Exception as exc:
            log.debug("[UFC] _advance_runtime failed: %s", exc)
            return False

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot."""
        return {
            "tick_count": self._tick_count,
            "last_tick": self._last_tick,
            "last_scores": dict(self._last_scores),
            "ale_available": self._ale is not None,
            "meta_evaluator_available": self._meta_evaluator is not None,
            "self_model_available": self._self_model is not None,
            "evolution_planner_available": self._evolution_planner is not None,
            "niblit_runtime_available": self._niblit_runtime is not None,
            "adaptive_learning_available": self._adaptive_learning is not None,
            "event_bus_available": self._event_bus is not None,
        }


# ── UnifiedSelfModules ────────────────────────────────────────────────────────


class UnifiedSelfModules:
    """
    Central bundle for all Niblit self-improvement subsystems.

    Wraps every self-improvement component and closes the autonomous feedback
    loop through :class:`UnifiedFeedbackController`.

    Usage::

        usm = get_unified_self_modules()
        usm.wire(ale=ale, msg_layer=msg, niblit_runtime=runtime, event_bus=bus)
        usm.start()   # background loop — runs tick() every 300 s
        usm.tick()    # manual single-cycle trigger

    The bundle implements the ``Adaptable`` protocol from
    ``modules.niblit_runtime`` so the NiblitRuntime can issue adaptation
    challenges and the bundle will respond by running a self-assessment tick.

    Singleton access via :func:`get_unified_self_modules`.
    """

    # Adaptable protocol fields
    aios_component_name: str = "unified_self_modules"
    aios_declared_level: float = 1.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Live subsystem references (injected via wire() or auto-resolved)
        self.ale: Optional[Any] = None
        self.msg_layer: Optional[Any] = None
        self.niblit_runtime: Optional[Any] = None
        self.adaptive_learning: Optional[Any] = None
        self.event_bus: Optional[Any] = None

        self._controller: Optional[UnifiedFeedbackController] = None
        self._wired = False

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire(
        self,
        *,
        ale: Optional[Any] = None,
        msg_layer: Optional[Any] = None,
        niblit_runtime: Optional[Any] = None,
        adaptive_learning: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        """
        Inject live subsystem references and (re)build the feedback controller.

        Safe to call multiple times — subsequent calls update any ``None``
        slots with newly provided values while leaving already-set ones intact.
        """
        with self._lock:
            if ale is not None:
                self.ale = ale
            if msg_layer is not None:
                self.msg_layer = msg_layer
            if niblit_runtime is not None:
                self.niblit_runtime = niblit_runtime
            if adaptive_learning is not None:
                self.adaptive_learning = adaptive_learning
            if event_bus is not None:
                self.event_bus = event_bus
        self._build_controller()
        self._wired = True
        log.debug(
            "[UnifiedSelfModules] Wired: ale=%s msg=%s runtime=%s adaptive=%s bus=%s",
            self.ale is not None,
            self.msg_layer is not None,
            self.niblit_runtime is not None,
            self.adaptive_learning is not None,
            self.event_bus is not None,
        )

    def _build_controller(self) -> None:
        """(Re)build the UnifiedFeedbackController from current references."""
        meta_evaluator = None
        self_model = None
        evolution_planner = None
        if self.msg_layer is not None:
            meta_evaluator = getattr(self.msg_layer, "meta_evaluator", None)
            self_model = getattr(self.msg_layer, "self_model", None)
            evolution_planner = getattr(self.msg_layer, "evolution_planner", None)

        self._controller = UnifiedFeedbackController(
            ale=self.ale,
            meta_evaluator=meta_evaluator,
            self_model=self_model,
            evolution_planner=evolution_planner,
            niblit_runtime=self.niblit_runtime,
            adaptive_learning=self.adaptive_learning,
            event_bus=self.event_bus,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def tick(self) -> Dict[str, Any]:
        """
        Run one complete feedback cycle synchronously.

        Also publishes ``LEARNING_CYCLE_STARTED`` / ``LEARNING_CYCLE_COMPLETED``
        events to the EventBus so downstream subsystems can react.
        """
        self._publish_event("learning_cycle_started", {"source": "unified_self_modules"})
        try:
            if self._controller is None:
                self._build_controller()
            result = self._controller.tick() if self._controller else {}
        except Exception as exc:
            log.warning("[UnifiedSelfModules] tick() error: %s", exc)
            result = {"error": str(exc)}
        self._publish_event(
            "learning_cycle_completed",
            {"source": "unified_self_modules", "summary": result},
        )
        return result

    def start(self) -> None:
        """Start the background feedback loop (daemon thread)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="unified-self-modules-loop",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "[UnifiedSelfModules] Background feedback loop started (interval=%.0fs)",
            _LOOP_SLEEP,
        )

    def stop(self) -> None:
        """Stop the background feedback loop gracefully."""
        with self._lock:
            if not self._running:
                return
            self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        log.info("[UnifiedSelfModules] Stopped")

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot of the full bundle."""
        ctrl_status = self._controller.status() if self._controller else {}
        return {
            "running": self._running,
            "wired": self._wired,
            "ale_available": self.ale is not None,
            "msg_layer_available": self.msg_layer is not None,
            "niblit_runtime_available": self.niblit_runtime is not None,
            "adaptive_learning_available": self.adaptive_learning is not None,
            "event_bus_available": self.event_bus is not None,
            "controller": ctrl_status,
        }

    # ── Adaptable protocol ────────────────────────────────────────────────────

    def on_adaptation_challenge(self, challenge: Any) -> None:
        """
        Respond to an ``AdaptationChallenge`` from NiblitRuntime.

        Runs an immediate self-assessment tick so MetaEvaluator scores are
        refreshed and ALE receives updated topic priorities before the runtime
        checks compatibility again.
        """
        log.info(
            "[UnifiedSelfModules] Adaptation challenge received (delta=%.4f) — running tick",
            getattr(challenge, "delta", 0.0),
        )
        self.tick()
        # Declare compatibility at the current runtime level.
        if self.niblit_runtime is not None:
            try:
                level = getattr(self.niblit_runtime, "level", self.aios_declared_level)
                self.niblit_runtime.adapt_component(self.aios_component_name, level)
                self.aios_declared_level = level
            except Exception as exc:
                log.debug("[UnifiedSelfModules] adapt_component failed: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Background thread: run a feedback tick every ``_LOOP_SLEEP`` seconds."""
        # Initial delay gives ALE and brain time to fully start.
        self._stop_event.wait(timeout=60.0)
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                log.warning("[UnifiedSelfModules] loop tick error: %s", exc)
            self._stop_event.wait(timeout=_LOOP_SLEEP)

    def _publish_event(self, event_type_str: str, payload: Dict[str, Any]) -> None:
        """Publish a named event to the EventBus (no-op when unavailable)."""
        if self.event_bus is None:
            return
        try:
            from core.event_bus import Event, EventType
            etype = EventType(event_type_str)
            self.event_bus.publish(Event(
                type=etype,
                payload=payload,
                source="unified_self_modules",
            ))
        except Exception as exc:
            log.debug("[UnifiedSelfModules] EventBus publish failed: %s", exc)

    def _auto_wire_from_singletons(self) -> None:
        """
        Attempt to resolve all subsystem references from process-level
        singletons.  Called once during singleton construction so the bundle
        is as fully wired as possible without any external configuration.
        """
        if self.ale is None:
            try:
                from modules.autonomous_learning_engine import get_autonomous_engine
                self.ale = get_autonomous_engine()
            except Exception:
                pass
        if self.msg_layer is None:
            try:
                from modules.meta_cognition import get_msg_layer
                self.msg_layer = get_msg_layer()
            except Exception:
                pass
        if self.niblit_runtime is None:
            try:
                from modules.niblit_runtime import get_niblit_runtime
                self.niblit_runtime = get_niblit_runtime()
            except Exception:
                pass
        if self.adaptive_learning is None:
            try:
                from modules.adaptive_learning import AdaptiveLearning
                self.adaptive_learning = AdaptiveLearning()
            except Exception:
                pass
        if self.event_bus is None:
            try:
                from core.event_bus import EventBus
                self.event_bus = EventBus()
            except Exception:
                pass
        self._build_controller()


# ── Singleton ──────────────────────────────────────────────────────────────────

_singleton: Optional[UnifiedSelfModules] = None
_singleton_lock = threading.Lock()


def get_unified_self_modules() -> UnifiedSelfModules:
    """Return the process-level :class:`UnifiedSelfModules` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                inst = UnifiedSelfModules()
                inst._auto_wire_from_singletons()
                _singleton = inst
    return _singleton


if __name__ == "__main__":
    print('Running unified_self_modules.py')
