from __future__ import annotations

import importlib


def _load_gee(tmp_path):
    """Import GEE with state/log redirected to tmp_path."""
    module = importlib.import_module(
        "nibblebots.governance_evolution_engine"
    )
    module._STATE_FILE = tmp_path / "governance_state.json"
    module._LOG_FILE = tmp_path / "governance_log.jsonl"
    # Reset in-memory state by calling _save_state with empty dict
    module._save_state({})
    return module


def test_record_governance_event_persists(tmp_path):
    gee = _load_gee(tmp_path)

    gee.record_governance_event(gee.EVT_SAFETY_OVERRIDE, {
        "system_id": "test_sys",
        "explore_rate_adj_before": 0.05,
        "explore_rate_adj_after": 0.0,
    })
    state = gee._load_state()
    events = state.get("events", [])

    assert len(events) == 1
    assert events[0]["type"] == gee.EVT_SAFETY_OVERRIDE
    assert events[0]["system_id"] == "test_sys"


def test_snapshot_override_frequency(tmp_path):
    gee = _load_gee(tmp_path)

    # 3 safety overrides, 1 authority denied
    for _ in range(3):
        gee.record_governance_event(gee.EVT_SAFETY_OVERRIDE, {
            "explore_rate_adj_before": 0.05,
            "explore_rate_adj_after": 0.0,
        })
    gee.record_governance_event(gee.EVT_AUTHORITY_DENIED, {
        "explore_rate_adj_before": 0.0,
        "explore_rate_adj_after": 0.0,
    })

    snap = gee.snapshot()

    assert snap.window_size == 4
    assert snap.override_frequency == 0.75   # 3/4


def test_snapshot_suppressed_exploration_rate(tmp_path):
    gee = _load_gee(tmp_path)

    # Both events have non-zero before, zero after → both suppressed
    for _ in range(2):
        gee.record_governance_event(gee.EVT_SAFETY_OVERRIDE, {
            "explore_rate_adj_before": 0.05,
            "explore_rate_adj_after": 0.0,
        })
    # One event where no suppression occurred
    gee.record_governance_event(gee.EVT_AUTHORITY_DENIED, {
        "explore_rate_adj_before": 0.0,
        "explore_rate_adj_after": 0.0,
    })

    snap = gee.snapshot()
    # suppressed: 2 out of 3 resonance events had explore_before!=0, after==0
    assert snap.suppressed_exploration_rate == round(2 / 3, 4)


def test_conflict_resolution_success_unsaturated(tmp_path):
    gee = _load_gee(tmp_path)

    # Two successful (not saturated) conflict resolutions
    gee.record_governance_event(gee.EVT_CONFLICT_RESOLVED, {"saturated": False})
    gee.record_governance_event(gee.EVT_CONFLICT_RESOLVED, {"saturated": False})

    snap = gee.snapshot()
    assert snap.conflict_resolution_success == 1.0


def test_conflict_resolution_success_mixed(tmp_path):
    gee = _load_gee(tmp_path)

    gee.record_governance_event(gee.EVT_CONFLICT_RESOLVED, {"saturated": True})
    gee.record_governance_event(gee.EVT_CONFLICT_RESOLVED, {"saturated": False})

    snap = gee.snapshot()
    assert snap.conflict_resolution_success == 0.5


def test_evaluate_and_adapt_respects_constitutional_floor(tmp_path, monkeypatch):
    """Adaptation must never drive SIL_OBJECTIVE_PENALTY below the floor."""
    gee = _load_gee(tmp_path)

    # Make adaptation trigger immediately (interval=1)
    monkeypatch.setattr(gee, "GEE_ADAPT_INTERVAL", 1)
    monkeypatch.setattr(gee, "GEE_OVERRIDE_THRESHOLD", 0.0)   # always above threshold

    # Ensure SIL is importable and has the attributes we need
    import nibblebots.system_interface_layer as sil
    monkeypatch.setattr(sil, "SIL_OBJECTIVE_PENALTY", 0.21)

    # Record many safety overrides with high preservation score
    for _ in range(5):
        gee.record_governance_event(gee.EVT_SAFETY_OVERRIDE, {
            "explore_rate_adj_before": 0.05,
            "explore_rate_adj_after": 0.0,
        })
    # Record good cycle outcomes so preservation_score > 0.55
    state = gee._load_state()
    for _ in range(5):
        state.setdefault("events", []).append({
            "ts": "2026-01-01T00:00:00+00:00",
            "type": gee.EVT_CYCLE,
            "outcome": 0.8,
            "had_safety_override": True,
        })
    state["cycle_count"] = 0
    gee._save_state(state)

    adaptation = gee.evaluate_and_adapt(outcome_score=0.8)

    assert adaptation is not None
    # Penalty must not be below the constitutional floor
    assert sil.SIL_OBJECTIVE_PENALTY >= gee.IMMUTABLE_OBJECTIVE_PENALTY_FLOOR


def test_evaluate_and_adapt_cadence(tmp_path, monkeypatch):
    """evaluate_and_adapt should return None when interval not yet reached."""
    gee = _load_gee(tmp_path)
    monkeypatch.setattr(gee, "GEE_ADAPT_INTERVAL", 5)

    # Only call once (cycle_count=1), not yet at interval
    result = gee.evaluate_and_adapt(outcome_score=0.7)
    assert result is None


def test_status_structure(tmp_path):
    gee = _load_gee(tmp_path)
    s = gee.status()

    assert "gee_enabled" in s
    assert "constitutional_invariants" in s
    assert "current_snapshot" in s
    assert "objective_penalty_floor" in s["constitutional_invariants"]
    assert "saturation_threshold_floor" in s["constitutional_invariants"]
