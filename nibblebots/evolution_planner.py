#!/usr/bin/env python3
"""
nibblebots/evolution_planner.py — Phase 3 Evolution Planner

Converts a list of SemanticIssues + ImpactScores into a ranked, gated
EvolutionPlan that the execution engine can safely commit.

This module replaces Phase 2's "apply everything that passes compile" with:

    "apply what is high-impact, low-risk, and above the confidence gate"

Key concepts
------------
SAFE vs RISK fixes
    Formatting and style fixes are always SAFE.
    Exception-handling fixes are SAFE only when confidence is high enough.
    Logic-changing fixes are always RISK (not currently in the catalogue, but
    the framework is in place so Phase 4 can add them).

Risk threshold
    A fix is skipped if its ImpactScore.net_score < RISK_THRESHOLD.
    Default: 0.05  (very permissive — almost everything passes).

Confidence gate
    A fix is skipped if SemanticIssue.confidence < CONFIDENCE_MIN.
    Default: 0.60

The planner NEVER includes:
    • Files in the ``_PROTECTED_MODULES`` set (decision engine, meta engine,
      trading logic) regardless of score.  These are off-limits for automated
      modification until a human explicitly removes them from the set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from nibblebots.semantic_engine import SemanticIssue
from nibblebots.impact_engine import ImpactScore, regression_adjusted_net_score
from nibblebots import anomaly_detector, strategic_planner


# ---------------------------------------------------------------------------
# Configuration (can be overridden via environment variables)
# ---------------------------------------------------------------------------

RISK_THRESHOLD = float(os.environ.get("EVOLUTION_RISK_THRESHOLD", "0.05"))
CONFIDENCE_MIN = float(os.environ.get("EVOLUTION_CONFIDENCE_MIN", "0.60"))

# Phase 8: minimum real-world value gain required for a fix to be executed
MIN_REAL_WORLD_GAIN = float(os.environ.get("VALUE_MIN_GAIN", "0.02"))

# Fix types that we consider RISK (no automated mutation without human review)
_RISK_FIX_TYPES: frozenset = frozenset({
    # Nothing in Phase 3 is logic-mutating yet; this guard is ready for Phase 4
})

# Repo-relative path substrings that are NEVER auto-modified
_PROTECTED_MODULES: frozenset = frozenset({
    "modules/decision_engine",
    "modules/meta_engine",
    "modules/policy_optimizer",
    "NiblitSignalStrategy",
    "freqtrade_adapter",
})


# ---------------------------------------------------------------------------
# EvolutionPlan data structure
# ---------------------------------------------------------------------------

class PlannedFix(NamedTuple):
    semantic_issue: SemanticIssue
    impact: ImpactScore
    fix_class: str   # "SAFE" or "RISK"
    rank: int        # lower = higher priority


class EvolutionPlan(NamedTuple):
    planned_fixes: List[PlannedFix]
    skipped_count: int
    expected_net_impact: float   # average net_score across planned fixes
    risk_level: float            # average risk across planned fixes
    workspace: Path


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_plan(
    paired: List[Tuple[SemanticIssue, ImpactScore]],
    workspace: Path,
    max_fixes: int = 5,
    dep_graph: Optional[Any] = None,   # DependencyGraph from dependency_analyzer
    strategic_decision: Optional[Any] = None,  # StrategicDecision from strategic_planner
    reality_snapshot: Optional[Dict[str, Any]] = None,  # Phase 8 RealitySnapshot
) -> EvolutionPlan:
    """Build a ranked EvolutionPlan from (SemanticIssue, ImpactScore) pairs.

    Selection criteria (all must pass):
      1. Not in a protected module
      2. confidence >= CONFIDENCE_MIN
      3. net_score   >= RISK_THRESHOLD  (Phase 4: uses regression-adjusted score)
      4. Not a RISK fix type (unless explicitly allowed in the future)
      5. Phase 5: high-fan-out files (dep_graph provided) → promote to RISK class
      6. Phase 7: strategic_decision.risk_budget enforced on avg risk
      7. Phase 7: "do_nothing" decision → empty plan regardless of scores
      8. Phase 8: value_engine gate — skip fix if value_delta < MIN_REAL_WORLD_GAIN
                  (only when reality_snapshot is provided)

    Ranking:
      Primary   : semantic type (error_handling_risk first)
      Secondary : net_score descending (explore mode: shuffle top tier for variety)
      Tertiary  : instance count descending
    """
    # Phase 7: honour strategic "do nothing" decision
    if strategic_decision is not None and not strategic_decision.should_proceed():
        return EvolutionPlan(
            planned_fixes=[],
            skipped_count=len(paired),
            expected_net_impact=0.0,
            risk_level=0.0,
            workspace=workspace,
        )

    # Phase 8: pre-compute value engine gate if snapshot is available
    value_gate_active = reality_snapshot is not None
    _value_engine = None
    if value_gate_active:
        try:
            from nibblebots import value_engine as _ve  # noqa: PLC0415
            _value_engine = _ve
        except Exception:  # noqa: BLE001
            value_gate_active = False

    eligible: List[Tuple[SemanticIssue, ImpactScore]] = []
    skipped = 0

    for issue, impact in paired:
        # Phase 4: use regression-adjusted net_score for gating
        adj_net = regression_adjusted_net_score(impact.net_score)
        impact_with_adj_score = impact._replace(net_score=adj_net)

        skip_reason = _check_skip(issue, impact_with_adj_score)
        if skip_reason:
            skipped += 1
            continue

        # Phase 8: gate on real-world value
        if value_gate_active and _value_engine is not None:
            try:
                assessment = _value_engine.evaluate_single(reality_snapshot)
                if not assessment.passes_gate:
                    skipped += 1
                    continue
            except Exception:  # noqa: BLE001
                pass   # degrade gracefully

        eligible.append((issue, impact_with_adj_score))

    # Sort: error_handling_risk > code_style_debt > others, then net_score
    def _rank_key(pair: Tuple[SemanticIssue, ImpactScore]) -> tuple:
        sem, imp = pair
        type_order = {"error_handling_risk": 0, "code_style_debt": 1}.get(
            sem.semantic_type, 2
        )
        return (type_order, -imp.net_score, -sem.count)

    eligible.sort(key=_rank_key)

    # Phase 7 exploration mode: shuffle within the same semantic-type tier
    if strategic_decision is not None and strategic_decision.is_exploring():
        import random as _random  # noqa: PLC0415
        groups: dict = {}
        for pair in eligible:
            key = _rank_key(pair)[0]
            groups.setdefault(key, []).append(pair)
        for grp in groups.values():
            _random.shuffle(grp)
        eligible = [p for k in sorted(groups) for p in groups[k]]

    selected = eligible[:max_fixes]

    planned: List[PlannedFix] = []
    for rank, (sem, imp) in enumerate(selected, start=1):
        fix_class = "RISK" if sem.fix_type in _RISK_FIX_TYPES else "SAFE"

        # Phase 5: escalate to RISK if file is high-fan-out
        if dep_graph is not None and fix_class == "SAFE":
            try:
                from nibblebots.dependency_analyzer import is_high_fan_out  # noqa: PLC0415
                if is_high_fan_out(sem.file_path, dep_graph):
                    fix_class = "RISK"
            except Exception:  # noqa: BLE001
                pass

        planned.append(PlannedFix(
            semantic_issue=sem,
            impact=imp,
            fix_class=fix_class,
            rank=rank,
        ))

    if planned:
        avg_net = sum(pf.impact.net_score for pf in planned) / len(planned)
        avg_risk = sum(pf.impact.risk_level for pf in planned) / len(planned)
    else:
        avg_net = 0.0
        avg_risk = 0.0

    # Phase 7: enforce risk_budget from strategic decision.
    # Sort by risk_level descending and drop the riskiest fixes first so we
    # maximise the net_score of the remaining plan within the budget.
    if (
        strategic_decision is not None
        and strategic_decision.should_proceed()
        and avg_risk > strategic_decision.risk_budget
    ):
        planned_sorted = sorted(planned, key=lambda pf: pf.impact.risk_level, reverse=True)
        while planned_sorted and avg_risk > strategic_decision.risk_budget:
            planned_sorted.pop(0)
            if planned_sorted:
                avg_risk = (
                    sum(pf.impact.risk_level for pf in planned_sorted) / len(planned_sorted)
                )
            else:
                avg_risk = 0.0
        # Re-rank by net_score after budget enforcement
        planned_sorted.sort(key=lambda pf: (-pf.impact.net_score, pf.rank))
        skipped += len(planned) - len(planned_sorted)
        planned = [
            PlannedFix(
                semantic_issue=pf.semantic_issue,
                impact=pf.impact,
                fix_class=pf.fix_class,
                rank=i + 1,
            )
            for i, pf in enumerate(planned_sorted)
        ]
        avg_net = sum(pf.impact.net_score for pf in planned) / max(len(planned), 1)

    return EvolutionPlan(
        planned_fixes=planned,
        skipped_count=skipped,
        expected_net_impact=round(avg_net, 3),
        risk_level=round(avg_risk, 3),
        workspace=workspace,
    )


def build_multi_domain_plan(
    domain_paired: Dict[str, List[Tuple[SemanticIssue, ImpactScore]]],
    workspace: Path,
    max_fixes_per_domain: int = 5,
    dep_graph: Optional[Any] = None,
) -> Dict[str, EvolutionPlan]:
    """Build separate plans for each domain and enforce the cross-domain cap.

    Parameters
    ----------
    domain_paired          : mapping of domain_name → paired (SemanticIssue, ImpactScore)
    workspace              : repo root
    max_fixes_per_domain   : max fixes per individual domain plan
    dep_graph              : optional DependencyGraph for fan-out risk

    Returns a dict of domain_name → EvolutionPlan.  The total number of SAFE
    planned fixes is capped at MAX_CROSS_DOMAIN_FIXES.
    """
    from nibblebots.domain_registry import MAX_CROSS_DOMAIN_FIXES  # noqa: PLC0415

    plans: Dict[str, EvolutionPlan] = {}
    total_safe = 0

    for domain_name, paired in domain_paired.items():
        plan = build_plan(
            paired=paired,
            workspace=workspace,
            max_fixes=max_fixes_per_domain,
            dep_graph=dep_graph,
        )
        # Trim to stay within cross-domain cap
        safe_fixes = [pf for pf in plan.planned_fixes if pf.fix_class == "SAFE"]
        if total_safe + len(safe_fixes) > MAX_CROSS_DOMAIN_FIXES:
            allowed = MAX_CROSS_DOMAIN_FIXES - total_safe
            safe_fixes = safe_fixes[:allowed]
            risk_fixes = [pf for pf in plan.planned_fixes if pf.fix_class == "RISK"]
            trimmed = safe_fixes + risk_fixes
            plan = plan._replace(
                planned_fixes=trimmed,
                skipped_count=plan.skipped_count + (len(plan.planned_fixes) - len(trimmed)),
            )
        total_safe += len([pf for pf in plan.planned_fixes if pf.fix_class == "SAFE"])
        plans[domain_name] = plan

    return plans


# ---------------------------------------------------------------------------
# Helper: decide whether to skip an issue
# ---------------------------------------------------------------------------

def _check_skip(
    issue: SemanticIssue,
    impact: ImpactScore,
) -> Optional[str]:
    """Return a skip reason string, or None if the fix is eligible."""
    rel = str(issue.file_path)
    for protected in _PROTECTED_MODULES:
        if protected in rel:
            return f"protected module ({protected})"

    if issue.fix_type in _RISK_FIX_TYPES:
        return f"RISK fix type ({issue.fix_type}) — requires human review"

    if issue.confidence < CONFIDENCE_MIN:
        return (
            f"confidence {issue.confidence:.2f} < gate {CONFIDENCE_MIN:.2f}"
        )

    if impact.net_score < RISK_THRESHOLD:
        return (
            f"net_score {impact.net_score:.3f} < threshold {RISK_THRESHOLD:.3f}"
        )

    return None


# ---------------------------------------------------------------------------
# Plan summary (for logging)
# ---------------------------------------------------------------------------

def print_plan(plan: EvolutionPlan) -> None:
    """Print a human-readable summary of the EvolutionPlan."""
    print(f"📋 Evolution Plan")
    print(f"   Planned fixes       : {len(plan.planned_fixes)}")
    print(f"   Skipped (gated)     : {plan.skipped_count}")
    print(f"   Expected net impact : {plan.expected_net_impact:+.3f}")
    print(f"   Avg risk level      : {plan.risk_level:.3f}")
    print()
    for pf in plan.planned_fixes:
        sem = pf.semantic_issue
        imp = pf.impact
        try:
            rel = sem.file_path.relative_to(plan.workspace)
        except ValueError:
            rel = sem.file_path
        print(
            f"  [{pf.rank}] {pf.fix_class:<4} | "
            f"score={imp.net_score:+.3f} | "
            f"conf={sem.confidence:.2f} | "
            f"{rel}"
        )
        print(f"       {sem.context_hint}")
