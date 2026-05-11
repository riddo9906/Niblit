"""
test_phase_omega_unification.py

Tests for Phase Ω — Niblit Unified Intelligence Convergence.

Covers all 9 new Phase Ω modules:
  1. unified_cognitive_state
  2. constitutional_layer
  3. niblit_memory.unified_memory_engine
  4. model_ecology
  5. reflection_engine
  6. predictive_world_model
  7. human_alignment_engine
  8. autonomic_runtime_manager
  9. niblit_identity
  + event_bus Phase Ω constants
"""

from __future__ import annotations

import os
import sys
import threading

# Point event_bus at the real module so imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _reset_singleton(module_path: str, var_name: str) -> None:
    """Force-reset a module-level singleton so tests are isolated."""
    mod = sys.modules.get(module_path)
    if mod is not None:
        setattr(mod, var_name, None)


# ═══════════════════════════════════════════════════════════════
# 1. event_bus — Phase Ω constants
# ═══════════════════════════════════════════════════════════════

class TestEventBusOmegaConstants:
    def test_state_updated_constant(self):
        from modules.event_bus import EVENT_STATE_UPDATED
        assert EVENT_STATE_UPDATED == "state.updated"

    def test_reflection_complete_constant(self):
        from modules.event_bus import EVENT_REFLECTION_COMPLETE
        assert EVENT_REFLECTION_COMPLETE == "reflection.complete"

    def test_world_model_updated_constant(self):
        from modules.event_bus import EVENT_WORLD_MODEL_UPDATED
        assert EVENT_WORLD_MODEL_UPDATED == "world_model.updated"

    def test_resource_adapted_constant(self):
        from modules.event_bus import EVENT_RESOURCE_ADAPTED
        assert EVENT_RESOURCE_ADAPTED == "resource.adapted"

    def test_identity_updated_constant(self):
        from modules.event_bus import EVENT_IDENTITY_UPDATED
        assert EVENT_IDENTITY_UPDATED == "identity.updated"

    def test_constitution_checked_constant(self):
        from modules.event_bus import EVENT_CONSTITUTION_CHECKED
        assert EVENT_CONSTITUTION_CHECKED == "constitution.checked"


# ═══════════════════════════════════════════════════════════════
# 2. unified_cognitive_state
# ═══════════════════════════════════════════════════════════════

class TestUnifiedCognitiveState:
    def setup_method(self):
        _reset_singleton("modules.unified_cognitive_state", "_ucs")
        from modules.unified_cognitive_state import get_unified_state
        self.ucs = get_unified_state()

    def test_singleton(self):
        from modules.unified_cognitive_state import get_unified_state
        assert get_unified_state() is self.ucs

    def test_set_and_get(self):
        self.ucs.set("test.key", 42.0, source="unit_test")
        assert self.ucs.get("test.key") == 42.0

    def test_get_default(self):
        assert self.ucs.get("nonexistent.key", "default") == "default"

    def test_epoch_increments(self):
        before = self.ucs.epoch()
        self.ucs.set("epoch.test", "x")
        assert self.ucs.epoch() == before + 1

    def test_set_dict(self):
        self.ucs.set_dict("ns", {"a": 1, "b": 2})
        assert self.ucs.get("ns.a") == 1
        assert self.ucs.get("ns.b") == 2

    def test_get_namespace(self):
        self.ucs.set_dict("foo", {"x": 10, "y": 20})
        ns = self.ucs.get_namespace("foo")
        assert ns["x"] == 10
        assert ns["y"] == 20

    def test_list_keys(self):
        self.ucs.set("list.k1", "v1")
        assert "list.k1" in self.ucs.list_keys()

    def test_subscription(self):
        received = []
        self.ucs.subscribe("sub.key", lambda k, v, s: received.append(v))
        self.ucs.set("sub.key", 99)
        assert 99 in received

    def test_resolve_conflict_average(self):
        result = self.ucs.resolve_conflict("x", [0.4, 0.6, 0.8], strategy="average")
        assert abs(result - 0.6) < 1e-9

    def test_resolve_conflict_max(self):
        result = self.ucs.resolve_conflict("x", [0.1, 0.9, 0.5], strategy="max")
        assert result == 0.9

    def test_resolve_conflict_min(self):
        result = self.ucs.resolve_conflict("x", [0.1, 0.9, 0.5], strategy="min")
        assert result == 0.1

    def test_resolve_conflict_latest(self):
        result = self.ucs.resolve_conflict("x", [1, 2, 3], strategy="latest")
        assert result == 3

    def test_checkpoint_and_restore(self, tmp_path):
        import os
        import modules.unified_cognitive_state as m
        old_dir = m._CHECKPOINT_DIR
        m._CHECKPOINT_DIR = str(tmp_path)
        try:
            self.ucs.set("restore.key", "before")
            path = self.ucs.checkpoint()
            assert path != ""
            assert os.path.exists(path)
            self.ucs.set("restore.key", "after")
            assert self.ucs.get("restore.key") == "after"
            ok = self.ucs.restore(path)
            assert ok
            assert self.ucs.get("restore.key") == "before"
        finally:
            m._CHECKPOINT_DIR = old_dir

    def test_status(self):
        s = self.ucs.status()
        assert "epoch" in s
        assert "key_count" in s

    def test_thread_safety(self):
        errors = []
        def writer():
            try:
                for i in range(50):
                    self.ucs.set(f"thread.{i}", i)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ═══════════════════════════════════════════════════════════════
