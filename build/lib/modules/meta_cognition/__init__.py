"""modules/meta_cognition — Meta-Cognitive Self-Governance (MSG) Layer v1.

Exposes the five MSG components as a unified package.  Each component is also
importable directly from its own submodule.

Singletons are available via ``get_msg_layer()`` (full bundle) or through
each submodule's own ``get_*()`` accessor.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

log = logging.getLogger("Niblit.MetaCognition")

_singleton: Optional["MSGLayer"] = None
_lock = threading.Lock()


class MSGLayer:
    """Thin bundle that holds all five MSG components in one place.

    Access via :func:`get_msg_layer` to get the process-wide singleton.
    """

    def __init__(self) -> None:
        from modules.meta_cognition.self_model import get_self_model
        from modules.meta_cognition.intent_engine import get_intent_engine
        from modules.meta_cognition.meta_evaluator import get_meta_evaluator
        from modules.meta_cognition.resource_allocator import get_resource_allocator
        from modules.meta_cognition.evolution_planner import get_evolution_planner

        self.self_model = get_self_model()
        self.intent_engine = get_intent_engine()
        self.meta_evaluator = get_meta_evaluator()
        self.resource_allocator = get_resource_allocator()
        self.evolution_planner = get_evolution_planner()
        log.info("✅ MSG Layer v1 initialised (SelfModel + IntentEngine + MetaEvaluator "
                 "+ ResourceAllocator + EvolutionPlanner)")

    # ── Convenience passthrough ───────────────────────────────────────────

    def pre_cycle(self, cycle: int, topic: str) -> None:
        """Run all MSG pre-cycle hooks.  Called by ALE Step 0."""
        try:
            intent = self.intent_engine.current_intent()
            allocation = self.resource_allocator.get_allocation()
            scores = self.meta_evaluator.scores()
            log.info(
                "🧠 [MSG] Cycle #%d | topic=%r | intent=%s | alloc=%s | scores=%s",
                cycle, topic, intent.get("label", "—"),
                {k: f"{v:.0%}" for k, v in allocation.items()},
                {k: f"{v:.2f}" for k, v in scores.items()},
            )
            self.self_model.record_cycle(cycle, topic)
        except Exception as exc:
            log.debug("[MSG] pre_cycle error: %s", exc)

    def status(self) -> dict:
        """Return a serialisable status snapshot of all MSG components."""
        try:
            return {
                "self_model": self.self_model.snapshot(),
                "intent_engine": self.intent_engine.snapshot(),
                "meta_evaluator": self.meta_evaluator.snapshot(),
                "resource_allocator": self.resource_allocator.snapshot(),
                "evolution_planner": self.evolution_planner.snapshot(),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def drive_ale(self, ale: Any) -> None:
        """
        Feed MetaEvaluator weakest subsystems back into ALE as priority topics.

        Called by the unified feedback loop (or directly from niblit_core) to
        ensure the weakest parts of the system receive focused research.

        Parameters
        ----------
        ale:
            A live ``AutonomousLearningEngine`` instance with an
            ``inject_priority_topic(topic: str) -> bool`` method.
        """
        try:
            from modules.unified_self_modules import _SUBSYSTEM_TOPICS, _WEAK_THRESHOLD
            scores = self.meta_evaluator.scores()
            weakest = self.meta_evaluator.weakest(n=3)
            for subsystem in weakest:
                score = scores.get(subsystem, 0.5)
                if score < _WEAK_THRESHOLD:
                    topics = _SUBSYSTEM_TOPICS.get(subsystem, [])
                    for topic in topics[:1]:
                        try:
                            ale.inject_priority_topic(topic)
                            log.debug("[MSG.drive_ale] Injected %r for weak %s (%.2f)",
                                      topic, subsystem, score)
                        except Exception:
                            pass
        except Exception as exc:
            log.debug("[MSG.drive_ale] error: %s", exc)

    def closed_loop_tick(self, ale: Any = None) -> dict:
        """
        Run a full MSG closed-loop tick: evaluate all subsystems, sync the
        SelfModel, optionally inject topics into ALE, and return a status dict.

        This is the single entry-point for any external caller that wants to
        trigger one MSG governance cycle without going through
        :class:`~modules.unified_self_modules.UnifiedSelfModules`.
        """
        try:
            scores = self.meta_evaluator.scores()
            # Sync SelfModel
            for subsystem, score in scores.items():
                self.self_model.update_confidence(subsystem.lower(), score)
            # Drive ALE if provided
            if ale is not None:
                self.drive_ale(ale)
            # Propose evolutions for critically weak subsystems
            from modules.unified_self_modules import _CRITICAL_THRESHOLD, _SUBSYSTEM_TOPICS
            for subsystem, score in scores.items():
                if score < _CRITICAL_THRESHOLD:
                    topics = _SUBSYSTEM_TOPICS.get(subsystem, [subsystem.lower()])
                    self.evolution_planner.propose(
                        description=(
                            f"Improve {subsystem} (score={score:.2f}): "
                            f"study {topics[0]}."
                        ),
                        target_module=subsystem.lower(),
                        expected_gain=round((0.5 - score) * 0.8, 3),
                        risk=0.1,
                    )
            return {"scores": scores, "weakest": self.meta_evaluator.weakest(3)}
        except Exception as exc:
            log.debug("[MSG.closed_loop_tick] error: %s", exc)
            return {"error": str(exc)}


def get_msg_layer() -> MSGLayer:
    """Return the process-wide :class:`MSGLayer` singleton."""
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = MSGLayer()
    return _singleton
if __name__ == "__main__":
    print('Running __init__.py')
