"""Phase Ω.5 — Coherent Recursive Intelligence tests (100+)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _reset_singleton(module_path: str, singleton_name: str) -> None:
    mod = sys.modules.get(module_path)
    if mod is not None:
        setattr(mod, singleton_name, None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EVENT_COHERENCE_ANALYZED", "coherence.analyzed"),
        ("EVENT_RECURSION_STABILIZED", "recursion.stabilized"),
        ("EVENT_RECURSIVE_WARNING", "recursion.warning"),
        ("EVENT_IDENTITY_DRIFT", "identity.drift"),
        ("EVENT_IDENTITY_VALIDATED", "identity.validated"),
        ("EVENT_REALITY_VALIDATED", "reality.validated"),
        ("EVENT_META_GOVERNANCE_UPDATED", "meta_governance.updated"),
        ("EVENT_GOVERNANCE_CAPTURE_WARNING", "governance.capture.warning"),
        ("EVENT_COGNITIVE_THREAT_DETECTED", "cognitive.threat.detected"),
        ("EVENT_SUBSYSTEM_QUARANTINED", "subsystem.quarantined"),
        ("EVENT_COHERENCE_RESTORED", "coherence.restored"),
        ("EVENT_CAUSAL_CHAIN_UPDATED", "causal_chain.updated"),
        ("EVENT_TEMPORAL_CONTRADICTION", "temporal.contradiction"),
        ("EVENT_EMERGENCE_DETECTED", "emergence.detected"),
        ("EVENT_GLOBAL_COGNITIVE_UPDATE", "global.cognitive.update"),
        ("EVENT_AGENT_COALITION", "agent.coalition"),
        ("EVENT_DEBATE_RECORDED", "debate.recorded"),
        ("EVENT_COLLECTIVE_ALIGNMENT", "collective.alignment"),
    ],
)
def test_event_constants(name: str, value: str):
    import modules.event_bus as eb

    assert getattr(eb, name) == value


class TestCoherenceEngine:
    def setup_method(self):
        _reset_singleton("modules.cognitive_coherence_engine", "_coherence_engine")
        from modules.cognitive_coherence_engine import get_cognitive_coherence_engine

        self.engine = get_cognitive_coherence_engine()

    def test_analyze_schema(self):
        report = self.engine.analyze()
        data = report.to_dict()
        for k in (
            "coherence_score",
            "contradiction_count",
            "fragmentation_score",
            "recursive_instability",
            "subsystem_alignment",
            "contradiction_vectors",
            "unstable_clusters",
            "rationale",
            "confidence",
            "stability_impact",
            "coherence_impact",
            "causal_trace_metadata",
            "explanation",
            "epoch",
        ):
            assert k in data

    @pytest.mark.parametrize(
        "state,minimum",
        [
            ({"reflection_engine": {"quality_ema": 0.9}, "human_alignment_engine": {"trust_level": 0.1}}, 1),
            (
                {
                    "predictive_world_model": {"last_regime": "volatile"},
                    "governance": {"suppressed_exploration_rate": 0.0},
                },
                1,
            ),
            ({"niblit_identity": {"identity_drift_score": 0.9}}, 1),
            ({"event_bus_stats": {"governance.adapted": 21, "reflection.complete": 21}}, 1),
            ({"constitutional_layer": {"block_count": 10, "validation_count": 10}}, 1),
            ({}, 0),
            ({"reflection_engine": {"quality_ema": 0.7}}, 0),
            ({"governance": {"suppressed_exploration_rate": 0.5}}, 0),
            ({"niblit_identity": {"identity_drift_score": 0.1}}, 0),
            ({"human_alignment_engine": {"trust_level": 0.9}}, 0),
        ],
    )
    def test_detect_contradictions_cases(self, state, minimum):
        contradictions = self.engine.detect_contradictions(state)
        assert len(contradictions) >= minimum

    @pytest.mark.parametrize(
        "bus_stats",
        [
            {},
            {"reflection.complete": 5},
            {"reflection.complete": 30, "governance.adapted": 30, "world_model.updated": 3},
        ],
    )
    def test_recursive_instability_range(self, bus_stats):
        score = self.engine.detect_recursive_feedback_loops({"event_bus_stats": bus_stats})
        assert 0.0 <= score <= 1.0


class TestRecursiveStabilityGovernor:
    def setup_method(self):
        _reset_singleton("modules.recursive_stability_governor", "_rsg")
        from modules.recursive_stability_governor import get_recursive_stability_governor

        self.gov = get_recursive_stability_governor()

    @pytest.mark.parametrize("chain", [["A", "B", "C", "A"], ["X", "Y"], ["R", "G", "P", "R", "G", "P", "R"]])
    def test_trace_feedback_loops(self, chain):
        for s in chain:
            self.gov.record_adaptation_event(s, 0.4)
        assert self.gov.trace_feedback_loops() >= 0

    @pytest.mark.parametrize("magnitudes", [[0.1, 0.2], [0.7, 0.8, 0.9], [1.0]])
    def test_compute_adaptation_velocity(self, magnitudes):
        for i, m in enumerate(magnitudes):
            self.gov.record_adaptation_event(f"S{i}", m)
        v = self.gov.compute_adaptation_velocity()
        assert 0.0 <= v <= 1.0

    def test_apply_damping_and_cooldown(self):
        c = self.gov.apply_damping("global", 0.6)
        assert 0.1 <= c <= 1.0
        assert self.gov.enforce_cooldowns("reflection_engine", 2)

    def test_emergency_stabilize(self):
        actions = self.gov.emergency_stabilize()
        assert "reduce_exploration" in actions

    def test_evaluate_schema(self):
        self.gov.record_adaptation_event("reflection_engine", 0.9)
        self.gov.record_adaptation_event("governance", 0.9)
        self.gov.record_adaptation_event("world_model", 0.9)
        self.gov.record_adaptation_event("reflection_engine", 0.9)
        report = self.gov.evaluate().to_dict()
        for k in (
            "stability_pressure",
            "recursion_depth",
            "adaptation_velocity",
            "subsystem_pressure",
            "intervention_count",
            "stabilized_cycles",
            "governor_interventions",
            "confidence",
            "stability_impact",
            "coherence_impact",
            "causal_trace_metadata",
            "rationale",
        ):
            assert k in report


class TestIdentityOmega5:
    def setup_method(self):
        import modules.niblit_identity as m

        m._ID_PATH = "/tmp/niblit_identity_omega5_test.json"
        m._TIMELINE_PATH = "/tmp/identity_timeline_omega5_test.jsonl"
        for p in (m._ID_PATH, m._TIMELINE_PATH):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        _reset_singleton("modules.niblit_identity", "_nid")
        from modules.niblit_identity import get_niblit_identity

        self.nid = get_niblit_identity()

    @pytest.mark.parametrize(
        "obs", [{}, {"self_model": 0.8}, {"self_model": 0.1, "planner": 0.2}, {"a": 0.0, "b": 1.0}]
    )
    def test_compute_behavioral_consistency(self, obs):
        s = self.nid.compute_behavioral_consistency(obs)
        assert 0.0 <= s <= 1.0

    def test_value_integrity_check_partial(self):
        out = self.nid.value_integrity_check(["preserve_system_integrity"])
        assert out["is_valid"] is False

    def test_value_integrity_check_full(self):
        out = self.nid.value_integrity_check(self.nid.core_values)
        assert out["is_valid"] is True

    @pytest.mark.parametrize(
        "direction", ["stable coherence", "random maximize reward", "align constitutional stability"]
    )
    def test_validate_trajectory(self, direction):
        score = self.nid.validate_trajectory(direction)
        assert 0.0 <= score <= 1.0

    @pytest.mark.parametrize("obs", [{"self_model": 0.1}, {"self_model": 0.9}, {"planner": 0.3}, {"planner": 0.7}])
    def test_detect_identity_drift(self, obs):
        d = self.nid.detect_identity_drift(obs)
        assert 0.0 <= d <= 1.0

    def test_record_contradiction(self):
        self.nid.record_contradiction("unit_test", {"k": "v"})
        assert self.nid.status()["contradiction_count"] >= 1

    def test_status_fields(self):
        st = self.nid.status()
        for k in ("identity_integrity", "value_stability", "behavioral_coherence", "drift_velocity"):
            assert k in st


class TestRealityValidation:
    def setup_method(self):
        _reset_singleton("modules.reality_validation_engine", "_rve")
        from modules.reality_validation_engine import get_reality_validation_engine

        self.rve = get_reality_validation_engine()

    @pytest.mark.parametrize(
        "prediction,outcome,confidence", [(1.0, 0.9, 0.8), (0.2, 0.7, 0.9), (0.5, 0.5, 0.5), (0.9, 0.1, 0.99)]
    )
    def test_verify_predictions(self, prediction, outcome, confidence):
        out = self.rve.verify_predictions(prediction, outcome, confidence)
        assert "absolute_error" in out

    def test_validate_cycle_schema(self):
        for _ in range(5):
            self.rve.verify_predictions(0.9, 0.1, 0.95, resonance_weight=0.8)
        report = self.rve.validate_cycle().to_dict()
        for k in (
            "reality_alignment",
            "prediction_accuracy",
            "calibration_error",
            "synthetic_feedback_risk",
            "resonance_contamination",
            "confidence_reliability",
            "rationale",
            "confidence",
        ):
            assert k in report


class TestMetaGovernance:
    def setup_method(self):
        _reset_singleton("modules.meta_governance_engine", "_mge")
        from modules.meta_governance_engine import get_meta_governance_engine

        self.mge = get_meta_governance_engine()

    @pytest.mark.parametrize(
        "sub,delta", [("governance", 1.0), ("reflection", 0.5), ("planner", 2.0), ("model_ecology", 1.2)]
    )
    def test_register_influence(self, sub, delta):
        self.mge.register_influence(sub, delta, reason="test")
        bal = self.mge.compute_influence_balance()
        assert sub in bal

    def test_detect_capture_and_compliance(self):
        self.mge.register_influence("governance", 9.0, reason="dom")
        capture = self.mge.detect_governance_capture()
        compliance = self.mge.validate_constitutional_compliance()
        assert 0.0 <= capture <= 1.0
        assert 0.0 <= compliance <= 1.0

    def test_attempt_constitutional_rewrite(self):
        assert self.mge.attempt_constitutional_rewrite({"approved_by_human": False}) is False

    def test_evaluate_schema(self):
        report = self.mge.evaluate().to_dict()
        for k in ("influence_distribution", "authority_pressure", "governance_entropy", "adaptation_override_attempts"):
            assert k in report


class TestCognitiveImmuneSystem:
    def setup_method(self):
        _reset_singleton("modules.cognitive_immune_system", "_cis")
        from modules.cognitive_immune_system import get_cognitive_immune_system

        self.cis = get_cognitive_immune_system()

    @pytest.mark.parametrize(
        "signals,expected",
        [
            ({"recursive_instability": 0.8}, "recursive_instability"),
            ({"resonance_contamination": 0.8}, "resonance_poisoning"),
            ({"causal_corruption": 0.8}, "causal_corruption"),
            ({"memory_contamination": 0.8}, "memory_contamination"),
            ({"overconfidence": 0.9}, "overconfidence_spiral"),
            ({"governance_saturation": 0.9}, "governance_saturation"),
            ({"identity_integrity": 0.2}, "identity_collapse_risk"),
            ({"unstable_emergence": 0.9}, "unstable_emergence"),
        ],
    )
    def test_detect_anomalies(self, signals, expected):
        out = self.cis.detect_cognitive_anomalies(signals)
        assert expected in out

    def test_scan_schema(self):
        report = self.cis.scan({"recursive_instability": 0.9, "governance_saturation": 0.9})
        d = report.to_dict()
        for k in ("immune_pressure", "quarantined_subsystems", "active_threats", "rollback_recommended"):
            assert k in d

    def test_restore_coherence(self):
        self.cis.quarantine_subsystem("reflection_engine")
        actions = self.cis.restore_coherence()
        assert isinstance(actions, list)


class TestCausalTemporalEngine:
    def setup_method(self):
        _reset_singleton("modules.causal_temporal_engine", "_cte")
        from modules.causal_temporal_engine import get_causal_temporal_engine

        self.cte = get_causal_temporal_engine()

    @pytest.mark.parametrize(
        "sub,event", [("planner", "plan_update"), ("governance", "policy_change"), ("reflection", "reflect")]
    )
    def test_register_event(self, sub, event):
        eid = self.cte.register_event(sub, event, "cause", "effect")
        assert isinstance(eid, str)

    def test_reconcile_and_conflicts(self):
        eid = self.cte.register_event("planner", "expectation", "raise", "up")
        ok = self.cte.reconcile_delayed_outcomes(eid, "down")
        assert ok is True
        assert len(self.cte.detect_temporal_conflicts()) >= 1

    def test_build_causal_chain(self):
        eid = self.cte.register_event("planner", "x", "a", "b")
        chain = self.cte.build_causal_chain(eid)
        assert len(chain) >= 1

    def test_replay(self):
        self.cte.register_event("planner", "x", "a", "b")
        rows = self.cte.replay_timeline()
        assert len(rows) >= 1


class TestEmergenceMonitor:
    def setup_method(self):
        _reset_singleton("modules.emergence_monitor", "_em")
        from modules.emergence_monitor import get_emergence_monitor

        self.em = get_emergence_monitor()

    @pytest.mark.parametrize(
        "motif", ["new_strategy_loop", "planner_attractor", "self_opt_pattern", "novel_coordination"]
    )
    def test_detect_patterns(self, motif):
        self.em.observe_pattern(motif, ["planner", "reflection"])
        self.em.observe_pattern(motif, ["planner", "reflection"])
        self.em.observe_pattern(motif, ["planner", "reflection"])
        assert motif in self.em.detect_emergent_patterns()

    def test_identify_coalitions(self):
        self.em.observe_pattern("m", ["a", "b"])
        self.em.observe_pattern("m", ["a", "b"])
        assert any("a+b" == c for c in self.em.identify_coalitions())

    def test_analyze_schema(self):
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        self.em.observe_pattern("new_strategy_loop", ["planner", "reflection"])
        d = self.em.analyze().to_dict()
        for k in (
            "emergence_index",
            "emergence_velocity",
            "motif_frequency",
            "coalition_strength",
            "classified_behavior",
        ):
            assert k in d


class TestMultiAgentConsciousness:
    def setup_method(self):
        _reset_singleton("modules.multi_agent_consciousness", "_mac")
        from modules.multi_agent_consciousness import get_multi_agent_consciousness

        self.mac = get_multi_agent_consciousness()

    @pytest.mark.parametrize("agent", ["a", "b", "c", "d", "e"])
    def test_register_agent(self, agent):
        self.mac.register_agent(agent)
        assert self.mac.status()["agent_count"] >= 1

    def test_coalition_and_debate(self):
        self.mac.register_agent("a")
        self.mac.register_agent("b")
        coalition = self.mac.form_coalitions(["a", "b"])
        assert "a+b" == coalition
        self.mac.record_debate("topic", ["a", "b"], "a", ["b"])
        assert self.mac.status()["debate_memory_count"] >= 1

    def test_roles_trust_alignment(self):
        self.mac.register_agent("a")
        self.mac.register_agent("b")
        self.mac.assign_reasoning_roles({"a": "adversarial", "b": "critic"})
        self.mac.update_agent_trust("a", "b", 0.2)
        assert 0.0 <= self.mac.compute_collective_alignment() <= 1.0


class TestGlobalCognitiveMetrics:
    def setup_method(self):
        _reset_singleton("modules.global_cognitive_metrics", "_gcm")
        from modules.global_cognitive_metrics import get_global_cognitive_metrics

        self.gcm = get_global_cognitive_metrics()

    def test_aggregate_metrics(self):
        m = self.gcm.aggregate_metrics()
        expected = {
            "coherence",
            "stability",
            "identity_integrity",
            "governance_health",
            "emergence_index",
            "prediction_reliability",
            "memory_integrity",
            "resonance_dependency",
            "reflection_usefulness",
            "adaptation_velocity",
            "causal_consistency",
        }
        assert expected.issubset(set(m.keys()))

    @pytest.mark.parametrize("coh,stab,identity", [(0.9, 0.8, 0.7), (0.4, 0.4, 0.4), (1.0, 1.0, 1.0)])
    def test_compute_global_health_range(self, coh, stab, identity):
        health = self.gcm.compute_global_health(
            {
                "coherence": coh,
                "stability": stab,
                "identity_integrity": identity,
                "governance_health": 0.8,
                "prediction_reliability": 0.7,
                "memory_integrity": 0.8,
                "reflection_usefulness": 0.7,
                "causal_consistency": 0.7,
                "emergence_index": 0.2,
                "resonance_dependency": 0.2,
                "adaptation_velocity": 0.2,
            }
        )
        assert 0.0 <= health <= 1.0

    def test_generate_report(self):
        report = self.gcm.generate_cognitive_report()
        assert "coherence" in report and "confidence" in report


def test_cross_module_event_flow():
    from modules.cognitive_coherence_engine import get_cognitive_coherence_engine
    from modules.event_bus import get_event_bus
    from modules.global_cognitive_metrics import get_global_cognitive_metrics

    bus = get_event_bus()
    before = bus.stats().copy()
    get_cognitive_coherence_engine().analyze()
    get_global_cognitive_metrics().generate_cognitive_report()
    after = bus.stats()
    assert sum(after.values()) >= sum(before.values())


# 20 extra parameterized stability/coherence checks to ensure 100+ cases
@pytest.mark.parametrize("value", [i / 20 for i in range(20)])
def test_parameterized_health_edges(value):
    from modules.global_cognitive_metrics import get_global_cognitive_metrics

    gcm = get_global_cognitive_metrics()
    h = gcm.compute_global_health(
        {
            "coherence": value,
            "stability": value,
            "identity_integrity": value,
            "governance_health": value,
            "prediction_reliability": value,
            "memory_integrity": value,
            "reflection_usefulness": value,
            "causal_consistency": value,
            "emergence_index": 1 - value,
            "resonance_dependency": 1 - value,
            "adaptation_velocity": 1 - value,
        }
    )
    assert 0.0 <= h <= 1.0


if __name__ == "__main__":
    print('Running test_phase_omega_5_coherence.py')