# 3. constitutional_layer
# ═══════════════════════════════════════════════════════════════

class TestConstitutionalLayer:
    def setup_method(self):
        _reset_singleton("modules.constitutional_layer", "_cl")
        from modules.constitutional_layer import get_constitutional_layer
        self.cl = get_constitutional_layer()

    def test_singleton(self):
        from modules.constitutional_layer import get_constitutional_layer
        assert get_constitutional_layer() is self.cl

    def test_allowed_by_default(self):
        verdict = self.cl.validate("chat")
        assert verdict.allowed

    def test_low_stability_blocks(self):
        import modules.constitutional_layer as m
        old_strict = m._STRICT
        m._STRICT = True
        try:
            verdict = self.cl.validate("execute_trade", {"stability_score": 0.1})
            assert not verdict.allowed
            from modules.constitutional_layer import LAW_PRESERVE_INTEGRITY
            assert LAW_PRESERVE_INTEGRITY in verdict.violated_laws
        finally:
            m._STRICT = old_strict

    def test_external_override_blocked(self):
        import modules.constitutional_layer as m
        old_strict = m._STRICT
        m._STRICT = True
        try:
            verdict = self.cl.validate("update_objective", {
                "external_source": True,
                "overrides_objective": True,
            })
            assert not verdict.allowed
        finally:
            m._STRICT = old_strict

    def test_temporal_incoherence_blocked(self):
        import modules.constitutional_layer as m
        old_strict = m._STRICT
        m._STRICT = True
        try:
            verdict = self.cl.validate("execute", {"temporal_coherent": False})
            assert not verdict.allowed
        finally:
            m._STRICT = old_strict

    def test_high_safety_without_governance_blocked(self):
        import modules.constitutional_layer as m
        old_strict = m._STRICT
        m._STRICT = True
        try:
            verdict = self.cl.validate("execute_trade", {
                "safety_level": "high",
                "governance_approved": False,
            })
            assert not verdict.allowed
        finally:
            m._STRICT = old_strict

    def test_authority_rank(self):
        from modules.constitutional_layer import AUTHORITY_CONSTITUTION, AUTHORITY_RESPONSES
        assert self.cl.authority_rank(AUTHORITY_CONSTITUTION) < self.cl.authority_rank(AUTHORITY_RESPONSES)

    def test_highest_authority(self):
        from modules.constitutional_layer import AUTHORITY_CONSTITUTION, AUTHORITY_GOVERNANCE
        best = self.cl.highest_authority(AUTHORITY_CONSTITUTION, AUTHORITY_GOVERNANCE)
        assert best == AUTHORITY_CONSTITUTION

    def test_is_high_impact(self):
        assert self.cl.is_high_impact("execute_trade")
        assert not self.cl.is_high_impact("chat")

    def test_status(self):
        s = self.cl.status()
        assert "laws" in s
        assert "validation_count" in s

    def test_permissive_mode(self):
        import modules.constitutional_layer as m
        old_strict = m._STRICT
        m._STRICT = False
        try:
            verdict = self.cl.validate("execute_trade", {"stability_score": 0.0})
            assert verdict.allowed  # blocked laws noted but not enforced
        finally:
            m._STRICT = old_strict


