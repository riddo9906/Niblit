"""Phase 5B tests: research orchestrator + trading read-only surface.

Covers: provider normalization/bounding/failure; topic parse + malformed
handling; internal-first gap logic; budgets/termination; promotion
accept/reject + recall; event emission; trading read-through, unavailability
and structural absence of any execution surface.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict, List, Optional, Tuple

import pytest

from modules.event_bus import NiblitEvent
from modules.governed_research import GovernedSearch
from modules.research_orchestrator import (
    MAX_LLM_RETRIES,
    ResearchOrchestrator,
    ResearchStructuralError,
    register_research_tools,
)
from modules.research_provider_adapter import DuckDuckGoSearchProvider
from modules.trading_read_tools import (
    FORBIDDEN_EXECUTION_NAMES,
    execute_trading_runtime_status,
    read_runtime_status,
    register as register_trading,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeLoop:
    """Scripted stand-in for LlmToolLoop.chat + register_capability."""

    def __init__(self, replies: List[Any]):
        self.replies = list(replies)
        self.chats: List[List[dict]] = []
        self.tool_map: Dict[str, Any] = {}
        self.schemas: Dict[str, Any] = {}

    def chat(self, messages, tools=None, model="test"):
        self.chats.append(messages)
        reply = self.replies.pop(0) if self.replies else "not json at all"
        if isinstance(reply, dict):
            reply = json.dumps(reply)
        return {"text": reply, "trace": [], "niblit_model": "test"}

    def register_capability(self, name, fn, schema):
        self.tool_map[name] = fn
        self.schemas[name] = schema


class FakeStore:
    """TieredKnowledgeSystem-compatible in-memory stand-in."""

    def __init__(self, initial: Optional[Dict[str, str]] = None):
        self.entries: Dict[str, List[str]] = {}
        for topic, content in (initial or {}).items():
            self.entries.setdefault(topic.lower(), []).append(content)
        self.stored_calls: List[Tuple[str, str, str]] = []

    def store_knowledge(self, topic, content, source="unknown", tier=None):
        self.stored_calls.append((topic, content, source))
        self.entries.setdefault(topic.lower(), []).append(content)

    def recall_knowledge(self, topic):
        items = self.entries.get(str(topic).lower())
        if not items:
            return None
        return "\n".join(f"[tier|source] {c}" for c in items)


class FakeBus:
    def __init__(self):
        self.published: List[NiblitEvent] = []

    def publish(self, event):
        self.published.append(event)


# ---------------------------------------------------------------------------
# Scripted fixtures
# ---------------------------------------------------------------------------

ASSESS = {
    "normalized_topic": "python asyncio taskgroup failure handling",
    "objective": "understand failure semantics",
    "scope": "focused",
    "subtopics": [],
    "key_questions": ["How does TaskGroup handle task failure?"],
    "terminology": ["TaskGroup", "ExceptionGroup"],
    "ambiguities": [],
    "expected_source_types": ["docs"],
    "searchability_score": 0.9,
    "decomposition_required": False,
}

PLAN = {
    "questions": ["How does TaskGroup handle task failure?"],
    "search_queries": ["asyncio TaskGroup failure semantics"],
    "source_preferences": ["official docs"],
    "knowledge_gaps": ["error propagation detail"],
    "max_searches": 2,
    "max_fetches": 3,
    "max_rounds": 2,
}

AUDIT_PASS = {
    "relevant": True,
    "supports_claims": ["TaskGroup cancels remaining tasks when one fails"],
    "unsupported_claims": [],
    "contradictions": [],
    "confidence": 0.9,
    "requires_followup": False,
    "followup_questions": [],
}

AUDIT_FOLLOWUP = {
    **AUDIT_PASS,
    "requires_followup": True,
    "followup_questions": ["which exception does it raise?"],
}

HITS = [{"title": "asyncio docs",
         "url": "https://docs.python.org/3/library/asyncio-task.html",
         "provider": "duckduckgo"}]


def make_search(hits):
    """GovernedSearch wired to an in-memory provider."""
    def provider(query, max_results):
        return [dict(h) for h in hits][:max_results]
    return GovernedSearch(provider=provider)


def make_fetch(monkeypatch, ok_urls, text="TaskGroup cancels siblings "
               "when a task fails."):
    """Replace governed_fetch inside the orchestrator (no network)."""
    def fake_fetch(url, max_bytes=None, timeout=None):
        if url in ok_urls:
            return {"evidence": {
                "evidence_id": "fetch-" + url[-6:],
                "source_url": url,
                "source_domain": url.split("//")[-1].split("/")[0],
                "retrieved_at": 1.0,
                "extracted_text": text,
            }, "bytes": len(text), "duration_ms": 1.0}
        return {"error": "http 404", "url": url}
    monkeypatch.setattr("modules.research_orchestrator.governed_fetch",
                        fake_fetch)


# ---------------------------------------------------------------------------
# Search provider adapter (real DuckDuckGo bridge)
# ---------------------------------------------------------------------------

def _stub_engine_module(monkeypatch, engine_cls):
    stub = types.ModuleType("modules.researcher_engine")
    stub.ResearcherEngine = engine_cls
    monkeypatch.setitem(sys.modules, "modules.researcher_engine", stub)


def test_provider_normalization_bounding_and_ranks(monkeypatch):
    class Engine:
        def web_search_hits(self, topic, max_results=5):
            hits = [{"title": f"t{i}", "url": f"https://example.com/{i}",
                     "snippet": f"s{i}"} for i in range(8)]
            hits.append({"title": "no url"})  # must be filtered out
            return hits

    _stub_engine_module(monkeypatch, Engine)
    results = DuckDuckGoSearchProvider().search("asyncio", max_results=3)
    assert len(results) == 3
    assert [r["rank"] for r in results] == [1, 2, 3]
    assert all(r["provider"] == "duckduckgo" for r in results)
    assert all(r["retrieved_at"] and r["url"] for r in results)
    assert results[0]["url"] == "https://example.com/0"
    assert results[0]["query"] == "asyncio"
    assert results[0]["snippet"] == "s0"


def test_provider_failure_surfaces_never_fakes_success(monkeypatch):
    class Engine:
        def web_search_hits(self, topic, max_results=5):
            raise RuntimeError("ddg down")

    _stub_engine_module(monkeypatch, Engine)
    with pytest.raises(RuntimeError, match="ddg down"):
        DuckDuckGoSearchProvider().search("q")


def test_provider_rejects_empty_query():
    with pytest.raises(ValueError, match="empty_search_query"):
        DuckDuckGoSearchProvider().search("   ")


def test_provider_legacy_summary_api_degrades_without_fabricating(monkeypatch):
    class LegacyEngine:  # pre-5B engine: summary-only, no structured hits
        def web_search(self, topic):
            return "TaskGroup cancels remaining tasks when one fails."

    _stub_engine_module(monkeypatch, LegacyEngine)
    results = DuckDuckGoSearchProvider().search("asyncio")
    assert results == []  # URL-less summary must NOT fabricate provenance


# ---------------------------------------------------------------------------
# Topic assessment boundary
# ---------------------------------------------------------------------------

def test_topic_assessment_parses_and_preserves_original():
    loop = FakeLoop([ASSESS])
    orchestrator = ResearchOrchestrator(loop)
    assessment = orchestrator.assess_topic(
        "How does Python asyncio TaskGroup handle task failure?")
    assert assessment.original_topic == (
        "How does Python asyncio TaskGroup handle task failure?")
    assert assessment.normalized_topic == (
        "python asyncio taskgroup failure handling")
    assert assessment.searchability_score == pytest.approx(0.9)
    assert assessment.key_questions == [
        "How does TaskGroup handle task failure?"]


def test_fenced_json_reply_is_accepted():
    loop = FakeLoop(["```json\n" + json.dumps(ASSESS) + "\n```"])
    assessment = ResearchOrchestrator(loop).assess_topic("t")
    assert assessment.searchability_score == pytest.approx(0.9)


def test_malformed_topic_fails_structurally_after_bounded_retries():
    loop = FakeLoop(["garbage"] * (MAX_LLM_RETRIES + 1))
    with pytest.raises(ResearchStructuralError):
        ResearchOrchestrator(loop).assess_topic("t")
    assert len(loop.chats) == MAX_LLM_RETRIES + 1
    assert any("not valid JSON" in m["content"] for m in loop.chats[-1])


# ---------------------------------------------------------------------------
# Internal-first inspection
# ---------------------------------------------------------------------------

def test_internal_first_empty_store_creates_gap():
    loop = FakeLoop([ASSESS, PLAN])
    orchestrator = ResearchOrchestrator(loop, knowledge_store=FakeStore())
    assessment = orchestrator.assess_topic("t")
    findings = orchestrator.internal_first(assessment)
    assert findings == []
    plan = orchestrator.plan_research(assessment, findings)
    assert any("internal" in g.lower() for g in plan.knowledge_gaps)
    planner_user = loop.chats[-1][1]["content"]
    assert '"internal_knowledge": []' in planner_user


def test_internal_first_surfaces_existing_knowledge():
    loop = FakeLoop([ASSESS, PLAN])
    store = FakeStore({"python asyncio taskgroup failure handling":
                       "TaskGroup gathers tasks"})
    orchestrator = ResearchOrchestrator(loop, knowledge_store=store)
    assessment = orchestrator.assess_topic("t")
    findings = orchestrator.internal_first(assessment)
    assert len(findings) == 1
    assert findings[0].provenance == "tiered_knowledge_system"
    plan = orchestrator.plan_research(assessment, findings)
    planner_user = loop.chats[-1][1]["content"]
    assert "TaskGroup gathers tasks" in planner_user
    assert plan.internal_findings
    assert not any("internal-first miss" in g for g in plan.knowledge_gaps)


# ---------------------------------------------------------------------------
# Full research run: budgets, promotion, recall, events
# ---------------------------------------------------------------------------

def test_full_run_promotes_and_proves_recall(monkeypatch):
    make_fetch(monkeypatch, ok_urls={HITS[0]["url"]})
    loop = FakeLoop([ASSESS, PLAN, AUDIT_PASS])
    store, bus = FakeStore(), FakeBus()
    orchestrator = ResearchOrchestrator(
        loop, knowledge_store=store, event_bus=bus, search=make_search(HITS),
        max_searches=2, max_fetches=2, max_rounds=2)
    result = orchestrator.run(
        "How does Python asyncio TaskGroup handle task failure?")
    assert result.decision.approved is True
    assert result.decision.status == "approved"
    assert result.stored == result.candidate.candidate_id
    assert store.stored_calls, "approved candidate must be persisted"
    assert store.stored_calls[0][0] == result.candidate.normalized_topic
    assert store.stored_calls[0][2] == "research_orchestrator"
    assert result.recall and result.recall["verified"] is True
    event_types = [e["type"] for e in result.events]
    assert event_types[0] == "research.started"
    assert event_types[-1] == "research.completed"
    assert "memory.promotion.approved" in event_types
    assert "memory.recalled" in event_types
    assert [p.type for p in bus.published] == event_types
    assert result.usage["searches"] == 1 and result.usage["fetches"] == 1
    artifact = result.artifact()
    assert artifact["promotion"]["status"] == "approved"
    assert artifact["bundle"]["supporting_evidence_ids"]


def test_budgets_bound_searches_fetches_and_rounds(monkeypatch):
    make_fetch(monkeypatch, ok_urls=set())  # every fetch fails
    many_hits = [{"title": f"h{i}", "url": f"https://example.com/{i}",
                  "provider": "duckduckgo"} for i in range(10)]
    plan_bloated = {**PLAN, "max_searches": 9, "max_fetches": 9,
                    "max_rounds": 4}
    loop = FakeLoop([ASSESS, plan_bloated, AUDIT_FOLLOWUP, AUDIT_PASS,
                     AUDIT_PASS, AUDIT_PASS])
    orchestrator = ResearchOrchestrator(
        loop, knowledge_store=FakeStore(), event_bus=FakeBus(),
        search=make_search(many_hits), max_searches=2, max_fetches=3,
        max_rounds=2)
    result = orchestrator.run("t")
    assert result.plan.max_searches == 2
    assert result.plan.max_fetches == 3
    assert result.plan.max_rounds == 2
    assert result.usage["searches"] <= 2
    assert result.usage["fetches"] <= 3
    assert result.usage["rounds"] <= 2
    assert result.usage["llm_chat_calls"] <= 2 + 3
    assert any("fetch budget" in e for e in result.errors)


def test_low_confidence_rejects_promotion_and_skips_persistence(monkeypatch):
    make_fetch(monkeypatch, ok_urls={HITS[0]["url"]})
    low = {**AUDIT_PASS, "confidence": 0.2}
    loop = FakeLoop([ASSESS, PLAN, low])
    store = FakeStore()
    orchestrator = ResearchOrchestrator(
        loop, knowledge_store=store, event_bus=FakeBus(),
        search=make_search(HITS))
    result = orchestrator.run("t")
    assert result.decision.approved is False
    assert any("below" in r for r in result.decision.reasons)
    assert result.stored is None
    assert "memory.promotion.rejected" in [e["type"] for e in result.events]
    assert store.stored_calls == []


def test_contradictions_retained_and_block_promotion(monkeypatch):
    make_fetch(monkeypatch, ok_urls={HITS[0]["url"]})
    contradiction = "docs raise ExceptionGroup, not plain Exception"
    contra = {**AUDIT_PASS, "contradictions": [contradiction]}
    loop = FakeLoop([ASSESS, PLAN, contra])
    orchestrator = ResearchOrchestrator(
        loop, knowledge_store=FakeStore(), event_bus=FakeBus(),
        search=make_search(HITS))
    result = orchestrator.run("t")
    assert contradiction in result.candidate.contradictions
    assert result.decision.approved is False
    assert any("contradiction" in r for r in result.decision.reasons)


def test_no_evidence_rejects_and_records_gap(monkeypatch):
    loop = FakeLoop([ASSESS, PLAN])
    orchestrator = ResearchOrchestrator(
        loop, knowledge_store=FakeStore(), event_bus=FakeBus(),
        search=make_search([]))
    result = orchestrator.run("t")
    assert result.decision.approved is False
    assert any("no retrievable evidence" in g
               for g in result.candidate.unresolved_gaps)
    assert result.usage["fetches"] == 0


def test_events_are_well_formed_and_ordered(monkeypatch):
    make_fetch(monkeypatch, ok_urls=set())
    loop = FakeLoop([ASSESS, PLAN])
    orchestrator = ResearchOrchestrator(loop, event_bus=FakeBus(),
                                        search=make_search([]))
    orchestrator.run("t")
    assert orchestrator.events[0]["type"] == "research.started"
    assert orchestrator.events[-1]["type"] == "research.completed"
    assert all(isinstance(e["payload"], dict) for e in orchestrator.events)
    stamps = [e["timestamp"] for e in orchestrator.events]
    assert stamps == sorted(stamps)
    assert all(e["source"] == "research_orchestrator"
               for e in orchestrator.events)


# ---------------------------------------------------------------------------
# Trading read-only surface
# ---------------------------------------------------------------------------

class StubRuntime:
    state = "running"
    backend = "paper"
    execution_mode = "paper"
    market_data_provider = "synthetic"
    execution_enabled = False


def test_trading_registration_uses_loop_signature_and_function_schema():
    loop = FakeLoop([])
    name = register_trading(loop, lambda: StubRuntime())
    assert name == "trading_runtime_status"
    assert callable(loop.tool_map["trading_runtime_status"])
    schema = loop.schemas["trading_runtime_status"]
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "trading_runtime_status"
    assert fn["parameters"]["type"] == "object"
    assert fn["parameters"]["required"] == []


def test_trading_read_through_truthful():
    status = read_runtime_status(StubRuntime())
    assert status["available"] is True
    assert status["read_only"] is True
    assert status["state"] == "running"
    assert status["backend"] == "paper"
    assert status["execution_mode"] == "paper"
    assert status["market_data_provider"] == "synthetic"
    assert status["execution_enabled"] is False


def test_trading_unavailable_is_truthful_not_fabricated():
    assert read_runtime_status(None) == {
        "available": False,
        "reason": "trading_runtime_not_initialized",
        "execution_tools_exposed": False,
    }
    missing = read_runtime_status(object())
    assert missing["available"] is True
    assert missing["state"] == "unavailable"
    assert missing["backend"] == "unavailable"
    assert missing["execution_enabled"] == "unavailable"


def test_trading_rejects_arguments_and_exposes_no_execution_surface():
    with pytest.raises(ValueError):
        execute_trading_runtime_status({"symbol": "BTC"}, StubRuntime())
    loop = FakeLoop([])
    register_trading(loop, lambda: StubRuntime())
    names = set(loop.tool_map)
    assert "trading_runtime_status" in names
    for forbidden in FORBIDDEN_EXECUTION_NAMES:
        assert forbidden not in names
        assert forbidden not in json.dumps(loop.schemas)


# ---------------------------------------------------------------------------
# Governed loop wiring (real LlmToolLoop)
# ---------------------------------------------------------------------------

def test_research_tools_registration_shapes():
    loop = FakeLoop([])
    search = register_research_tools(loop)
    assert isinstance(search, GovernedSearch)
    assert {"web_search", "web_fetch"} <= set(loop.tool_map)
    ws = loop.schemas["web_search"]
    assert ws["type"] == "function"
    assert ws["function"]["name"] == "web_search"
    assert ws["function"]["parameters"]["required"] == ["query"]
    wf = loop.schemas["web_fetch"]
    assert wf["function"]["parameters"]["required"] == ["url"]


def test_real_loop_accepts_registered_tools_and_validator_passes():
    from modules.llm_tool_loop import LlmToolLoop, ToolCallError

    loop = LlmToolLoop()
    register_trading(loop, lambda: None)
    register_research_tools(loop)
    names = set(loop.allowed_tool_names())
    assert {"trading_runtime_status", "web_search", "web_fetch",
            "runtime_status"} <= names
    assert not (names & set(FORBIDDEN_EXECUTION_NAMES))

    trading_call = {"function": {"name": "trading_runtime_status",
                                 "arguments": "{}"}}
    tool, args = loop._validate_call(trading_call, loop._schemas)
    assert tool == "trading_runtime_status" and args == {}

    search_call = {"function": {"name": "web_search",
                                "arguments": json.dumps(
                                    {"query": "asyncio", "max_results": 2})}}
    tool, args = loop._validate_call(search_call, loop._schemas)
    assert tool == "web_search" and args["query"] == "asyncio"

    # handler invocation style matches the loop's fn(**args) convention
    result = loop._tool_map["trading_runtime_status"]()
    assert result["available"] is False  # truthful: no runtime wired

    # execution-named capability never registered -> validator rejects
    with pytest.raises(ToolCallError):
        loop._validate_call(
            {"function": {"name": "place_order", "arguments": "{}"}},
            loop._schemas)
