from modules.desktop_runtime_shell import DesktopRuntimeShell


def test_market_intelligence_text_value_renders_core_sections() -> None:
    rendered = DesktopRuntimeShell._market_intelligence_text_value(
        {
            "market_intelligence": {
                "experience_count": 2,
                "last_bundle": {"query": "btc volatile breakout", "telemetry": {"dqi_score": 0.72, "risk_score": 0.41}},
                "market_cognition_timeline": [
                    {"timestamp": "2026-06-01T00:00:00Z", "topic": "btc breakout", "regime": "volatile", "risk_score": 0.41, "dqi_score": 0.72}
                ],
                "similar_market_retrievals": [
                    {"query": "btc breakout", "similar_market_hits": 3, "memory_hits": 2, "risk_score": 0.41}
                ],
                "dqi_scores": [{"topic": "btc breakout", "latest": 0.72, "outcome_quality": 0.68}],
                "risk_intelligence": [{"topic": "btc breakout", "risk_score": 0.41, "volatility_state": "high", "regime_uncertainty": 0.33}],
                "reflection_summaries": [{"summary": "confidence outran evidence during the breakout."}],
                "market_memory_retrievals": [{"summary": "historical breakout with drawdown risk"}],
                "unresolved_market_contradictions": [{"summary": "similar breakout had mixed outcomes"}],
            }
        }
    )
    assert "Market Intelligence" in rendered
    assert "market_cognition_timeline" in rendered
    assert "similar_market_retrievals" in rendered
    assert "dqi_scores" in rendered
    assert "risk_intelligence" in rendered
    assert "reflection_summaries" in rendered


def test_hypothesis_tabs_render_from_runtime_state() -> None:
    runtime_state = {
        "hypothesis_intelligence": {
            "summary": {
                "hypothesis_count": 3,
                "status_counts": {"emerging": 2, "unresolved_contradiction": 1},
                "origin_counts": {"market_cognition": 2, "reflection_cognition": 1},
                "evidence_count": 7,
                "unresolved_contradiction_count": 1,
            },
            "beliefs": [{"hypothesis_id": "hyp-1", "topic": "btc regime", "status": "emerging", "confidence": 0.62}],
            "directed_questions": [{"type": "missing_data", "question": "Which data reduces uncertainty?"}],
        },
        "market_knowledge_graph": {
            "chain_model": "Regime→Signal→Confidence→Risk→Outcome→Reflection→Evaluation",
            "chain_count": 4,
            "nodes": [{"stage": "Regime", "label": "volatile"}],
            "edges": [{"from": "a", "to": "b", "label": "Regime→Signal"}],
        },
        "contradiction_dashboard": {
            "status_counts": {"unresolved_contradiction": 1},
            "unresolved_contradictions": [{"contradiction_id": "hcon-1", "hypothesis_id": "hyp-1", "summary": "mixed outcomes"}],
            "directed_questions": [{"type": "contradiction_resolution", "question": "Why mixed outcomes?"}],
        },
    }
    hypothesis = DesktopRuntimeShell._hypothesis_intelligence_text_value(runtime_state)
    graph = DesktopRuntimeShell._market_knowledge_graph_text_value(runtime_state)
    contradictions = DesktopRuntimeShell._contradiction_dashboard_text_value(runtime_state)
    assert "Hypothesis Intelligence" in hypothesis
    assert "hypothesis_count" in hypothesis
    assert "Market Knowledge Graph" in graph
    assert "chain_model" in graph
    assert "Contradiction Dashboard" in contradictions
    assert "unresolved_total" in contradictions
