#!/usr/bin/env python3
"""
aios_runtime.py — NIBLIT-AIOS Runtime Manager
==============================================
Owns the canonical Phase 0→7 boot sequence as a single callable
``AIOSRuntime.boot()`` method, replacing the implicit ordering spread
across ``main.py``.

Boot phases
-----------
+-------+-------------+---------------------------------------------------+
| Phase | Name        | Responsibility                                    |
+-------+-------------+---------------------------------------------------+
|   0   | ENV         | Load environment variables, configure logging     |
|   1   | HAL         | Hardware Abstraction Layer probe (``aios_hal``)   |
|   2   | BOOTLOADER  | Kernel + self-improving runtime start             |
|   3   | MEMORY      | Memory subsystem (KnowledgeDB, MemoryManager)     |
|   4   | BRAIN       | AI reasoning layer (NiblitBrain)                  |
|   5   | LEARNING    | ALE / self-improvement engine start               |
|   6   | AGENTS      | Router / agent dispatch initialisation            |
|   7   | INTERFACE   | CLI / REST API / notification layer ready         |
+-------+-------------+---------------------------------------------------+

Boot telemetry
--------------
At Phase 7 completion ``AIOSRuntime`` emits a structured ``aios.boot.complete``
event so ``MonitoringAlerting`` can track cold-start time across deployments::

    {
        "event": "aios.boot.complete",
        "boot_id": "<uuid4>",
        "phases": [{"phase": "ENV", "duration_ms": 12, "ok": True}, …],
        "total_ms": 1234,
        "timestamp": "2026-04-07T21:00:00Z",
    }

This telemetry is emitted to the ``aios.runtime`` logger at DEBUG level and,
if available, pushed to ``core.notification_queue.notif_queue``.

Singleton access via ``get_aios_runtime()``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("aios.runtime")

# ── Phase constants (match aios_scheduler.AIOS_PHASES) ───────────────────────

PHASE_ENV = "ENV"
PHASE_HAL = "HAL"
PHASE_BOOTLOADER = "BOOTLOADER"
PHASE_MEMORY = "MEMORY"
PHASE_BRAIN = "BRAIN"
PHASE_LEARNING = "LEARNING"
PHASE_AGENTS = "AGENTS"
PHASE_INTERFACE = "INTERFACE"

BOOT_PHASES: List[str] = [
    PHASE_ENV,
    PHASE_HAL,
    PHASE_BOOTLOADER,
    PHASE_MEMORY,
    PHASE_BRAIN,
    PHASE_LEARNING,
    PHASE_AGENTS,
    PHASE_INTERFACE,
]


# ── PhaseResult ───────────────────────────────────────────────────────────────

class PhaseResult:
    """Records the outcome of a single boot phase."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.ok: bool = False
        self.duration_ms: float = 0.0
        self.error: Optional[Exception] = None
        self._start: float = time.monotonic()

    def finish(self, ok: bool = True, error: Optional[Exception] = None) -> None:
        elapsed = time.monotonic() - self._start
        self.duration_ms = round(elapsed * 1000, 2)
        self.ok = ok
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "error": str(self.error) if self.error else None,
        }


# ── AIOSRuntime ───────────────────────────────────────────────────────────────

