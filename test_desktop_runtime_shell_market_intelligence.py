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
