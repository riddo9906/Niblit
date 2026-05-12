from __future__ import annotations

import json
from pathlib import Path

from modules.distributed_runtime_coordinator import DistributedRuntimeCoordinator
from modules.event_bus import (
    EVENT_EXECUTION_ENVELOPE_PUBLISHED,
    EVENT_MARKET_EPISODE_INGESTED,
    EVENT_RUNTIME_MODE_CHANGED,
    EVENT_TRADE_REFLECTION_INGESTED,
    get_event_bus,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def test_runtime_mode_normalization() -> None:
    assert DistributedRuntimeCoordinator._normalize_runtime_mode("normal") == "normal"
    assert DistributedRuntimeCoordinator._normalize_runtime_mode("constrained") == "cautious"
    assert DistributedRuntimeCoordinator._normalize_runtime_mode("CAUTIOUS") == "cautious"
    assert DistributedRuntimeCoordinator._normalize_runtime_mode("survival") == "survival"
    assert DistributedRuntimeCoordinator._normalize_runtime_mode("invalid") == "normal"


def test_refresh_builds_contract_and_ingests_streams(tmp_path: Path) -> None:
    signal_file = tmp_path / "signal.json"
    reflection_file = tmp_path / "reflection.jsonl"
    episodes_file = tmp_path / "episodes.jsonl"
    trace_file = tmp_path / "trace.jsonl"

    _write_json(
        signal_file,
        {
            "schema_version": "2.0",
            "timestamp": 1710000000,
            "signal": "BUY",
            "confidence": 0.81,
            "market_regime": "trending",
            "governance": {"governance_mode": "constrained", "constitution_passed": True},
            "runtime": {"mode": "constrained", "attention_pressure": 0.33, "runtime_health": 0.72},
            "temporal": {"epoch_id": 1710000000, "coherence_score": 0.64},
            "resources": {"cognitive_budget": 0.66, "attention_available": 0.58},
            "forecast_consensus": {"direction": "UP", "agreement": 0.71, "uncertainty": 0.29},
        },
    )
    _write_jsonl(reflection_file, [{"id": 1, "kind": "trade_reflection"}])
    _write_jsonl(episodes_file, [{"id": 1, "kind": "market_episode"}])

    coord = DistributedRuntimeCoordinator(
        cloud_url="",
        signal_file=signal_file,
        reflection_file=reflection_file,
        episodes_file=episodes_file,
        trace_file=trace_file,
    )

    state = coord.refresh()
    contract = state.runtime_contract

    assert state.source == "local"
    assert contract["schema_version"] == "2.0"
    assert "compatibility" in contract
    assert contract["signal"] == "BUY"
    assert contract["runtime"]["mode"] == "cautious"
    assert contract["governance"]["governance_mode"] == "cautious"
    assert 0.0 <= contract["temporal"]["coherence_score"] <= 1.0

    assert trace_file.exists()
    trace_lines = [line for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(trace_lines) >= 1

    bus = get_event_bus()
    assert bus.last_event(EVENT_EXECUTION_ENVELOPE_PUBLISHED) is not None
    assert bus.last_event(EVENT_RUNTIME_MODE_CHANGED) is not None
    assert bus.last_event(EVENT_TRADE_REFLECTION_INGESTED) is not None
    assert bus.last_event(EVENT_MARKET_EPISODE_INGESTED) is not None

    status = coord.status()
    assert "compatibility" in status
    assert "drift_report" in status


def test_cloud_status_mapping_to_contract() -> None:
    coord = DistributedRuntimeCoordinator(cloud_url="")
    mapped = coord._from_cloud_status(
        {
            "runtime": {"mode": "constrained", "health": "ok", "runtime_health": 0.9},
            "governance": {"governance_mode": "constrained", "constitution_passed": True},
            "coherence": {"score": 0.87, "drift": 0.04},
            "attention": {"pressure": 0.22, "budget": 0.78, "available": 0.64},
            "epoch": {"current": 42, "alignment": "aligned"},
            "models": {"state": "balanced", "trust": 0.73},
            "trading": {
                "signal": "HOLD",
                "confidence": 0.62,
                "market_regime": "ranging",
                "forecast_consensus": {"direction": "NEUTRAL", "agreement": 0.66, "uncertainty": 0.34},
            },
        }
    )

    assert mapped["runtime"]["mode"] == "cautious"
    assert mapped["governance"]["governance_mode"] == "cautious"
    assert mapped["temporal"]["epoch_id"] == 42
    assert mapped["resources"]["cognitive_budget"] == 0.78
    assert mapped["model_trust"] == 0.73


if __name__ == "__main__":
    print('Running test_distributed_runtime_coordinator.py')