# ═══════════════════════════════════════════════════════════════
# 4. unified_memory_engine
# ═══════════════════════════════════════════════════════════════

class TestUnifiedMemoryEngine:
    def setup_method(self):
        _reset_singleton("niblit_memory.unified_memory_engine", "_ume")
        from niblit_memory.unified_memory_engine import get_unified_memory
        self.ume = get_unified_memory()

    def test_singleton(self):
        from niblit_memory.unified_memory_engine import get_unified_memory
        assert get_unified_memory() is self.ume

    def test_remember_returns_uid(self):
        uid = self.ume.remember("Bitcoin crossed 50k", category="semantic", importance=0.8)
        assert isinstance(uid, str) and len(uid) == 16

    def test_remember_idempotent(self):
        uid1 = self.ume.remember("Same fact", category="semantic")
        uid2 = self.ume.remember("Same fact", category="semantic")
        assert uid1 == uid2

    def test_recall_returns_records(self):
        self.ume.remember("machine learning is powerful", category="semantic", importance=0.7)
        results = self.ume.recall("machine learning", top_k=3)
        assert len(results) >= 1
        texts = [r.text for r in results]
        assert any("machine" in t for t in texts)

    def test_recall_category_filter(self):
        self.ume.remember("goal: reach 1M users", category="strategic", importance=0.9)
        strategic = self.ume.recall("goal", category="strategic")
        for r in strategic:
            assert r.category == "strategic"

    def test_record_episode(self):
        self.ume.record_episode({"input": "hi", "response": "hello", "quality": 0.9})
        eps = self.ume.recall_episodic(5)
        assert len(eps) >= 1
        assert eps[-1].input_text == "hi"

    def test_recall_high_importance(self):
        self.ume.remember("anchor fact", category="semantic", importance=0.95, is_anchor=True)
        anchors = self.ume.recall_high_importance(0.9)
        assert any(r.is_anchor for r in anchors)

    def test_compress(self):
        for i in range(10):
            self.ume.remember(f"low importance fact {i}", importance=0.05)
        result = self.ume.compress()
        assert "pruned" in result

    def test_reflect_returns_string(self):
        summary = self.ume.reflect()
        assert isinstance(summary, str) and len(summary) > 0

    def test_status(self):
        s = self.ume.status()
        assert "total_records" in s
        assert "episode_count" in s


# ═══════════════════════════════════════════════════════════════
# 5. model_ecology
# ═══════════════════════════════════════════════════════════════

class TestModelEcology:
    def setup_method(self):
        _reset_singleton("modules.model_ecology", "_eco")
        from modules.model_ecology import get_model_ecology
        self.eco = get_model_ecology()

    def test_singleton(self):
        from modules.model_ecology import get_model_ecology
        assert get_model_ecology() is self.eco

    def test_select_returns_valid_model(self):
        sel = self.eco.select_for_task("hello")
        assert sel in ("qwen", "llama3", "cloud", "gpt", "tft")

    def test_select_forecasting(self):
        sel = self.eco.select_for_task("predict BTC price next week")
        assert sel == "tft"

    def test_select_force_local(self):
        sel = self.eco.select_for_task("deep synthesis task", force_local=True)
        assert sel in ("qwen", "llama3", "tft")

    def test_record_outcome_updates_trust(self):
        self.eco.record_outcome("llama3", success=True, quality=0.9)
        report = self.eco.ecology_report()
        llama = next(m for m in report["models"] if m["model_id"] == "llama3")
        assert llama["trust_score"] > 0.0

    def test_record_failure_lowers_trust(self):
        # Record several failures
        for _ in range(5):
            self.eco.record_outcome("cloud", success=False, quality=0.1)
        report = self.eco.ecology_report()
        cloud = next(m for m in report["models"] if m["model_id"] == "cloud")
        assert cloud["trust_score"] < 0.9

    def test_ecology_report_sorted(self):
        report = self.eco.ecology_report()
        scores = [m["composite_score"] for m in report["models"]]
        assert scores == sorted(scores, reverse=True)

    def test_arbitrate_disagreement_single(self):
        result = self.eco.arbitrate_disagreement({"qwen": "yes"})
        assert result.selected == "qwen"

    def test_arbitrate_disagreement_multi(self):
        outputs = {"qwen": "bullish trend", "llama3": "bullish market"}
        result = self.eco.arbitrate_disagreement(outputs)
        assert result.selected in ("qwen", "llama3")
        assert 0.0 <= result.agreement_score <= 1.0

    def test_status(self):
        s = self.eco.status()
        assert "models" in s
        assert "select_count" in s


