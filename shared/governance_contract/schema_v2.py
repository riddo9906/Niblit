"""Canonical schema-v2 cognitive envelope helpers."""

from __future__ import annotations

import time
from typing import Any

SCHEMA_VERSION = "2.0"
SCHEMA_V2_REQUIRED_FIELDS = (
    "schema_version",
    "signal",
    "confidence",
    "timestamp",
    "forecast_consensus",
    "governance",
    "runtime",
    "temporal",
    "resources",
)


def ensure_schema_v2(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return schema-v2-compatible envelope with backward-safe defaults."""
    src = dict(payload or {})
    now = int(src.get("timestamp", time.time()))

    signal = str(src.get("signal", "HOLD")).upper()
    if signal not in {"BUY", "SELL", "HOLD"}:
        signal = "HOLD"

    confidence = max(0.0, min(1.0, float(src.get("confidence", 0.5))))

    runtime = dict(src.get("runtime") or {})
    governance = dict(src.get("governance") or {})
    temporal = dict(src.get("temporal") or {})
    resources = dict(src.get("resources") or {})

    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now,
        "signal": signal,
        "confidence": confidence,
        "market_regime": str(src.get("market_regime", "ranging")),
        "forecast_consensus": {
            "direction": str((src.get("forecast_consensus") or {}).get("direction", "NEUTRAL")).upper(),
            "agreement": max(0.0, min(1.0, float((src.get("forecast_consensus") or {}).get("agreement", confidence)))),
            "uncertainty": max(0.0, min(1.0, float((src.get("forecast_consensus") or {}).get("uncertainty", 1.0 - confidence)))),
        },
        "governance": {
            "constitution_passed": bool(governance.get("constitution_passed", True)),
            "governance_mode": str(governance.get("governance_mode", runtime.get("mode", "normal"))).lower(),
            "survival_mode": bool(governance.get("survival_mode", False)),
            "governance_stability": max(0.0, min(1.0, float(governance.get("governance_stability", 1.0)))),
            "authority": str(governance.get("authority", "niblit_core")),
            "risk_tier": str(governance.get("risk_tier", "medium")),
            "current_drawdown_pct": max(0.0, float(governance.get("current_drawdown_pct", 0.0))),
            "max_drawdown_pct": max(0.0, float(governance.get("max_drawdown_pct", 0.12))),
        },
        "runtime": {
            "mode": str(runtime.get("mode", governance.get("governance_mode", "normal"))).lower(),
            "health": str(runtime.get("health", "ok")),
            "instability": max(0.0, min(1.0, float(runtime.get("instability", 0.0)))),
            "attention_pressure": max(0.0, min(1.0, float(runtime.get("attention_pressure", 0.0)))),
            "runtime_health": max(0.0, min(1.0, float(runtime.get("runtime_health", 1.0)))),
            "runtime_pressure": max(0.0, min(1.0, float(runtime.get("runtime_pressure", 0.0)))),
        },
        "temporal": {
            "epoch_id": int(temporal.get("epoch_id", src.get("epoch", now))),
            "temporal_epoch": int(temporal.get("temporal_epoch", temporal.get("epoch_id", src.get("epoch", now)))),
            "coherence_score": max(0.0, min(1.0, float(temporal.get("coherence_score", 1.0)))),
            "coherence_drift": max(0.0, min(1.0, float(temporal.get("coherence_drift", src.get("coherence_drift", 0.0))))),
            "epoch_alignment": str(temporal.get("epoch_alignment", "aligned")),
        },
        "resources": {
            "cognitive_budget": max(0.0, min(1.0, float(resources.get("cognitive_budget", 1.0)))),
            "attention_available": max(0.0, min(1.0, float(resources.get("attention_available", 1.0)))),
        },
        "trace": dict(src.get("trace") or {}) if isinstance(src.get("trace"), dict) else {},
        "advisors": dict(src.get("advisors") or {}) if isinstance(src.get("advisors"), dict) else {},
    }
    return out


if __name__ == "__main__":
    print('Running schema_v2.py')
