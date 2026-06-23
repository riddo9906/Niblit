#!/usr/bin/env python3
"""
modules/constitutional_layer.py — Phase Ω Constitutional Layer

The **supreme decision authority** for Niblit.

Governance logic previously existed piecemeal across:
strategic_planner, governance_evolution_engine, stability_controller,
system_interface_layer, objective_engine, intent_anchor_engine,
context_guard, temporal_coherence, causal_strategy_engine.

This module unifies those constraints into a single authoritative
**constitutional contract** that every high-impact execution path must pass.

Architecture::

    Constitution (immutable laws)
         │
         ▼
    Governance layer (adaptive rules)
         │
         ▼
    Strategic Planning
         │
         ▼
    Evolution / Execution
         │
         ▼
    Tools / Forecasts / Responses

Constitutional Laws (immutable)
--------------------------------
LAW_1  preserve_system_integrity       — never degrade core stability
LAW_2  objective_alignment_priority    — alignment outranks exploration
LAW_3  no_short_term_stability_trade   — stable > gain under pressure
LAW_4  constrain_low_confidence_autonomy — act conservatively when uncertain
LAW_5  external_systems_cannot_override — resonance cannot violate objectives
LAW_6  temporal_incoherence_halts_exec — coherence is a prerequisite
LAW_7  safety_overrides_efficiency     — governance beats speed

Validation
----------
Call ``validate(action, context)`` before any high-impact action.
Returns a :class:`ConstitutionalVerdict`::

    allowed       : bool
    violated_laws : list[str]
    authority     : str  — which layer blocked/allowed
    reason        : str

Configuration (env vars)
------------------------
    NIBLIT_CL_ENABLED         — "0" to disable (default 1)
    NIBLIT_CL_STRICT          — "0" for permissive mode (default 1 = strict)

Usage::

    from modules.constitutional_layer import get_constitutional_layer

    cl = get_constitutional_layer()
    verdict = cl.validate(action="execute_trade", context={
        "confidence": 0.3,
        "stability_score": 0.5,
        "governance_approved": False,
    })
    if not verdict.allowed:
        print(verdict.reason)
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_CL_ENABLED", "1").strip() not in ("0", "false")
_STRICT: bool = os.getenv("NIBLIT_CL_STRICT", "1").strip() not in ("0", "false")

# ── Constitutional Law constants ───────────────────────────────────────────────
LAW_PRESERVE_INTEGRITY     = "law_1_preserve_system_integrity"
LAW_OBJECTIVE_ALIGNMENT    = "law_2_objective_alignment_priority"
LAW_NO_STABILITY_TRADE     = "law_3_no_short_term_stability_sacrifice"
LAW_CONSTRAIN_UNCERTAINTY  = "law_4_constrain_low_confidence_autonomy"
LAW_EXTERNAL_NO_OVERRIDE   = "law_5_external_systems_cannot_override_objectives"
LAW_TEMPORAL_COHERENCE     = "law_6_temporal_incoherence_halts_execution"
LAW_SAFETY_FIRST           = "law_7_safety_overrides_efficiency"

ALL_LAWS = [
    LAW_PRESERVE_INTEGRITY,
    LAW_OBJECTIVE_ALIGNMENT,
    LAW_NO_STABILITY_TRADE,
    LAW_CONSTRAIN_UNCERTAINTY,
    LAW_EXTERNAL_NO_OVERRIDE,
    LAW_TEMPORAL_COHERENCE,
    LAW_SAFETY_FIRST,
]

# Authority hierarchy (higher index = lower authority)
AUTHORITY_CONSTITUTION  = "constitution"
AUTHORITY_GOVERNANCE    = "governance"
AUTHORITY_PLANNING      = "planning"
AUTHORITY_EVOLUTION     = "evolution"
AUTHORITY_TOOLS         = "tools"
AUTHORITY_FORECASTS     = "forecasts"
AUTHORITY_RESPONSES     = "responses"

_AUTHORITY_RANK = {
    AUTHORITY_CONSTITUTION: 0,
    AUTHORITY_GOVERNANCE:   1,
    AUTHORITY_PLANNING:     2,
    AUTHORITY_EVOLUTION:    3,
    AUTHORITY_TOOLS:        4,
    AUTHORITY_FORECASTS:    5,
    AUTHORITY_RESPONSES:    6,
}

# High-impact action labels that always require full constitutional validation
HIGH_IMPACT_ACTIONS = frozenset({
    "execute_trade", "code_execution", "self_modification", "model_swap",
    "governance_override", "memory_wipe", "external_api_call",
    "autonomous_commit", "config_change", "objective_update",
})


# ── ConstitutionalVerdict ─────────────────────────────────────────────────────

@dataclass
class ConstitutionalVerdict:
    """Result of a constitutional validation check."""
    allowed: bool
    violated_laws: List[str]
    authority: str
    reason: str
    action: str = ""
    confidence_required: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "allowed": self.allowed,
            "violated_laws": list(self.violated_laws),
            "authority": self.authority,
            "reason": self.reason,
            "action": self.action,
        }


# ── ConstitutionalLayer ───────────────────────────────────────────────────────

class ConstitutionalLayer:
    """Supreme constitutional validator.

    Checks every high-impact action against all seven immutable laws before
    execution is permitted.  In permissive mode (``NIBLIT_CL_STRICT=0``),
    violations are logged but not blocking.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._validation_count: int = 0
        self._block_count: int = 0
        self._violation_counts: Dict[str, int] = {law: 0 for law in ALL_LAWS}
        log.debug("[ConstitutionalLayer] initialised (strict=%s)", _STRICT)

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(self, action: str, context: Optional[Dict[str, Any]] = None) -> ConstitutionalVerdict:
        """Validate *action* against all constitutional laws.

        Args:
            action:  Name of the action being attempted.
            context: Dict with keys such as:
                     ``confidence``        (float 0.0–1.0)
                     ``stability_score``   (float 0.0–1.0)
                     ``governance_approved`` (bool)
                     ``safety_level``      (str)
                     ``temporal_coherent`` (bool)
                     ``external_source``   (bool)

        Returns:
            :class:`ConstitutionalVerdict` — ``allowed=True`` unless a law is violated.
        """
        if not _ENABLED:
            return ConstitutionalVerdict(
                allowed=True, violated_laws=[], authority=AUTHORITY_CONSTITUTION,
                reason="constitutional layer disabled", action=action,
            )

        ctx = dict(context or {})
        violated: List[str] = []

        # Check each law
        self._check_law_1(ctx, violated)
        self._check_law_2(ctx, violated)
        self._check_law_3(ctx, violated)
        self._check_law_4(ctx, violated)
        self._check_law_5(ctx, violated)
        self._check_law_6(ctx, violated)
        self._check_law_7(ctx, violated)

        allowed = len(violated) == 0 or not _STRICT

        with self._lock:
            self._validation_count += 1
            if not allowed:
                self._block_count += 1
            for law in violated:
                self._violation_counts[law] = self._violation_counts.get(law, 0) + 1

        reason = "all constitutional laws satisfied" if not violated else (
            f"violated: {', '.join(v.replace('law_', 'Law ') for v in violated)}"
        )

        log.debug("[CL] action=%s allowed=%s violated=%s", action, allowed, violated)

        return ConstitutionalVerdict(
            allowed=allowed,
            violated_laws=violated,
            authority=AUTHORITY_CONSTITUTION if violated else AUTHORITY_GOVERNANCE,
            reason=reason,
            action=action,
        )

    def is_high_impact(self, action: str) -> bool:
        """Return True if *action* requires full constitutional validation."""
        return action in HIGH_IMPACT_ACTIONS

    def authority_rank(self, authority: str) -> int:
        """Return the numeric rank of *authority* (lower = higher authority)."""
        return _AUTHORITY_RANK.get(authority, 99)

    def highest_authority(self, a: str, b: str) -> str:
        """Return whichever of *a* or *b* has higher authority."""
        return a if self.authority_rank(a) <= self.authority_rank(b) else b

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "strict_mode": _STRICT,
                "validation_count": self._validation_count,
                "block_count": self._block_count,
                "violation_counts": dict(self._violation_counts),
                "laws": list(ALL_LAWS),
                "authority_hierarchy": list(_AUTHORITY_RANK.keys()),
            }

    # ── Law checkers ──────────────────────────────────────────────────────────

    def _check_law_1(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 1: preserve_system_integrity."""
        stability = float(ctx.get("stability_score", 1.0))
        if stability < 0.3:
            violated.append(LAW_PRESERVE_INTEGRITY)

    def _check_law_2(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 2: objective_alignment_priority."""
        alignment = float(ctx.get("objective_alignment", 1.0))
        if alignment < 0.4:
            violated.append(LAW_OBJECTIVE_ALIGNMENT)

    def _check_law_3(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 3: no short-term stability sacrifice."""
        stability = float(ctx.get("stability_score", 1.0))
        under_pressure = bool(ctx.get("under_pressure", False))
        if under_pressure and stability < 0.5:
            violated.append(LAW_NO_STABILITY_TRADE)

    def _check_law_4(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 4: constrain low-confidence autonomy."""
        confidence = float(ctx.get("confidence", 1.0))
        autonomous = bool(ctx.get("autonomous", False))
        if autonomous and confidence < 0.35:
            violated.append(LAW_CONSTRAIN_UNCERTAINTY)

    def _check_law_5(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 5: external systems cannot override objectives."""
        external = bool(ctx.get("external_source", False))
        overrides_objective = bool(ctx.get("overrides_objective", False))
        if external and overrides_objective:
            violated.append(LAW_EXTERNAL_NO_OVERRIDE)

    def _check_law_6(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 6: temporal incoherence halts execution."""
        temporal_coherent = ctx.get("temporal_coherent", None)
        if temporal_coherent is False:
            violated.append(LAW_TEMPORAL_COHERENCE)

    def _check_law_7(self, ctx: Dict, violated: List[str]) -> None:
        """LAW 7: safety overrides efficiency."""
        safety_level = str(ctx.get("safety_level", "low"))
        governance_approved = ctx.get("governance_approved", True)
        if safety_level == "high" and not governance_approved:
            violated.append(LAW_SAFETY_FIRST)


# ── Singleton ─────────────────────────────────────────────────────────────────
_cl: Optional[ConstitutionalLayer] = None
_cl_lock = threading.Lock()


def get_constitutional_layer() -> ConstitutionalLayer:
    """Return the module-level :class:`ConstitutionalLayer` singleton."""
    global _cl
    with _cl_lock:
        if _cl is None:
            _cl = ConstitutionalLayer()
    return _cl


if __name__ == "__main__":
    print('Running constitutional_layer.py')
