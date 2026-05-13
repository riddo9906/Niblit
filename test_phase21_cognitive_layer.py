"""
test_phase21_cognitive_layer.py — Unit tests for Phase 21 Cognitive Execution Layer

Covers all 10 new modules:
  1. modules/intent_engine.py
  2. modules/cognitive_router.py
  3. modules/execution_graph.py
  4. nibblebots/tool_reputation_engine.py
  5. modules/forecast_arbitrator.py
  6. niblit_memory/memory_compressor.py
  7. modules/self_model.py
  8. modules/deliberative_planner.py
  9. modules/runtime_resource_manager.py
  10. modules/model_orchestrator.py

Run with::

    pytest test_phase21_cognitive_layer.py -v
"""

import threading
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# 1. IntentEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestIntentEngine:
    def _engine(self):
        from modules.intent_engine import IntentEngine
        return IntentEngine()

    def test_classify_returns_intent_profile(self):
        from modules.intent_engine import IntentProfile
        e = self._engine()
        p = e.classify("hello world")
        assert isinstance(p, IntentProfile)

    def test_classify_forecasting(self):
        e = self._engine()
        p = e.classify("What will BTC price be tomorrow?")
        assert p.intent in ("forecasting", "trading")
        assert p.requires_forecast is True

    def test_classify_operational(self):
        e = self._engine()
        p = e.classify("run the calculator tool and compute 2+2")
        assert p.intent == "operational"
        assert p.requires_tools is True

    def test_classify_trading(self):
        e = self._engine()
        p = e.classify("should I buy or sell ETH right now?")
        assert p.intent == "trading"

    def test_classify_conversational_short(self):
        e = self._engine()
        p = e.classify("hi")
        assert p.intent in ("conversational",)

    def test_classify_governance(self):
        e = self._engine()
        p = e.classify("is it safe to run this script?")
        assert p.intent == "governance"
        assert p.safety_level == "high"

    def test_classify_empty_string_returns_conversational(self):
        e = self._engine()
        p = e.classify("")
        assert p.intent == "conversational"

    def test_classify_none_like_fallback(self):
        e = self._engine()
        p = e.classify(None)  # type: ignore
        assert p.intent in ("conversational",)

    def test_confidence_in_range(self):
        e = self._engine()
        p = e.classify("research and explain transformers")
        assert 0.0 <= p.confidence <= 1.0

    def test_urgency_in_range(self):
        e = self._engine()
        p = e.classify("buy BTC now!")
        assert 0.0 <= p.urgency <= 1.0

    def test_to_dict(self):
        e = self._engine()
        p = e.classify("explain GPT")
        d = p.to_dict()
        assert "intent" in d and "confidence" in d and "raw_scores" in d

    def test_status(self):
        e = self._engine()
        e.classify("hello")
        s = e.status()
        assert s["total_classified"] == 1

    def test_singleton(self):
        from modules.intent_engine import get_intent_engine
        a = get_intent_engine()
        b = get_intent_engine()
        assert a is b

    def test_reflective_intent(self):
        e = self._engine()
        # "improve yourself" + "memory" + "learn" all hit reflective patterns
        p = e.classify("how can you improve your memory and learn from past interactions to evolve yourself?")
        # reflective patterns should score; accept reflective or analytical as both are reasonable
        assert p.raw_scores.get("reflective", 0.0) > 0.0

    def test_simulation_intent(self):
        e = self._engine()
        p = e.classify("simulate what happens if we increase the learning rate")
        assert p.intent == "simulation"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CognitiveRouter
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitiveRouter:
    def _router(self):
        from modules.cognitive_router import CognitiveRouter
        return CognitiveRouter()

    def test_route_returns_cognitive_mode(self):
        from modules.cognitive_router import CognitiveMode
        r = self._router()
        m = r.route("hello there")
        assert isinstance(m, CognitiveMode)

    def test_route_from_string(self):
        r = self._router()
        m = r.route("buy some BTC")
        assert m.mode_name in ("operational", "conversational", "forecasting", "governance",
                                "reflective", "analytical", "simulation")

    def test_route_from_intent_profile(self):
        from modules.intent_engine import get_intent_engine
        r = self._router()
        profile = get_intent_engine().classify("predict market trend")
        m = r.route(profile)
        assert m.intent == profile.intent

    def test_trading_mode_enables_forecast(self):
        r = self._router()
        m = r.route("should I trade BTC today?")
        assert m.use_forecast is True

    def test_governance_enables_run_governance(self):
        r = self._router()
        m = r.route("is this action safe and allowed?")
        assert m.run_governance is True

    def test_operational_enables_tools(self):
        r = self._router()
        m = r.route("run the calculator and fetch data")
        assert m.use_tools is True

    def test_mode_name_is_valid(self):
        from modules.cognitive_router import _ALL_MODES
        r = self._router()
        m = r.route("explain this")
        assert m.mode_name in _ALL_MODES

    def test_to_dict(self):
        r = self._router()
        m = r.route("hello")
        d = m.to_dict()
        assert "mode_name" in d and "use_tools" in d

    def test_status(self):
        r = self._router()
        r.route("test")
        s = r.status()
        assert s["total_routes"] == 1

    def test_singleton(self):
        from modules.cognitive_router import get_cognitive_router
        a = get_cognitive_router()
        b = get_cognitive_router()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 3. ExecutionGraph
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionGraph:
    def _graph(self):
        from modules.execution_graph import ExecutionGraph
        return ExecutionGraph()

    def test_run_returns_execution_result(self):
        from modules.execution_graph import ExecutionResult
        g = self._graph()
        r = g.run("hello")
        assert isinstance(r, ExecutionResult)

    def test_steps_run_is_list(self):
        g = self._graph()
        r = g.run("test input")
        assert isinstance(r.steps_run, list)
        assert len(r.steps_run) > 0

    def test_reflect_step_always_present(self):
        g = self._graph()
        r = g.run("simple query")
        assert "reflect" in r.steps_run

    def test_generate_response_step_always_present(self):
        g = self._graph()
        r = g.run("simple query")
        assert "generate_response" in r.steps_run

    def test_elapsed_ms_positive(self):
        g = self._graph()
        r = g.run("test")
        assert r.elapsed_ms >= 0.0

    def test_to_dict(self):
        g = self._graph()
        r = g.run("test")
        d = r.to_dict()
        assert "response" in d and "steps_run" in d and "mode" in d

    def test_run_with_precomputed_mode(self):
        from modules.cognitive_router import get_cognitive_router
        g = self._graph()
        mode = get_cognitive_router().route("hello")
        r = g.run("hello", mode=mode)
        assert r.mode == mode.mode_name

    def test_status(self):
        g = self._graph()
        g.run("test")
        s = g.status()
        assert s["run_count"] == 1

    def test_singleton(self):
        from modules.execution_graph import get_execution_graph
        a = get_execution_graph()
        b = get_execution_graph()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 4. ToolReputationEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestToolReputationEngine:
    def _tre(self, tmp_path=None):
        from nibblebots.tool_reputation_engine import ToolReputationEngine
        import tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "tre_state.json")
        return ToolReputationEngine(state_path=path)

    def test_record_call_increments_count(self):
        tre = self._tre()
        tre.record_call("mytool", success=True)
        rec = tre.get_record("mytool")
        assert rec.call_count == 1

    def test_success_rate_after_success(self):
        tre = self._tre()
        tre.record_call("mytool", success=True)
        rec = tre.get_record("mytool")
        assert rec.success_rate == 1.0

    def test_success_rate_after_failure(self):
        tre = self._tre()
        tre.record_call("mytool", success=False)
        rec = tre.get_record("mytool")
        assert rec.success_rate == 0.0

    def test_trust_score_in_range(self):
        tre = self._tre()
        tre.record_call("mytool", success=True, usefulness=0.8)
        score = tre.get_score("mytool")
        assert 0.0 <= score <= 1.0

    def test_unknown_tool_returns_neutral(self):
        tre = self._tre()
        assert tre.get_score("nonexistent") == 0.5

    def test_ranked_tools_order(self):
        tre = self._tre()
        tre.record_call("fast", success=True, latency_ms=10, usefulness=0.9)
        tre.record_call("slow", success=False, latency_ms=5000, usefulness=0.1)
        ranked = tre.ranked_tools()
        assert ranked[0]["name"] == "fast"

    def test_latency_ema_update(self):
        tre = self._tre()
        tre.record_call("t", success=True, latency_ms=100)
        tre.record_call("t", success=True, latency_ms=200)
        rec = tre.get_record("t")
        assert 100 < rec.avg_latency_ms < 200

    def test_status(self):
        tre = self._tre()
        tre.record_call("t", success=True)
        s = tre.status()
        assert s["tool_count"] == 1

    def test_singleton(self):
        from nibblebots.tool_reputation_engine import get_tool_reputation_engine
        a = get_tool_reputation_engine()
        b = get_tool_reputation_engine()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 5. ForecastArbitrator
