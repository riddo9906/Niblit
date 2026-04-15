"""modules/meta_cognition — Meta-Cognitive Self-Governance (MSG) Layer v1.

Exposes the five MSG components as a unified package.  Each component is also
importable directly from its own submodule.

Singletons are available via ``get_msg_layer()`` (full bundle) or through
each submodule's own ``get_*()`` accessor.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

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
