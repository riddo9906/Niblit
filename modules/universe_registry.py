#!/usr/bin/env python3
"""
modules/universe_registry.py — Niblit Universe Registry
=========================================================
A lightweight registry of all "worlds" (universes) that the
:class:`~modules.niblit_cognitive_graph_kernel.CognitiveGraphKernel`
manages as part of its FortressCycle.

Each universe represents a distinct operational domain with its own
goals, state locations, and priority weight.  The kernel's
``begin_cycle()`` loads the registry and selects universes to work on;
``execute_cycle()`` dispatches tasks per-universe through the
relevant adapters.

Universe kinds
--------------
``TRADING``              — Autonomous Trading Brain + LEAN + Kelly
``RESEARCH``             — Phased research / SelfResearcher / Graph RAG
``REPO_SELF_IMPROVEMENT``— Code self-improvement via Nibblebot + EvolveEngine
``CIVILIZATION``         — STACA / DPAIS civilization subsystems
``INFRA``                — Infrastructure / diagnostics / health

Singleton
---------
``get_universe_registry()`` returns the process-wide
:class:`UniverseRegistry` instance.

Configuration
-------------
``NIBLIT_UNIVERSE_ENABLED_IDS`` — comma-separated list of universe IDs to
  activate (default: all).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

log = logging.getLogger(__name__)

UniverseKind = Literal[
    "TRADING", "RESEARCH", "REPO_SELF_IMPROVEMENT", "CIVILIZATION", "INFRA"
]

_ENABLED_IDS_ENV = os.environ.get("NIBLIT_UNIVERSE_ENABLED_IDS", "")


@dataclass
class Universe:
    """A single managed universe within the FortressCycle."""
    id: str
    kind: UniverseKind
    description: str
    state_locations: Dict[str, str] = field(default_factory=dict)
    goals: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_touched: float = field(default_factory=time.time)


# ── Built-in universe definitions ─────────────────────────────────────────────

def _default_universes() -> List[Universe]:
    return [
        Universe(
            id="trading_btc",
            kind="TRADING",
            description="Autonomous BTC/USDT trading via TradingBrain + LEAN + Kelly sizing.",
            state_locations={
                "module": "modules/trading_brain.py",
                "runner": "run_trading_brain.py",
                "config": ".env",
            },
            goals={
                "target_metric": "pnl_cumulative",
                "min_sharpe": 1.0,
                "max_drawdown_pct": 15.0,
            },
            priority=8,
        ),
        Universe(
            id="trading_eth",
            kind="TRADING",
            description="Autonomous ETH/USDT trading universe (secondary pair).",
            state_locations={
                "module": "modules/trading_brain.py",
                "symbol_env": "TRADING_SYMBOL",
            },
            goals={"target_metric": "pnl_cumulative"},
            priority=6,
        ),
        Universe(
            id="research_general",
            kind="RESEARCH",
            description="Phased research / SelfResearcher / Graph RAG knowledge growth.",
            state_locations={
                "module": "modules/autonomous_learning_engine.py",
                "researcher": "SelfResearcher.py",
                "graph_rag": "modules/graph_rag.py",
                "slsa": "modules/slsa_generator.py",
            },
            goals={
                "target_metric": "kb_facts_added",
                "quality_floor": 0.7,
            },
            priority=7,
        ),
        Universe(
            id="repo_self_improvement",
            kind="REPO_SELF_IMPROVEMENT",
            description="Code self-improvement via Nibblebot scanner + EvolveEngine + CodeErrorFixer.",
            state_locations={
                "evolve_module": "modules/evolve.py",
                "diagnostics": "run_diagnostics.py",
                "audit_log": "niblit_audit_report.json",
                "self_heal_log": "niblit_self_heal.log",
            },
            goals={
                "target_metric": "test_pass_rate",
                "min_test_pass_rate": 0.95,
            },
            priority=9,
        ),
        Universe(
            id="civilization_core",
            kind="CIVILIZATION",
            description=(
                "STACA / DPAIS civilization framework — CivilizationController "
                "managing agent population, collaboration, evolution, governance."
            ),
            state_locations={
                "controller": "civilization/civilization_core/civilization_controller.py",
                "agent_population": "civilization/agent_population/",
                "collaboration_network": "civilization/collaboration_network/",
                "evolution_engine": "civilization/evolution_engine/",
                "governance": "civilization/governance/",
            },
            goals={
                "target_metric": "agents_active",
                "min_research_quality": 0.6,
                "max_errors_per_cycle": 5,
            },
            priority=7,
        ),
        Universe(
            id="civilization_knowledge",
            kind="CIVILIZATION",
            description="Civilization knowledge_ecosystem — VectorMemory, GraphMemory, EmbeddingService.",
            state_locations={
                "module": "civilization/knowledge_ecosystem/",
            },
            goals={"target_metric": "knowledge_entries"},
            priority=5,
        ),
        Universe(
            id="civilization_training",
            kind="CIVILIZATION",
            description="Civilization training_arena — competitive agent training episodes.",
            state_locations={
                "module": "civilization/training_arena/",
            },
            goals={"target_metric": "episodes_completed"},
            priority=4,
        ),
        Universe(
            id="civilization_experiments",
            kind="CIVILIZATION",
            description="Civilization experiment_labs — sandboxed hypothesis testing.",
            state_locations={
                "module": "civilization/experiment_labs/",
            },
            goals={"target_metric": "experiments_run"},
            priority=3,
        ),
        Universe(
            id="infra_diagnostics",
            kind="INFRA",
            description="System diagnostics, health checks, log analysis, audit.",
            state_locations={
                "diagnostics": "run_diagnostics.py",
                "niblit_state": "niblit_state.json",
                "events": "events.jsonl",
            },
            goals={"target_metric": "error_count"},
            priority=6,
        ),
    ]


# ── Registry class ─────────────────────────────────────────────────────────────

class UniverseRegistry:
    """
    In-process registry of all managed universes.

    Thread-safe.  Universes can be registered at runtime; built-in
    universes are seeded automatically on first access.
    """

    def __init__(self) -> None:
        self._universes: Dict[str, Universe] = {}
        self._lock = threading.Lock()
        self._seed_defaults()

        # Apply NIBLIT_UNIVERSE_ENABLED_IDS filter (empty = all enabled)
        if _ENABLED_IDS_ENV.strip():
            enabled = {uid.strip() for uid in _ENABLED_IDS_ENV.split(",")}
            with self._lock:
                for u in self._universes.values():
                    u.enabled = u.id in enabled

    def _seed_defaults(self) -> None:
        for u in _default_universes():
            self._universes[u.id] = u

    # ── API ───────────────────────────────────────────────────────────────────

    def register(self, universe: Universe) -> None:
        """Register or replace a universe."""
        with self._lock:
            self._universes[universe.id] = universe
        log.debug("[UniverseRegistry] registered universe %s (%s)", universe.id, universe.kind)

    def list_universes(self, enabled_only: bool = True) -> List[Universe]:
        """Return all (or only enabled) universes sorted by descending priority."""
        with self._lock:
            items = list(self._universes.values())
        if enabled_only:
            items = [u for u in items if u.enabled]
        return sorted(items, key=lambda u: u.priority, reverse=True)

    def get_universe(self, uid: str) -> Optional[Universe]:
        """Return a specific universe by ID, or ``None``."""
        with self._lock:
            return self._universes.get(uid)

    def update_universe(self, uid: str, **kwargs: Any) -> bool:
        """Update fields of an existing universe.  Returns True if found."""
        with self._lock:
            u = self._universes.get(uid)
            if u is None:
                return False
            for k, v in kwargs.items():
                if hasattr(u, k):
                    setattr(u, k, v)
        return True

    def touch(self, uid: str) -> None:
        """Record that a universe was touched this cycle."""
        with self._lock:
            u = self._universes.get(uid)
            if u is not None:
                u.last_touched = time.time()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            kinds: Dict[str, int] = {}
            for u in self._universes.values():
                kinds[u.kind] = kinds.get(u.kind, 0) + 1
            return {
                "total": len(self._universes),
                "enabled": sum(1 for u in self._universes.values() if u.enabled),
                "by_kind": kinds,
            }

    def to_dict(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": u.id,
                    "kind": u.kind,
                    "description": u.description,
                    "priority": u.priority,
                    "enabled": u.enabled,
                    "goals": u.goals,
                    "last_touched": u.last_touched,
                }
                for u in sorted(self._universes.values(), key=lambda x: x.priority, reverse=True)
            ]


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry_instance: Optional[UniverseRegistry] = None
_registry_lock = threading.Lock()


def get_universe_registry() -> UniverseRegistry:
    """Return the process-wide :class:`UniverseRegistry` singleton."""
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = UniverseRegistry()
    return _registry_instance
