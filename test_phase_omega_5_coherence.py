"""Tests for Phase Ω.5 — Cognitive Coherence & Recursive Stability."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _reset_singleton(module_path: str, singleton_name: str) -> None:
    mod = sys.modules.get(module_path)
    if mod is not None:
        setattr(mod, singleton_name, None)


class TestEventBusOmega5Constants:
    def test_event_coherence_evaluated(self):
        from modules.event_bus import EVENT_COHERENCE_EVALUATED

        assert EVENT_COHERENCE_EVALUATED == "coherence.evaluated"

    def test_event_recursion_governed(self):
        from modules.event_bus import EVENT_RECURSION_GOVERNED

        assert EVENT_RECURSION_GOVERNED == "recursion.governed"

    def test_event_reality_validated(self):
        from modules.event_bus import EVENT_REALITY_VALIDATED

        assert EVENT_REALITY_VALIDATED == "reality.validated"

    def test_event_global_metrics_updated(self):
        from modules.event_bus import EVENT_GLOBAL_METRICS_UPDATED

        assert EVENT_GLOBAL_METRICS_UPDATED == "global.metrics.updated"


class TestCognitiveCoherenceEngine:
    def setup_method(self):
        _reset_singleton("modules.cognitive_coherence_engine", "_coherence_engine")
        from modules.cognitive_coherence_engine import get_cognitive_coherence_engine

        self.engine = get_cognitive_coherence_engine()

    def test_analyze_returns_report(self):
        report = self.engine.analyze()
        assert 0.0 <= report.coherence_score <= 1.0

    def test_detect_contradictions(self):
        contradictions = self.engine.detect_contradictions(
            {
                "reflection_engine": {"quality_ema": 0.2},
                "governance": {"stability_preservation_score": 0.9},
                "predictive_world_model": {"last_regime": "volatile"},
                "human_alignment_engine": {"trust_level": 0.3},
            }
        )
        assert len(contradictions) >= 1

    def test_measure_goal_alignment(self):
        score = self.engine.measure_goal_alignment(
            {
                "constitutional_layer": {"validation_count": 10, "block_count": 0},
                "niblit_identity": {"continuity_score": 0.9},
                "unified_cognitive_state": {"key_count": 30},
            }
        )
        assert 0.0 <= score <= 1.0

    def test_status(self):
        self.engine.analyze()
        status = self.engine.status()
        assert status["run_count"] >= 1


class TestRecursiveStabilityGovernor:
    def setup_method(self):
        _reset_singleton("modules.recursive_stability_governor", "_rsg")
        from modules.recursive_stability_governor import get_recursive_stability_governor

        self.gov = get_recursive_stability_governor()

    def test_record_and_evaluate(self):
        self.gov.record_adaptation_event("reflection_engine", 0.8)
        self.gov.record_adaptation_event("governance", 0.7)
        report = self.gov.evaluate()
        assert 0.0 <= report.stability_pressure <= 1.0

    def test_compute_velocity(self):
        self.gov.record_adaptation_event("a", 1.0)
        v = self.gov.compute_adaptation_velocity()
        assert 0.0 <= v <= 1.0

    def test_trace_recursive_loops(self):
        self.gov.record_adaptation_event("A", 0.1)
        self.gov.record_adaptation_event("B", 0.1)
        self.gov.record_adaptation_event("C", 0.1)
        self.gov.record_adaptation_event("A", 0.1)
        d = self.gov.trace_recursive_loops()
        assert d >= 0

    def test_status(self):
        s = self.gov.status()
        assert "event_count" in s


class TestRealityValidationEngine:
    def setup_method(self):
        _reset_singleton("modules.reality_validation_engine", "_rve")
        from modules.reality_validation_engine import get_reality_validation_engine

        self.rve = get_reality_validation_engine()

    def test_verify_prediction(self):
        out = self.rve.verify_prediction(0.8, 0.7, 0.9)
        assert "error" in out

    def test_validate_cycle(self):
        self.rve.verify_prediction(1.0, 0.5, 0.9, resonance_weight=0.4)
        report = self.rve.validate_cycle()
        assert 0.0 <= report.reality_score <= 1.0

    def test_status(self):
        s = self.rve.status()
        assert "pair_count" in s


class TestMetaGovernanceEngine:
    def setup_method(self):
        _reset_singleton("modules.meta_governance_engine", "_mge")
        from modules.meta_governance_engine import get_meta_governance_engine

        self.mge = get_meta_governance_engine()

    def test_register_and_evaluate(self):
        self.mge.register_influence("governance", 3.0, reason="policy clamp")
        self.mge.register_influence("reflection", 1.0, reason="quality update")
        report = self.mge.evaluate()
        assert 0.0 <= report.governance_saturation <= 1.0

    def test_block_rewrite(self):
        allowed = self.mge.attempt_constitutional_rewrite({"approved_by_human": False})
        assert allowed is False
        report = self.mge.evaluate()
        assert report.blocked_rewrites >= 1

    def test_status(self):
        assert "blocked_rewrites" in self.mge.status()


class TestCognitiveImmuneSystem:
    def setup_method(self):
        _reset_singleton("modules.cognitive_immune_system", "_cis")
        from modules.cognitive_immune_system import get_cognitive_immune_system

        self.cis = get_cognitive_immune_system()

    def test_scan_detects_anomalies(self):
        report = self.cis.scan(
            {
                "coherence_score": 0.2,
                "recursion_depth": 5,
                "governance_saturation": 0.9,
                "prediction_dependency": 0.8,
                "identity_integrity": 0.2,
            }
        )
        assert len(report.anomalies) >= 1
        assert isinstance(report.rollback_recommended, bool)

    def test_quarantine(self):
        self.cis.scan({"governance_saturation": 0.9})
        assert self.cis.is_quarantined("governance_evolution_engine")

    def test_status(self):
        s = self.cis.status()
        assert "quarantined_subsystems" in s


class TestCausalTemporalEngine:
    def setup_method(self):
        _reset_singleton("modules.causal_temporal_engine", "_cte")
        from modules.causal_temporal_engine import get_causal_temporal_engine

        self.cte = get_causal_temporal_engine()

    def test_record_expectation(self):
        eid = self.cte.record_expectation("planner", "raise_exploration", "more_diversity", time.time() + 30)
        assert isinstance(eid, str) and len(eid) > 0

    def test_reconcile_outcome(self):
        eid = self.cte.record_expectation("planner", "adjust", "ok", time.time() + 10)
        assert self.cte.reconcile_delayed_outcome(eid, "ok")

    def test_contradiction_tracking(self):
        eid = self.cte.record_expectation("planner", "adjust", "ok", time.time() + 10)
        self.cte.reconcile_delayed_outcome(eid, "bad")
        assert len(self.cte.temporal_contradictions()) >= 1

    def test_replay(self):
        self.cte.record_expectation("planner", "a", "b", time.time() + 5)
        rows = self.cte.replay_timeline(since=0)
        assert len(rows) >= 1

    def test_status(self):
        assert "episode_count" in self.cte.status()


class TestEmergenceMonitor:
    def setup_method(self):
        _reset_singleton("modules.emergence_monitor", "_em")
        from modules.emergence_monitor import get_emergence_monitor

        self.em = get_emergence_monitor()

    def test_observe_and_analyze(self):
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        report = self.em.analyze()
        assert 0.0 <= report.emergence_index <= 1.0

    def test_coalitions(self):
        self.em.observe_pattern("motif", ["a", "b"])
        self.em.observe_pattern("motif", ["a", "b"])
        report = self.em.analyze()
        assert any("a+b" == c for c in report.subsystem_coalitions)


class TestMultiAgentConsciousness:
    def setup_method(self):
        _reset_singleton("modules.multi_agent_consciousness", "_mac")
        from modules.multi_agent_consciousness import get_multi_agent_consciousness

        self.mac = get_multi_agent_consciousness()

    def test_register_agent(self):
        self.mac.register_agent("planner_agent")
        st = self.mac.status()
        assert st["agent_count"] >= 1

    def test_debate_memory_and_coalition(self):
        self.mac.register_agent("a")
        self.mac.register_agent("b")
        self.mac.record_debate("topic", ["a", "b"], winner="a", dissenters=["b"])
        st = self.mac.status()
        assert st["debate_memory_count"] >= 1

    def test_trust_edge(self):
        self.mac.update_trust("a", "b", 0.2)
        st = self.mac.status()
        assert st["trust_edge_count"] >= 1


class TestGlobalCognitiveMetrics:
    def setup_method(self):
        _reset_singleton("modules.global_cognitive_metrics", "_gcm")
        from modules.global_cognitive_metrics import get_global_cognitive_metrics

        self.gcm = get_global_cognitive_metrics()

    def test_refresh_keys(self):
        m = self.gcm.refresh()
        expected = {
            "coherence",
            "stability",
            "identity_integrity",
            "adaptation_velocity",
            "prediction_reliability",
            "governance_saturation",
            "memory_health",
            "emergence_index",
            "reflection_usefulness",
            "resonance_dependency",
            "causal_calibration",
            "human_alignment_stability",
        }
        assert expected.issubset(set(m.keys()))

    def test_status(self):
        self.gcm.refresh()
        st = self.gcm.status()
        assert "metrics" in st


class TestIdentityOmega5Upgrade:
    def setup_method(self):
        import modules.niblit_identity as m

        m._ID_PATH = "/tmp/niblit_identity_omega5_test.json"
        try:
            os.remove(m._ID_PATH)
        except FileNotFoundError:
            pass
        _reset_singleton("modules.niblit_identity", "_nid")
        from modules.niblit_identity import get_niblit_identity

        self.nid = get_niblit_identity()

    def test_behavioral_consistency(self):
        s = self.nid.behavioral_consistency_score({"self_model": 0.7})
        assert 0.0 <= s <= 1.0

    def test_value_integrity_check(self):
        out = self.nid.value_integrity_check(["preserve_system_integrity"])
        assert "score" in out
        assert out["is_valid"] in (True, False)

    def test_trajectory_validation(self):
        score = self.nid.validate_long_term_trajectory("Unify subsystems with stable governance")
        assert 0.0 <= score <= 1.0

    def test_identity_drift(self):
        drift = self.nid.detect_identity_drift({"self_model": 0.1})
        assert 0.0 <= drift <= 1.0

    def test_record_contradiction(self):
        self.nid.record_contradiction("test", {"k": "v"})
        snap = self.nid.snapshot()
        assert len(snap["contradiction_memory"]) >= 1

    def test_status_contains_omega5_fields(self):
        st = self.nid.status()
        assert "identity_drift_score" in st
        assert "behavioral_consistency_score" in st
        assert "contradiction_count" in st


class TestOmega5Integration:
    def test_coherence_to_immune_to_metrics_pipeline(self):
        _reset_singleton("modules.cognitive_coherence_engine", "_coherence_engine")
        _reset_singleton("modules.cognitive_immune_system", "_cis")
        _reset_singleton("modules.global_cognitive_metrics", "_gcm")
        from modules.cognitive_coherence_engine import get_cognitive_coherence_engine
        from modules.cognitive_immune_system import get_cognitive_immune_system
        from modules.global_cognitive_metrics import get_global_cognitive_metrics

        coherence = get_cognitive_coherence_engine().analyze()
        immune = get_cognitive_immune_system().scan(
            {"coherence_score": coherence.coherence_score, "identity_integrity": 0.9}
        )
        metrics = get_global_cognitive_metrics().refresh()
        assert isinstance(immune.rollback_recommended, bool)
        assert "coherence" in metrics

    def test_reality_and_temporal_consistency(self):
        _reset_singleton("modules.reality_validation_engine", "_rve")
        _reset_singleton("modules.causal_temporal_engine", "_cte")
        from modules.causal_temporal_engine import get_causal_temporal_engine
        from modules.reality_validation_engine import get_reality_validation_engine

        rve = get_reality_validation_engine()
        cte = get_causal_temporal_engine()
        eid = cte.record_expectation("forecast", "predict_up", "up", time.time() + 10)
        cte.reconcile_delayed_outcome(eid, "down")
        rve.verify_prediction(1.0, 0.0, 0.95, resonance_weight=0.8)
        report = rve.validate_cycle()
        assert report.calibration_error >= 0.0
        assert len(cte.temporal_contradictions()) >= 1