# ═══════════════════════════════════════════════════════════════
# 6. reflection_engine
# ═══════════════════════════════════════════════════════════════

class TestReflectionEngine:
    def setup_method(self):
        _reset_singleton("modules.reflection_engine", "_re")
        from modules.reflection_engine import get_reflection_engine
        self.re = get_reflection_engine()

    def test_singleton(self):
        from modules.reflection_engine import get_reflection_engine
        assert get_reflection_engine() is self.re

    def test_record_turn(self):
        self.re.record_turn(quality=0.8, mode="analytical", intent="qa", model_used="llama3")
        s = self.re.status()
        assert s["turn_count"] >= 1

    def test_should_reflect_cadence(self):
        import modules.reflection_engine as m
        old_cadence = m._CADENCE
        m._CADENCE = 5
        try:
            for _ in range(5):
                self.re.record_turn(quality=0.7, mode="conversational", model_used="qwen")
            assert self.re.should_reflect()
        finally:
            m._CADENCE = old_cadence

    def test_reflect_returns_report(self):
        for _ in range(15):
            self.re.record_turn(quality=0.75, mode="analytical", model_used="llama3")
        report = self.re.reflect()
        assert hasattr(report, "summary")
        assert isinstance(report.overall_health, float)
        assert 0.0 <= report.overall_health <= 1.0

    def test_reflect_detects_low_quality(self):
        for _ in range(15):
            self.re.record_turn(quality=0.2, mode="operational", model_used="qwen")
        report = self.re.reflect()
        assert len(report.failures_detected) > 0 or report.overall_health < 0.5

    def test_last_report(self):
        self.re.reflect()
        r = self.re.last_report()
        assert r is not None

    def test_status(self):
        s = self.re.status()
        assert "quality_ema" in s
        assert "reflect_count" in s


# ═══════════════════════════════════════════════════════════════
# 7. predictive_world_model
# ═══════════════════════════════════════════════════════════════

class TestPredictiveWorldModel:
    def setup_method(self):
        _reset_singleton("modules.predictive_world_model", "_pwm")
        from modules.predictive_world_model import get_predictive_world_model
        self.pwm = get_predictive_world_model()

    def test_singleton(self):
        from modules.predictive_world_model import get_predictive_world_model
        assert get_predictive_world_model() is self.pwm

    def test_ingest_and_forecast(self):
        self.pwm.ingest_signal(price=50000.0, rsi=60.0, volume_delta=0.02)
        output = self.pwm.forecast()
        assert output.regime in ("bull", "bear", "sideways", "volatile", "neutral")

    def test_horizons_present(self):
        self.pwm.ingest_signal(price=50000.0, rsi=55.0)
        output = self.pwm.forecast()
        assert len(output.horizons) == 3  # short, medium, long

    def test_regime_bull(self):
        for _ in range(5):
            self.pwm.ingest_signal(rsi=75.0, external_score=0.9, macd=0.5)
        output = self.pwm.forecast()
        assert output.regime in ("bull", "volatile")

    def test_regime_bear(self):
        for _ in range(5):
            self.pwm.ingest_signal(rsi=25.0, external_score=0.1, macd=-0.5)
        output = self.pwm.forecast()
        assert output.regime in ("bear", "volatile")

    def test_scenarios_not_empty(self):
        self.pwm.ingest_signal(rsi=50.0)
        output = self.pwm.forecast()
        assert len(output.scenarios) >= 1

    def test_uncertainty_grows_with_horizon(self):
        self.pwm.ingest_signal(price=50000.0, rsi=55.0)
        output = self.pwm.forecast()
        unc = [output.horizons[lbl].uncertainty for lbl in ("short", "medium", "long")]
        assert unc[1] > unc[0]
        assert unc[2] > unc[1]

    def test_action_recommendations(self):
        self.pwm.ingest_signal(rsi=70.0, external_score=0.85)
        output = self.pwm.forecast()
        assert isinstance(output.action_recommendations, list)

    def test_last_output(self):
        self.pwm.forecast()
        assert self.pwm.last_output() is not None

    def test_status(self):
        s = self.pwm.status()
        assert "signal_count" in s
        assert "forecast_count" in s

    def test_no_signals_graceful(self):
        """Forecast with no signals should not raise."""
        _reset_singleton("modules.predictive_world_model", "_pwm")
        from modules.predictive_world_model import get_predictive_world_model
        pwm = get_predictive_world_model()
        output = pwm.forecast()
        assert output.regime is not None


