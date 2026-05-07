from __future__ import annotations

import importlib


def _load_sil(monkeypatch, tmp_path):
    module = importlib.import_module("nibblebots.system_interface_layer")
    monkeypatch.setattr(module, "_STATE_FILE", tmp_path / "system_interface_state.json")
    monkeypatch.setattr(module, "_LOG_FILE", tmp_path / "system_interface_log.jsonl")
    return module


def _set_trust(module, system_id: str, trust_weight: float) -> None:
    state = module._load_state()
    state["profiles"][system_id]["trust_weight"] = trust_weight
    module._save_state(state)


def test_authority_domains_block_unauthorized_exploration(monkeypatch, tmp_path):
    sil = _load_sil(monkeypatch, tmp_path)

    profile = sil.mirror_system(
        "stability_monitor",
        {"anomaly_spike": 1.0, "warning_flag": 1.0},
        current_objective="maximize_stability",
        authority_domains=["risk"],
    )

    config = sil.establish_resonance(profile, current_objective="maximize_stability")

    assert profile.authority_domains == ["risk"]
    assert config.explore_rate_adj == 0.0
    assert "AUTHORITY_DENIED(exploration)" in config.rationale


def test_safety_objective_blocks_non_risk_override(monkeypatch, tmp_path):
    sil = _load_sil(monkeypatch, tmp_path)

    profile = sil.mirror_system(
        "external_llm",
        {"anomaly_spike": 1.0, "unknown_pattern": 1.0},
        current_objective="maximize_stability",
        authority_domains=["exploration"],
    )

    config = sil.establish_resonance(profile, current_objective="maximize_stability")

    assert config.explore_rate_adj == 0.0
    assert "SAFETY_OVERRIDE(exploration)" in config.rationale


def test_resolve_conflict_dampens_when_resonance_saturates(monkeypatch, tmp_path):
    sil = _load_sil(monkeypatch, tmp_path)
    monkeypatch.setattr(sil, "SIL_SATURATION_THRESHOLD", 0.2)

    first = sil.mirror_system(
        "market_agent_a",
        {"anomaly_spike": 1.0, "price_signal": 1.0},
        current_objective="improve_learning",
        authority_domains=["exploration", "market_signals"],
    )
    second = sil.mirror_system(
        "market_agent_b",
        {"anomaly_spike": 1.0, "price_signal": 1.0},
        current_objective="improve_learning",
        authority_domains=["exploration", "market_signals"],
    )

    _set_trust(sil, first.system_id, 0.95)
    _set_trust(sil, second.system_id, 0.95)

    individual = sil.establish_resonance(
        sil.get_profile(first.system_id),
        current_objective="improve_learning",
    )
    resolved = sil.resolve_conflict(objective="improve_learning")

    assert resolved is not None
    assert "SATURATED(scale=" in resolved.rationale
    assert 0.0 < resolved.explore_rate_adj < individual.explore_rate_adj
    assert resolved.signal_weight_adj > individual.signal_weight_adj
