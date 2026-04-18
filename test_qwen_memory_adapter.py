#!/usr/bin/env python3
"""test_qwen_memory_adapter.py — Unit tests for QwenMemoryAdapter."""
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from modules.qwen_memory_adapter import (
    QwenMemoryAdapter,
    _fact_text,
    _is_internal_fact,
    _parse_audit_decision,
    get_qwen_memory_adapter,
    reset_qwen_memory_adapter,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_brain(response: str = "KEEP") -> MagicMock:
    brain = MagicMock()
    brain.ask.return_value = response
    return brain


def _make_kb(facts=None):
    kb = MagicMock()
    kb.list_facts.return_value = facts or []
    kb.get_learning_log.return_value = []
    kb.get_learning_queue.return_value = []
    kb.data = {"facts": list(facts or [])}
    kb.lock = __import__("threading").RLock()
    kb._save = MagicMock()
    kb.add_fact = MagicMock()
    return kb


def _fact(key="test:fact", value="some info", tags=None):
    return {"key": key, "value": value, "tags": tags or ["research"], "ts": int(time.time())}


# ── _fact_text ────────────────────────────────────────────────────────────────

def test_fact_text_string():
    assert _fact_text({"value": "hello"}) == "hello"


def test_fact_text_dict():
    d = {"value": {"summary": "short summary"}}
    result = _fact_text(d)
    assert "short summary" in result


def test_fact_text_truncated():
    long_val = "x" * 1000
    assert len(_fact_text({"value": long_val})) <= 400


# ── _is_internal_fact ─────────────────────────────────────────────────────────

def test_internal_fact_by_tag():
    assert _is_internal_fact({"tags": ["routing"]}) is True
    assert _is_internal_fact({"tags": ["loop"]}) is True
    assert _is_internal_fact({"tags": ["research"]}) is False


def test_internal_fact_by_key():
    assert _is_internal_fact({"key": "ale_step:14", "tags": []}) is True
    assert _is_internal_fact({"key": "cycle_count", "tags": []}) is True
    assert _is_internal_fact({"key": "python:async_patterns", "tags": ["code"]}) is False


# ── _parse_audit_decision ─────────────────────────────────────────────────────

@pytest.mark.parametrize("response,expected_action", [
    ("KEEP", "keep"),
    ("keep", "keep"),
    ("REWRITE: Use list comprehensions for clarity.", "rewrite"),
    ("REMOVE: duplicate entry", "remove"),
    ("some random text", "keep"),   # unrecognized → keep (safe default)
    ("", "keep"),
])
def test_parse_audit_decision_action(response, expected_action):
    action, _, _ = _parse_audit_decision(response)
    assert action == expected_action


def test_parse_audit_decision_rewrite_value():
    _, new_val, _ = _parse_audit_decision("REWRITE: Better, concise fact text here.")
    assert "Better, concise fact text here." in new_val


def test_parse_audit_decision_remove_reason():
    _, _, reason = _parse_audit_decision("REMOVE: stale after refactor")
    assert "stale" in reason


# ── QwenMemoryAdapter.get_memory_summary ─────────────────────────────────────

def test_get_memory_summary_no_kb():
    adapter = QwenMemoryAdapter(local_brain=_make_brain(), knowledge_db=None)
    # Patch auto-resolve to return None
    with patch("modules.qwen_memory_adapter.KnowledgeDB", side_effect=ImportError):
        adapter.knowledge_db = None
        result = adapter.get_memory_summary()
    assert "not available" in result.lower() or "empty" in result.lower()


def test_get_memory_summary_with_facts():
    facts = [_fact(f"fact:{i}", f"value {i}") for i in range(5)]
    kb = _make_kb(facts=facts)
    adapter = QwenMemoryAdapter(local_brain=_make_brain(), knowledge_db=kb)
    result = adapter.get_memory_summary(limit=5)
    assert "Niblit Memory Snapshot" in result
    assert "fact:0" in result


def test_get_memory_summary_empty():
    adapter = QwenMemoryAdapter(local_brain=_make_brain(), knowledge_db=_make_kb())
    result = adapter.get_memory_summary()
    assert "empty" in result.lower()


# ── QwenMemoryAdapter.review_fact ────────────────────────────────────────────

def test_review_fact_keep():
    brain = _make_brain("KEEP")
    adapter = QwenMemoryAdapter(brain, _make_kb())
    decision = adapter.review_fact(_fact())
    assert decision["action"] == "keep"
    assert brain.ask.called


def test_review_fact_rewrite():
    brain = _make_brain("REWRITE: More concise version of the fact.")
    adapter = QwenMemoryAdapter(brain, _make_kb())
    decision = adapter.review_fact(_fact())
    assert decision["action"] == "rewrite"
    assert "concise" in decision["new_value"].lower()


def test_review_fact_remove():
    brain = _make_brain("REMOVE: duplicate of existing entry")
    adapter = QwenMemoryAdapter(brain, _make_kb())
    decision = adapter.review_fact(_fact())
    assert decision["action"] == "remove"
    assert "duplicate" in decision["reason"]


def test_review_fact_no_brain():
    adapter = QwenMemoryAdapter(local_brain=None, knowledge_db=_make_kb())
    decision = adapter.review_fact(_fact())
    assert decision["action"] == "keep"
    assert "unavailable" in decision["reason"]


# ── QwenMemoryAdapter.run_memory_audit ───────────────────────────────────────

def test_run_memory_audit_dry_run_no_changes():
    facts = [_fact(f"k:{i}", "some research content") for i in range(3)]
    brain = _make_brain("REWRITE: Better version.")
    kb = _make_kb(facts=facts)
    adapter = QwenMemoryAdapter(brain, kb)
    result = adapter.run_memory_audit(max_facts=3, apply_changes=False)
    assert "dry run" in result.lower()
    assert "REWRITE" in result
    assert kb.add_fact.call_count == 0  # no writes in dry run


def test_run_memory_audit_applies_rewrites():
    facts = [_fact("important:fact", "a fact needing improvement")]
    brain = _make_brain("REWRITE: Improved, concise fact.")
    kb = _make_kb(facts=facts)
    adapter = QwenMemoryAdapter(brain, kb)
    result = adapter.run_memory_audit(max_facts=5, apply_changes=True)
    assert kb.add_fact.called
    assert "Improved" in str(kb.add_fact.call_args)


def test_run_memory_audit_skips_internal_facts():
    internal = _fact("ale_step:3", "internal counter", tags=["loop"])
    research = _fact("python:async", "asyncio patterns", tags=["research"])
    kb = _make_kb(facts=[internal, research])
    brain = _make_brain("KEEP")
    adapter = QwenMemoryAdapter(brain, kb)
    adapter.run_memory_audit(max_facts=10, apply_changes=False)
    # Should only have reviewed the research fact (1 call), not the internal one
    assert brain.ask.call_count == 1


def test_run_memory_audit_applies_removes():
    facts = [_fact("old:stale", "outdated content")]
    brain = _make_brain("REMOVE: no longer relevant")
    kb = _make_kb(facts=facts)
    # Place the fact into kb.data.facts so _remove_fact can find it
    kb.data["facts"] = list(facts)
    adapter = QwenMemoryAdapter(brain, kb)
    result = adapter.run_memory_audit(max_facts=5, apply_changes=True)
    assert "REMOVE" in result
    assert kb._save.called


# ── QwenMemoryAdapter.coach_niblit ───────────────────────────────────────────

def test_coach_niblit_returns_report():
    facts = [_fact("python:syntax", "list comprehensions rock")]
    brain = _make_brain(
        "1. **KB Health**: 3/5\n"
        "2. **Gaps**: async patterns, decorators\n"
        "3. **Stale**: none\n"
        "4. **Next**: Study threading"
    )
    kb = _make_kb(facts=facts)
    adapter = QwenMemoryAdapter(brain, kb)
    result = adapter.coach_niblit()
    assert "Coaching Report" in result
    assert brain.ask.called


def test_coach_niblit_no_brain():
    adapter = QwenMemoryAdapter(local_brain=None, knowledge_db=_make_kb())
    result = adapter.coach_niblit()
    assert "unavailable" in result.lower()


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_singleton_returns_same_instance():
    reset_qwen_memory_adapter()
    brain = _make_brain()
    kb = _make_kb()
    a1 = get_qwen_memory_adapter(local_brain=brain, knowledge_db=kb)
    a2 = get_qwen_memory_adapter(local_brain=brain, knowledge_db=kb)
    assert a1 is a2
    reset_qwen_memory_adapter()  # cleanup for other tests


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_accumulate():
    facts = [_fact(f"k:{i}", "content") for i in range(4)]
    brain = _make_brain("KEEP")
    kb = _make_kb(facts=facts)
    adapter = QwenMemoryAdapter(brain, kb)
    adapter.run_memory_audit(max_facts=4, apply_changes=False)
    stats = adapter.get_stats()
    assert stats["audits_run"] == 1
    assert stats["facts_reviewed"] >= 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
