"""Canonical advisor protocol normalization utilities."""

from __future__ import annotations

from typing import Any


def _clamp(value: object) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_advisor_votes(envelope: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Normalize advisor votes to canonical fields for replay-safe debate traces."""
    env = dict(envelope or {})
    advisors = env.get("advisors") or {}
    votes = advisors.get("votes") if isinstance(advisors, dict) else {}
    if not isinstance(votes, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for advisor_id, payload in votes.items():
        if not isinstance(payload, dict):
            continue
        direction = str(payload.get("direction", "HOLD")).upper()
        if direction not in {"BUY", "SELL", "HOLD"}:
            direction = "HOLD"
        out[str(advisor_id)] = {
            "direction": direction,
            "confidence": _clamp(payload.get("confidence", 0.5)),
            "uncertainty": _clamp(payload.get("uncertainty", 0.5)),
            "risk_estimate": _clamp(payload.get("risk_estimate", 0.5)),
            "rationale": str(payload.get("rationale", "")),
            "regime_interpretation": str(payload.get("regime_interpretation", env.get("market_regime", "unknown"))),
            "causal_hint": str(payload.get("causal_hint", "")),
        }
    return out


if __name__ == "__main__":
    print('Running advisor_protocol.py')