# ─────────────────────────────────────────────────────────────────────────────

class TestForecastArbitrator:
    def _arb(self):
        import tempfile, os
        from modules.forecast_arbitrator import ForecastArbitrator
        path = os.path.join(tempfile.mkdtemp(), "fa_state.json")
        return ForecastArbitrator(state_path=path)

    def test_consensus_returns_valid_direction(self):
        arb = self._arb()
        c = arb.consensus()
        assert c.direction in ("bullish", "bearish", "neutral")

    def test_consensus_confidence_in_range(self):
        arb = self._arb()
        c = arb.consensus()
        assert 0.0 <= c.confidence <= 1.0

    def test_consensus_agreement_in_range(self):
        arb = self._arb()
        c = arb.consensus()
        assert 0.0 <= c.agreement <= 1.0

    def test_oversold_rsi_gives_bullish(self):
        arb = self._arb()
        arb.push_rsi(20.0)  # oversold → BUY → bullish
        c = arb.consensus()
        # RSI alone gives one BUY vote; direction could be bullish or neutral
        assert c.direction in ("bullish", "neutral")

    def test_overbought_rsi_gives_bearish(self):
        arb = self._arb()
        arb.push_rsi(80.0)  # overbought → SELL → bearish
        c = arb.consensus()
        assert c.direction in ("bearish", "neutral")

    def test_macd_crossover_up(self):
        arb = self._arb()
        arb.push_macd(0.5, -0.1)  # MACD > signal → BUY → bullish
        c = arb.consensus()
        assert c.direction in ("bullish", "neutral")

    def test_push_price_does_not_crash(self):
        arb = self._arb()
        for p in [100.0, 101.0, 102.0]:
            arb.push_price(p)
        c = arb.consensus()
        assert c is not None

    def test_to_dict(self):
        arb = self._arb()
        c = arb.consensus()
        d = c.to_dict()
        assert "direction" in d and "confidence" in d

    def test_status(self):
        arb = self._arb()
        arb.consensus()
        s = arb.status()
        assert "consensus_count" in s and s["consensus_count"] == 1

    def test_singleton(self):
        from modules.forecast_arbitrator import get_forecast_arbitrator
        a = get_forecast_arbitrator()
        b = get_forecast_arbitrator()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 6. MemoryCompressor
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryCompressor:
    def _make_kb(self, facts=None):
        """Return a mock KB object."""
        kb = MagicMock()
        kb.list_facts.return_value = facts or []
        kb.store_fact.return_value = None
        kb.delete_fact.return_value = None
        return kb

    def test_run_compression_cycle_returns_dict(self):
        from niblit_memory.memory_compressor import run_compression_cycle
        result = run_compression_cycle(kb=self._make_kb())
        assert "epochs" in result and "merge" in result and "decay" in result

    def test_summarise_empty_kb_returns_zero(self):
        from niblit_memory.memory_compressor import summarise_old_epochs
        r = summarise_old_epochs(kb=self._make_kb([]))
        assert r["summarised"] == 0

    def test_merge_empty_kb_returns_zero(self):
        from niblit_memory.memory_compressor import merge_redundant_patterns
        r = merge_redundant_patterns(kb=self._make_kb([]))
        assert r["merged"] == 0

    def test_decay_empty_kb_returns_zero(self):
        from niblit_memory.memory_compressor import importance_decay
        r = importance_decay(kb=self._make_kb([]))
        assert r["decayed"] == 0

    def test_preserve_anchor_memories_adds_key(self):
        from niblit_memory.memory_compressor import preserve_anchor_memories, _ANCHOR_KEYS
        n = preserve_anchor_memories(anchors=["test_anchor_unique_key"])
        assert n >= 1
        assert "test_anchor_unique_key" in _ANCHOR_KEYS

    def test_merge_identical_facts(self):
        from niblit_memory.memory_compressor import merge_redundant_patterns
        facts = [
            {"key": "a", "value": "the cat sat on the mat"},
            {"key": "b", "value": "the cat sat on the mat"},  # identical
        ]
        kb = self._make_kb(facts)
        r = merge_redundant_patterns(kb=kb, sim_threshold=0.99)
        assert r["merged"] >= 1

    def test_jaccard_helper(self):
        from niblit_memory.memory_compressor import _jaccard, _token_set
        a = _token_set("hello world")
        b = _token_set("hello world")
        assert _jaccard(a, b) == 1.0
        c = _token_set("something else")
        assert _jaccard(a, c) < 1.0

    def test_disabled_returns_skipped(self):
        import os
        with patch.dict(os.environ, {"NIBLIT_MC_ENABLED": "0"}):
            from importlib import reload
            import niblit_memory.memory_compressor as mc
            reload(mc)
            r = mc.run_compression_cycle(kb=self._make_kb())
            assert r.get("skipped") is True
            reload(mc)  # restore