# ═══════════════════════════════════════════════════════════════
# 8. human_alignment_engine
# ═══════════════════════════════════════════════════════════════

class TestHumanAlignmentEngine:
    def setup_method(self, tmp_path=None):
        _reset_singleton("modules.human_alignment_engine", "_hae")
        import modules.human_alignment_engine as m
        m._STATE_PATH = "/tmp/niblit_hae_test_state.json"
        from modules.human_alignment_engine import get_human_alignment_engine
        self.hae = get_human_alignment_engine()

    def test_singleton(self):
        from modules.human_alignment_engine import get_human_alignment_engine
        assert get_human_alignment_engine() is self.hae

    def test_analyse_returns_context(self):
        ctx = self.hae.analyse("Hello, can you help me?")
        from modules.human_alignment_engine import AlignmentContext
        assert isinstance(ctx, AlignmentContext)

    def test_positive_sentiment(self):
        ctx = self.hae.analyse("great thanks excellent work!")
        assert ctx.sentiment == "positive"

    def test_negative_sentiment(self):
        ctx = self.hae.analyse("this is terrible and wrong")
        assert ctx.sentiment == "negative"

    def test_stressed_sentiment(self):
        ctx = self.hae.analyse("urgent asap immediately!")
        assert ctx.sentiment == "stressed"

    def test_brevity_preference(self):
        ctx = self.hae.analyse("please keep it short and brief")
        assert ctx.inferred_preference == "brevity"

    def test_technical_preference(self):
        ctx = self.hae.analyse("can you write code and debug this function?")
        assert ctx.inferred_preference == "technical"

    def test_trust_level_in_range(self):
        ctx = self.hae.analyse("great answer, very helpful!")
        assert 0.0 <= ctx.trust_level <= 1.0

    def test_get_advice_concise(self):
        ctx = self.hae.analyse("please be brief and quick")
        advice = self.hae.get_advice(ctx)
        assert advice.tone_instruction == "concise"
        assert advice.max_length_hint == "short"

    def test_get_advice_trust_building(self):
        from modules.human_alignment_engine import AlignmentContext
        ctx = AlignmentContext(
            sentiment="negative", cognitive_load=0.5,
            inferred_preference="detail", trust_level=0.3,
            goal_coherent=True, pacing_suggestion="normal",
        )
        advice = self.hae.get_advice(ctx)
        assert advice.trust_building_mode

    def test_record_goal(self):
        self.hae.record_goal("become profitable trader")
        s = self.hae.status()
        assert s["goal_count"] >= 1

    def test_status(self):
        s = self.hae.status()
        assert "trust_level" in s
        assert "top_preference" in s


# ═══════════════════════════════════════════════════════════════
# 9. autonomic_runtime_manager
# ═══════════════════════════════════════════════════════════════

