"""Offline regressions for unified memory identity and retention rules."""
from unittest.mock import Mock

import pytest

from niblit_memory import unified_memory_engine as ume


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setattr(ume, "_ENABLED", True)
    engine = ume.UnifiedMemoryEngine()
    # Exercise real in-process storage without accessing existing databases.
    monkeypatch.setattr(engine, "_try_store_kb", Mock())
    monkeypatch.setattr(engine, "_try_store_governed_memory", Mock())
    monkeypatch.setattr(engine, "_get_governed_cluster", lambda: None)
    return engine


def test_shared_opening_does_not_discard_distinct_memories(memory):
    prefix = "Project requirements: " + "shared context " * 12
    first = memory.remember(prefix + "Use SQLite for durable facts.")
    second = memory.remember(prefix + "Use Qdrant for semantic retrieval.")

    assert first != second
    assert memory.status()["total_records"] == 2
    assert memory.recall("SQLite")[0].text.endswith("durable facts.")
    assert memory.recall("Qdrant")[0].text.endswith("semantic retrieval.")


@pytest.mark.parametrize("importance,is_anchor", [(0.95, False), (0.6, True)])
def test_repeated_memory_can_gain_anchor_protection(memory, importance, is_anchor):
    uid = memory.remember("Keep this project decision", importance=0.4)
    repeated = memory.remember(
        "Keep this project decision", importance=importance, is_anchor=is_anchor
    )
    memory.compress()

    assert repeated == uid
    assert memory.status()["total_records"] == 1
    record = memory.recall_high_importance(0)[0]
    assert record.is_anchor is True
    assert record.importance == importance


def test_exact_repeat_stays_deduplicated_without_losing_tags(memory):
    uid = memory.remember("Project decision", tags=["project"], importance=0.8)
    assert memory.remember(
        "Project decision", tags=["project", "confirmed"], importance=0.3
    ) == uid

    record = memory.recall_high_importance(0)[0]
    assert memory.status()["total_records"] == 1
    assert record.importance == 0.8
    assert record.tags == ["project", "confirmed"]
    assert record.access_count == 1


def test_same_text_in_different_categories_is_distinct(memory):
    semantic = memory.remember("Project decision", category="semantic")
    strategic = memory.remember("Project decision", category="strategic")
    assert semantic != strategic
    assert memory.status()["total_records"] == 2
