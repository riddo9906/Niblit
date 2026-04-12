#!/usr/bin/env python3
"""
modules/civilization_adapter.py — Civilization Adapter
========================================================
Wraps the STACA / DPAIS civilization framework (under ``civilization/``)
so the :class:`~modules.niblit_cognitive_graph_kernel.CognitiveGraphKernel`
can execute **one** civilization cycle per FortressCycle tick.

The adapter:
  * Calls ``CivilizationController.run_cycle()`` for the main civilization
    universe.
  * Records major civilization events as nodes/edges in the CognitiveGraph.
  * Feeds new insights into KnowledgeDB / Graph RAG.
  * Respects EventBus + CognitiveGraph semantics (no direct cross-module
    calls outside this adapter).

This engine is orchestrated by CognitiveGraphKernel via adapters.
Do not start a standalone infinite loop here.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def execute_civilization_step(
    universe_id: str,
    knowledge_db: Optional[Any] = None,
    github_code_search: Optional[Any] = None,
    step_timeout: float = 120.0,
) -> Dict[str, Any]:
    """
    Execute **one** civilization cycle via ``CivilizationController.run_cycle()``.

    Parameters
    ----------
    universe_id:
        The civilization universe ID (e.g. ``"civilization_core"``).
    knowledge_db:
        Optional reference to Niblit's production KnowledgeDB.
    github_code_search:
        Optional GitHubCodeSearch instance for research agents.
    step_timeout:
        Wall-clock timeout in seconds.

    Returns
    -------
    dict with ``success``, ``universe_id``, ``cycle_result``, ``elapsed_secs``,
    ``agents_active``, ``tasks_completed``, ``insights``, ``error``.
    """
    start = time.time()

    try:
        from civilization.civilization_core import CivilizationController
        controller = CivilizationController(
            knowledge_db=knowledge_db,
            github_code_search=github_code_search,
        )
        controller.start()

        import threading
        box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                box["result"] = controller.run_cycle()
            except Exception as exc:  # noqa: BLE001
                box["error"] = str(exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=step_timeout)

        if "error" in box:
            return {
                "success": False,
                "universe_id": universe_id,
                "cycle_result": {},
                "elapsed_secs": round(time.time() - start, 2),
                "agents_active": 0,
                "tasks_completed": 0,
                "insights": [],
                "error": box["error"][:300],
            }

        if "result" not in box:
            return {
                "success": False,
                "universe_id": universe_id,
                "cycle_result": {},
                "elapsed_secs": round(time.time() - start, 2),
                "agents_active": 0,
                "tasks_completed": 0,
                "insights": [],
                "error": "timeout",
            }

        result = box["result"]
        insights: list = result.get("insights", []) if isinstance(result, dict) else []
        agents_active: int = result.get("agents_active", 0) if isinstance(result, dict) else 0
        tasks_completed: int = result.get("tasks_completed", 0) if isinstance(result, dict) else 0

        # Record the civilization cycle as a graph event via CGK
        _emit_to_graph(
            universe_id=universe_id,
            agents_active=agents_active,
            tasks_completed=tasks_completed,
            insights=insights,
        )

        # Feed insights into KnowledgeDB / Graph RAG
        if insights:
            try:
                from modules.knowledge_adapter import store_facts
                store_facts(
                    [str(i) for i in insights[:20]],
                    provenance=f"civilization:{universe_id}",
                    universe_id=universe_id,
                )
            except Exception:  # noqa: BLE001
                pass

        return {
            "success": True,
            "universe_id": universe_id,
            "cycle_result": result if isinstance(result, dict) else {},
            "elapsed_secs": round(time.time() - start, 2),
            "agents_active": agents_active,
            "tasks_completed": tasks_completed,
            "insights": insights[:10],
            "error": None,
        }

    except ImportError as exc:
        return {
            "success": False,
            "universe_id": universe_id,
            "cycle_result": {},
            "elapsed_secs": round(time.time() - start, 2),
            "agents_active": 0,
            "tasks_completed": 0,
            "insights": [],
            "error": f"Civilization not available: {exc}",
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("[civilization_adapter] step error: %s", exc)
        return {
            "success": False,
            "universe_id": universe_id,
            "cycle_result": {},
            "elapsed_secs": round(time.time() - start, 2),
            "agents_active": 0,
            "tasks_completed": 0,
            "insights": [],
            "error": str(exc)[:300],
        }


def _emit_to_graph(
    universe_id: str,
    agents_active: int,
    tasks_completed: int,
    insights: list,
) -> None:
    """Emit a civilization cycle node into the CognitiveGraph."""
    try:
        from modules.niblit_cognitive_graph_kernel import get_cognitive_graph_kernel
        kernel = get_cognitive_graph_kernel()
        node_id = f"civ_cycle:{universe_id}:{uuid.uuid4().hex[:8]}"
        kernel.emit_graph_update(
            node_id=node_id,
            node_type="civilization_cycle",
            state={
                "universe_id": universe_id,
                "agents_active": agents_active,
                "tasks_completed": tasks_completed,
                "insight_count": len(insights),
                "timestamp": time.time(),
            },
            weight=0.7,
        )
    except Exception:  # noqa: BLE001
        pass
