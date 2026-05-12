"""Canonical telemetry + replay normalization helpers."""

from __future__ import annotations

import time
from typing import Any


def normalize_telemetry(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize runtime telemetry to stable cross-repo fields."""
    src = dict(payload or {})
    return {
        "timestamp": int(src.get("timestamp", time.time())),
        "runtime_mode": str(src.get("runtime_mode", "normal")).lower(),
        "governance_mode": str(src.get("governance_mode", "normal")).lower(),
        "epoch_id": int(src.get("epoch_id", 0)),
        "coherence_score": max(0.0, min(1.0, float(src.get("coherence_score", 1.0)))),
        "coherence_drift": max(0.0, min(1.0, float(src.get("coherence_drift", 0.0)))),
        "attention_pressure": max(0.0, min(1.0, float(src.get("attention_pressure", 0.0)))),
        "runtime_health": max(0.0, min(1.0, float(src.get("runtime_health", 1.0)))),
        "model_trust": max(0.0, min(1.0, float(src.get("model_trust", 0.5)))),
        "execution_risk": max(0.0, min(1.0, float(src.get("execution_risk", 0.0)))),
        "source": str(src.get("source", "unknown")),
    }


def normalize_replay_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize replay metadata for causal/temporal reconstruction."""
    src = dict(payload or {})
    return {
        "trace_id": str(src.get("trace_id", src.get("causal_trace_id", f"trace-{int(time.time())}"))),
        "decision_lineage": list(src.get("decision_lineage", [])),
        "confidence_evolution": list(src.get("confidence_evolution", [])),
        "governance_replay": dict(src.get("governance_replay", {})),
        "causal_references": list(src.get("causal_references", src.get("memory_reference_ids", []))),
    }


if __name__ == "__main__":
    print('Running telemetry_contract.py')
