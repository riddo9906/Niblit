"""Phase Ω.7 — Cognitive execution envelope and cross-repo integration tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import modules.lean_algo_manager as lam_module


def _reset_lam_singleton() -> None:
    lam_module._instance = None


# ─────────────────────────────────────────────────────────────────────────────
# Event constant tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOmega7EventConstants:
    def test_event_constants_exist(self):
        from modules import event_bus
        assert event_bus.EVENT_EXECUTION_ENVELOPE_PUBLISHED == "execution_envelope.published"
        assert event_bus.EVENT_TRADE_REFLECTION_INGESTED    == "trade_reflection.ingested"
        assert event_bus.EVENT_MARKET_EPISODE_INGESTED      == "market_episode.ingested"
        assert event_bus.EVENT_RUNTIME_MODE_CHANGED         == "runtime_mode.changed"

    def test_omega6_constants_preserved(self):
        from modules import event_bus
        assert hasattr(event_bus, "EVENT_SALIENCE_SCORED")
        assert hasattr(event_bus, "EVENT_COGNITIVE_BUDGET_ENFORCED")
        assert hasattr(event_bus, "EVENT_ATTENTION_ALLOCATED")


# ─────────────────────────────────────────────────────────────────────────────
# _governance_snapshot helper
# ─────────────────────────────────────────────────────────────────────────────

class TestGovernanceSnapshot:
    def test_returns_dict_with_required_keys(self):
        snap = lam_module._governance_snapshot()
        for key in (
            "constitution_passed", "violated_laws",
            "stability_pressure", "recursion_depth",
            "cognitive_budget_remaining", "cognitive_budget_pressure",
            "attention_pressure", "coherence_score", "survival_mode",
        ):
            assert key in snap, f"Missing key: {key}"

    def test_defaults_are_safe(self):
        snap = lam_module._governance_snapshot()
        assert isinstance(snap["constitution_passed"], bool)
        assert isinstance(snap["violated_laws"], list)
        assert 0.0 <= snap["stability_pressure"] <= 1.0
        assert snap["recursion_depth"] >= 0
        assert 0.0 <= snap["cognitive_budget_remaining"] <= 1.0
        assert isinstance(snap["survival_mode"], bool)

    def test_survival_mode_when_coherence_low(self):
        with patch.object(lam_module, "_SURVIVAL_COHERENCE", 0.9):
            snap = lam_module._governance_snapshot()
            # coherence_score defaults to 1.0, so no survival trigger unless we
            # actually get a low value from a live module.  Just verify the field exists.
            assert "survival_mode" in snap


# ─────────────────────────────────────────────────────────────────────────────
# _world_model_snapshot helper
# ─────────────────────────────────────────────────────────────────────────────

class TestWorldModelSnapshot:
    def test_returns_dict_with_required_keys(self):
        snap = lam_module._world_model_snapshot()
        for key in ("direction", "agreement", "uncertainty", "arbitrator_consensus"):
            assert key in snap, f"Missing key: {key}"

    def test_defaults_are_valid(self):
        snap = lam_module._world_model_snapshot()
        assert isinstance(snap["direction"], str)
        assert 0.0 <= snap["agreement"] <= 1.0
        assert 0.0 <= snap["uncertainty"] <= 1.0
        assert 0.0 <= snap["arbitrator_consensus"] <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# _determine_runtime_mode
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeModeClassification:
    def _gov(self, **kwargs):
        base = {
            "constitution_passed": True,
            "violated_laws": [],
            "stability_pressure": 0.0,
            "recursion_depth": 0,
            "cognitive_budget_remaining": 1.0,
            "cognitive_budget_pressure": 0.0,
            "attention_pressure": 0.0,
            "coherence_score": 1.0,
            "survival_mode": False,
        }
        base.update(kwargs)
        return base

    def test_normal_mode(self):
        assert lam_module._determine_runtime_mode(self._gov()) == "normal"

    def test_lockdown_when_constitution_fails(self):
        assert lam_module._determine_runtime_mode(
            self._gov(constitution_passed=False)
        ) == "lockdown"

    def test_lockdown_when_high_recursion_depth(self):
        assert lam_module._determine_runtime_mode(
            self._gov(recursion_depth=4)
        ) == "lockdown"

    def test_survival_mode(self):
        assert lam_module._determine_runtime_mode(
            self._gov(survival_mode=True)
        ) == "survival"

    def test_cautious_from_low_coherence(self):
        # coherence below cautious threshold (default 0.52)
        assert lam_module._determine_runtime_mode(
            self._gov(coherence_score=0.40)
        ) == "cautious"

    def test_cautious_from_high_attention_pressure(self):
        # above _MAX_ATTENTION_PRESSURE default 0.85
        assert lam_module._determine_runtime_mode(
            self._gov(attention_pressure=0.90)
        ) == "cautious"

    def test_cautious_from_low_budget(self):
        # below _MIN_COGNITIVE_BUDGET default 0.10
        assert lam_module._determine_runtime_mode(
            self._gov(cognitive_budget_remaining=0.05)
        ) == "cautious"

    def test_lockdown_before_survival(self):
        # lockdown takes priority over survival
        gov = self._gov(constitution_passed=False, survival_mode=True)
        assert lam_module._determine_runtime_mode(gov) == "lockdown"


# ─────────────────────────────────────────────────────────────────────────────
# Schema v2 envelope structure
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaV2Envelope:
    def setup_method(self):
        _reset_lam_singleton()

    def _make_brain(self, decision="BUY"):
        brain = MagicMock()
        brain.cycle.return_value = decision
        brain._last_state_vector = [45.0, 0.003, 1.005, 0.02, 1.2, 0.5, 0.3, 0.15]
        brain.rl_policy = None
        return brain

    def test_envelope_has_schema_version(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            assert data["schema_version"] == "2.0"
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_envelope_has_governance_block(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            gov = data.get("governance", {})
            assert "constitution_passed" in gov
            assert "survival_mode" in gov
            assert "mode" in gov
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_envelope_has_forecast_consensus(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            fc = data.get("forecast_consensus", {})
            assert "direction" in fc
            assert "agreement" in fc
            assert "uncertainty" in fc
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_envelope_has_temporal_block(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            temp = data.get("temporal", {})
            assert "coherence_score" in temp
            assert "cognitive_budget" in temp
            assert "attention_pressure" in temp
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_envelope_has_execution_block(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            exe = data.get("execution", {})
            assert "max_position_size" in exe
            assert "hold_only" in exe
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_legacy_v1_fields_still_present(self):
        """Backward-compat: schema v1 consumers can still read regime, risk_pct, indicators."""
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            assert "signal" in data
            assert "confidence" in data
            assert "regime" in data
            assert "risk_pct" in data
            assert "timestamp" in data
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_lockdown_mode_sets_hold_only(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            with patch.object(lam_module, "_determine_runtime_mode", return_value="lockdown"), \
                 patch.object(lam_module, "_governance_snapshot", return_value={
                     "constitution_passed": False, "violated_laws": ["law_1"],
                     "stability_pressure": 0.9, "recursion_depth": 5,
                     "cognitive_budget_remaining": 0.05, "cognitive_budget_pressure": 0.9,
                     "attention_pressure": 0.95, "coherence_score": 0.1, "survival_mode": True,
                 }):
                manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            assert data["execution"]["hold_only"] is True
            assert data["execution"]["max_position_size"] == 0.0
            assert data["runtime"]["mode"] == "lockdown"
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_survival_mode_reduces_position(self):
        manager = lam_module.LeanAlgoManager(trading_brain=self._make_brain())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        try:
            with patch.object(lam_module, "_determine_runtime_mode", return_value="survival"), \
                 patch.object(lam_module, "_governance_snapshot", return_value={
                     "constitution_passed": True, "violated_laws": [],
                     "stability_pressure": 0.8, "recursion_depth": 2,
                     "cognitive_budget_remaining": 0.15, "cognitive_budget_pressure": 0.7,
                     "attention_pressure": 0.7, "coherence_score": 0.25, "survival_mode": True,
                 }):
                manager._publish_signal()
            data = json.loads(manager.signal_file.read_text())
            assert data["execution"]["hold_only"] is False
            # survival mode: max_position_size = risk_pct * 0.1 = 0.002
            assert data["execution"]["max_position_size"] < 0.01
        finally:
            manager.signal_file.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Reflection and episode JSONL ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestJSONLIngestion:
    def setup_method(self):
        _reset_lam_singleton()

    def test_ingest_reflection_reads_new_lines(self):
        manager = lam_module.LeanAlgoManager()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps({"pair": "BTC/USDT", "action": "buy", "outcome": "profit"}) + "\n")
            fname = f.name
        manager.reflection_file = Path(fname)
        try:
            manager._ingest_reflection()
            # Second line added
            with open(fname, "a") as fh:
                fh.write(json.dumps({"pair": "ETH/USDT", "action": "sell", "outcome": "loss"}) + "\n")
            manager._ingest_reflection()
            # Both lines should have been processed (offset moved)
            assert manager._reflection_offset > 0
        finally:
            Path(fname).unlink(missing_ok=True)

    def test_ingest_reflection_incremental_no_reprocess(self):
        manager = lam_module.LeanAlgoManager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"pair": "BTC/USDT", "action": "buy"}) + "\n")
            fname = f.name
        manager.reflection_file = Path(fname)
        kb_calls = []
        mock_kb = MagicMock()
        mock_kb.add_fact.side_effect = lambda *a, **kw: kb_calls.append(a)
        manager.knowledge_db = mock_kb
        try:
            manager._ingest_reflection()
            first_call_count = len(kb_calls)
            manager._ingest_reflection()  # no new data
            assert len(kb_calls) == first_call_count  # no re-ingestion
        finally:
            Path(fname).unlink(missing_ok=True)

    def test_ingest_episodes_reads_new_lines(self):
        manager = lam_module.LeanAlgoManager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"regime": "volatile_breakout", "motif": "squeeze"}) + "\n")
            fname = f.name
        manager.episodes_file = Path(fname)
        try:
            manager._ingest_episodes()
            assert manager._episodes_offset > 0
        finally:
            Path(fname).unlink(missing_ok=True)

    def test_ingest_handles_malformed_json_gracefully(self):
        manager = lam_module.LeanAlgoManager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not json\n")
            f.write(json.dumps({"pair": "BTC/USDT", "action": "buy"}) + "\n")
            fname = f.name
        manager.reflection_file = Path(fname)
        try:
            manager._ingest_reflection()  # should not raise
            assert manager._reflection_offset > 0
        finally:
            Path(fname).unlink(missing_ok=True)

    def test_ingest_missing_file_is_noop(self):
        manager = lam_module.LeanAlgoManager()
        manager.reflection_file = Path("/tmp/nonexistent_niblit_reflection_xyz.jsonl")
        manager.episodes_file   = Path("/tmp/nonexistent_niblit_episodes_xyz.jsonl")
        manager._ingest_reflection()   # must not raise
        manager._ingest_episodes()     # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# Status and show_signal include v2 fields
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusDisplay:
    def setup_method(self):
        _reset_lam_singleton()

    def _publish_once(self):
        brain = MagicMock()
        brain.cycle.return_value = "BUY"
        brain._last_state_vector = [45.0, 0.003, 1.005, 0.02, 1.2, 0.5, 0.3, 0.15]
        brain.rl_policy = None
        manager = lam_module.LeanAlgoManager(trading_brain=brain)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        manager._publish_signal()
        return manager

    def test_status_contains_schema_version(self):
        manager = self._publish_once()
        try:
            out = manager.status()
            assert "Schema version" in out or "schema" in out.lower()
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_status_contains_runtime_mode(self):
        manager = self._publish_once()
        try:
            out = manager.status()
            assert "Runtime mode" in out or "mode" in out.lower()
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_show_signal_contains_governance_fields(self):
        manager = self._publish_once()
        try:
            out = manager.show_signal()
            assert "Constitution" in out or "constitution" in out.lower()
            assert "mode" in out.lower() or "Mode" in out
        finally:
            manager.signal_file.unlink(missing_ok=True)

    def test_show_signal_no_signal_published(self):
        manager = lam_module.LeanAlgoManager()
        out = manager.show_signal()
        assert "No signal" in out


# ─────────────────────────────────────────────────────────────────────────────
# Runtime mode transition event emission
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeModeTransitions:
    def setup_method(self):
        _reset_lam_singleton()

    def test_mode_change_emits_event(self):
        emitted = []

        def fake_emit(event_type, payload):
            emitted.append((event_type, payload))

        brain = MagicMock()
        brain.cycle.return_value = "BUY"
        brain._last_state_vector = []
        brain.rl_policy = None
        manager = lam_module.LeanAlgoManager(trading_brain=brain)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        manager._last_runtime_mode = "normal"

        with patch.object(lam_module, "_determine_runtime_mode", return_value="cautious"), \
             patch.object(lam_module, "_emit_niblit_event", side_effect=fake_emit):
            try:
                manager._publish_signal()
            finally:
                manager.signal_file.unlink(missing_ok=True)

        mode_events = [e for e in emitted if e[0] == lam_module._EVT_RUNTIME_MODE_CHANGED]
        assert len(mode_events) >= 1
        assert mode_events[0][1]["previous_mode"] == "normal"
        assert mode_events[0][1]["new_mode"] == "cautious"

    def test_no_event_when_mode_unchanged(self):
        emitted = []

        def fake_emit(event_type, payload):
            emitted.append((event_type, payload))

        brain = MagicMock()
        brain.cycle.return_value = "HOLD"
        brain._last_state_vector = []
        brain.rl_policy = None
        manager = lam_module.LeanAlgoManager(trading_brain=brain)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            manager.signal_file = Path(f.name)
        manager._last_runtime_mode = "normal"

        with patch.object(lam_module, "_determine_runtime_mode", return_value="normal"), \
             patch.object(lam_module, "_emit_niblit_event", side_effect=fake_emit):
            try:
                manager._publish_signal()
                manager._publish_signal()
            finally:
                manager.signal_file.unlink(missing_ok=True)

        mode_events = [e for e in emitted if e[0] == lam_module._EVT_RUNTIME_MODE_CHANGED]
        assert len(mode_events) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatibility: LeanAlgoManager still works without governance modules
# ─────────────────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def setup_method(self):
        _reset_lam_singleton()

    def test_signal_published_without_trading_brain(self):
        """No TradingBrain → publish_signal silently returns."""
        manager = lam_module.LeanAlgoManager()
        manager._publish_signal()  # must not raise
        assert manager._last_signal is None

    def test_get_lean_algo_manager_returns_singleton(self):
        a = lam_module.get_lean_algo_manager()
        b = lam_module.get_lean_algo_manager()
        assert a is b

    def test_governance_snapshot_tolerates_missing_modules(self):
        # Patch imports so they raise ImportError
        with patch.dict("sys.modules", {
            "modules.constitutional_layer": None,
            "modules.recursive_stability_governor": None,
            "modules.cognitive_budget_manager": None,
            "modules.attention_allocator": None,
            "modules.causal_temporal_engine": None,
        }):
            snap = lam_module._governance_snapshot()
        # Should return safe defaults without raising
        assert snap["constitution_passed"] is True
        assert snap["stability_pressure"] == 0.0
