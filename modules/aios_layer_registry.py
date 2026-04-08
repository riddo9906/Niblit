#!/usr/bin/env python3
"""
modules/aios_layer_registry.py — NIBLIT-AIOS 8-Layer Architecture Registry
===========================================================================
Implements the formal 8-layer architecture diagram from the NIBLIT AI OS
Complete proposal.  Every subsystem registers itself under one of the eight
canonical layers so the runtime has a unified view of the system.

Layers
------
+------+---------------------+----------------------------------------------+
| ID   | Name                | Responsibilities                             |
+------+---------------------+----------------------------------------------+
| APP  | Application         | Router, Commands, Dashboard, Voice, API      |
| INT  | Intelligence        | Brain, LLM Adapters, Reasoning, Research     |
| LRN  | Learning            | ALE, Curriculum, Self-Researcher, Evolve     |
| MEM  | Memory              | VectorStore, KnowledgeDB                     |
| NET  | Network             | DistributedMesh, P2P inter-device comms      |
| SEC  | Security            | SLSA, Membrane, Permissions, Guard           |
| KRN  | Kernel              | Runtime, EventBus, TaskQueue, Lifecycle      |
| HAL  | Hardware Abstraction| Swift/iOS · TypeScript/Web · Rust/Embedded   |
+------+---------------------+----------------------------------------------+

Usage
-----
    from modules.aios_layer_registry import get_aios_layer_registry, LAYER_SEC

    registry = get_aios_layer_registry()
    registry.register(LAYER_SEC, "security_membrane", membrane_instance)
    health = registry.health()

Singleton access via ``get_aios_layer_registry()``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("aios.layer_registry")

# ── Layer constants ────────────────────────────────────────────────────────────

LAYER_APP = "APP"   # Application
LAYER_INT = "INT"   # Intelligence
LAYER_LRN = "LRN"   # Learning
LAYER_MEM = "MEM"   # Memory
LAYER_NET = "NET"   # Network
LAYER_SEC = "SEC"   # Security
LAYER_KRN = "KRN"   # Kernel
LAYER_HAL = "HAL"   # Hardware Abstraction

ALL_LAYERS: List[str] = [
    LAYER_HAL,
    LAYER_KRN,
    LAYER_SEC,
    LAYER_NET,
    LAYER_MEM,
    LAYER_LRN,
    LAYER_INT,
    LAYER_APP,
]

_LAYER_DESCRIPTIONS: Dict[str, str] = {
    LAYER_APP: "Application — Router · Commands · Dashboard · Voice · API",
    LAYER_INT: "Intelligence — Brain · LLM Adapters · Reasoning · Research",
    LAYER_LRN: "Learning — ALE · Curriculum · Self-Researcher · Evolve",
    LAYER_MEM: "Memory — VectorStore · KnowledgeDB",
    LAYER_NET: "Network — DistributedMesh · P2P",
    LAYER_SEC: "Security — SLSA · Membrane · Permissions · Guard",
    LAYER_KRN: "Kernel — Runtime · EventBus · TaskQueue · Lifecycle",
    LAYER_HAL: "HAL — Swift/iOS · TypeScript/Web · Rust/Embedded",
}


# ── ComponentRecord ────────────────────────────────────────────────────────────

@dataclass
class ComponentRecord:
    """Metadata about a component registered under a layer."""

    layer: str
    name: str
    instance: Any
    registered_at: float = field(default_factory=time.time)
    healthy: bool = True
    health_check: Optional[Callable[[], bool]] = None

    def check_health(self) -> bool:
        """Run the optional health-check callback and update ``healthy``."""
        if self.health_check is None:
            return self.healthy
        try:
            self.healthy = bool(self.health_check())
        except Exception as exc:
            log.debug("AIOSLayerRegistry: health check for %s.%s raised — %s",
                      self.layer, self.name, exc)
            self.healthy = False
        return self.healthy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "name": self.name,
            "healthy": self.healthy,
            "registered_at": self.registered_at,
            "has_health_check": self.health_check is not None,
        }


# ── AIOSLayerRegistry ──────────────────────────────────────────────────────────

class AIOSLayerRegistry:
    """
    Central registry for all NIBLIT-AIOS subsystem components.

    Components register themselves under one of the eight canonical layers.
    The registry provides:

    * ``register()``     — add a component to a layer
    * ``get()``          — retrieve a named component from a layer
    * ``health()``       — run all health checks and return a status dict
    * ``layer_summary()``— human-readable layer overview
    * ``cross_wire()``   — convenience helper to inject common subsystems
                           across layers after boot
    """

    def __init__(self) -> None:
        # layer_id → {component_name: ComponentRecord}
        self._components: Dict[str, Dict[str, ComponentRecord]] = {
            layer: {} for layer in ALL_LAYERS
        }
        self._lock = threading.Lock()
        self._created_at: float = time.time()
        log.debug("AIOSLayerRegistry initialised with %d layers", len(ALL_LAYERS))

    # ── Registration ────────────────────────────────────────────────────────

    def register(
        self,
        layer: str,
        name: str,
        instance: Any,
        *,
        health_check: Optional[Callable[[], bool]] = None,
    ) -> ComponentRecord:
        """
        Register a component under the given layer.

        Parameters
        ----------
        layer:        One of the ``LAYER_*`` constants.
        name:         Unique name within the layer (e.g. ``"security_membrane"``).
        instance:     The live component object.
        health_check: Zero-argument callable that returns ``True`` when healthy.
                      If omitted the component is assumed always healthy.

        Returns
        -------
        The created ``ComponentRecord``.
        """
        if layer not in self._components:
            raise ValueError(
                f"Unknown AIOS layer: {layer!r}. Must be one of {ALL_LAYERS}"
            )
        record = ComponentRecord(
            layer=layer,
            name=name,
            instance=instance,
            health_check=health_check,
        )
        with self._lock:
            self._components[layer][name] = record
        log.debug("AIOSLayerRegistry: registered %s/%s", layer, name)
        return record

    def get(self, layer: str, name: str) -> Optional[Any]:
        """
        Retrieve the instance of a registered component.

        Returns ``None`` if the layer or name is not registered.
        """
        with self._lock:
            layer_comps = self._components.get(layer, {})
            record = layer_comps.get(name)
        return record.instance if record is not None else None

    def list_components(self, layer: Optional[str] = None) -> List[ComponentRecord]:
        """Return all registered components, optionally filtered by layer."""
        with self._lock:
            if layer is not None:
                return list(self._components.get(layer, {}).values())
            return [
                rec
                for layer_comps in self._components.values()
                for rec in layer_comps.values()
            ]

    # ── Health ───────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """
        Run all registered health-check callbacks and return a status summary.

        Returns
        -------
        Dict with keys:
        * ``layers``  — per-layer health dict
        * ``healthy`` — ``True`` when every registered component passes its
                        health check; empty layers do not affect this flag
        * ``total_components`` — total registered component count
        """
        with self._lock:
            snapshot = {
                layer: dict(comps)
                for layer, comps in self._components.items()
            }

        result: Dict[str, Any] = {"layers": {}, "healthy": True, "total_components": 0}

        for layer_id in ALL_LAYERS:
            comps = snapshot.get(layer_id, {})
            layer_result: Dict[str, Any] = {
                "description": _LAYER_DESCRIPTIONS.get(layer_id, layer_id),
                "components": {},
                "healthy": True,
                "count": len(comps),
            }
            for name, rec in comps.items():
                ok = rec.check_health()
                layer_result["components"][name] = ok
                if not ok:
                    layer_result["healthy"] = False
            # A layer with no components is marked as "empty" but not unhealthy
            result["layers"][layer_id] = layer_result
            result["total_components"] += len(comps)

        result["healthy"] = all(
            info["healthy"] for info in result["layers"].values()
        )
        return result

    # ── Diagnostic ───────────────────────────────────────────────────────────

    def layer_summary(self) -> str:
        """Return a human-readable summary of all registered layers."""
        lines = ["NIBLIT AI OS — Layer Registry", "=" * 62]
        with self._lock:
            for layer_id in ALL_LAYERS:
                comps = self._components.get(layer_id, {})
                desc = _LAYER_DESCRIPTIONS.get(layer_id, layer_id)
                names = ", ".join(sorted(comps.keys())) or "(none)"
                lines.append(f"  [{layer_id}] {desc}")
                lines.append(f"         ↳ {names}")
        return "\n".join(lines)

    def status(self) -> Dict[str, Any]:
        """Return a compact status dict suitable for telemetry."""
        return {
            "total_layers": len(ALL_LAYERS),
            "total_components": sum(
                len(c) for c in self._components.values()
            ),
            "layer_counts": {
                layer: len(comps)
                for layer, comps in self._components.items()
            },
        }

    # ── Cross-wiring helper ───────────────────────────────────────────────────

    def cross_wire(self, aios_runtime: Any) -> None:
        """
        Convenience method: read subsystem references from an ``AIOSRuntime``
        instance and register them under the correct layers.

        This is called at the end of the AIOS boot sequence to populate the
        registry from the already-initialised subsystems.
        """
        _wire_map = [
            # (layer, name, attr_on_runtime)
            (LAYER_HAL, "hal",           "hal"),
            (LAYER_KRN, "kernel",        "kernel"),
            (LAYER_KRN, "niblit_runtime","niblit_runtime"),
            (LAYER_KRN, "scheduler",     "scheduler"),
            (LAYER_MEM, "memory",        "memory"),
            (LAYER_INT, "brain",         "brain"),
            (LAYER_LRN, "ale",           "ale"),
            (LAYER_APP, "router",        "router"),
            (LAYER_SEC, "security_hardening", "security_hardening"),
            (LAYER_SEC, "security_membrane",  "security_membrane"),
        ]
        for layer, comp_name, attr in _wire_map:
            instance = getattr(aios_runtime, attr, None)
            if instance is not None:
                try:
                    self.register(layer, comp_name, instance)
                except Exception as exc:
                    log.debug(
                        "AIOSLayerRegistry.cross_wire: could not register %s/%s — %s",
                        layer, comp_name, exc,
                    )

        # Also try to pick up NiblitCore security_membrane if available
        core = getattr(aios_runtime, "core", None)
        if core is not None:
            membrane = getattr(core, "security_membrane", None)
            if membrane is not None:
                try:
                    self.register(LAYER_SEC, "core_membrane", membrane)
                except Exception:
                    pass

        log.debug(
            "AIOSLayerRegistry.cross_wire: wired %d components",
            self.status()["total_components"],
        )


# ── Singleton ──────────────────────────────────────────────────────────────────

_registry: Optional[AIOSLayerRegistry] = None
_registry_lock = threading.Lock()


def get_aios_layer_registry() -> AIOSLayerRegistry:
    """Return the process-level AIOSLayerRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AIOSLayerRegistry()
    return _registry
