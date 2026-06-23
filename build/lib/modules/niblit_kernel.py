#!/usr/bin/env python3
"""
modules/niblit_kernel.py — Niblit's unified cognitive kernel.

The NiblitKernel is the "brain of brains" — the central self-awareness layer
that understands what Niblit is, how all modules function, and how the system
can improve itself over time.

Responsibilities:
  1. Module registry — knows all live modules and their health state
  2. Crash isolation — catches and records module failures without cascades
  3. Self-repair — attempts to restart/recover failed modules
  4. Cognitive identity — maintains Niblit's self-model (what it is, what it knows)
  5. Experience accumulation — learns from every success AND failure
  6. World model — builds a model of the external environment from research results
  7. Improvement proposals — surfaces actionable upgrades from accumulated experience
  8. Unified health API — any module can query "what is broken and why?"
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

log = logging.getLogger("NiblitKernel")

# ══════════════════════════════════════════════════════════════════════════════
# ModuleRecord dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModuleRecord:
    """Tracks the live state of a single registered module."""
    name: str
    instance: Any
    status: str = "ok"          # "ok" | "degraded" | "failed" | "restarting"
    error_count: int = 0
    last_error: str = ""
    last_ok: float = field(default_factory=time.time)
    restart_fn: Optional[Callable] = None
    success_count: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# NiblitKernel
# ══════════════════════════════════════════════════════════════════════════════

class NiblitKernel:
    """
    Central self-awareness and recovery layer for Niblit.

    Every module can register here, report health events, and be automatically
    repaired.  The kernel also maintains a persistent self-model (identity),
    an accumulating world model, and an improvement log.

    All public mutating methods are thread-safe.

    Parameters
    ----------
    hybrid_manager:
        Optional HybridMemoryManager (or compatible) used to upsert error /
        improvement facts into the knowledge base.
    self_monitor:
        Optional SelfMonitor instance; error / success events are forwarded to
        it so the full experience log stays in sync.
    """

    # Default self-model seeded at construction time.
    _DEFAULT_IDENTITY: Dict[str, Any] = {
        "name": "Niblit",
        "purpose": (
            "An autonomous, self-improving AI assistant that learns from experience, "
            "repairs itself, and continuously upgrades its own capabilities."
        ),
        "capabilities": [
            "natural language understanding",
            "autonomous learning",
            "self-monitoring",
            "self-repair",
            "code generation",
            "multi-agent orchestration",
        ],
        "version": "1.0.0",
        "author": "Niblit Project",
    }

    def __init__(
        self,
        hybrid_manager: Any = None,
        self_monitor: Any = None,
    ) -> None:
        self._hybrid_manager = hybrid_manager
        self._self_monitor = self_monitor
        self._lock = threading.Lock()

        # Module registry
        self._modules: Dict[str, ModuleRecord] = {}

        # Niblit self-model (mutable copy of defaults)
        self._identity: Dict[str, Any] = dict(self._DEFAULT_IDENTITY)

        # World model: {topic: {"fact": str, "confidence": float, "updated_at": float}}
        self._world_model: Dict[str, Dict[str, Any]] = {}

        # Improvement log — ring buffer of improvement event dicts
        self._improvement_log: Deque[Dict[str, Any]] = deque(maxlen=200)

        # Per-module success counter (complementing ModuleRecord.success_count)
        self._success_counts: Counter = Counter()

        log.info("[NiblitKernel] Cognitive kernel initialised.")

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Module registry ───────────────────────────────────────────────────────

    def register_module(
        self,
        name: str,
        instance: Any,
        restart_fn: Optional[Callable] = None,
    ) -> ModuleRecord:
        """
        Add a module to the kernel registry.

        Parameters
        ----------
        name:
            Unique module identifier (e.g. ``"HybridMemoryManager"``).
        instance:
            The live object.
        restart_fn:
            Optional zero-argument callable that recreates and returns a fresh
            instance of the module.  Used by ``attempt_repair``.

        Returns
        -------
        ModuleRecord
            The newly created registry entry.
        """
        record = ModuleRecord(
            name=name,
            instance=instance,
            restart_fn=restart_fn,
            last_ok=self._now(),
        )
        with self._lock:
            self._modules[name] = record
        log.info("[NiblitKernel] Registered module '%s'", name)
        return record

    def update_module_status(
        self,
        name: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Update the health status of a registered module.

        Parameters
        ----------
        name:
            Module identifier.
        status:
            One of ``"ok"``, ``"degraded"``, ``"failed"``, ``"restarting"``.
        error:
            Optional error description to record.
        """
        with self._lock:
            if name not in self._modules:
                log.warning("[NiblitKernel] update_module_status: unknown module '%s'", name)
                return
            rec = self._modules[name]
            rec.status = status
            if error:
                rec.last_error = error
            if status == "ok":
                rec.last_ok = self._now()
        log.debug("[NiblitKernel] Module '%s' status → %s", name, status)

    def report_error(
        self,
        name: str,
        error: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Called when a module raises an exception or encounters a failure.

        Increments the error counter, logs to self_monitor, upserts a fact
        into hybrid_manager, and schedules auto-repair if ``restart_fn`` is
        available.

        Parameters
        ----------
        name:
            Module identifier.
        error:
            Exception or error description.
        context:
            Optional dict with additional diagnostic information.
        """
        error_str = str(error)
        with self._lock:
            if name not in self._modules:
                self._modules[name] = ModuleRecord(name=name, instance=None)
            rec = self._modules[name]
            rec.error_count += 1
            rec.last_error = error_str
            rec.status = "failed"

        log.error("[NiblitKernel] Module '%s' error #%d: %s", name, rec.error_count, error_str)

        # Forward to self_monitor
        if self._self_monitor is not None:
            try:
                self._self_monitor.log_event(
                    "HEAL_REPAIR",
                    f"[{name}] error: {error_str}",
                    metadata={"module": name, "context": context or {}},
                    outcome="failure",
                )
            except Exception as exc:  # pragma: no cover
                log.debug("[NiblitKernel] self_monitor.log_event failed: %s", exc)

        # Persist to hybrid_manager / knowledge store (duck-typed)
        if self._hybrid_manager is not None:
            try:
                key = f"module_error_{name}"
                value = f"Module {name} failed: {error_str}"
                meta = {"module": name, "error": error_str, "context": context or {}}
                if hasattr(self._hybrid_manager, "store_fact"):
                    self._hybrid_manager.store_fact(key, value, list(meta.keys()))
                elif hasattr(self._hybrid_manager, "add_fact"):
                    self._hybrid_manager.add_fact(key, value)
                elif hasattr(self._hybrid_manager, "upsert"):
                    self._hybrid_manager.upsert(key, value, metadata=meta)
            except Exception as exc:  # pragma: no cover
                log.debug("[NiblitKernel] hybrid_manager store failed: %s", exc)

        # Attempt auto-repair if restart_fn is registered
        if rec.restart_fn is not None:
            self.attempt_repair(name)

    def report_success(
        self,
        name: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Called when a module completes an action successfully.

        Parameters
        ----------
        name:
            Module identifier.
        action:
            Short description of what succeeded.
        context:
            Optional diagnostic context.
        """
        with self._lock:
            if name not in self._modules:
                self._modules[name] = ModuleRecord(name=name, instance=None)
            rec = self._modules[name]
            rec.success_count += 1
            rec.last_ok = self._now()
            if rec.status != "ok":
                rec.status = "ok"
        self._success_counts[name] += 1
        log.debug("[NiblitKernel] Module '%s' success: %s", name, action)

        if self._self_monitor is not None:
            try:
                self._self_monitor.log_event(
                    "AGENT_ACTION",
                    f"[{name}] {action}",
                    metadata={"module": name, "context": context or {}},
                    outcome="success",
                )
            except Exception as exc:  # pragma: no cover
                log.debug("[NiblitKernel] self_monitor.log_event failed: %s", exc)

    def wrap_call(
        self,
        module_name: str,
        fn: Callable,
        *args: Any,
        **kwargs: Any,
    ):
        """
        Safely call *fn* and report success/failure to the kernel.

        Parameters
        ----------
        module_name:
            The registry name to associate this call with.
        fn:
            The callable to invoke.
        *args, **kwargs:
            Forwarded to *fn*.

        Returns
        -------
        tuple[Any, Optional[Exception]]
            ``(result, None)`` on success, ``(None, exception)`` on failure.
        """
        try:
            result = fn(*args, **kwargs)
            self.report_success(module_name, getattr(fn, "__name__", str(fn)))
            return result, None
        except Exception as exc:
            self.report_error(module_name, exc)
            return None, exc

    # ── Health queries ────────────────────────────────────────────────────────

    def get_health_report(self) -> Dict[str, Dict[str, Any]]:
        """
        Return a snapshot of every module's health.

        Returns
        -------
        dict
            ``{module_name: {"status": str, "error_count": int, "last_error": str}}``
        """
        with self._lock:
            return {
                name: {
                    "status": rec.status,
                    "error_count": rec.error_count,
                    "last_error": rec.last_error,
                    "success_count": rec.success_count,
                    "last_ok_iso": self._iso(rec.last_ok),
                }
                for name, rec in self._modules.items()
            }

    def get_failed_modules(self) -> List[ModuleRecord]:
        """Return a list of ModuleRecord objects whose status is ``"failed"``."""
        with self._lock:
            return [rec for rec in self._modules.values() if rec.status == "failed"]

    # ── Self-repair ───────────────────────────────────────────────────────────

    def attempt_repair(self, name: str) -> bool:
        """
        Attempt to restart a failed module using its registered ``restart_fn``.

        Parameters
        ----------
        name:
            Module identifier.

        Returns
        -------
        bool
            ``True`` if repair succeeded, ``False`` otherwise.
        """
        with self._lock:
            rec = self._modules.get(name)
        if rec is None:
            log.warning("[NiblitKernel] attempt_repair: unknown module '%s'", name)
            return False
        if rec.restart_fn is None:
            log.info("[NiblitKernel] No restart_fn for module '%s' — cannot repair.", name)
            return False

        log.info("[NiblitKernel] Attempting repair of module '%s' …", name)
        self.update_module_status(name, "restarting")
        try:
            new_instance = rec.restart_fn()
            with self._lock:
                rec.instance = new_instance
                rec.status = "ok"
                rec.last_ok = self._now()
                rec.last_error = ""
            self.log_improvement(
                f"Auto-repaired module '{name}'",
                category="self_repair",
                before="failed",
                after="ok",
            )
            log.info("[NiblitKernel] Module '%s' repaired successfully.", name)
            return True
        except Exception as exc:
            self.update_module_status(name, "failed", error=str(exc))
            log.error("[NiblitKernel] Repair of '%s' failed: %s", name, exc)
            return False

    def run_self_repair_cycle(self) -> str:
        """
        Attempt to repair all modules currently in ``"failed"`` status.

        Returns
        -------
        str
            Human-readable summary of the repair pass.
        """
        failed = self.get_failed_modules()
        if not failed:
            return "Self-repair cycle: all modules healthy — nothing to repair."

        results: List[str] = []
        for rec in failed:
            ok = self.attempt_repair(rec.name)
            results.append(f"  {rec.name}: {'✓ repaired' if ok else '✗ repair failed'}")

        summary = f"Self-repair cycle ({len(failed)} module(s)):\n" + "\n".join(results)
        log.info("[NiblitKernel] %s", summary)
        return summary

    # ── Cognitive identity ────────────────────────────────────────────────────

    def update_self_identity(self, key: str, value: Any) -> None:
        """
        Update a key in Niblit's self-model.

        Parameters
        ----------
        key:
            Identity key (e.g. ``"version"``, ``"capabilities"``).
        value:
            New value.
        """
        with self._lock:
            self._identity[key] = value
        log.debug("[NiblitKernel] Identity updated: %s = %r", key, value)

    def get_self_identity(self) -> Dict[str, Any]:
        """Return a copy of Niblit's current self-model."""
        with self._lock:
            return dict(self._identity)

    # ── World model ───────────────────────────────────────────────────────────

    def update_world_model(
        self,
        topic: str,
        fact: str,
        confidence: float = 1.0,
    ) -> None:
        """
        Add or update a fact in the world model.

        Parameters
        ----------
        topic:
            Short topic key (e.g. ``"python_version"``, ``"host_os"``).
        fact:
            The fact string to associate with the topic.
        confidence:
            Float in ``[0, 1]`` indicating confidence in the fact.
        """
        with self._lock:
            self._world_model[topic] = {
                "fact": fact,
                "confidence": float(max(0.0, min(1.0, confidence))),
                "updated_at": self._now(),
            }
        log.debug("[NiblitKernel] World model updated: %s = %r (conf=%.2f)", topic, fact, confidence)

    def get_world_model_summary(self) -> str:
        """
        Return a human-readable summary of the world model.

        Returns
        -------
        str
            Multi-line string, one fact per line.
        """
        with self._lock:
            items = list(self._world_model.items())
        if not items:
            return "World model: (empty)"
        lines = ["World model:"]
        for topic, entry in sorted(items):
            ts_iso = self._iso(entry["updated_at"])
            lines.append(
                f"  [{topic}] {entry['fact']}  (conf={entry['confidence']:.2f}, updated={ts_iso})"
            )
        return "\n".join(lines)

    # ── Improvement log ───────────────────────────────────────────────────────

    def log_improvement(
        self,
        description: str,
        category: str = "general",
        before: Optional[Any] = None,
        after: Optional[Any] = None,
    ) -> None:
        """
        Record an improvement event in the ring buffer.

        Parameters
        ----------
        description:
            What changed or improved.
        category:
            Logical category (e.g. ``"self_repair"``, ``"learning"``,
            ``"performance"``).
        before:
            Optional "before" state or value.
        after:
            Optional "after" state or value.
        """
        ts = self._now()
        entry: Dict[str, Any] = {
            "description": description,
            "category": category,
            "before": before,
            "after": after,
            "timestamp": ts,
            "timestamp_iso": self._iso(ts),
        }
        with self._lock:
            self._improvement_log.append(entry)
        log.debug("[NiblitKernel] Improvement logged [%s]: %s", category, description)

    def get_improvement_history(self, n: int = 20) -> List[Dict[str, Any]]:
        """
        Return the *n* most recent improvement events (newest first).

        Parameters
        ----------
        n:
            Maximum number of events to return.
        """
        with self._lock:
            items = list(self._improvement_log)
        return list(reversed(items[-n:]))

    # ── Heuristic improvement proposals ──────────────────────────────────────

    def propose_improvements(self) -> List[str]:
        """
        Surface actionable improvement proposals based on failure/success patterns.

        Returns
        -------
        list[str]
            Ordered list of proposal strings (most pressing first).
        """
        proposals: List[str] = []

        with self._lock:
            modules_snapshot = list(self._modules.values())
            improvement_snapshot = list(self._improvement_log)

        # Failed modules with no restart_fn
        no_repair = [r for r in modules_snapshot if r.status == "failed" and r.restart_fn is None]
        for rec in no_repair:
            proposals.append(
                f"Module '{rec.name}' is failed and has no restart_fn — "
                "consider adding a factory function for automatic recovery."
            )

        # High error-count modules still running
        degraded = [r for r in modules_snapshot if r.error_count >= 5 and r.status != "failed"]
        for rec in degraded:
            proposals.append(
                f"Module '{rec.name}' has accumulated {rec.error_count} errors — "
                "review its error handling or increase defensive coverage."
            )

        # Repair failures in improvement log
        repair_failures = [
            e for e in improvement_snapshot
            if e.get("category") == "self_repair" and e.get("after") != "ok"
        ]
        if len(repair_failures) >= 3:
            proposals.append(
                "Multiple self-repair attempts have failed — consider implementing "
                "a deeper diagnostic pass or adding fallback module implementations."
            )

        # World-model gaps
        if len(self._world_model) == 0:
            proposals.append(
                "World model is empty — wire research results into "
                "kernel.update_world_model() to build situational awareness."
            )

        if not proposals:
            proposals.append("No critical improvements detected — system appears healthy.")

        return proposals

    # ── CLI report ────────────────────────────────────────────────────────────

    def cli_report(self) -> str:
        """
        Return a formatted terminal string showing kernel health, identity,
        and recent improvements.

        Returns
        -------
        str
            Multi-line human-readable report.
        """
        sep = "─" * 60
        lines: List[str] = [
            sep,
            "  NiblitKernel — Cognitive Kernel Report",
            sep,
        ]

        # Identity
        identity = self.get_self_identity()
        lines.append(f"  Name    : {identity.get('name', 'N/A')}")
        lines.append(f"  Version : {identity.get('version', 'N/A')}")
        lines.append(f"  Purpose : {identity.get('purpose', 'N/A')[:80]}")
        caps = identity.get("capabilities", [])
        lines.append(f"  Capabilities ({len(caps)}): {', '.join(caps[:5])}" + (" …" if len(caps) > 5 else ""))

        # Module health
        lines.append("")
        lines.append("  Module Health:")
        health = self.get_health_report()
        if not health:
            lines.append("    (no modules registered)")
        else:
            for mod_name, info in sorted(health.items()):
                icon = "✓" if info["status"] == "ok" else "!" if info["status"] == "degraded" else "✗"
                lines.append(
                    f"    {icon} {mod_name:<30} status={info['status']:<12} "
                    f"errors={info['error_count']}  successes={info['success_count']}"
                )

        # Recent improvements
        lines.append("")
        lines.append("  Recent Improvements:")
        history = self.get_improvement_history(5)
        if not history:
            lines.append("    (none recorded)")
        else:
            for entry in history:
                lines.append(
                    f"    [{entry['category']}] {entry['description']}  "
                    f"({entry['timestamp_iso']})"
                )

        # Proposals
        lines.append("")
        lines.append("  Improvement Proposals:")
        for proposal in self.propose_improvements():
            lines.append(f"    • {proposal}")

        lines.append(sep)
        return "\n".join(lines)

    # ── Knowledge persistence ─────────────────────────────────────────────────

    def flush_knowledge(self, knowledge_db: Any) -> None:
        """
        Persist identity, world model, and improvement log to a knowledge DB.

        Supports duck-typed knowledge store objects.  The following store
        interfaces are tried in order:

        1. ``knowledge_db.store_fact(key, value, tags)``  — KnowledgeDB style
        2. ``knowledge_db.add_fact(key, value)``          — minimal interface
        3. ``knowledge_db.upsert(key, value, metadata)``  — generic KV style

        Parameters
        ----------
        knowledge_db:
            Compatible knowledge-base object (e.g. KnowledgeDB, custom store).
        """
        if knowledge_db is None:
            return

        if hasattr(knowledge_db, "store_fact"):
            def _store(key: str, value: str, tags: list) -> None:
                knowledge_db.store_fact(key, value, tags)
        elif hasattr(knowledge_db, "add_fact"):
            def _store(key: str, value: str, tags: list) -> None:
                knowledge_db.add_fact(key, value)
        elif hasattr(knowledge_db, "upsert"):
            def _store(key: str, value: str, tags: list) -> None:
                knowledge_db.upsert(key, value, metadata={"tags": tags})
        else:
            log.warning(
                "[NiblitKernel] flush_knowledge: knowledge_db (%s) has no compatible "
                "store method (store_fact / add_fact / upsert).",
                type(knowledge_db).__name__,
            )
            return

        items = [
            ("niblit_kernel_identity",    str(self.get_self_identity()),        ["kernel", "identity"]),
            ("niblit_kernel_world_model", self.get_world_model_summary(),       ["kernel", "world_model"]),
            (
                "niblit_kernel_improvements",
                "\n".join(
                    f"[{e['category']}] {e['description']}"
                    for e in self.get_improvement_history(50)
                ) or "(none)",
                ["kernel", "improvements"],
            ),
        ]
        for key, value, tags in items:
            try:
                _store(key, value, tags)
            except Exception as exc:  # pragma: no cover
                log.warning("[NiblitKernel] flush_knowledge: failed to persist '%s': %s", key, exc)
        log.info("[NiblitKernel] Knowledge flushed to KB.")


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════════════════════

_kernel_instance: Optional[NiblitKernel] = None


def get_kernel() -> NiblitKernel:
    """
    Return the process-wide NiblitKernel singleton, creating it if necessary.

    Returns
    -------
    NiblitKernel
        The shared kernel instance.
    """
    global _kernel_instance
    if _kernel_instance is None:
        _kernel_instance = NiblitKernel()
    return _kernel_instance


if __name__ == "__main__":
    print('Running niblit_kernel.py')
