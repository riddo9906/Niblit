"""tests/test_knowledge_gap_cognition.py — Unit tests for the governed
Knowledge-Gap Cognition escalation layer.

Tests verify:
  - KnowledgeGapSignal construction and auto-trace_id
  - CognitionEscalationLayer disabled path
  - Budget enforcement (max escalations per cycle)
  - RouterV2 unavailable → graceful failure
  - Successful escalation populates result fields
  - Quality estimation heuristics
  - Metrics snapshot
  - Event bus emission (no exception on missing bus)
  - Event constants added to event_bus
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ── Helpers ────────────────────────────────────────────────────────────────────

def _fresh_layer():
    """Return a fresh (non-singleton) CognitionEscalationLayer."""
    from modules.knowledge_gap_cognition import CognitionEscalationLayer
    return CognitionEscalationLayer()


# ── KnowledgeGapSignal ─────────────────────────────────────────────────────────

def test_gap_signal_auto_trace_id():
    from modules.knowledge_gap_cognition import KnowledgeGapSignal
    gap = KnowledgeGapSignal(topic="asyncio patterns")
    assert len(gap.trace_id) == 16


def test_gap_signal_explicit_trace_id():
    from modules.knowledge_gap_cognition import KnowledgeGapSignal
    gap = KnowledgeGapSignal(topic="x", trace_id="my_trace")
    assert gap.trace_id == "my_trace"


def test_gap_signal_defaults():
    from modules.knowledge_gap_cognition import GAP_CLASS_RESEARCH, KnowledgeGapSignal
    gap = KnowledgeGapSignal()
    assert gap.gap_class == GAP_CLASS_RESEARCH
    assert gap.confidence == 0.0
    assert isinstance(gap.context, dict)


# ── Disabled flag ──────────────────────────────────────────────────────────────

def test_escalate_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setenv("NIBLIT_COGNITION_ESCALATION_ENABLED", "0")
    # Force module reload to pick up new env var
    import modules.knowledge_gap_cognition as mod
    monkeypatch.setattr(mod, "_ENABLED", False)

    layer = _fresh_layer()
    from modules.knowledge_gap_cognition import KnowledgeGapSignal
    result = layer.escalate(KnowledgeGapSignal(topic="test"))
    assert result["success"] is False
    assert result["synthesis"] == ""


# ── Budget enforcement ─────────────────────────────────────────────────────────

def test_budget_enforcement():
    import modules.knowledge_gap_cognition as mod
    old_enabled = mod._ENABLED
    old_budget = mod._MAX_BUDGET
    mod._ENABLED = True
    mod._MAX_BUDGET = 2

    try:
        layer = _fresh_layer()
        # Simulate budget already exhausted
        layer._budget_used = 2
        layer._budget_reset_cycle = 0

        from modules.knowledge_gap_cognition import KnowledgeGapSignal
        result = layer.escalate(KnowledgeGapSignal(topic="x"), cycle_id=0)
        assert result["success"] is False
    finally:
        mod._ENABLED = old_enabled
        mod._MAX_BUDGET = old_budget


# ── Router unavailable ─────────────────────────────────────────────────────────

def test_router_unavailable_returns_failure(monkeypatch):
    import modules.knowledge_gap_cognition as mod
    monkeypatch.setattr(mod, "_ENABLED", True)

    layer = _fresh_layer()
    layer._router = None

    # Patch the import of RuntimeRouterV2 to fail
    with patch.dict("sys.modules", {"modules.runtime_router_v2": None}):
        # _get_router will return None since import fails
        original_get_router = layer._get_router

        def _no_router():
            return None

        layer._get_router = _no_router
        from modules.knowledge_gap_cognition import KnowledgeGapSignal
        result = layer.escalate(KnowledgeGapSignal(topic="test"))
        assert result["success"] is False


# ── Successful escalation ──────────────────────────────────────────────────────

def test_successful_escalation():
    import modules.knowledge_gap_cognition as mod
    original_enabled = mod._ENABLED
    mod._ENABLED = True

    try:
        layer = _fresh_layer()

        mock_router = MagicMock()
        mock_router.generate.return_value = (
            "Python asyncio is an asynchronous I/O framework that provides "
            "coroutines, tasks, and event loops for concurrent programming. "
            "It is widely used in web servers, network clients, and data pipelines."
        )
        layer._router = mock_router

        # Suppress memory and event writes
        layer._write_governed_memory = MagicMock()
        layer._emit_event = MagicMock()
        layer._increment_counter = MagicMock()
        layer._record_histogram = MagicMock()

        from modules.knowledge_gap_cognition import KnowledgeGapSignal
        gap = KnowledgeGapSignal(topic="asyncio patterns", source_module="test")
        result = layer.escalate(gap, write_memory=False)

        assert result["success"] is True
        assert len(result["synthesis"]) > 20
        assert result["quality"] > 0.0
        assert result["trace_id"] == gap.trace_id
        mock_router.generate.assert_called_once()
    finally:
        mod._ENABLED = original_enabled


# ── Quality estimation ────────────────────────────────────────────────────────

def test_quality_empty_synthesis():
    from modules.knowledge_gap_cognition import CognitionEscalationLayer, KnowledgeGapSignal
    assert CognitionEscalationLayer._estimate_quality("", KnowledgeGapSignal()) == 0.0


def test_quality_long_synthesis():
    from modules.knowledge_gap_cognition import CognitionEscalationLayer, KnowledgeGapSignal
    text = "word " * 100
    quality = CognitionEscalationLayer._estimate_quality(text, KnowledgeGapSignal(topic="x"))
    assert quality > 0.5


def test_quality_verbatim_echo_penalised():
    from modules.knowledge_gap_cognition import CognitionEscalationLayer, KnowledgeGapSignal
    # Synthesis that just repeats the topic word has low novelty score
    gap = KnowledgeGapSignal(topic="asyncio asyncio asyncio")
    text = "asyncio asyncio asyncio " * 5
    quality = CognitionEscalationLayer._estimate_quality(text, gap)
    # Should be lower than a novel synthesis
    novel_text = "This is a completely different set of words about coroutines and tasks " * 3
    novel_quality = CognitionEscalationLayer._estimate_quality(novel_text, gap)
    assert novel_quality > quality


# ── Metrics snapshot ──────────────────────────────────────────────────────────

def test_metrics_structure():
    layer = _fresh_layer()
    m = layer.metrics()
    assert "gap_detected_total" in m
    assert "synthesis_success_rate" in m
    assert "avg_synthesis_quality" in m
    assert "budget_max" in m
    assert m["synthesis_success_rate"] == 0.0


# ── Event constants ────────────────────────────────────────────────────────────

def test_event_constants_exist():
    from modules.event_bus import (
        EVENT_COGNITION_GAP_DETECTED,
        EVENT_COGNITION_SYNTHESIS_COMPLETE,
    )
    assert EVENT_COGNITION_GAP_DETECTED == "cognition.gap.detected"
    assert EVENT_COGNITION_SYNTHESIS_COMPLETE == "cognition.synthesis.complete"


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_singleton_identity():
    from modules.knowledge_gap_cognition import get_cognition_escalation_layer
    a = get_cognition_escalation_layer()
    b = get_cognition_escalation_layer()
    assert a is b


# ── get_telemetry_collector singleton ────────────────────────────────────────

def test_get_telemetry_collector_singleton():
    from modules.metrics_observability import TelemetryCollector, get_telemetry_collector
    a = get_telemetry_collector()
    b = get_telemetry_collector()
    assert a is b
    assert isinstance(a, TelemetryCollector)