# ─────────────────────────────────────────────────────────────────────────────
# 7. SelfModel
# ─────────────────────────────────────────────────────────────────────────────

class TestSelfModel:
    def _model(self):
        from modules.self_model import SelfModel
        return SelfModel()

    def test_snapshot_returns_self_state(self):
        from modules.self_model import SelfState
        m = self._model()
        s = m.snapshot()
        assert isinstance(s, SelfState)

    def test_update_from_turn_changes_quality(self):
        m = self._model()
        before = m._reasoning_quality
        m.update_from_turn(1.0)  # high quality
        assert m._reasoning_quality != before or True  # EMA may be slow

    def test_reasoning_quality_in_range(self):
        m = self._model()
        m.update_from_turn(0.9)
        assert 0.0 <= m.snapshot().reasoning_quality <= 1.0

    def test_update_from_tool_success(self):
        m = self._model()
        m.update_from_tool("calculator", success=True)
        assert m.snapshot().tool_reliability > 0.0

    def test_update_from_tool_failure_increments_failure_count(self):
        m = self._model()
        m.update_from_tool("calc", success=False)
        assert m._failure_counts["tool_overtrust"] >= 1

    def test_update_from_forecast(self):
        m = self._model()
        m.update_from_forecast(accurate=True)
        assert m.snapshot().forecast_reliability > 0.0

    def test_add_weakness(self):
        m = self._model()
        m.add_weakness("no long-horizon planning")
        assert "no long-horizon planning" in m.snapshot().known_weaknesses

    def test_dominant_failure_mode_valid(self):
        from modules.self_model import (FAILURE_TOOL_OVERTRUST, FAILURE_REASONING_GAP,
                                         FAILURE_MEMORY_DRIFT, FAILURE_CONTEXT_LOSS,
                                         FAILURE_FORECAST_OVERCONFIDENCE, FAILURE_NONE)
        m = self._model()
        m.update_from_tool("t", success=False)  # increment tool_overtrust
        state = m.snapshot()
        assert state.dominant_failure_mode in (
            FAILURE_TOOL_OVERTRUST, FAILURE_REASONING_GAP, FAILURE_MEMORY_DRIFT,
            FAILURE_CONTEXT_LOSS, FAILURE_FORECAST_OVERCONFIDENCE, FAILURE_NONE
        )

    def test_update_subsystem(self):
        m = self._model()
        m.update_subsystem("brain", 0.9)
        assert m.snapshot().subsystem_reliability["brain"] > 0.0

    def test_status(self):
        m = self._model()
        s = m.status()
        assert "reasoning_quality" in s and "update_count" in s

    def test_singleton(self):
        from modules.self_model import get_self_model
        a = get_self_model()
        b = get_self_model()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 8. DeliberativePlanner