class AIOSRuntime:
    """
    NIBLIT-AIOS runtime manager.

    Owns the canonical Phase 0→7 boot sequence and emits boot telemetry at
    Phase 7 completion.  Higher-level code (``main.py``, test harnesses) can
    call ``boot()`` to drive the full sequence, or call individual
    ``phase_N_*()`` methods for fine-grained control.
    """

    def __init__(self) -> None:
        self._boot_id: str = str(uuid.uuid4())
        self._boot_results: List[PhaseResult] = []
        self._booted: bool = False
        self._lock = threading.Lock()
        self._phase_hooks: Dict[str, List[Callable[[], None]]] = {p: [] for p in BOOT_PHASES}

        # References to major subsystems populated during boot
        self.hal: Optional[Any] = None
        self.kernel: Optional[Any] = None
        self.niblit_runtime: Optional[Any] = None
        self.scheduler: Optional[Any] = None
        self.memory: Optional[Any] = None
        self.brain: Optional[Any] = None
        self.ale: Optional[Any] = None
        self.router: Optional[Any] = None
        self.core: Optional[Any] = None
        # Security & layer-registry subsystems (SEC layer)
        self.security_hardening: Optional[Any] = None
        self.security_membrane: Optional[Any] = None
        self.layer_registry: Optional[Any] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register_hook(self, phase: str, fn: Callable[[], None]) -> None:
        """
        Register a zero-argument callable to run at the end of ``phase``.

        Hooks are called in registration order after the built-in phase logic.
        """
        if phase not in self._phase_hooks:
            raise ValueError(f"Unknown AIOS phase: {phase!r}. Must be one of {BOOT_PHASES}")
        self._phase_hooks[phase].append(fn)

    def boot(self) -> Dict[str, Any]:
        """
        Execute the full Phase 0→7 boot sequence.

        Returns the boot telemetry dict.  Safe to call only once; subsequent
        calls return the cached telemetry immediately.
        """
        with self._lock:
            if self._booted:
                return self._build_telemetry()

        boot_start = time.monotonic()

        phase_methods = [
            (PHASE_ENV,        self._phase_0_env),
            (PHASE_HAL,        self._phase_1_hal),
            (PHASE_BOOTLOADER, self._phase_2_bootloader),
            (PHASE_MEMORY,     self._phase_3_memory),
            (PHASE_BRAIN,      self._phase_4_brain),
            (PHASE_LEARNING,   self._phase_5_learning),
            (PHASE_AGENTS,     self._phase_6_agents),
            (PHASE_INTERFACE,  self._phase_7_interface),
        ]

        for phase_name, phase_fn in phase_methods:
            result = PhaseResult(phase_name)
            try:
                phase_fn()
                self._run_hooks(phase_name)
                result.finish(ok=True)
            except Exception as exc:
                result.finish(ok=False, error=exc)
                log.warning("AIOSRuntime: phase %s failed — %s", phase_name, exc)
            self._boot_results.append(result)

        total_ms = round((time.monotonic() - boot_start) * 1000, 2)

        with self._lock:
            self._booted = True

        telemetry = self._build_telemetry(total_ms=total_ms)
        self._emit_telemetry(telemetry)
        return telemetry

    @property
    def is_booted(self) -> bool:
        """True after ``boot()`` has completed."""
        with self._lock:
            return self._booted

    def status(self) -> Dict[str, Any]:
        """Return a summary of the boot status."""
        return {
            "boot_id": self._boot_id,
            "booted": self._booted,
            "phases": [r.to_dict() for r in self._boot_results],
            "hal_available": self.hal is not None,
            "brain_available": self.brain is not None,
            "ale_available": self.ale is not None,
            "router_available": self.router is not None,
            "security_hardening_available": self.security_hardening is not None,
            "security_membrane_available": self.security_membrane is not None,
            "layer_registry_available": self.layer_registry is not None,
        }

    # ── Phase implementations ─────────────────────────────────────────────────

    def _phase_0_env(self) -> None:
        """Phase 0 — ENV: load .env, assert required environment variables."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
            log.debug("AIOSRuntime[0/ENV]: .env loaded")
        except ImportError:
            log.debug("AIOSRuntime[0/ENV]: dotenv not installed — relying on os.environ")

    def _phase_1_hal(self) -> None:
        """Phase 1 — HAL: probe hardware and platform capabilities."""
        try:
            from aios_hal import get_aios_hal
            self.hal = get_aios_hal()
            self.hal.probe()
            log.debug(
                "AIOSRuntime[1/HAL]: probed platform=%s",
                self.hal.platform_type,
            )
        except Exception as exc:
            log.debug("AIOSRuntime[1/HAL]: HAL probe skipped — %s", exc)

    def _phase_2_bootloader(self) -> None:
        """Phase 2 — BOOTLOADER: start kernel and self-improving runtime."""
        # NiblitKernel
        try:
            from modules.niblit_kernel import get_niblit_kernel
            self.kernel = get_niblit_kernel()
            log.debug("AIOSRuntime[2/BOOTLOADER]: NiblitKernel ready")
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: NiblitKernel unavailable — %s", exc)

        # NiblitRuntime (self-improving component ecosystem)
        try:
            from modules.niblit_runtime import get_niblit_runtime
            self.niblit_runtime = get_niblit_runtime()
            self.niblit_runtime.start()
            log.debug("AIOSRuntime[2/BOOTLOADER]: NiblitRuntime started (level=%.2f)",
                      self.niblit_runtime.level)
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: NiblitRuntime unavailable — %s", exc)

        # AIOSScheduler
        try:
            from aios_scheduler import get_aios_scheduler
            self.scheduler = get_aios_scheduler()
            self.scheduler.start()
            self.scheduler.advance_phase(PHASE_BOOTLOADER)
            log.debug("AIOSRuntime[2/BOOTLOADER]: AIOSScheduler started")
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: AIOSScheduler unavailable — %s", exc)

        # SecurityHardening — initialise early so all later phases can use it
        try:
            from modules.security_hardening import get_security_hardening
            self.security_hardening = get_security_hardening()
            log.debug("AIOSRuntime[2/BOOTLOADER]: SecurityHardening ready (%s)",
                      self.security_hardening.status()["kdf_algorithm"])
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: SecurityHardening unavailable — %s", exc)

        # SecurityMembrane — defensive API wrapper
        try:
            from modules.security_membrane import get_security_membrane
            self.security_membrane = get_security_membrane()
            log.debug("AIOSRuntime[2/BOOTLOADER]: SecurityMembrane ready")
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: SecurityMembrane unavailable — %s", exc)

        # AIOSLayerRegistry — formal 8-layer architecture registry
        try:
            from modules.aios_layer_registry import get_aios_layer_registry
            self.layer_registry = get_aios_layer_registry()
            log.debug("AIOSRuntime[2/BOOTLOADER]: AIOSLayerRegistry ready")
        except Exception as exc:
            log.debug("AIOSRuntime[2/BOOTLOADER]: AIOSLayerRegistry unavailable — %s", exc)

    def _phase_3_memory(self) -> None:
        """Phase 3 — MEMORY: initialise memory subsystem."""
        try:
            from niblit_memory import MemoryManager
            self.memory = MemoryManager()
            log.debug("AIOSRuntime[3/MEMORY]: MemoryManager ready")
        except Exception as exc:
            log.debug("AIOSRuntime[3/MEMORY]: MemoryManager unavailable — %s", exc)

        if self.scheduler is not None:
            try:
                self.scheduler.advance_phase(PHASE_MEMORY)
            except Exception:
                pass

    def _phase_4_brain(self) -> None:
        """Phase 4 — BRAIN: initialise AI reasoning layer."""
        try:
            from niblit_brain import NiblitBrain
            self.brain = NiblitBrain()
            log.debug("AIOSRuntime[4/BRAIN]: NiblitBrain ready")
        except Exception as exc:
            log.debug("AIOSRuntime[4/BRAIN]: NiblitBrain unavailable — %s", exc)

        if self.scheduler is not None:
            try:
                self.scheduler.advance_phase(PHASE_BRAIN)
            except Exception:
                pass

    def _phase_5_learning(self) -> None:
        """Phase 5 — LEARNING: start ALE / self-improvement engine."""
        try:
            from modules.autonomous_learning_engine import get_autonomous_learning_engine
            self.ale = get_autonomous_learning_engine()
            log.debug("AIOSRuntime[5/LEARNING]: ALE ready")
        except Exception as exc:
            log.debug("AIOSRuntime[5/LEARNING]: ALE unavailable — %s", exc)

        if self.scheduler is not None:
            try:
                self.scheduler.advance_phase(PHASE_LEARNING)
            except Exception:
                pass

    def _phase_6_agents(self) -> None:
        """Phase 6 — AGENTS: initialise router / agent dispatch."""
        try:
            from niblit_router import NiblitRouter
            self.router = NiblitRouter(brain=self.brain)
            log.debug("AIOSRuntime[6/AGENTS]: NiblitRouter ready")
        except Exception as exc:
            log.debug("AIOSRuntime[6/AGENTS]: NiblitRouter unavailable — %s", exc)

        if self.scheduler is not None:
            try:
                self.scheduler.advance_phase(PHASE_AGENTS)
            except Exception:
                pass

    def _phase_7_interface(self) -> None:
        """Phase 7 — INTERFACE: notification layer and CLI/API readiness."""
        try:
            from core.notification_queue import install_queue_log_handler
            install_queue_log_handler(level=logging.INFO)
            log.debug("AIOSRuntime[7/INTERFACE]: background log capture active")
        except Exception as exc:
            log.debug("AIOSRuntime[7/INTERFACE]: notification queue unavailable — %s", exc)

        # Cross-wire all booted subsystems into the 8-layer registry
        if self.layer_registry is not None:
            try:
                self.layer_registry.cross_wire(self)
                log.debug(
                    "AIOSRuntime[7/INTERFACE]: AIOSLayerRegistry cross-wired — %s",
                    self.layer_registry.status(),
                )
            except Exception as exc:
                log.debug("AIOSRuntime[7/INTERFACE]: layer registry cross-wire failed — %s", exc)

        if self.scheduler is not None:
            try:
                self.scheduler.advance_phase(PHASE_INTERFACE)
            except Exception:
                pass

    # ── Telemetry ─────────────────────────────────────────────────────────────

    def _build_telemetry(self, total_ms: float = 0.0) -> Dict[str, Any]:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        return {
            "event": "aios.boot.complete",
            "boot_id": self._boot_id,
            "phases": [r.to_dict() for r in self._boot_results],
            "total_ms": total_ms,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _emit_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Emit boot telemetry to the logger and (optionally) notification queue."""
        import json
        log.debug("aios.boot.complete: %s", json.dumps(telemetry))

        # Push to notification queue if available
        try:
            from core.notification_queue import notif_queue
            if notif_queue is not None:
                notif_queue.push(
                    f"[AIOS] Boot complete in {telemetry['total_ms']:.0f} ms "
                    f"(id={self._boot_id[:8]})"
                )
        except Exception:
            pass

    # ── Hooks ─────────────────────────────────────────────────────────────────

    def _run_hooks(self, phase: str) -> None:
        for fn in self._phase_hooks.get(phase, []):
            try:
                fn()
            except Exception as exc:
                log.debug("AIOSRuntime: hook for phase %s raised — %s", phase, exc)


# ── Singleton ──────────────────────────────────────────────────────────────────

_aios_runtime: Optional[AIOSRuntime] = None
_aios_runtime_lock = threading.Lock()


def get_aios_runtime() -> AIOSRuntime:
    """Return the process-level AIOSRuntime singleton."""
    global _aios_runtime
    if _aios_runtime is None:
        with _aios_runtime_lock:
            if _aios_runtime is None:
                _aios_runtime = AIOSRuntime()
    return _aios_runtime


if __name__ == "__main__":
    print('Running aios_runtime.py')
