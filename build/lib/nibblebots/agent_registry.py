#!/usr/bin/env python3
"""
nibblebots/agent_registry.py — Phase 15 Agent Role Manifest Registry

Ruflo-inspired declarative registry: every nibblebot declares its role type,
capability list, and trust score.  The autonomous evolution agent queries this
registry to select fix strategies rather than hard-coding a fixed catalogue.

Design principles (inspired by ruvnet/ruflo AGENTS.md)
------------------------------------------------------
* LEDGER/EXECUTOR split: the registry is the ledger — it tracks what each agent
  can do and how trusted it is.  The autonomous_evolution_agent is the executor
  that actually applies changes.
* Search before starting: query ``get_capable_agents()`` or
  ``fix_types_by_trust()`` BEFORE selecting what to fix.
* Store after success: call ``update_agent_trust()`` after a CI pass to
  reinforce winning strategies.
* Background workers: audit_agent, testgap_agent, doc_agent register here
  so the planner can route their observations to the right executor.

Architecture note
-----------------
This module is PASSIVE — it never imports from other nibblebots at module-load
time (to avoid circular imports and keep the registry cheap to load anywhere).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Role type constants  (mirrors Ruflo's agent taxonomy, adapted for Niblit)
# ---------------------------------------------------------------------------

ROLE_AUDITOR  = "auditor"    # security / exception-handling scanner
ROLE_PLANNER  = "planner"    # strategic and causal decision making
ROLE_CODER    = "coder"      # applies code fixes
ROLE_TESTER   = "tester"     # gap analysis / regression check
ROLE_REVIEWER = "reviewer"   # code quality and documentation


# ---------------------------------------------------------------------------
# AgentObservation — typed event emitted by background worker agents
# ---------------------------------------------------------------------------

@dataclass
class AgentObservation:
    """An observation emitted by a background worker agent.

    Background agents (audit_agent, testgap_agent, doc_agent) emit these
    rather than writing fixes directly.  The evolution_planner decides
    which observations to act on.

    Attributes
    ----------
    agent_name  : name of the emitting agent (matches AGENT_REGISTRY key)
    obs_type    : capability string (e.g. "bare_except", "test_gap")
    file_path   : relative repo path of the affected file
    count       : number of instances found in the file
    severity    : 0.0–1.0 urgency rating
    description : human-readable description of the finding
    metadata    : optional extra data (e.g. line numbers, fix hints)
    """

    agent_name: str
    obs_type: str
    file_path: str
    count: int = 1
    severity: float = 0.5
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name":  self.agent_name,
            "obs_type":    self.obs_type,
            "file_path":   self.file_path,
            "count":       self.count,
            "severity":    round(self.severity, 3),
            "description": self.description,
            "metadata":    self.metadata,
        }


# ---------------------------------------------------------------------------
# AgentRoleManifest — declarative description of a nibblebot
# ---------------------------------------------------------------------------

@dataclass
class AgentRoleManifest:
    """Declarative description of a nibblebot's role and capabilities."""

    name: str                   # module name (matches AGENT_REGISTRY key)
    role: str                   # one of the ROLE_* constants
    capabilities: List[str]     # fix_types or observation types this agent handles
    trust: float = 0.5          # initial trust score (0.0–1.0)
    description: str = ""       # human-readable one-liner

    def can_handle(self, capability: str) -> bool:
        """Return True if this agent declares *capability*."""
        return capability in self.capabilities

    def __repr__(self) -> str:
        return (
            f"AgentRoleManifest(name={self.name!r}, role={self.role!r}, "
            f"trust={self.trust:.2f}, caps={self.capabilities!r})"
        )


