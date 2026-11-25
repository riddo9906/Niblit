"""Evidence-linked, observation-only thesis for registered strategy votes.

Never selects a strategy, changes a signal, or grants execution rights.
"""
from __future__ import annotations

import hashlib
import json

SIDES = ("buy", "sell")


def build_market_thesis(assessment, observation):
    """Describe agreement, opposition, invalidation and provenance without trading."""
    votes = assessment.get("candidates", ())
    if not isinstance(votes, list):
        votes = []
    support = {side: [] for side in SIDES}
    undecided = []
    failures = []
    for item in votes[:24]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("strategy") or "unknown")[:80]
        side = item.get("side")
        if item.get("status") == "failed":
            failures.append(name)
        elif side in SIDES:
            support[side].append(name)
        else:
            undecided.append(name)
    selected = assessment.get("side")
    if failures or assessment.get("assessment_complete") is not True:
        classification = "incomplete_evidence"
    elif support["buy"] and support["sell"]:
        classification = "directional_conflict"
    elif selected in SIDES and support[selected]:
        classification = "directional_hypothesis"
    else:
        classification = "no_qualifying_setup"
    scope = observation.get("observation") or {}
    context = {
        key: scope.get(key) for key in
        ("symbol", "venue", "account_scope", "timeframe", "mode", "source", "bar", "completed_at")
    } if isinstance(scope, dict) else {}
    provenance = {
        "scope": context,
        "strategies": [
            {"strategy": str(v.get("strategy") or "")[:80],
             "side": v.get("side") if v.get("side") in (*SIDES, "wait") else "wait",
             "status": v.get("status", "unknown"),
             "measurement": v.get("evidence") or {},
             "snapshot_id": v.get("snapshot_id"),
             "context_contradictions": v.get("context_contradictions") or []}
            for v in votes[:24] if isinstance(v, dict)
        ],
    }
    evidence_id = hashlib.sha256(
        json.dumps(provenance, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    invalidation = (
        "Reassess on next completed M5 bar, changed strategy votes, stale data, "
        "unavailable evaluators, or changed higher-timeframe context."
    )
    return {
        "schema": "niblit.market-thesis/2",
        "classification": classification,
        "hypothesis": (
            f"Registered rules currently support {selected.upper()} on the observed M5 setup."
            if classification == "directional_hypothesis" else
            "Competing bullish and bearish setups remain unresolved."
            if classification == "directional_conflict" else
            "No directional market thesis can be established from this snapshot."
        ),
        "supporting_strategies": support[selected] if selected in SIDES else [],
        "opposing_strategies": support["sell" if selected == "buy" else "buy"] if selected in SIDES else support["buy"] + support["sell"],
        "abstaining_strategies": undecided,
        "failed_strategies": failures,
        "vote_counts": {side: len(support[side]) for side in SIDES},
        "provenance": provenance["scope"],
        "evidence_id": evidence_id,
        "invalidation_conditions": invalidation,
        "uncertainty": "Uncalibrated rule evidence; no probability or profitability claim.",
        "execution_authorized": False,
        "analysis_only": True,
    }
