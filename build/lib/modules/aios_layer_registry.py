#!/usr/bin/env python3
"""
modules/aios_layer_registry.py — NIBLIT-AIOS 9-Layer Architecture Registry
===========================================================================
Implements the formal 9-layer unified-feedback-loop architecture for NIBLIT
AI OS Complete.  Every subsystem registers itself under one of the nine
canonical layers so the runtime has a single, observable view of the system.

The architecture is designed around **one unified feedback loop**: every
layer communicates exclusively through the Kernel EventBus, and the MSG
(Meta-Self-Governance) layer at the top provides continuous meta-cognition,
resource allocation, and evolution planning across all other layers.

Layers (top → bottom)
----------------------
+------+---------------------+----------------------------------------------+
| ID   | Name                | Responsibilities                             |
+------+---------------------+----------------------------------------------+
| MSG  | Meta-Self-Governance| SelfModel · IntentEngine · MetaEvaluator     |
|      |                     | ResourceAllocator · EvolutionPlanner         |
| APP  | Application         | Router · Commands · Dashboard · Voice · API  |
| INT  | Intelligence        | Brain · LLM Adapters · Reasoning · Research  |
| LRN  | Learning            | ALE · Curriculum · Self-Researcher · Evolve  |
| MEM  | Memory              | VectorStore · KnowledgeDB · FusedMemory      |
| NET  | Network             | DistributedMesh · P2P · SyncEngine           |
| SEC  | Security            | SLSA · Membrane · Permissions · Guard        |
| KRN  | Kernel              | EventBus · CognitiveGraphKernel · Runtime    |
| HAL  | Hardware Abstraction| Swift/iOS · TypeScript/Web · Rust/Embedded   |
+------+---------------------+----------------------------------------------+

Unified Feedback Loop
---------------------
All cross-layer calls are mediated by the Kernel EventBus
(``modules/niblit_cognitive_graph_kernel.EventBus``).  No layer calls another
layer's public API directly.  The cycle is:

    User Input
        │
       APP  ──(event)──► KRN/EventBus ──(route)──► INT
                                                      │
                                                     LRN ◄──(learn from result)
                                                      │
                                                     MEM  (persist knowledge)
                                                      │
                                              KRN/EventBus
                                                      │
                                                     INT ──(improved response)──► APP
                                                      │
                                                    loop ◄── MSG governs & adjusts

Usage
-----
    from modules.aios_layer_registry import get_aios_layer_registry, LAYER_MSG, LAYER_SEC

    registry = get_aios_layer_registry()
    registry.register(LAYER_MSG, "msg_layer", msg_layer_instance)
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

LAYER_MSG = "MSG"   # Meta-Self-Governance (top-level feedback control)
LAYER_APP = "APP"   # Application
LAYER_INT = "INT"   # Intelligence
LAYER_LRN = "LRN"   # Learning
LAYER_MEM = "MEM"   # Memory
LAYER_NET = "NET"   # Network
LAYER_SEC = "SEC"   # Security
LAYER_KRN = "KRN"   # Kernel (central EventBus backbone)
LAYER_HAL = "HAL"   # Hardware Abstraction

# Ordered top-to-bottom: MSG governs all; KRN is the backbone; HAL is the floor
ALL_LAYERS: List[str] = [
    LAYER_MSG,
    LAYER_APP,
    LAYER_INT,
    LAYER_LRN,
    LAYER_MEM,
    LAYER_NET,
    LAYER_SEC,
    LAYER_KRN,
    LAYER_HAL,
]

_LAYER_DESCRIPTIONS: Dict[str, str] = {
    LAYER_MSG: (
        "MSG — Meta-Self-Governance: SelfModel · IntentEngine · MetaEvaluator "
        "· ResourceAllocator · EvolutionPlanner  "
        "[meta_cognition/__init__.py · self_model.py · intent_engine.py "
        "· meta_evaluator.py · resource_allocator.py · evolution_planner.py "
        "· metacognition.py · meta_adapter.py · self_monitor.py "
        "· self_improvement_orchestrator.py · gap_analyzer.py · metrics_observability.py "
        "· modules/unified_self_modules.py · modules/self_healer.py "
        "· modules/self_maintenance.py · self_maintenance_full.py · healer_full.py]"
    ),
    LAYER_APP: (
        "APP — Application: Router · Commands · Dashboard · Voice · API  "
        "[niblit_router.py · niblit_core.py · niblit_identity.py · server.py "
        "· app.py · main.py · kivy_app.py · niblit_voice_full.py "
        "· niblit_dashboard.py · niblit_actions.py · niblit_io.py "
        "· niblit_tasks.py · niblit_manager.py · live_command_tester.py "
        "· run_realtime.py · run_trading_brain.py · run_diagnostics.py "
        "· modules/control_panel.py · modules/dashboard.py "
        "· modules/command_registry.py · modules/game_engine.py "
        "· modules/niblit_personality.py · modules/enterprise_utility.py "
        "· core/notification_queue.py · orchestrator.py · niblit_orchestrator.py · api/]"
    ),
    LAYER_INT: (
        "INT — Intelligence: Brain · LLM Adapters · Reasoning · Research  "
        "[niblit_brain.py · modules/hf_brain.py · modules/brain_router.py "
        "· modules/local_brain.py · modules/llm_adapter.py "
        "· modules/llm_controller.py · modules/llm_module.py "
        "· modules/anthropic_adapter.py · modules/openai_adapter.py "
        "· modules/hf_adapter.py · modules/local_llm_adapter.py "
        "· modules/github_models_client.py · modules/llm_provider_manager.py "
        "· modules/llm_architect_engine.py · modules/reasoning_engine.py "
        "· modules/concept_synthesizer.py · modules/intent_parser.py "
        "· modules/language_module.py · modules/reflect.py "
        "· modules/phased_research_engine.py · modules/researcher_engine.py "
        "· modules/multimodal_intelligence.py · modules/chat_completions.py "
        "· modules/cognition_core.py · modules/prediction_engine.py "
        "· modules/software_studier.py · modules/trading_brain.py "
        "· modules/trading_swing_v3.py · modules/position_sizer.py "
        "· modules/idea_generator.py · modules/code_generator.py "
        "· modules/code_compiler.py · modules/code_error_fixer.py "
        "· modules/code_quality_checker.py · modules/agentic_workflows.py "
        "· modules/github_deep_research.py · modules/github_code_search.py "
        "· modules/market_researcher.py · modules/pypi_search.py "
        "· modules/stackoverflow_search.py · modules/searchcode_search.py "
        "· modules/topic_constructor.py · modules/dynamic_topic_manager.py "
        "· modules/background_topic_refresh.py · modules/build_scanner.py "
        "· modules/global_code_intelligence/ · modules/ai_dev_lab/ "
        "· SelfResearcher.py · agents/]"
    ),
    LAYER_LRN: (
        "LRN — Learning: ALE · Curriculum · Self-Researcher · Evolve  "
        "[modules/autonomous_learning_engine.py · modules/evolve.py "
        "· modules/graded_curriculum.py · modules/self_teacher.py "
        "· modules/self_researcher.py · modules/self_implementer.py "
        "· modules/self_idea_generator.py · modules/self_idea_implementation.py "
        "· modules/collaborative_learner.py · modules/parallel_learner.py "
        "· modules/parallel_learning_engine.py · modules/adaptive_learning.py "
        "· modules/llm_training_agent.py · modules/tokenizer_trainer.py "
        "· modules/reward_model.py · modules/knowledge_comprehension.py "
        "· modules/ale_checkpoint.py · modules/improvement_integrator.py "
        "· modules/universe_registry.py · modules/evolution_queue.py "
        "· modules/evolve_adapter.py · modules/ale_adapter.py "
        "· modules/knowledge_adapter.py · modules/civilization_adapter.py "
        "· modules/niblit_defensive_evolution_loop.py · modules/rl_trading_policy.py "
        "· modules/trading_study.py · modules/academic_study_module.py "
        "· modules/goal_engine.py · modules/niblit_kernel_v3.py "
        "· niblit_learning.py · niblit_hf.py · trainer_full.py "
        "· niblit_full_upgrade_pipeline.py · collector_full.py · generator_full.py]"
    ),
    LAYER_MEM: (
        "MEM — Memory: VectorStore · KnowledgeDB · FusedMemory  "
        "[niblit_memory/ · modules/memory_weighting.py "
        "· modules/memory_graph.py · modules/memory_optimizer.py "
        "· modules/fused_memory.py · modules/fused_memory_primary.py "
        "· modules/vector_store.py · modules/hybrid_qdrant_manager.py "
        "· modules/qdrant_tools.py · modules/knowledge_db.py "
        "· modules/knowledge_engine/ · modules/knowledge_digest.py "
        "· modules/knowledge_filter.py · modules/knowledge_synthesizer.py "
        "· modules/tiered_knowledge_system.py · modules/graph_rag.py "
        "· modules/graph_rag_bridge.py · modules/rag_pipeline.py "
        "· modules/ingestion.py · modules/llm_chat_memory.py "
        "· modules/multi_level_caching.py · modules/storage.py "
        "· modules/db.py · niblit_sqlite_db.py · niblit_memory.py "
        "· modules/sqlite_researcher.py]"
    ),
    LAYER_NET: (
        "NET — Network: DistributedMesh · P2P · SyncEngine · LEAN Bridge  "
        "[modules/sync_engine.py · modules/autonomous_network.py "
        "· modules/device_mesh.py · modules/internet_manager.py "
        "· modules/connection_pooling.py · modules/realtime_stream.py "
        "· modules/github_sync.py · modules/rate_limiting.py "
        "· modules/lean_algo_manager.py · modules/market_data_providers.py "
        "· niblit_net.py · niblit_network_full.py "
        "· distributed_niblit/ · modules/mcp_server.py "
        "· modules/event_sourcing.py · modules/deployment_bridge.py "
        "· modules/lean_deploy_engine.py · modules/lean_engine.py "
        "· modules/monitoring_alerting.py · modules/analytics.py "
        "· niblit-lean-algos/niblit_bridge/]"
    ),
    LAYER_SEC: (
        "SEC — Security: SLSA · Membrane · Permissions · Guard  "
        "[modules/niblit_cyber_membrane.py · modules/security_hardening.py "
        "· modules/security_membrane.py · modules/slice_guard.py "
        "· modules/slsa_generator.py · modules/slsa_manager.py "
        "· modules/permission_manager.py · modules/antifraud.py "
        "· modules/niblit_defensive_evolution_loop.py "
        "· modules/counter_active_membrane.py · niblit_guard.py "
        "· slsa_generator_full.py · Slsa_generator_full.py "
        "· membrane_full.py · SECURITY.md]"
    ),
    LAYER_KRN: (
        "KRN — Kernel (Central EventBus Backbone): "
        "CognitiveGraphKernel · EventBus · TaskQueue · Lifecycle  "
        "[modules/niblit_cognitive_graph_kernel.py · modules/niblit_core_kernel.py "
        "· modules/niblit_core_kernel_v2.py · modules/niblit_kernel_v3.py "
        "· modules/niblit_kernel.py · modules/niblit_runtime.py "
        "· modules/aios_layer_registry.py · modules/layered_architecture.py "
        "· modules/plugin_architecture.py · modules/orphan_imports.py "
        "· modules/batch_processing.py · modules/parameter_manager.py "
        "· modules/live_updater.py · modules/builds_integrator.py "
        "· core/event_bus.py · core/task_queue.py · core/runtime_manager.py "
        "· core/orchestrator.py · core/notification_queue.py "
        "· modules/kernel_integration.py · modules/bios.py "
        "· modules/bios_integration.py · modules/bootloader.py "
        "· modules/firmware.py · modules/platform_bootstrap.py "
        "· modules/module_autonomy.py · modules/circuit_breaker.py "
        "· modules/resilience_wrapper.py · modules/dependency_injection.py "
        "· modules/safe_loader.py · modules/background_jobs.py "
        "· modules/async_first.py · modules/structured_logging.py "
        "· aios_runtime.py · aios_scheduler.py · lifecycle_engine.py "
        "· module_loader.py · workspace_init.py · orchestrator.py "
        "· niblit_core.py · niblit_core_full.py · niblit_core_refactor_full.py "
        "· config.py · modules/structural_awareness.py]"
    ),
    LAYER_HAL: (
        "HAL — Hardware Abstraction: Swift/iOS · TypeScript/Web · Rust/Embedded  "
        "[aios_hal.py · modules/device_control.py · modules/device_manager.py "
        "· modules/device_mesh.py · modules/hardware_scanner.py "
        "· modules/env_adapter.py · modules/env_state.py "
        "· modules/os_integration.py · modules/terminal_tools.py "
        "· modules/binary_tools.py · modules/termux_wakelock.py "
        "· modules/filesystem_manager.py · modules/universal_file_manager.py "
        "· modules/proot_env.py · modules/apk_bootstrap.py "
        "· niblit_env.py · niblit_sensors_full.py "
        "· Package.swift · nodes/ · builds/ · buildozer.spec]"
    ),
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
        registry from the already-initialised subsystems.  All layers are wired
        through the Kernel EventBus so the unified feedback loop is active.
        """
        _wire_map = [
            # (layer, name, attr_on_runtime)
            # MSG — top-level meta-cognition governs all other layers
            (LAYER_MSG, "msg_layer",             "msg_layer"),
            (LAYER_MSG, "unified_self_modules",  "unified_self_modules"),
            # APP — user-facing interfaces
            (LAYER_APP, "router",             "router"),
            (LAYER_APP, "core",               "core"),
            # INT — intelligence & reasoning
            (LAYER_INT, "brain",              "brain"),
            # LRN — learning & self-improvement
            (LAYER_LRN, "ale",                "ale"),
            # MEM — persistent memory
            (LAYER_MEM, "memory",             "memory"),
            # NET — network & external bridges (includes LEAN algo bridge)
            (LAYER_NET, "sync_engine",        "sync_engine"),
            (LAYER_NET, "lean_algo_manager",  "lean_algo_manager"),
            # KRN — kernel backbone (EventBus lives here)
            (LAYER_KRN, "kernel",             "kernel"),
            (LAYER_KRN, "niblit_runtime",     "niblit_runtime"),
            (LAYER_KRN, "scheduler",          "scheduler"),
            # HAL — hardware abstraction
            (LAYER_HAL, "hal",                "hal"),
            # SEC — security layer
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

        # Also try to pick up NiblitCore cyber_membrane and cognitive_graph_kernel
        core = getattr(aios_runtime, "core", None)
        if core is not None:
            membrane = getattr(core, "cyber_membrane", None) or getattr(
                core, "security_membrane", None
            )
            if membrane is not None:
                try:
                    self.register(LAYER_SEC, "core_membrane", membrane)
                except Exception:
                    pass
            cgk = getattr(core, "cognitive_graph_kernel", None)
            if cgk is not None:
                try:
                    self.register(LAYER_KRN, "cognitive_graph_kernel", cgk)
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


if __name__ == "__main__":
    print('Running aios_layer_registry.py')