# ---------------------------------------------------------------------------
# The registry — single source of truth for all nibblebots
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, AgentRoleManifest] = {

    # ── Auditor tier ──────────────────────────────────────────────────────────
    "audit_agent": AgentRoleManifest(
        name="audit_agent",
        role=ROLE_AUDITOR,
        capabilities=["bare_except", "bare_except_pass", "security_issue"],
        trust=0.70,
        description="Scans for security and exception-handling issues",
    ),
    "signal_integrity_engine": AgentRoleManifest(
        name="signal_integrity_engine",
        role=ROLE_AUDITOR,
        capabilities=["ci_health", "trading_health", "runtime_health"],
        trust=0.75,
        description="Assesses signal confidence across CI/trading/runtime",
    ),
    "anomaly_detector": AgentRoleManifest(
        name="anomaly_detector",
        role=ROLE_AUDITOR,
        capabilities=["ewma_anomaly", "iqr_anomaly", "drift_anomaly"],
        trust=0.70,
        description="EWMA+IQR control chart anomaly detection",
    ),
    "context_guard": AgentRoleManifest(
        name="context_guard",
        role=ROLE_AUDITOR,
        capabilities=["context_mismatch", "context_spike"],
        trust=0.65,
        description="Detects context mismatches and intent spikes",
    ),

    # ── Planner tier ──────────────────────────────────────────────────────────
    "strategic_planner": AgentRoleManifest(
        name="strategic_planner",
        role=ROLE_PLANNER,
        capabilities=["goal_planning", "epsilon_greedy_explore", "risk_budget"],
        trust=0.75,
        description="Sets strategic goals and risk budgets each cycle",
    ),
    "causal_strategy_engine": AgentRoleManifest(
        name="causal_strategy_engine",
        role=ROLE_PLANNER,
        capabilities=["causal_rule_derive", "batch_recommend", "regime_shift"],
        trust=0.80,
        description="Derives causal fix-strategy rules from episode history",
    ),
    "evolution_planner": AgentRoleManifest(
        name="evolution_planner",
        role=ROLE_PLANNER,
        capabilities=["fix_ranking", "risk_gate", "domain_split"],
        trust=0.80,
        description="Ranks and gates fixes into a safe EvolutionPlan",
    ),
    "goal_adaptation_engine": AgentRoleManifest(
        name="goal_adaptation_engine",
        role=ROLE_PLANNER,
        capabilities=["goal_switch", "hysteresis_guard"],
        trust=0.70,
        description="Hysteresis-gated goal switching (stability/profit/learning)",
    ),
    "stability_controller": AgentRoleManifest(
        name="stability_controller",
        role=ROLE_PLANNER,
        capabilities=["mode_lock", "mode_memory", "exploration_epsilon"],
        trust=0.75,
        description="Mode locking with asymmetric hysteresis and switch penalty",
    ),

    # ── Coder tier ────────────────────────────────────────────────────────────
    "autonomous_evolution_agent": AgentRoleManifest(
        name="autonomous_evolution_agent",
        role=ROLE_CODER,
        capabilities=[
            "bare_except", "bare_except_pass",
            "trailing_whitespace", "double_blank_lines", "eof_newline",
        ],
        trust=0.75,
        description="Phase 3–15 autonomous code evolution and fix application",
    ),

    # ── Tester tier ───────────────────────────────────────────────────────────
    "testgap_agent": AgentRoleManifest(
        name="testgap_agent",
        role=ROLE_TESTER,
        capabilities=["test_gap"],
        trust=0.65,
        description="Detects production files with no corresponding test module",
    ),
    "rollback_guard": AgentRoleManifest(
        name="rollback_guard",
        role=ROLE_TESTER,
        capabilities=["regression_check", "auto_revert"],
        trust=0.85,
        description="Auto-reverts on CI regression; emits revert command",
    ),

    # ── Reviewer tier ─────────────────────────────────────────────────────────
    "doc_agent": AgentRoleManifest(
        name="doc_agent",
        role=ROLE_REVIEWER,
        capabilities=["missing_docstring"],
        trust=0.55,
        description="Flags public functions without docstrings",
    ),
    "feedback_learner": AgentRoleManifest(
        name="feedback_learner",
        role=ROLE_REVIEWER,
        capabilities=["outcome_record", "weight_update", "pattern_memory"],
        trust=0.80,
        description="Records CI outcomes and updates impact weights",
    ),
}


# ---------------------------------------------------------------------------
# Query helpers  (Ruflo "search-before-start" pattern)
# ---------------------------------------------------------------------------

def get_agent(name: str) -> Optional[AgentRoleManifest]:
    """Return the manifest for *name*, or None."""
    return AGENT_REGISTRY.get(name)


def get_capable_agents(capability: str) -> List[AgentRoleManifest]:
    """Return all agents that declare *capability*, sorted by trust descending."""
    matches = [a for a in AGENT_REGISTRY.values() if a.can_handle(capability)]
    return sorted(matches, key=lambda a: a.trust, reverse=True)


def get_agents_by_role(role: str) -> List[AgentRoleManifest]:
    """Return all agents with *role*, sorted by trust descending."""
    matches = [a for a in AGENT_REGISTRY.values() if a.role == role]
    return sorted(matches, key=lambda a: a.trust, reverse=True)


def best_agent_for(capability: str) -> Optional[AgentRoleManifest]:
    """Return the highest-trust agent capable of *capability*, or None."""
    agents = get_capable_agents(capability)
    return agents[0] if agents else None


def fix_types_by_trust() -> List[str]:
    """Return all coder-tier fix types ordered by the coder's trust score.

    This is the Ruflo-inspired replacement for a hard-coded fix priority list:
    the registry drives the order, and trust scores adapt based on CI outcomes.
    """
    coders = get_agents_by_role(ROLE_CODER)
    seen: Dict[str, float] = {}
    for agent in coders:
        for cap in agent.capabilities:
            if cap not in seen or agent.trust > seen[cap]:
                seen[cap] = agent.trust
    return sorted(seen, key=lambda c: seen[c], reverse=True)


def update_agent_trust(name: str, new_trust: float) -> None:
    """Update the in-memory trust score for *name* (clamped to [0.05, 0.95]).

    The caller is responsible for persisting this value if needed.
    Typically called by feedback_learner after a CI cycle.
    """
    manifest = AGENT_REGISTRY.get(name)
    if manifest is not None:
        manifest.trust = max(0.05, min(0.95, new_trust))


def registry_summary() -> Dict[str, Any]:
    """Return a summary dict suitable for logging / monitoring."""
    roles: Dict[str, int] = {}
    for m in AGENT_REGISTRY.values():
        roles[m.role] = roles.get(m.role, 0) + 1
    return {
        "total_agents": len(AGENT_REGISTRY),
        "by_role": roles,
        "avg_trust": round(
            sum(m.trust for m in AGENT_REGISTRY.values()) / max(len(AGENT_REGISTRY), 1),
            3,
        ),
    }


if __name__ == "__main__":
    print('Running agent_registry.py')
