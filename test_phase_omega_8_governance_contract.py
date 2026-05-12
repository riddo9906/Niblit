from __future__ import annotations

from shared.governance_contract import (
    CANONICAL_EVENTS,
    EVENT_EXECUTION_ENVELOPE_PUBLISHED,
    EVENT_MARKET_EPISODE_INGESTED,
    EVENT_RUNTIME_MODE_CHANGED,
    EVENT_TRADE_REFLECTION_INGESTED,
    compatibility_metadata,
    ensure_schema_v2,
    normalize_runtime_mode,
    validate_compatibility,
    validate_runtime_contract,
)


def test_runtime_mode_normalization_contract() -> None:
    assert normalize_runtime_mode("normal") == "normal"
    assert normalize_runtime_mode("constrained") == "cautious"
    assert normalize_runtime_mode("survival") == "survival"
    assert normalize_runtime_mode("lockdown") == "lockdown"
    assert normalize_runtime_mode("unknown") == "normal"


def test_schema_v2_defaults_and_required_fields() -> None:
    env = ensure_schema_v2({"signal": "BUY", "confidence": 0.8})
    assert env["schema_version"] == "2.0"
    assert env["signal"] == "BUY"
    assert "governance" in env
    assert "runtime" in env
    assert "temporal" in env
    assert "resources" in env


def test_compatibility_validation() -> None:
    meta = compatibility_metadata()
    verdict = validate_compatibility(meta)
    assert verdict["compatible"] is True

    mismatch = dict(meta)
    mismatch["schema_version"] = "3.x"
    verdict2 = validate_compatibility(mismatch)
    assert verdict2["compatible"] is False
    assert "schema_version" in verdict2["mismatches"]


def test_contract_validator_detects_mode_mismatch() -> None:
    env = ensure_schema_v2(
        {
            "runtime": {"mode": "normal"},
            "governance": {"governance_mode": "lockdown"},
        }
    )
    check = validate_runtime_contract(env)
    assert check["valid"] is False
    assert "mode_mismatch:runtime_vs_governance" in check["issues"]


def test_canonical_events_present() -> None:
    assert EVENT_EXECUTION_ENVELOPE_PUBLISHED in CANONICAL_EVENTS
    assert EVENT_TRADE_REFLECTION_INGESTED in CANONICAL_EVENTS
    assert EVENT_MARKET_EPISODE_INGESTED in CANONICAL_EVENTS
    assert EVENT_RUNTIME_MODE_CHANGED in CANONICAL_EVENTS


if __name__ == "__main__":
    print('Running test_phase_omega_8_governance_contract.py')
