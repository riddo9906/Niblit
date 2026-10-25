"""Empty provider output must not suppress retrieval-backed reasoning."""
from unittest.mock import Mock

from modules.reasoning_engine import ReasoningEngine


def test_empty_provider_result_uses_ranked_memory(monkeypatch):
    scoring = Mock()
    scoring.rank_candidates.return_value = [{
        "node_id": "storage", "text": "SQLite stores durable project facts.", "final_score": 0.8,
    }]
    engine = ReasoningEngine(graph_scoring_engine=scoring)
    monkeypatch.setattr(engine, "_llm_chain_of_thought", lambda *args: {
        "steps": [], "conclusion": "", "confidence": 0.5,
    })
    result = engine.chain_of_thought("How are project facts stored?")
    assert result.conclusion
    assert result.source != "llm"
    assert any("SQLite" in step.answer for step in result.steps)