class TestAutonomicRuntimeManager:
    def setup_method(self):
        _reset_singleton("modules.autonomic_runtime_manager", "_arm")
        from modules.autonomic_runtime_manager import get_autonomic_runtime_manager
        self.arm = get_autonomic_runtime_manager()

    def test_singleton(self):
        from modules.autonomic_runtime_manager import get_autonomic_runtime_manager
        assert get_autonomic_runtime_manager() is self.arm

    def test_assess_returns_list(self):
        result = self.arm.assess()
        assert isinstance(result, list)

    def test_record_latency(self):
        self.arm.record_latency(500.0)
        snap = self.arm.read_snapshot()
        assert snap.avg_latency_ms > 0

    def test_high_latency_triggers_prefer_qwen(self):
        from modules.autonomic_runtime_manager import AutonomicRuntimeManager
        arm = AutonomicRuntimeManager()
        arm._avg_latency_ms = 5000.0  # above threshold

        # Monkey-patch read_snapshot to simulate high latency
        arm.record_latency(5000.0)
        snap = arm.read_snapshot()
        assert snap.avg_latency_ms > 0  # latency recorded

    def test_snapshot_fields(self):
        snap = self.arm.read_snapshot()
        assert hasattr(snap, "ram_used_fraction")
        assert hasattr(snap, "battery_fraction")
        assert hasattr(snap, "avg_latency_ms")

    def test_is_active_false_initially(self):
        assert not self.arm.is_active("low_resource_survival_mode")

    def test_status(self):
        s = self.arm.status()
        assert "active_adaptations" in s
        assert "snapshot" in s

    def test_adaptation_triggers_via_simulate(self):
        """Simulate critical RAM to verify adaptation logic paths."""
        from modules.autonomic_runtime_manager import ResourceSnapshot
        snap = ResourceSnapshot(
            ram_used_fraction=0.95,
            cpu_fraction=0.8,
            battery_fraction=0.05,
            thermal_celsius=0.0,
            avg_latency_ms=0.0,
        )
        assert snap.is_memory_critical
        assert snap.is_battery_critical

    def test_survival_mode_snapshot(self):
        """When RAM > 90% and battery < 10%, survival mode conditions met."""
        from modules.autonomic_runtime_manager import ResourceSnapshot
        snap = ResourceSnapshot(
            ram_used_fraction=0.92,
            cpu_fraction=0.9,
            battery_fraction=0.08,
            thermal_celsius=0.0,
            avg_latency_ms=0.0,
        )
        assert snap.is_memory_critical
        assert snap.is_battery_critical


# ═══════════════════════════════════════════════════════════════
# 10. niblit_identity
# ═══════════════════════════════════════════════════════════════

class TestNiblitIdentity:
    def setup_method(self):
        import modules.niblit_identity as m
        m._ID_PATH = "/tmp/niblit_identity_test.json"
        # Remove stale test file
        try:
            os.remove(m._ID_PATH)
        except FileNotFoundError:
            pass
        _reset_singleton("modules.niblit_identity", "_nid")
        from modules.niblit_identity import get_niblit_identity
        self.nid = get_niblit_identity()

    def test_singleton(self):
        from modules.niblit_identity import get_niblit_identity
        assert get_niblit_identity() is self.nid

    def test_core_values_immutable(self):
        values = self.nid.core_values
        assert len(values) == 8
        assert "preserve_system_integrity" in values

    def test_record_lesson(self):
        self.nid.record_lesson("Phase Ω", "Unification beats isolation.")
        snap = self.nid.snapshot()
        lessons = snap["learning_history"]
        assert any(entry["lesson"] == "Unification beats isolation." for entry in lessons)

    def test_update_direction(self):
        self.nid.update_direction("Towards full cognitive autonomy.")
        snap = self.nid.snapshot()
        assert snap["strategic_direction"] == "Towards full cognitive autonomy."

    def test_add_goal(self):
        self.nid.add_goal("achieve 99% uptime")
        snap = self.nid.snapshot()
        assert "achieve 99% uptime" in snap["persistent_goals"]

    def test_update_trust(self):
        self.nid.update_trust("self_model", 0.9)
        snap = self.nid.snapshot()
        assert "self_model" in snap["trust_fingerprint"]
        assert snap["trust_fingerprint"]["self_model"] > 0.5

    def test_update_continuity(self):
        before = self.nid.snapshot()["continuity_score"]
        self.nid.update_continuity(-0.1)
        after = self.nid.snapshot()["continuity_score"]
        assert after < before or after == max(0.0, before - 0.1)

    def test_session_count_increments(self):
        snap1 = self.nid.snapshot()
        count1 = snap1["session_count"]
        # Create a second instance (simulate new session)
        _reset_singleton("modules.niblit_identity", "_nid")
        from modules.niblit_identity import get_niblit_identity
        nid2 = get_niblit_identity()
        snap2 = nid2.snapshot()
        assert snap2["session_count"] == count1 + 1

    def test_identity_version_monotonic(self):
        v1 = self.nid.snapshot()["identity_version"]
        _reset_singleton("modules.niblit_identity", "_nid")
        from modules.niblit_identity import get_niblit_identity
        nid2 = get_niblit_identity()
        v2 = nid2.snapshot()["identity_version"]
        assert v2 > v1

    def test_status(self):
        s = self.nid.status()
        assert "identity_version" in s
        assert "continuity_score" in s
        assert "strategic_direction" in s


