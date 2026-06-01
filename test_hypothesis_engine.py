from __future__ import annotations

import json

from modules.hypothesis_engine import HypothesisEngine


def test_hypothesis_engine_lifecycle_and_commands() -> None:
    engine = HypothesisEngine()
    created = engine.create_hypothesis(
        topic="btc volatility",
        statement="Volatility regime transitions increase drawdown risk.",
        origin_stream="market_cognition",
        confidence=0.52,
    )
    assert created["status"] == "emerging"
    hypothesis_id = created["hypothesis_id"]
    evidence_id = engine.ingest_evidence(
        source="adaptive_market_cognition",
        source_type="market_cognition",
        source_id="trace-1",
        summary="recent episodes show elevated drawdown under volatile regime",
        payload={"topic": "btc volatility", "confidence_score": 0.74, "risk_score": 0.68},
        hypothesis_id=hypothesis_id,
    )
    assert evidence_id
    contradiction = engine.register_contradiction(
        hypothesis_id=hypothesis_id,
        summary="similar regime had conflicting outcomes",
        source="adaptive_market_cognition",
        evidence_ids=[evidence_id],
    )
    assert contradiction is not None
    listed = engine.list_hypotheses(topic="btc")
    assert listed
    shown = engine.get_hypothesis(hypothesis_id)
    assert shown is not None
    assert shown["support"]
    assert shown["contradictions"]
    assert shown["status"] == "unresolved_contradiction"
    status = json.loads(engine.render_command("hypothesis status"))
    assert "summary" in status
    assert status["summary"]["hypothesis_count"] >= 1


def test_hypothesis_engine_auto_generation_streams_and_graph() -> None:
    engine = HypothesisEngine()
    engine.observe_runtime_event(
        "market_episode.ingested",
        "lean_algo_manager",
        {
            "trace_id": "trace-market-1",
            "topic": "eth drawdown replay",
            "regime": "bear",
            "signal": "breakdown",
            "confidence_score": 0.57,
            "risk_score": 0.66,
            "evaluation_score": 0.48,
            "reflection_summary": "confidence outran evidence",
        },
    )
    engine.observe_runtime_event(
        "reflection.complete",
        "reflection_engine",
        {
            "trace_id": "trace-refl-1",
            "topic": "provider routing quality",
            "summary": "low recent quality detected",
            "overall_health": 0.41,
            "overconfident_areas": ["provider selection"],
        },
    )
    graph = engine.build_market_knowledge_graph()
    assert graph["chain_model"].startswith("Regime")
    assert graph["chain_count"] >= 1
    gaps = engine.analyze_knowledge_gaps()
    assert "learning_priorities" in gaps
    assert isinstance(engine.directed_hypothesis_questions(), list)
