"""Phase Ω.6 — Attention economy and cognitive resource allocation tests."""

from __future__ import annotations

import modules.attention_allocator as attention_allocator_module
import modules.cognitive_budget_manager as budget_manager_module
import modules.global_cognitive_metrics as global_metrics_module
import modules.salience_engine as salience_engine_module


def _reset_singletons() -> None:
    attention_allocator_module._attention_allocator = None
    budget_manager_module._budget_manager = None
    global_metrics_module._gcm = None
    salience_engine_module._salience_engine = None


def test_omega6_event_constants():
    from modules import event_bus

    assert event_bus.EVENT_SALIENCE_SCORED == "salience.scored"
    assert event_bus.EVENT_COGNITIVE_BUDGET_ENFORCED == "cognitive_budget.enforced"
    assert event_bus.EVENT_ATTENTION_ALLOCATED == "attention.allocated"


class TestSalienceEngine:
    def setup_method(self):
        _reset_singletons()
        self.engine = salience_engine_module.get_salience_engine()

    def test_assess_range_and_schema(self):
        assessment = self.engine.assess(
            "planner",
            urgency=0.8,
            relevance=0.7,
            novelty=0.4,
            governance_weight=0.9,
        )
        data = assessment.to_dict()
        assert 0.0 <= data["salience"] <= 1.0
        assert data["target"] == "planner"
        assert "rationale" in data

    def test_rank_orders_by_salience(self):
        ranked = self.engine.rank(
            [
                {"target": "background_sync", "urgency": 0.1, "relevance": 0.2},
                {"target": "governance", "urgency": 0.9, "relevance": 0.8, "governance_weight": 0.9},
            ]
        )
        assert ranked[0].target == "governance"
        assert ranked[0].salience >= ranked[1].salience


class TestCognitiveBudgetManager:
    def setup_method(self):
        _reset_singletons()
        self.manager = budget_manager_module.get_cognitive_budget_manager()

    def test_context_pressure_reduces_effective_budget(self):
        effective = self.manager.reset_cycle(total_budget=1.0, context_pressure=0.6)
        assert effective < 1.0
        assert self.manager.status()["effective_budget"] == round(effective, 4)

    def test_recursive_cap_limits_deep_request(self):
        self.manager.reset_cycle(total_budget=1.0, context_pressure=0.0)
        decision = self.manager.allocate("reflection", 0.9, salience=0.3, recursion_depth=6)
        assert decision.capped is True
        assert decision.granted_units < 0.9


class TestAttentionAllocator:
    def setup_method(self):
        _reset_singletons()
        self.allocator = attention_allocator_module.get_attention_allocator()

    def test_priority_arbitration_prefers_high_salience(self):
        allocation = self.allocator.allocate(
            [
                {
                    "subsystem": "governance",
                    "requested_units": 0.6,
                    "urgency": 0.9,
                    "relevance": 0.9,
                    "governance_weight": 0.9,
                },
                {
                    "subsystem": "background_reflection",
                    "requested_units": 0.6,
                    "urgency": 0.1,
                    "relevance": 0.2,
                },
            ],
            total_budget=0.8,
        )
        assert allocation["allocations"]["governance"] > allocation["allocations"]["background_reflection"]

    def test_starvation_floor_preserves_small_share(self):
        allocation = self.allocator.allocate(
            [
                {"subsystem": "planner", "requested_units": 0.6, "urgency": 0.8, "relevance": 0.8},
                {"subsystem": "memory", "requested_units": 0.3, "urgency": 0.5, "relevance": 0.4},
                {"subsystem": "router", "requested_units": 0.2, "urgency": 0.4, "relevance": 0.5},
            ],
            total_budget=0.7,
        )
        assert allocation["allocations"]["memory"] > 0.0
        assert allocation["allocations"]["router"] > 0.0

    def test_attention_pressure_tracks_budget_use(self):
        allocation = self.allocator.allocate(
            [{"subsystem": "planner", "requested_units": 0.9, "urgency": 0.9, "relevance": 0.9}],
            total_budget=0.5,
            context_pressure=0.3,
        )
        assert 0.0 <= allocation["attention_pressure"] <= 1.0
        assert allocation["budget_utilization"] >= 0.0


def test_omega6_event_flow():
    _reset_singletons()
    from modules.event_bus import get_event_bus

    bus = get_event_bus()
    before = dict(bus.stats())
    attention_allocator_module.get_attention_allocator().allocate(
        [{"subsystem": "planner", "requested_units": 0.5, "urgency": 0.8, "relevance": 0.7}],
        total_budget=0.5,
    )
    after = bus.stats()
    assert after.get("salience.scored", 0) >= before.get("salience.scored", 0)
    assert after.get("cognitive_budget.enforced", 0) >= before.get("cognitive_budget.enforced", 0)
    assert after.get("attention.allocated", 0) >= before.get("attention.allocated", 0)


def test_global_metrics_include_attention_telemetry():
    _reset_singletons()
    attention_allocator_module.get_attention_allocator().allocate(
        [{"subsystem": "planner", "requested_units": 0.6, "urgency": 0.9, "relevance": 0.8}],
        total_budget=0.5,
    )
    report = global_metrics_module.get_global_cognitive_metrics().generate_cognitive_report()
    assert "attention_pressure" in report
    assert "budget_health" in report
    assert report["causal_trace_metadata"]["attention_pressure"] >= 0.0


if __name__ == "__main__":
    print('Running test_phase_omega_6_attention.py')
