"""Bounded memory projection cycle: no SQLite, embeddings, broker or Qdrant."""
import threading
from types import SimpleNamespace

import pytest
from modules.memory_laboratory.runtime import MemoryRuntime


def test_memory_projection_cycle_respects_budgets(monkeypatch):
    from modules.memory_laboratory import market
    monkeypatch.setattr(market, "MarketJournal", lambda gateway: SimpleNamespace(repair_pending=lambda: None))
    runtime = object.__new__(MemoryRuntime)
    runtime.gateway = object()
    runtime.stop_event = threading.Event()
    runtime._last_sync = 0
    runtime.last_cycle = None
    calls = []
    runtime._phase = lambda name, fn: fn()
    runtime.tick = lambda limit: calls.append(("general", limit)) or {"completed": 0, "failed": 0}
    runtime.tick_market_partitions = lambda limit: calls.append(("market", limit)) or {}
    runtime.tick_remote = lambda limit: calls.append(("remote", limit)) or {}

    monkeypatch.delenv("NIBLIT_MEMORY_SYNC_SOURCE", raising=False)
    monkeypatch.setenv("NIBLIT_MEMORY_GENERAL_JOBS_PER_CYCLE", "2")
    monkeypatch.setenv("NIBLIT_MEMORY_MARKET_JOBS_PER_CYCLE", "1")
    runtime.run_once()
    assert calls == [("general", 2), ("market", 1), ("remote", 2)]
    assert runtime.last_cycle is not None

    calls.clear()
    monkeypatch.setenv("NIBLIT_MEMORY_GENERAL_JOBS_PER_CYCLE", "5")
    monkeypatch.setenv("NIBLIT_MEMORY_MARKET_JOBS_PER_CYCLE", "3")
    runtime.run_once()
    assert calls == [("general", 4), ("market", 3), ("general", 1), ("remote", 2)]

    calls.clear()
    monkeypatch.delenv("NIBLIT_MEMORY_GENERAL_JOBS_PER_CYCLE", raising=False)
    monkeypatch.delenv("NIBLIT_MEMORY_MARKET_JOBS_PER_CYCLE", raising=False)
    runtime.run_once()
    assert calls == [("general", 4), ("market", 8), ("general", 28), ("remote", 2)]


@pytest.mark.parametrize("value, expected", [("0", 1), ("-4", 1), ("9000", 32), ("invalid", 32)])
def test_general_budget_invalid_or_unbounded(monkeypatch, value, expected):
    from modules.memory_laboratory import market
    monkeypatch.setattr(market, "MarketJournal", lambda gateway: SimpleNamespace(repair_pending=lambda: None))
    runtime = object.__new__(MemoryRuntime)
    runtime.gateway = object()
    runtime.stop_event = threading.Event()
    runtime._last_sync = 0
    runtime.last_cycle = None
    calls = []
    runtime._phase = lambda name, fn: fn()
    runtime.tick = lambda limit: calls.append(limit) or {"completed": 0, "failed": 0}
    runtime.tick_market_partitions = lambda limit: {}
    runtime.tick_remote = lambda limit: {}
    monkeypatch.delenv("NIBLIT_MEMORY_SYNC_SOURCE", raising=False)
    monkeypatch.setenv("NIBLIT_MEMORY_GENERAL_JOBS_PER_CYCLE", value)
    monkeypatch.setenv("NIBLIT_MEMORY_MARKET_JOBS_PER_CYCLE", "1")
    runtime.run_once()
    assert sum(calls) == expected
