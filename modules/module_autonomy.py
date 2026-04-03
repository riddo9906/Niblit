"""
modules/module_autonomy.py — Module robustness, intelligence & unification framework.

Gives every Niblit module a uniform self-improvement lifecycle:

  • Self-monitoring  — each module's health is tracked
  • Self-healing     — failing modules are restarted/reset automatically
  • Self-improvement — periodic refinement driven by ALE research
  • Unification      — modules can share insights and collectively improve

The ModuleAutonomy manager is wired into NiblitCore and runs a light
background loop.  All participating modules register themselves; the loop
runs health-checks, triggers mini-improvement cycles, and emits unification
events so related modules can align their behaviour.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

log = logging.getLogger("ModuleAutonomy")

_HEALTH_INTERVAL = int(os.getenv("NIBLIT_AUTONOMY_HEALTH_INTERVAL", "60"))
_IMPROVE_INTERVAL = int(os.getenv("NIBLIT_AUTONOMY_IMPROVE_INTERVAL", "300"))
_UNIFY_INTERVAL = int(os.getenv("NIBLIT_AUTONOMY_UNIFY_INTERVAL", "600"))


# ─────────────────────────────────────────────────────────────────────────────


class ModuleRecord:
    """Metadata and health state for a single registered module."""

    __slots__ = ("name", "instance", "category", "healthy", "fail_count",
                 "last_health_check", "last_improved", "improvement_count",
                 "capabilities")

    def __init__(self, name: str, instance: Any, category: str = "general") -> None:
        self.name = name
        self.instance = instance
        self.category = category
        self.healthy = True
        self.fail_count = 0
        self.last_health_check: Optional[str] = None
        self.last_improved: Optional[str] = None
        self.improvement_count = 0
        self.capabilities: Set[str] = set()


class ModuleAutonomy:
    """Central autonomy manager for all Niblit modules.

    Lifecycle
    ---------
    1. `register(name, instance)` — modules announce themselves.
    2. Background health loop       — calls `health_check()` if available.
    3. Background improve loop      — calls `autonomous_improve()` if available.
    4. Background unify loop        — broadcasts shared insights across modules.
    5. `report()`                   — human-readable status of all modules.
    """

    def __init__(self, core: Optional[Any] = None) -> None:
        self.core = core
        self._modules: Dict[str, ModuleRecord] = {}
        self._lock = threading.Lock()
        self._running = False
        self._stop = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._improve_thread: Optional[threading.Thread] = None
        self._unify_thread: Optional[threading.Thread] = None
        self._unify_log: List[str] = []
        self._cycle = 0

    # ── registration ─────────────────────────────────────────────────────────

    def register(self, name: str, instance: Any,
                 category: str = "general",
                 capabilities: Optional[List[str]] = None) -> None:
        with self._lock:
            rec = ModuleRecord(name, instance, category)
            if capabilities:
                rec.capabilities = set(capabilities)
            self._modules[name] = rec
            log.debug("[Autonomy] Registered: %s (%s)", name, category)

    def register_all_from_core(self, core: Any) -> int:
        """Auto-register all non-None module attributes from ``core``."""
        CORE_MODULE_MAP: Dict[str, str] = {
            "db": "memory", "brain": "cognition", "router": "routing",
            "memory": "memory", "network": "connectivity",
            "internet": "connectivity", "tasks": "execution",
            "lifecycle": "lifecycle", "collector": "data",
            "trainer": "learning", "self_healer": "health",
            "self_teacher": "learning", "self_researcher": "research",
            "self_implementer": "execution", "idea_generator": "creativity",
            "reflect": "cognition", "llm": "cognition",
            "improvements": "evolution", "autonomous_engine": "learning",
            "slsa_engine": "knowledge", "live_updater": "evolution",
            "structural_awareness": "awareness", "code_generator": "code",
            "code_compiler": "code", "file_manager": "filesystem",
            "software_studier": "research", "evolve_engine": "evolution",
            "command_registry": "routing", "rate_limiter": "resilience",
            "plugin_manager": "extensibility", "metacognition": "cognition",
            "reasoning_engine": "cognition", "gap_analyzer": "learning",
            "memory_optimizer": "memory", "adaptive_learning": "learning",
            "trading_brain": "trading", "lean_engine": "trading",
            "game_engine": "simulation", "universal_file_manager": "filesystem",
            "background_trainer": "learning", "deployment_bridge": "deployment",
            "autonomous_network": "connectivity",
        }
        self.core = core
        count = 0
        for attr, category in CORE_MODULE_MAP.items():
            obj = getattr(core, attr, None)
            if obj is not None and attr not in self._modules:
                self.register(attr, obj, category)
                count += 1
        return count

    # ── background loops ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        for name, target, iv in (
            ("health",  self._health_loop,  _HEALTH_INTERVAL),
            ("improve", self._improve_loop, _IMPROVE_INTERVAL),
            ("unify",   self._unify_loop,   _UNIFY_INTERVAL),
        ):
            t = threading.Thread(target=target, args=(iv,), daemon=True,
                                 name=f"NiblitModuleAutonomy_{name}")
            setattr(self, f"_{name}_thread", t)
            t.start()
        log.info("[Autonomy] Background loops started (%d modules registered)",
                 len(self._modules))

    def stop(self) -> None:
        self._stop.set()
        self._running = False

    def _health_loop(self, interval: int) -> None:
        while not self._stop.wait(interval):
            self._run_health_checks()

    def _improve_loop(self, interval: int) -> None:
        while not self._stop.wait(interval):
            self._run_improvement_cycle()

    def _unify_loop(self, interval: int) -> None:
        while not self._stop.wait(interval):
            self._run_unification()

    # ── health checks ─────────────────────────────────────────────────────────

    def _run_health_checks(self) -> None:
        with self._lock:
            records = list(self._modules.values())
        for rec in records:
            try:
                if hasattr(rec.instance, "health_check"):
                    result = rec.instance.health_check()
                    rec.healthy = bool(result)
                elif hasattr(rec.instance, "is_healthy"):
                    rec.healthy = bool(rec.instance.is_healthy())
                else:
                    rec.healthy = True   # assume healthy if no health method
                rec.fail_count = 0 if rec.healthy else rec.fail_count + 1
            except Exception as exc:
                rec.healthy = False
                rec.fail_count += 1
                log.debug("[Autonomy] Health check failed for %s: %s", rec.name, exc)
            rec.last_health_check = datetime.now(timezone.utc).isoformat()

            # Auto-repair attempt
            if not rec.healthy and rec.fail_count >= 3:
                self._attempt_repair(rec)

    def _attempt_repair(self, rec: ModuleRecord) -> None:
        """Attempt to call a reset/repair method on a failing module."""
        for method in ("repair", "reset", "restart", "reconnect"):
            fn = getattr(rec.instance, method, None)
            if callable(fn):
                try:
                    fn()
                    rec.healthy = True
                    rec.fail_count = 0
                    log.info("[Autonomy] Repaired %s via .%s()", rec.name, method)
                    return
                except Exception as exc:
                    log.debug("[Autonomy] Repair attempt %s.%s() failed: %s",
                              rec.name, method, exc)

    # ── improvement cycles ────────────────────────────────────────────────────

    def _run_improvement_cycle(self) -> None:
        self._cycle += 1
        with self._lock:
            records = list(self._modules.values())

        ale = getattr(self.core, "autonomous_engine", None)
        db = getattr(self.core, "db", None)

        for rec in records:
            fn = getattr(rec.instance, "autonomous_improve", None)
            if not callable(fn):
                continue
            try:
                result = fn()
                rec.improvement_count += 1
                rec.last_improved = datetime.now(timezone.utc).isoformat()
                if result and db:
                    db.add_fact(
                        key=f"module_improve_{rec.name}_{self._cycle}",
                        value=str(result)[:500],
                        tags=["module_autonomy", "improvement"],
                    )
            except Exception as exc:
                log.debug("[Autonomy] Improve %s: %s", rec.name, exc)

        # Trigger ALE reflection step for the overall system
        if ale and hasattr(ale, "_autonomous_reflection"):
            try:
                ale._autonomous_reflection()
            except Exception:
                pass

    # ── unification ───────────────────────────────────────────────────────────

    def _run_unification(self) -> None:
        """Broadcast shared insights across modules to encourage alignment."""
        db = getattr(self.core, "db", None)
        if db is None:
            return

        try:
            recent_facts = list(db.data.get("facts", []))[-30:]
        except Exception:
            return

        # Find facts tagged "network", "evolve", or "improvement"
        insight_facts = [f for f in recent_facts
                         if any(t in f.get("tags", [])
                                for t in ("network", "evolve", "improvement",
                                          "module_autonomy", "learning"))]
        if not insight_facts:
            return

        # Share insights with learning/research modules
        researcher = getattr(self.core, "self_researcher", None)
        teacher = getattr(self.core, "self_teacher", None)

        for fact in insight_facts[:5]:
            key = fact.get("key", "")
            value = fact.get("value", "")
            if researcher and hasattr(researcher, "add_topic"):
                try:
                    researcher.add_topic(key)
                except Exception:
                    pass
            if teacher and hasattr(teacher, "add_learning_item"):
                try:
                    teacher.add_learning_item(f"{key}: {value}"[:200])
                except Exception:
                    pass

        note = (f"[Unification cycle {self._cycle}] "
                f"shared {len(insight_facts)} insights with research/learning")
        self._unify_log = (self._unify_log + [note])[-20:]
        log.debug("[Autonomy] %s", note)

    # ── status / report ───────────────────────────────────────────────────────

    def report(self) -> str:
        with self._lock:
            records = list(self._modules.values())

        by_category: Dict[str, List[ModuleRecord]] = {}
        for rec in records:
            by_category.setdefault(rec.category, []).append(rec)

        healthy_count = sum(1 for r in records if r.healthy)
        lines = [
            f"🤖 **ModuleAutonomy** (cycle {self._cycle})",
            f"  Modules     : {len(records)} registered, {healthy_count} healthy",
            f"  Running     : {'✅' if self._running else '⚫'}",
        ]
        for cat in sorted(by_category):
            lines.append(f"\n  ── {cat.upper()} ──")
            for rec in by_category[cat]:
                health_icon = "🟢" if rec.healthy else "🔴"
                improved = f"  (improved {rec.improvement_count}x)" if rec.improvement_count else ""
                lines.append(f"    {health_icon} {rec.name}{improved}")

        if self._unify_log:
            lines.append(f"\n  Latest unification: {self._unify_log[-1]}")
        return "\n".join(lines)

    def module_status(self, name: str) -> str:
        rec = self._modules.get(name)
        if rec is None:
            return f"⚫ Module '{name}' not registered in ModuleAutonomy"
        return (
            f"🔍 {rec.name} ({rec.category})\n"
            f"  Healthy     : {'✅' if rec.healthy else '❌'} (fail_count={rec.fail_count})\n"
            f"  Improvements: {rec.improvement_count}\n"
            f"  Last health : {rec.last_health_check or 'never'}\n"
            f"  Last improve: {rec.last_improved or 'never'}\n"
            f"  Capabilities: {', '.join(rec.capabilities) or 'none declared'}"
        )


# ── singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ModuleAutonomy] = None


def get_module_autonomy(core: Optional[Any] = None) -> ModuleAutonomy:
    global _instance
    if _instance is None:
        _instance = ModuleAutonomy(core=core)
    elif core is not None and _instance.core is None:
        _instance.core = core
    return _instance


if __name__ == "__main__":
    print("Running module_autonomy.py")
    ma = get_module_autonomy()

    class MockModule:
        def health_check(self):
            return True

    ma.register("test_module", MockModule(), "testing")
    ma.start()
    time.sleep(0.1)
    print(ma.report())
    ma.stop()
