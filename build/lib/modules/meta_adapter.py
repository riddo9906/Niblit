#!/usr/bin/env python3
"""
modules/meta_adapter.py — Diagnostics / Nibblebot / Meta Adapter
=================================================================
Reads outputs from Nibblebot (repo improvement scanner),
``run_diagnostics.py``, logs, and test failures, and converts them into
:class:`~modules.evolution_queue.EvolutionItem`s in the
:class:`~modules.evolution_queue.EvolutionQueue`.

Called by ``CognitiveGraphKernel.evolve_self()`` during the FortressCycle
to surface actionable improvement proposals without requiring any
background daemon.

This engine is orchestrated by CognitiveGraphKernel via adapters.
Do not start a standalone infinite loop here.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_AUDIT_REPORT_PATH = os.environ.get("NIBLIT_AUDIT_REPORT", "niblit_audit_report.json")
_SELF_HEAL_LOG_PATH = os.environ.get("NIBLIT_SELF_HEAL_LOG", "niblit_self_heal.log")
_NIBLIT_STATE_PATH = os.environ.get("NIBLIT_STATE_PATH", "niblit_state.json")


def collect_evolution_items(
    max_items: int = 5,
    include_audit: bool = True,
    include_self_heal: bool = True,
    include_diagnostics: bool = True,
    include_nibblebot: bool = True,
) -> List[Dict[str, Any]]:
    """
    Collect improvement signals from all meta sources and return a list
    of dicts suitable for ``EvolutionQueue.enqueue_item()``.

    The caller (EvolutionGraphRuntime / CognitiveGraphKernel) decides
    which items to actually enqueue.
    """
    items: List[Dict[str, Any]] = []

    if include_audit:
        items.extend(_from_audit_report(max_items))
    if include_self_heal:
        items.extend(_from_self_heal_log(max_items))
    if include_diagnostics:
        items.extend(_from_diagnostics(max_items))
    if include_nibblebot:
        items.extend(_from_nibblebot(max_items))

    return items[:max_items]


def push_to_evolution_queue(
    max_items: int = 5,
    deduplicate: bool = True,
) -> int:
    """
    Collect signals, convert to EvolutionItems, and push to the
    EvolutionQueue.

    Returns the number of items actually enqueued.
    """
    from modules.evolution_queue import get_evolution_queue
    queue = get_evolution_queue()

    # Build a set of existing descriptions to deduplicate
    existing_descriptions: set = set()
    if deduplicate:
        existing_descriptions = {
            i.description[:80] for i in queue.list_all(limit=200)
        }

    candidates = collect_evolution_items(max_items=max_items * 3)
    enqueued = 0
    for c in candidates:
        if enqueued >= max_items:
            break
        desc = c.get("description", "")[:80]
        if deduplicate and desc in existing_descriptions:
            continue
        queue.enqueue_item(
            source=c.get("source", "DIAGNOSTICS"),  # type: ignore[arg-type]
            description=c.get("description", "improvement"),
            target_modules=c.get("target_modules", []),
            risk_class=c.get("risk_class", "LOW"),  # type: ignore[arg-type]
            priority=c.get("priority", 1.0),
            metadata=c.get("metadata", {}),
        )
        existing_descriptions.add(desc)
        enqueued += 1

    return enqueued


# ── Signal collectors ─────────────────────────────────────────────────────────

def _from_audit_report(limit: int) -> List[Dict[str, Any]]:
    path = Path(_AUDIT_REPORT_PATH)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        issues = data.get("issues", data.get("errors", data.get("findings", [])))
        if not isinstance(issues, list):
            return []
        result = []
        for issue in issues[:limit]:
            desc = str(issue.get("description", issue.get("message", str(issue))))[:300]
            module = issue.get("file", issue.get("module", ""))
            result.append({
                "source": "DIAGNOSTICS",
                "description": f"[audit] {desc}",
                "target_modules": [module] if module else [],
                "risk_class": "LOW",
                "priority": 1.5,
                "metadata": {"origin": "audit_report"},
            })
        return result
    except Exception:  # noqa: BLE001
        return []


def _from_self_heal_log(limit: int) -> List[Dict[str, Any]]:
    path = Path(_SELF_HEAL_LOG_PATH)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        result = []
        for line in reversed(lines[-200:]):
            if "ERROR" in line or "FAIL" in line or "heal" in line.lower():
                result.append({
                    "source": "DIAGNOSTICS",
                    "description": f"[self_heal] {line.strip()[:250]}",
                    "target_modules": [],
                    "risk_class": "LOW",
                    "priority": 1.2,
                    "metadata": {"origin": "self_heal_log"},
                })
            if len(result) >= limit:
                break
        return result
    except Exception:  # noqa: BLE001
        return []


def _from_diagnostics(limit: int) -> List[Dict[str, Any]]:
    """Try to import run_diagnostics and read its latest output."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_diagnostics", Path("run_diagnostics.py")
        )
        if spec is None:
            return []
        mod = importlib.util.module_from_spec(spec)
        # We do NOT exec the module to avoid running side effects;
        # just check for a cached results file.
    except Exception:  # noqa: BLE001
        pass

    # Read niblit_state.json for degraded services
    path = Path(_NIBLIT_STATE_PATH)
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        degraded = state.get("degraded", [])
        if not isinstance(degraded, list):
            return []
        return [
            {
                "source": "DIAGNOSTICS",
                "description": f"[state] Degraded service: {svc}",
                "target_modules": [str(svc)],
                "risk_class": "LOW",
                "priority": 2.0,
                "metadata": {"origin": "niblit_state"},
            }
            for svc in degraded[:limit]
        ]
    except Exception:  # noqa: BLE001
        return []


def _from_nibblebot(limit: int) -> List[Dict[str, Any]]:
    """Try to collect improvement proposals from Nibblebot scanner."""
    try:
        # Nibblebot may be in different locations depending on install
        scanner = None
        for mod_path in ("modules.nibblebot", "nibblebot", "tools.nibblebot"):
            try:
                import importlib
                m = importlib.import_module(mod_path)
                scanner = getattr(m, "NibbleBot", getattr(m, "Nibblebot", None))
                if scanner:
                    break
            except ImportError:
                continue

        if scanner is None:
            return []

        nb = scanner()
        if hasattr(nb, "scan"):
            findings = nb.scan() or []
        elif hasattr(nb, "get_proposals"):
            findings = nb.get_proposals() or []
        else:
            return []

        result = []
        for f in findings[:limit]:
            desc = str(f.get("description", f.get("message", str(f))))[:300]
            result.append({
                "source": "NIBBLEBOT",
                "description": f"[nibblebot] {desc}",
                "target_modules": f.get("files", f.get("modules", [])),
                "risk_class": f.get("risk", "LOW"),
                "priority": float(f.get("priority", 1.0)),
                "metadata": {"origin": "nibblebot"},
            })
        return result
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    print('Running meta_adapter.py')
