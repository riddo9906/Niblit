"""
niblit_runtime.py — Niblit Self-Improving Runtime Environment
=============================================================
Niblit maintains its own runtime environment that continuously improves itself.
Software that wants to run *inside* Niblit's environment must meet a rising
compatibility bar — it must adapt and improve alongside the runtime to keep
running.

Core ideas
----------
1. **Runtime version** — an ever-incrementing integer that represents how
   evolved the Niblit environment currently is.

2. **Compatibility contract** — every hosted component declares the minimum
   runtime version it was built for.  The runtime checks this at load time
   and periodically during operation.  Components that fall behind receive
   an ``AdaptationChallenge`` — a structured description of what they need
   to improve to stay compatible.

3. **Self-improvement cycle** — on every improvement cycle the runtime:
   a. Learns from the environment adapters (``EnvAdapterRegistry``).
   b. Raises the global ``runtime_level`` by the improvement delta.
   c. Publishes the new ``RuntimeSpec`` (capability set + compatibility rules).
   d. Notifies all registered components so they can self-adapt.
   e. Persists the spec to ``niblit_env_state.json`` via ``EnvStateManager``.

4. **Adaptation API** — components call ``register_component()``, implement
   ``Adaptable``, and receive ``AdaptationChallenge`` objects when the runtime
   outpaces them.  The challenge contains the delta of new capabilities the
   component must adopt.

5. **Self-awareness** — the runtime tracks its own growth history so Niblit
   can reflect on how much it has improved across environments.

This is a *purely internal* mechanism.  Nothing here interacts with external
systems; it only governs Niblit's own component ecosystem.

Singleton access via ``get_niblit_runtime()``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
try:
    from typing import Protocol, runtime_checkable
except ImportError:  # Python < 3.8
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[assignment]

log = logging.getLogger(__name__)

# ── Tuneable constants ─────────────────────────────────────────────────────
_IMPROVE_INTERVAL_SECS = int(os.environ.get("NIBLIT_RT_IMPROVE_INTERVAL", "3600"))  # 1 h
_INITIAL_LEVEL = float(os.environ.get("NIBLIT_RT_INITIAL_LEVEL", "1.0"))
_LEVEL_INCREMENT = float(os.environ.get("NIBLIT_RT_INCREMENT", "0.1"))


# ── Adaptable contract ────────────────────────────────────────────────────────

@runtime_checkable
class Adaptable(Protocol):
    """
    Contract for first-class AIOS citizens.

    Any module that implements this Protocol becomes auto-upgradeable: when the
    runtime level advances, ``on_adaptation_challenge`` is called with an
    ``AdaptationChallenge`` describing the delta the component must adopt to
    remain compatible.

    Usage::

        class MyModule:
            aios_component_name: str = "my_module"
            aios_declared_level: float = 1.0

            def on_adaptation_challenge(self, challenge: "AdaptationChallenge") -> None:
                # self-upgrade logic here
                ...

    Register with the runtime::

        runtime = get_niblit_runtime()
        runtime.register_component(
            MyModule.aios_component_name,
            declared_level=MyModule.aios_declared_level,
            adapt_callback=my_instance.on_adaptation_challenge,
        )
    """

    #: Unique component identifier (used in ``register_component``).
    aios_component_name: str

    #: The runtime level this component was built for.
    aios_declared_level: float

    def on_adaptation_challenge(self, challenge: "AdaptationChallenge") -> None:
        """Called when the runtime issues an adaptation challenge."""
        ...


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class RuntimeSpec:
    """
    The published specification of the Niblit runtime at a given level.

    ``capabilities`` is a free-form dict; its keys are feature names, values
    are the minimum component version required to use that feature.
    ``compat_rules`` maps feature names to human-readable adaptation guidance.
    """
    level: float
    capabilities: Dict[str, Any] = field(default_factory=dict)
    compat_rules: Dict[str, str] = field(default_factory=dict)
    published_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSpec":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AdaptationChallenge:
    """
    Describes what a lagging component must do to stay compatible.

    Delivered to components whose declared version is below the current
    runtime level.
    """
    component_name: str
    current_runtime_level: float
    component_level: float
    delta: float
    required_capabilities: List[str]
    guidance: Dict[str, str]          # feature → adaptation advice
    issued_at: float = field(default_factory=time.time)
    deadline_secs: float = 86400.0    # component has 24 h by default


@dataclass
class _ComponentRecord:
    name: str
    declared_level: float
    adapt_callback: Optional[Callable[["AdaptationChallenge"], None]]
    last_adapted_at: float = 0.0
    adaptation_count: int = 0
    compatible: bool = True


# ── NiblitRuntime ─────────────────────────────────────────────────────────────

class NiblitRuntime:
    """
    Niblit's self-improving runtime environment.

    The runtime evolves continuously.  Components that run inside it must keep
    up with its growth or receive adaptation challenges.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        env_adapter_registry: Optional[Any] = None,
        env_state_manager: Optional[Any] = None,
    ) -> None:
        self._knowledge_db = knowledge_db
        self._env_adapter = env_adapter_registry
        self._env_state = env_state_manager

        self._lock = threading.RLock()
        self._level: float = _INITIAL_LEVEL
        self._spec: RuntimeSpec = RuntimeSpec(level=self._level)
        self._components: Dict[str, _ComponentRecord] = {}
        self._history: List[Dict[str, Any]] = []  # growth log
        self._challenges_issued: int = 0

        self._improve_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Restore persisted level if available
        self._restore_level()
        self._rebuild_spec()

        log.info(
            "NiblitRuntime initialised — level=%.2f improve_interval=%ds",
            self._level, _IMPROVE_INTERVAL_SECS,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background self-improvement loop."""
        if self._improve_thread and self._improve_thread.is_alive():
            return
        self._stop_event.clear()
        self._improve_thread = threading.Thread(
            target=self._improvement_loop, daemon=True, name="NiblitRuntimeImprover"
        )
        self._improve_thread.start()
        log.debug("NiblitRuntime: improvement loop started")

    def stop(self) -> None:
        """Stop the improvement loop gracefully."""
        self._stop_event.set()
        if self._improve_thread:
            self._improve_thread.join(timeout=5)

    def register_component(
        self,
        name: str,
        declared_level: float = 1.0,
        adapt_callback: Optional[Callable[[AdaptationChallenge], None]] = None,
    ) -> bool:
        """
        Register a component with the runtime.

        Parameters
        ----------
        name:            Unique component identifier.
        declared_level:  The runtime level this component was built for.
        adapt_callback:  Called when the runtime issues an adaptation challenge.

        Returns True if the component is immediately compatible.
        """
        with self._lock:
            record = _ComponentRecord(
                name=name,
                declared_level=declared_level,
                adapt_callback=adapt_callback,
            )
            self._components[name] = record
            compatible = self._check_component(record)
            log.debug(
                "NiblitRuntime: registered '%s' at level %.2f — compatible=%s",
                name, declared_level, compatible,
            )
            return compatible

    def adapt_component(self, name: str, new_level: float) -> None:
        """
        Called by a component after it has self-adapted.

        Updates the component's declared_level so it passes compatibility checks.
        """
        with self._lock:
            if name not in self._components:
                log.warning("NiblitRuntime.adapt_component: unknown component '%s'", name)
                return
            record = self._components[name]
            old = record.declared_level
            record.declared_level = new_level
            record.last_adapted_at = time.time()
            record.adaptation_count += 1
            record.compatible = new_level >= self._level
            log.info(
                "NiblitRuntime: '%s' adapted %.2f → %.2f (compatible=%s)",
                name, old, new_level, record.compatible,
            )

    def improve(self, delta: Optional[float] = None) -> RuntimeSpec:
        """
        Manually trigger one improvement cycle.

        Raises the runtime level by ``delta`` (default ``_LEVEL_INCREMENT``),
        rebuilds the spec, issues adaptation challenges to lagging components,
        and persists state.
        """
        inc = delta if delta is not None else _LEVEL_INCREMENT
        with self._lock:
            old_level = self._level
            self._level = round(old_level + inc, 4)
            self._rebuild_spec()
            self._record_growth(old_level, self._level)
            self._notify_components()
            self._persist()
        log.info("NiblitRuntime: improved %.4f → %.4f", old_level, self._level)
        return self._spec

    @property
    def level(self) -> float:
        """Current runtime level."""
        return self._level

    @property
    def spec(self) -> RuntimeSpec:
        """Current published RuntimeSpec (snapshot)."""
        with self._lock:
            return RuntimeSpec.from_dict(asdict(self._spec))

    def is_compatible(self, component_level: float) -> bool:
        """Return True if a component at ``component_level`` is compatible."""
        return component_level >= self._level

    def status(self) -> Dict[str, Any]:
        """Return a human-readable status dict."""
        with self._lock:
            compatible = sum(1 for c in self._components.values() if c.compatible)
            total = len(self._components)
            return {
                "runtime_level": self._level,
                "registered_components": total,
                "compatible_components": compatible,
                "lagging_components": total - compatible,
                "challenges_issued": self._challenges_issued,
                "improvement_history": self._history[-5:],
                "spec_capabilities": list(self._spec.capabilities.keys()),
                "improve_interval_secs": _IMPROVE_INTERVAL_SECS,
            }

    def growth_history(self) -> List[Dict[str, Any]]:
        """Return the full growth history."""
        with self._lock:
            return list(self._history)

    # ── Internal ────────────────────────────────────────────────────────────

    def _improvement_loop(self) -> None:
        """Background loop: improve once per interval."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_IMPROVE_INTERVAL_SECS)
            if self._stop_event.is_set():
                break
            try:
                # Gather environment learning delta
                delta = self._compute_improvement_delta()
                self.improve(delta=delta)
            except Exception as exc:
                log.debug("NiblitRuntime: improvement loop error — %s", exc)

    def _compute_improvement_delta(self) -> float:
        """
        Determine how much to grow this cycle based on what Niblit has learned.

        Signals considered (all optional, degrade gracefully):
        * Base increment always applied.
        * +bonus if new environment capabilities were discovered.
        * +bonus if knowledge_db has grown since last check.
        * ×scale factor from MetaEvaluator average score (real quality signal):
          avg=1.0 → 2× base; avg=0.5 → 1× base; avg<0.5 → 0.5× base.
        """
        delta = _LEVEL_INCREMENT
        if self._env_adapter:
            try:
                caps = self._env_adapter.capabilities()
                new_caps = set(caps.keys()) - set(self._spec.capabilities.keys())
                if new_caps:
                    delta += _LEVEL_INCREMENT * min(len(new_caps), 5) * 0.1
                    log.debug("NiblitRuntime: %d new env capabilities → delta bonus", len(new_caps))
            except Exception:
                pass
        if self._knowledge_db:
            try:
                fact_count = len(self._knowledge_db.data.get("facts", {}))
                baseline = self._spec.capabilities.get("_knowledge_facts_baseline", 0)
                growth = fact_count - baseline
                if growth > 10:
                    delta += _LEVEL_INCREMENT * min(growth / 100, 1.0)
            except Exception:
                pass
        # MetaEvaluator quality multiplier — scales delta by real subsystem health.
        try:
            from modules.meta_cognition import get_msg_layer
            scores = get_msg_layer().meta_evaluator.scores()
            if scores:
                avg = sum(scores.values()) / len(scores)
                # avg=1.0 → factor 2.0; avg=0.5 → factor 1.0; avg<0.5 → floor 0.5
                meta_factor = max(0.5, min(2.0, avg * 2.0))
                delta = round(delta * meta_factor, 4)
                log.debug(
                    "NiblitRuntime: MetaEvaluator avg=%.3f → factor=%.2f delta=%.4f",
                    avg, meta_factor, delta,
                )
        except Exception:
            pass
        return round(delta, 4)

    def _rebuild_spec(self) -> None:
        """Reconstruct the RuntimeSpec from current state."""
        caps: Dict[str, Any] = {
            "runtime_level": self._level,
            "state_portability": True,
            "env_adapters": True,
            "security_membrane": True,
            "knowledge_exchange": True,
            "async_io": True,
        }
        if self._env_adapter:
            try:
                caps.update(self._env_adapter.capabilities())
            except Exception:
                pass
        if self._knowledge_db:
            try:
                caps["_knowledge_facts_baseline"] = len(
                    self._knowledge_db.data.get("facts", {})
                )
            except Exception:
                pass

        compat_rules: Dict[str, str] = {
            "runtime_level": (
                f"Component must declare level ≥ {self._level:.2f}. "
                "Call runtime.adapt_component(name, new_level) after self-updating."
            ),
            "state_portability": (
                "Component must read/write NiblitStateEnvelope JSON to participate "
                "in cross-environment state. See modules/env_state.py."
            ),
            "security_membrane": (
                "Component must route all external I/O through SecurityMembrane.inspect(). "
                "See modules/security_membrane.py."
            ),
            "knowledge_exchange": (
                "Component should contribute facts via knowledge_db.add_fact() "
                "and consume via knowledge_db.get_facts()."
            ),
        }
        self._spec = RuntimeSpec(
            level=self._level,
            capabilities=caps,
            compat_rules=compat_rules,
        )

    def _check_component(self, record: _ComponentRecord) -> bool:
        """Check a single component and issue a challenge if needed."""
        if record.declared_level >= self._level:
            record.compatible = True
            return True
        record.compatible = False
        self._issue_challenge(record)
        return False

    def _notify_components(self) -> None:
        """Check all registered components against the new level."""
        for record in self._components.values():
            self._check_component(record)

    def _issue_challenge(self, record: _ComponentRecord) -> None:
        """Create and deliver an AdaptationChallenge to a lagging component."""
        delta = self._level - record.declared_level
        # Build list of newly required capabilities the component lacks
        required_caps = [
            k for k, v in self._spec.capabilities.items()
            if isinstance(v, bool) and v
            and k not in ("runtime_level", "_knowledge_facts_baseline")
        ]
        challenge = AdaptationChallenge(
            component_name=record.name,
            current_runtime_level=self._level,
            component_level=record.declared_level,
            delta=delta,
            required_capabilities=required_caps,
            guidance=dict(self._spec.compat_rules),
        )
        self._challenges_issued += 1
        log.debug(
            "NiblitRuntime: challenge issued to '%s' (delta=%.4f)",
            record.name, delta,
        )
        if record.adapt_callback:
            try:
                record.adapt_callback(challenge)
            except Exception as exc:
                log.debug(
                    "NiblitRuntime: adapt_callback for '%s' raised — %s",
                    record.name, exc,
                )

    def _record_growth(self, old: float, new: float) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from": old,
            "to": new,
            "delta": round(new - old, 4),
            "components": len(self._components),
        }
        self._history.append(entry)
        if self._knowledge_db:
            try:
                self._knowledge_db.add_fact(
                    f"niblit_runtime:level:{new:.4f}",
                    f"Runtime improved {old:.4f} → {new:.4f} at {entry['ts']}",
                )
            except Exception:
                pass

    def _persist(self) -> None:
        """Push current level into the env_state envelope.

        Falls back to writing a small JSON file (``niblit_runtime_level.json``)
        when no EnvStateManager is available, so the level survives restarts
        even in minimal deployments.
        """
        if self._env_state:
            try:
                self._env_state.update({
                    "extras": {"niblit_runtime_level": self._level}
                })
                self._env_state.save()
                return
            except Exception:
                pass
        # Fallback: local JSON file
        try:
            _state_path = Path(os.environ.get("NIBLIT_RUNTIME_STATE", "niblit_runtime_level.json"))
            _state_path.write_text(json.dumps({"level": self._level}), encoding="utf-8")
        except Exception:
            pass

    def _restore_level(self) -> None:
        """Restore a previously persisted runtime level from env_state or JSON fallback."""
        if self._env_state:
            try:
                snap = self._env_state.snapshot()
                stored = snap.extras.get("niblit_runtime_level")
                if stored and float(stored) > self._level:
                    self._level = float(stored)
                    log.debug("NiblitRuntime: restored level %.4f from env_state", self._level)
                    return
            except Exception:
                pass
        # Fallback: local JSON file
        try:
            _state_path = Path(os.environ.get("NIBLIT_RUNTIME_STATE", "niblit_runtime_level.json"))
            if _state_path.exists():
                data = json.loads(_state_path.read_text(encoding="utf-8"))
                stored = float(data.get("level", 0))
                if stored > self._level:
                    self._level = stored
                    log.debug("NiblitRuntime: restored level %.4f from JSON fallback", self._level)
        except Exception:
            pass


# ── Singleton ──────────────────────────────────────────────────────────────
_runtime: Optional[NiblitRuntime] = None
_runtime_lock = threading.Lock()


def get_niblit_runtime(
    knowledge_db: Optional[Any] = None,
    env_adapter_registry: Optional[Any] = None,
    env_state_manager: Optional[Any] = None,
) -> NiblitRuntime:
    """Return the process-level NiblitRuntime singleton."""
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = NiblitRuntime(
                    knowledge_db=knowledge_db,
                    env_adapter_registry=env_adapter_registry,
                    env_state_manager=env_state_manager,
                )
    return _runtime


if __name__ == "__main__":
    print('Running niblit_runtime.py')
