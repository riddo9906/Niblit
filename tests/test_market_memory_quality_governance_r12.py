"""Regression: decision quality is not temporal coherence."""
import pytest
from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer
from shared.governance_contract.memory_contracts import governed_recall_allowed

def _capture(monkeypatch, coherence=None):
    import niblit_memory.governed_qdrant_memory as memory_module
    writes = []
    class Cluster:
        def write_memory(self, text, *, memory_type, payload):
            writes.append((memory_type, dict(payload)))
            return {"id": "synthetic"}
    monkeypatch.setattr(memory_module, "get_governed_qdrant_memory_cluster", lambda: Cluster())
    record = {"trace_id": "r12-recall-test", "topic": "synthetic", "symbol": "EURUSD",
              "regime": "bull", "volatility_regime": "unknown", "risk_score": 0.0,
              "risk_state": {"risk_evidence": {"state": "missing", "missing": ["volatility"]}},
              "dqi_score": 0.2935, "reflection": "low-evidence",
              "outcome_state": {"label": "unknown"}, "causal_chain": []}
    if coherence is not None: record["coherence_score"] = coherence
    AdaptiveMarketCognitionLayer()._persist_experience(record)
    assert len(writes) == 2
    return writes

def test_low_dqi_does_not_block_memory_recall(monkeypatch):
    for memory_type, payload in _capture(monkeypatch):
        assert payload["dqi_score"] == 0.2935
        assert payload["dqi_policy"] == AdaptiveMarketCognitionLayer._DQI_POLICY
        assert payload["coherence_score"] >= 0.3
        assert governed_recall_allowed({**payload, "memory_type": memory_type})

def test_explicit_temporal_incoherence_remains_governed(monkeypatch):
    for memory_type, payload in _capture(monkeypatch, coherence=0.1):
        assert payload["coherence_score"] == pytest.approx(0.1)
        assert not governed_recall_allowed({**payload, "memory_type": memory_type})

def test_fallback_is_minimal_admissibility_floor(monkeypatch):
    assert all(payload["coherence_score"] == pytest.approx(0.3)
               for _, payload in _capture(monkeypatch))
