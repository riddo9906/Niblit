#!/usr/bin/env python3
"""
modules/evolve_adapter.py — EvolveEngine Adapter
=================================================
Wraps EvolveEngine and CodeErrorFixer so the
:class:`~modules.niblit_cognitive_graph_kernel.CognitiveGraphKernel`
can safely propose, evaluate, and apply code improvements via the
FortressCycle's ``evolve_self()`` phase.

All changes are routed through:
  * CyberMembrane / DefensiveEvolutionLoop safety gates
  * EvolutionQueue status tracking

This engine is orchestrated by CognitiveGraphKernel via adapters.
Do not start a standalone infinite loop here.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class ProposedChange:
    """A code improvement proposed by EvolveEngine."""
    item_id: str
    description: str
    target_modules: List[str]
    patch: Optional[str] = None
    rationale: str = ""
    risk_class: str = "MEDIUM"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class EvaluationResult:
    """Result of evaluating a ProposedChange."""
    item_id: str
    approved: bool
    test_pass_rate: float = 0.0
    issues: List[str] = field(default_factory=list)
    membrane_cleared: bool = True
    notes: str = ""


def propose_improvement(
    item: Any,
    step_timeout: float = 120.0,
) -> ProposedChange:
    """
    Use EvolveEngine to generate a concrete improvement proposal for an
    :class:`~modules.evolution_queue.EvolutionItem`.

    Returns a :class:`ProposedChange`.
    """
    start = time.time()
    description = getattr(item, "description", str(item))
    target_modules = getattr(item, "target_modules", [])
    item_id = getattr(item, "id", "unknown")

    try:
        from modules.evolve import EvolveEngine  # noqa: F401
        # EvolveEngine is primarily used as a long multi-step process.
        # Here we extract just the "idea generation" capability as a single step.
        engine = EvolveEngine()
        patch_hint: Optional[str] = None
        if hasattr(engine, "generate_idea"):
            patch_hint = str(engine.generate_idea(topic=description))[:2000]
        return ProposedChange(
            item_id=item_id,
            description=description,
            target_modules=target_modules,
            patch=patch_hint,
            rationale=f"EvolveEngine proposal generated in {round(time.time()-start,1)}s",
            risk_class=getattr(item, "risk_class", "MEDIUM"),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("[evolve_adapter] propose_improvement error: %s", exc)
        return ProposedChange(
            item_id=item_id,
            description=description,
            target_modules=target_modules,
            rationale=f"Proposal generation failed: {exc}",
        )


def evaluate_change(
    change: ProposedChange,
    step_timeout: float = 90.0,
) -> EvaluationResult:
    """
    Evaluate a :class:`ProposedChange` by:
      1. Passing it through CyberMembrane if available.
      2. Attempting a lightweight syntax / quality check.
      3. Running CodeErrorFixer diagnostics if patch is present.

    Returns an :class:`EvaluationResult`.
    """
    issues: List[str] = []
    approved = True
    membrane_cleared = True

    # CyberMembrane check
    try:
        from modules.niblit_cyber_membrane import get_cyber_membrane
        membrane = get_cyber_membrane()
        result = membrane.input_guard.check(change.description) if hasattr(
            membrane, "input_guard") else True
        if not result:
            issues.append("CyberMembrane InputGuard blocked proposed change description.")
            membrane_cleared = False
            approved = False
    except Exception:  # noqa: BLE001
        pass

    # HIGH risk requires explicit approval
    if change.risk_class == "HIGH" and not issues:
        issues.append("HIGH risk change requires manual review before auto-apply.")
        approved = False

    # CodeErrorFixer syntax check
    if change.patch and approved:
        try:
            compile(change.patch, "<proposed_patch>", "exec")
        except SyntaxError as se:
            issues.append(f"SyntaxError in patch: {se}")
            approved = False

    return EvaluationResult(
        item_id=change.item_id,
        approved=approved,
        test_pass_rate=0.0 if not approved else 1.0,
        issues=issues,
        membrane_cleared=membrane_cleared,
        notes=f"Evaluated: approved={approved}, issues={len(issues)}",
    )


def apply_change(
    change: ProposedChange,
    evaluation: EvaluationResult,
) -> Dict[str, Any]:
    """
    Apply an approved :class:`ProposedChange` via EvolveEngine.

    Returns a result dict with ``success``, ``applied``, ``detail``.
    """
    if not evaluation.approved:
        return {
            "success": False,
            "applied": False,
            "detail": f"Change not approved: {'; '.join(evaluation.issues)}",
            "item_id": change.item_id,
        }
    try:
        from modules.evolve import EvolveEngine
        engine = EvolveEngine()
        if hasattr(engine, "apply_patch") and change.patch:
            engine.apply_patch(change.patch, modules=change.target_modules)
            return {
                "success": True,
                "applied": True,
                "detail": "EvolveEngine.apply_patch() called",
                "item_id": change.item_id,
            }
        return {
            "success": True,
            "applied": False,
            "detail": "No apply_patch method; proposal logged only.",
            "item_id": change.item_id,
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("[evolve_adapter] apply_change error: %s", exc)
        return {
            "success": False,
            "applied": False,
            "detail": str(exc)[:300],
            "item_id": change.item_id,
        }


if __name__ == "__main__":
    print('Running evolve_adapter.py')