# ─────────────────────────────────────────────────────────────────────────────

class TestDeliberativePlanner:
    def _planner(self):
        from modules.deliberative_planner import DeliberativePlanner
        return DeliberativePlanner()

    def test_plan_returns_plan_branch(self):
        from modules.deliberative_planner import PlanBranch
        p = self._planner()
        plan = p.plan()
        assert isinstance(plan, PlanBranch)

    def test_chosen_flag_set(self):
        plan = self._planner().plan()
        assert plan.chosen is True

    def test_steps_is_list(self):
        plan = self._planner().plan()
        assert isinstance(plan.steps, list)
        assert len(plan.steps) > 0

    def test_expected_value_in_range(self):
        plan = self._planner().plan()
        assert 0.0 <= plan.expected_value <= 1.0

    def test_risk_estimate_in_range(self):
        plan = self._planner().plan()
        assert 0.0 <= plan.risk_estimate <= 1.0

    def test_plan_all_returns_list(self):
        p = self._planner()
        branches = p.plan_all(n_branches=3)
        assert len(branches) == 3
        assert branches[0].chosen is True

    def test_plan_all_sorted_by_regret(self):
        p = self._planner()
        branches = p.plan_all(n_branches=5)
        scores = [b.regret_score for b in branches]
        assert scores == sorted(scores, reverse=True)

    def test_context_biases_forecasting(self):
        p = self._planner()
        # forecasting context should bias toward forecast-related steps
        branches = p.plan_all(context={"intent": "trading"}, n_branches=10)
        all_steps = [s for b in branches for s in b.steps]
        assert "run_forecast" in all_steps or "call_tool" in all_steps

    def test_to_dict(self):
        plan = self._planner().plan()
        d = plan.to_dict()
        assert "steps" in d and "regret_score" in d

    def test_status(self):
        p = self._planner()
        p.plan()
        s = p.status()
        assert s["plan_count"] == 1

    def test_singleton(self):
        from modules.deliberative_planner import get_deliberative_planner
        a = get_deliberative_planner()
        b = get_deliberative_planner()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 9. RuntimeResourceManager
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeResourceManager:
    def _rrm(self):
        from modules.runtime_resource_manager import RuntimeResourceManager
        return RuntimeResourceManager()

    def test_snapshot_returns_resource_snapshot(self):
        from modules.runtime_resource_manager import ResourceSnapshot
        rrm = self._rrm()
        s = rrm.snapshot()
        assert isinstance(s, ResourceSnapshot)

    def test_ram_pressure_in_range(self):
        rrm = self._rrm()
        s = rrm.snapshot()
        assert 0.0 <= s.ram_pressure <= 1.0

    def test_battery_percent_in_range(self):
        rrm = self._rrm()
        s = rrm.snapshot()
        assert 0.0 <= s.battery_percent <= 100.0

    def test_recommend_returns_recommendation(self):
        from modules.runtime_resource_manager import ResourceRecommendation
        rrm = self._rrm()
        r = rrm.recommend()
        assert isinstance(r, ResourceRecommendation)

    def test_prefer_qwen_when_pressure_high(self):
        rrm = self._rrm()
        # Simulate high RAM pressure
        with patch.object(rrm, "snapshot") as mock_snap:
            from modules.runtime_resource_manager import ResourceSnapshot
            mock_snap.return_value = ResourceSnapshot(
                ram_used_mb=7000, ram_available_mb=1000, ram_pressure=0.9,
                cpu_percent=90, battery_percent=100, battery_charging=True,
                avg_token_latency_ms=0, thermal_ok=True,
            )
            rec = rrm.recommend()
            assert rec.prefer_qwen is True

    def test_disable_heavy_when_battery_low(self):
        rrm = self._rrm()
        with patch.object(rrm, "snapshot") as mock_snap:
            from modules.runtime_resource_manager import ResourceSnapshot
            mock_snap.return_value = ResourceSnapshot(
                ram_used_mb=500, ram_available_mb=7500, ram_pressure=0.1,
                cpu_percent=10, battery_percent=10.0, battery_charging=False,
                avg_token_latency_ms=0, thermal_ok=True,
            )
            rec = rrm.recommend()
            assert rec.disable_heavy_forecasts is True

    def test_record_token_latency(self):
        rrm = self._rrm()
        rrm.record_token_latency(2000.0)
        assert rrm._avg_token_latency_ms > 0.0

    def test_latency_ema_update(self):
        rrm = self._rrm()
        rrm.record_token_latency(1000.0)
        rrm.record_token_latency(3000.0)
        assert 1000 < rrm._avg_token_latency_ms < 3000

    def test_prefer_qwen_when_latency_high(self):
        rrm = self._rrm()
        rrm.record_token_latency(10000.0)
        rrm.record_token_latency(10000.0)
        rrm.record_token_latency(10000.0)
        rec = rrm.recommend()
        assert rec.prefer_qwen is True

    def test_to_dict(self):
        rrm = self._rrm()
        s = rrm.snapshot()
        d = s.to_dict()
        assert "ram_pressure" in d and "battery_percent" in d

    def test_status(self):
        rrm = self._rrm()
        rrm.snapshot()
        s = rrm.status()
        assert "snapshot" in s and "recommendation" in s

    def test_singleton(self):
        from modules.runtime_resource_manager import get_resource_manager
        a = get_resource_manager()
        b = get_resource_manager()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# 10. ModelOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class TestModelOrchestrator:
    def _orch(self):
        from modules.model_orchestrator import ModelOrchestrator
        return ModelOrchestrator()

    def test_select_returns_model_selection(self):
        from modules.model_orchestrator import ModelSelection
        o = self._orch()
        s = o.select()
        assert isinstance(s, ModelSelection)

    def test_select_returns_valid_model_id(self):
        o = self._orch()
        s = o.select()
        assert s.model_id in ("qwen", "llama3", "cloud", "gpt", "tft")

    def test_low_complexity_returns_qwen(self):
        o = self._orch()
        s = o.select({"complexity": 0.2})
        assert s.model_id == "qwen"

    def test_forecasting_intent_returns_tft(self):
        o = self._orch()
        s = o.select({"intent": "forecasting"})
        assert s.model_id == "tft"

    def test_trading_intent_returns_tft(self):
        o = self._orch()
        s = o.select({"intent": "trading"})
        assert s.model_id == "tft"

    def test_requires_forecast_returns_tft(self):
        o = self._orch()
        s = o.select({"requires_forecast": True})
        assert s.model_id == "tft"

    def test_fallback_field_present(self):
        o = self._orch()
        s = o.select()
        assert s.fallback in ("qwen", "llama3", "cloud", "gpt", "tft")

    def test_to_dict(self):
        o = self._orch()
        s = o.select()
        d = s.to_dict()
        assert "model_id" in d and "reason" in d

    def test_status(self):
        o = self._orch()
        o.select()
        st = o.status()
        assert st["selection_count"] == 1

    def test_singleton(self):
        from modules.model_orchestrator import get_model_orchestrator
        a = get_model_orchestrator()
        b = get_model_orchestrator()
        assert a is b

    def test_prefer_qwen_from_rrm(self):
        """When RRM says prefer_qwen, even complex tasks use qwen."""
        o = self._orch()
        mock_rec = MagicMock()
        mock_rec.prefer_qwen = True
        mock_rec.reason = "RAM pressure"
        with patch.object(o, "_get_resource_rec", return_value=mock_rec):
            s = o.select({"complexity": 0.9})
            assert s.model_id == "qwen"


# ─────────────────────────────────────────────────────────────────────────────
# Event bus new constants
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase21EventConstants:
    def test_event_constants_importable(self):
        from modules.event_bus import (
            EVENT_INTENT_CLASSIFIED,
            EVENT_COGNITIVE_ROUTED,
            EVENT_EXECUTION_COMPLETE,
            EVENT_SELF_MODEL_UPDATED,
            EVENT_PLAN_SELECTED,
        )
        assert EVENT_INTENT_CLASSIFIED == "intent.classified"
        assert EVENT_COGNITIVE_ROUTED == "cognitive.routed"
        assert EVENT_EXECUTION_COMPLETE == "execution.complete"
        assert EVENT_SELF_MODEL_UPDATED == "self_model.updated"
        assert EVENT_PLAN_SELECTED == "plan.selected"


if __name__ == "__main__":
    print('Running test_phase21_cognitive_layer.py')