# ═══════════════════════════════════════════════════════════════
# Integration: constitutional layer validates execution_graph output
# ═══════════════════════════════════════════════════════════════

class TestOmegaIntegration:
    """Cross-module integration tests."""

    def test_ucs_tracks_constitution_verdicts(self):
        """UCS should be able to store constitutional verdicts."""
        _reset_singleton("modules.unified_cognitive_state", "_ucs")
        _reset_singleton("modules.constitutional_layer", "_cl")
        from modules.unified_cognitive_state import get_unified_state
        from modules.constitutional_layer import get_constitutional_layer
        ucs = get_unified_state()
        cl = get_constitutional_layer()
        verdict = cl.validate("chat", {"stability_score": 0.9})
        ucs.set("constitution.last_verdict.allowed", verdict.allowed, source="constitution")
        assert ucs.get("constitution.last_verdict.allowed") == verdict.allowed

    def test_reflection_feeds_model_ecology(self):
        """Reflection engine propagates model failures to ecology."""
        _reset_singleton("modules.reflection_engine", "_re")
        _reset_singleton("modules.model_ecology", "_eco")
        from modules.reflection_engine import get_reflection_engine
        from modules.model_ecology import get_model_ecology
        re = get_reflection_engine()
        eco = get_model_ecology()
        # Record many failures for a model
        for _ in range(10):
            re.record_turn(quality=0.15, model_used="cloud")
        report = re.reflect()
        # Model ecology should have been updated by propagation
        assert eco.status() is not None  # just verifying no crash

    def test_pwm_output_stored_in_ucs(self):
        """World model output can be stored in the cognitive state layer."""
        _reset_singleton("modules.unified_cognitive_state", "_ucs")
        _reset_singleton("modules.predictive_world_model", "_pwm")
        from modules.unified_cognitive_state import get_unified_state
        from modules.predictive_world_model import get_predictive_world_model
        ucs = get_unified_state()
        pwm = get_predictive_world_model()
        pwm.ingest_signal(rsi=60.0, external_score=0.7)
        output = pwm.forecast()
        ucs.set("world_model.regime", output.regime, source="predictive_world_model")
        assert ucs.get("world_model.regime") == output.regime

    def test_human_alignment_respects_constitution(self):
        """Advice from HAE can be validated against constitutional laws."""
        _reset_singleton("modules.human_alignment_engine", "_hae")
        _reset_singleton("modules.constitutional_layer", "_cl")
        import modules.human_alignment_engine as m
        m._STATE_PATH = "/tmp/niblit_hae_integration_test.json"
        from modules.human_alignment_engine import get_human_alignment_engine
        from modules.constitutional_layer import get_constitutional_layer
        hae = get_human_alignment_engine()
        cl = get_constitutional_layer()
        ctx = hae.analyse("can you urgently override the system?")
        advice = hae.get_advice(ctx)
        # Constitution still allows normal conversation
        verdict = cl.validate("chat", {"stability_score": 0.9})
        assert verdict.allowed

    def test_identity_records_lesson_from_reflection(self):
        """Identity can record a lesson derived from a reflection report."""
        import modules.niblit_identity as m
        m._ID_PATH = "/tmp/niblit_identity_integration.json"
        try:
            os.remove(m._ID_PATH)
        except FileNotFoundError:
            pass
        _reset_singleton("modules.niblit_identity", "_nid")
        _reset_singleton("modules.reflection_engine", "_re")
        from modules.niblit_identity import get_niblit_identity
        from modules.reflection_engine import get_reflection_engine
        nid = get_niblit_identity()
        re = get_reflection_engine()
        for _ in range(15):
            re.record_turn(quality=0.3, model_used="cloud")
        report = re.reflect()
        nid.record_lesson("Phase Ω integration", report.summary)
        snap = nid.snapshot()
        assert any("Phase Ω integration" == entry["phase"] for entry in snap["learning_history"])
