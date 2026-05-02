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
from typing import List, NamedTuple, Optional, Tuple

from nibblebots.semantic_engine import SemanticIssue
from nibblebots.impact_engine import ImpactScore


# ---------------------------------------------------------------------------
# Configuration (can be overridden via environment variables)
# ---------------------------------------------------------------------------

RISK_THRESHOLD = float(os.environ.get("EVOLUTION_RISK_THRESHOLD", "0.05"))
CONFIDENCE_MIN = float(os.environ.get("EVOLUTION_CONFIDENCE_MIN", "0.60"))

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
) -> EvolutionPlan:
    """Build a ranked EvolutionPlan from (SemanticIssue, ImpactScore) pairs.

    Selection criteria (all must pass):
      1. Not in a protected module
      2. confidence >= CONFIDENCE_MIN
      3. net_score   >= RISK_THRESHOLD
      4. Not a RISK fix type (unless explicitly allowed in the future)

    Ranking:
      Primary   : semantic type (error_handling_risk first)
      Secondary : net_score descending
      Tertiary  : instance count descending
    """
    eligible: List[Tuple[SemanticIssue, ImpactScore]] = []
    skipped = 0

    for issue, impact in paired:
        skip_reason = _check_skip(issue, impact)
        if skip_reason:
            skipped += 1
            continue
        eligible.append((issue, impact))

    # Sort: error_handling_risk > code_style_debt > others, then net_score
    def _rank_key(pair: Tuple[SemanticIssue, ImpactScore]) -> tuple:
        sem, imp = pair
        type_order = {"error_handling_risk": 0, "code_style_debt": 1}.get(
            sem.semantic_type, 2
        )
        return (type_order, -imp.net_score, -sem.count)

    eligible.sort(key=_rank_key)
    selected = eligible[:max_fixes]

    planned: List[PlannedFix] = []
    for rank, (sem, imp) in enumerate(selected, start=1):
        fix_class = "RISK" if sem.fix_type in _RISK_FIX_TYPES else "SAFE"
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

    return EvolutionPlan(
        planned_fixes=planned,
        skipped_count=skipped,
        expected_net_impact=round(avg_net, 3),
        risk_level=round(avg_risk, 3),
        workspace=workspace,
    )


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
