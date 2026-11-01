import json
import sqlite3

import pytest

from modules.memory_laboratory.runtime import MemoryRuntime, readable
from modules.memory_laboratory.market import MarketJournal
from test_memory_laboratory_gateway import Backend, gateway


def test_durable_queue_outage_reopen_correction_and_backup(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    runtime = MemoryRuntime(g, scope={"namespace": "test", "principal": "operator"})
    first = runtime.enqueue(source="note", content="The desk code is copper.")
    assert first == runtime.enqueue(source="note", content="The desk code is copper.")
    backend.offline = True
    assert runtime.tick()["failed"] == 1
    with g.db() as db:
        row = db.execute("SELECT * FROM ingestion_outbox").fetchone()
        assert row["state"] == "pending" and "copper" in row["body"]
        db.execute("UPDATE ingestion_outbox SET next_attempt=0")
    backend.offline = False
    reopened = MemoryRuntime(gateway(tmp_path, backend), scope=runtime.scope)
    assert reopened.tick()["completed"] == 1
    assert g.retrieve("copper", **runtime.scope)["results"][0]["verification"] == "unverified"
    reopened.enqueue(source="note", content="The desk code is violet.")
    reopened.tick()
    results = g.retrieve("desk", **runtime.scope)["results"]
    assert len(results) == 1 and "violet" in results[0]["content"]
    reopened.enqueue(source="note", content="The desk code is copper.")
    reopened.tick()
    assert "copper" in g.retrieve("desk", **runtime.scope)["results"][0]["content"]
    path = tmp_path / "backup.sqlite"
    reopened.backup(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM records WHERE active=1").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_import_prose_confidence_secrets_and_review(tmp_path):
    g = gateway(tmp_path, Backend())
    runtime = MemoryRuntime(g, scope={"namespace": "test", "principal": "operator"})
    fact = {"key": "topic:1", "value": {"content": "Liquidity is the ability to trade without large price changes.", "confidence_score": .4}}
    source = tmp_path / "memory.json"
    source.write_text(json.dumps({"facts": [fact]}))
    assert runtime.sync_knowledge_file(source) == 1
    assert runtime.sync_knowledge_file(source) == 0
    runtime.tick()
    hit = g.retrieve("Liquidity", **runtime.scope)["results"][0]
    assert hit["confidence"] == .4 and hit["verification"] == "unverified"
    assert readable("{'topic':'liquidity','content':'Readable prose.'}") == "Readable prose."
    with pytest.raises(PermissionError):
        runtime.enqueue(source="test", content="sk-proj-" + "x"*40)
    g.review_record(hit["id"], **runtime.scope, verification="rejected", confidence=.1, evidence="Operator found the source incorrect.")
    assert not g.retrieve("Liquidity", **runtime.scope)["results"]


def test_failed_old_job_is_superseded_and_pending_evidence_can_be_rebuilt(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    runtime = MemoryRuntime(g, scope={"namespace": "test", "principal": "operator"})
    runtime.enqueue(source="note", content="Old fact.")
    runtime.enqueue(source="note", content="New fact.")
    assert runtime.tick()["completed"] == 1
    assert "New fact" in g.retrieve("fact", **runtime.scope)["results"][0]["content"]
    backend.points.clear()
    assert runtime.rebuild()["repaired"] == 1
    assert len(backend.points) == 1


def test_market_point_in_time_isolation_and_outcome_no_lookahead(tmp_path, monkeypatch):
    g = gateway(tmp_path, Backend())
    market = MarketJournal(g)
    monkeypatch.setattr(market, "project", lambda key: None)
    kwargs = dict(symbol="BTCUSDT", venue="fixture", interval="1m", mode="paper")
    before = "2026-10-27T10:00:00+00:00"
    key = market.observe([1., 2., 3.], **kwargs, observed_at=before, available_at=before)
    market.observe([1., 2., 3.], **{**kwargs, "mode": "replay"}, observed_at=before, available_at=before)
    market.observe([1., 2., 3.], **kwargs, observed_at="2026-10-27T12:00:00+00:00", available_at="2026-10-27T12:00:00+00:00")
    market.record_outcome(key, realized_return=.02, available_at="2026-10-27T11:00:00+00:00", evidence="Paper fill ledger abc, fees included.")
    prior = market.similar([1., 2., 3.], **kwargs, as_of="2026-10-27T10:30:00+00:00")
    assert len(prior) == 1 and prior[0]["outcome"] is None
    later = market.similar([1., 2., 3.], **kwargs, as_of="2026-10-27T11:30:00+00:00")
    assert len(later) == 1 and later[0]["outcome"]["realized_return"] == .02
    assert not market.similar([1., 2., 3.], **kwargs, as_of="2026-10-27T10:00:00+00:00")
    with pytest.raises(ValueError):
        market.observe([9., 2., 3.], **kwargs, observed_at=before, available_at=before)
    with pytest.raises(ValueError):
        market.record_outcome(key, realized_return=999., available_at="2026-10-27T11:00:00+00:00", evidence="changed")


def test_unified_memory_recovers_evidence_after_recreating_facade(tmp_path, monkeypatch):
    from modules.memory_laboratory import runtime as runtime_module
    from niblit_memory.unified_memory_engine import UnifiedMemoryEngine
    monkeypatch.setenv("NIBLIT_MEMORY_LAB_ENABLED", "1")
    g = gateway(tmp_path, Backend())
    r = MemoryRuntime(g, scope={"namespace": "test", "principal": "operator"})
    monkeypatch.setattr(runtime_module, "runtime_memory", lambda:r)
    monkeypatch.setattr(UnifiedMemoryEngine, "_try_store_kb", lambda *args:None)
    monkeypatch.setattr(UnifiedMemoryEngine, "_try_store_governed_memory", lambda *args, **kwargs:None)
    first = UnifiedMemoryEngine()
    first.remember("The cobalt toolbox belongs to the workspace.")
    r.tick()
    second = UnifiedMemoryEngine()
    assert second.recall("cobalt toolbox")[0].text == "The cobalt toolbox belongs to the workspace."


def test_similarity_alone_does_not_become_a_buy_signal(monkeypatch):
    import modules.trading_brain as module
    monkeypatch.setenv("NIBLIT_MEMORY_LAB_ENABLED", "1")
    monkeypatch.setattr(module, "_TFT_AVAILABLE", False)
    monkeypatch.setattr(module, "_RL_ENABLED", False)
    brain = object.__new__(module.TradingBrain)
    brain.retrieve_similar_states = lambda vector:[{"score": 1.0}] * 10
    assert brain.decide_action([1.,2.,3.]) == "HOLD"
