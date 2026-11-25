"""Versioned, reproducible explanation of a trading decision.

Observation only. Never alters a strategy vote or grants broker authority.
"""
from __future__ import annotations
import hashlib
import json
from collections.abc import Mapping


def decision_trace(assessment: Mapping, *, adapter: str, symbol: str,
                   account: str, environment: str) -> dict:
    if not isinstance(assessment, Mapping):
        raise TypeError("Assessment must be a mapping")
    thesis = assessment.get("market_thesis")
    if not isinstance(thesis, Mapping) or not thesis.get("evidence_id"):
        raise ValueError("Evidence-linked market thesis required")
    candidates = assessment.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Registered strategy evaluations required")
    votes = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("Invalid strategy result")
        votes.append({
            "strategy": str(candidate.get("strategy") or "")[:80],
            "side": candidate.get("side") if candidate.get("side") in ("buy", "sell", "wait") else "wait",
            "status": str(candidate.get("status") or "assessed")[:48],
        })
    regime=assessment.get("regime_evidence")
    if not isinstance(regime, Mapping):
        regime={}
    side = assessment.get("side")
    if side not in ("buy", "sell", "wait"):
        raise ValueError("Invalid chosen direction")
    scope = {
        "adapter": adapter, "symbol": symbol, "account": account,
        "environment": environment, "timeframe": "5m", "bar": assessment.get("bar"),
    }
    basis = {
        "schema": "niblit.market-decision-trace/1",
        "scope": scope,
        "market_evidence_id": str(thesis["evidence_id"]),
        "thesis_classification": thesis.get("classification"),
        "market_regime": regime.get("regime"),
        "regime_evidence_id": regime.get("evidence_id"),
        "selection_policy": assessment.get("policy_version"),
        "selected_strategy": assessment.get("strategy"),
        "selected_direction": side,
        "selection_reason": assessment.get("selection_reason"),
        "assessment_complete": assessment.get("assessment_complete") is True,
        "strategy_votes": votes,
        "alternatives": [
            {"strategy": v["strategy"], "direction": v["side"]}
            for v in votes if v["strategy"] != assessment.get("strategy")
        ],
        "counterfactual_outcomes": None,
        "broker_execution_authorized": False,
        "learning_action": "record_only",
    }
    raw = json.dumps(basis, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**basis, "trace_id": hashlib.sha256(raw.encode("utf-8")).hexdigest()}


def outcome_attribution(order_payload: Mapping, broker_report: Mapping, performance: Mapping) -> dict:
    """Link a reconciled broker outcome to original point-in-time decision."""
    decision = order_payload.get("decision") or {}
    if not isinstance(decision, Mapping):
        raise ValueError("Original decision not available")
    trace = decision.get("decision_trace")
    if not isinstance(trace, Mapping) or not trace.get("trace_id"):
        return {"trace_id": None, "attribution": "legacy_order_without_decision_trace",
                "counterfactual_outcomes": None, "learning_action": "record_only"}
    return {
        "trace_id": trace["trace_id"],
        "market_evidence_id": trace.get("market_evidence_id"),
        "selection_policy": trace.get("selection_policy"),
        "selected_strategy": trace.get("selected_strategy"),
        "competing_strategies": trace.get("alternatives", []),
        "broker_outcome_state": broker_report.get("state"),
        "realized_net": broker_report.get("realized_net"),
        "net_realized_r": performance.get("net_realized_r"),
        "counterfactual_outcomes": None,
        "learning_action": "record_only",
        "attribution": "verified_broker_reconciliation",
    }
