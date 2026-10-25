"""Phase 5A tests: topic/planning contracts, governed retrieval, evidence
audit, promotion gate, and research tools in the governed loop."""

import json

import pytest

from modules.llm_tool_loop import LlmToolLoop, ToolCallError
from modules.research_contracts import (
    EvidenceAudit,
    EvidenceBundle,
    EvidenceItem,
    KnowledgeCandidate,
    TopicAssessment,
    evaluate_promotion,
)
from modules.governed_research import (
    GovernedSearch,
    _url_allowed,
    WEB_FETCH_SCHEMA,
    WEB_SEARCH_SCHEMA,
    governed_fetch,
)


# ── topic / planning ────────────────────────────────────────────────────
def test_topic_assessment_preserves_original_and_normalized():
    t = TopicAssessment(original_topic="Teach yourself Python async programming",
                        normalized_topic="Python asyncio concurrency",
                        subtopics=["event loop", "coroutines"],
                        key_questions=["How does the event loop schedule tasks?"],
                        searchability_score=0.9)
    assert t.original_topic != t.normalized_topic
    assert "async programming" in t.original_topic
    assert t.subtopics and t.key_questions
    d = t.__dict__
    assert d["original_topic"] == "Teach yourself Python async programming"


def test_broad_topic_flags_decomposition():
    broad = TopicAssessment(original_topic="transformers",
                            normalized_topic="ambiguous: electrical vs ML",
                            ambiguities=["electrical transformer vs neural network"],
                            decomposition_required=True, searchability_score=0.3)
    assert broad.decomposition_required and broad.ambiguities
    focused = TopicAssessment(original_topic="x", normalized_topic="x",
                              decomposition_required=False)
    assert not focused.decomposition_required


# ── governed fetch (SSRF + provenance) ──────────────────────────────────
def test_fetch_rejects_local_and_private_urls():
    for url in ("http://127.0.0.1:8000/x", "http://localhost/y",
                "http://192.168.1.5/z", "file:///etc/passwd",
                "ftp://example.com/a"):
        res = governed_fetch(url)
        assert "error" in res, url


def test_fetch_rejects_dns_rebind_to_private(monkeypatch):
    import socket as _s
    monkeypatch.setattr(_s, "getaddrinfo",
                        lambda h, p: [(2, 1, 6, "", ("10.0.0.7", 0))])
    res = governed_fetch("https://evil.example.com/payload")
    assert "non-public" in res.get("error", "")


def test_url_allowed_accepts_public_domain(monkeypatch):
    import socket as _s
    monkeypatch.setattr(_s, "getaddrinfo",
                        lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    ok, reason = _url_allowed("https://docs.example.com/guide")
    assert ok, reason


# ── governed search ─────────────────────────────────────────────────────
def test_search_requires_permission_when_configured():
    s = GovernedSearch(permission_check=lambda cap: False)
    out = s.search("python asyncio", 3)
    assert "permission denied" in out["error"]


def test_search_bounded_results_and_provenance():
    def fake_provider(q, n):
        return [{"title": f"r{i}", "url": f"https://docs.example.com/{i}",
                 "provider": "fake"} for i in range(20)]
    s = GovernedSearch(provider=fake_provider)
    out = s.search("q", 4)
    assert out["count"] == 4
    assert all(r["domain"] == "docs.example.com" for r in out["results"])
    assert all(r["provider"] for r in out["results"])


def test_search_structural_failure_not_exception():
    def boom(q, n):
        raise RuntimeError("network down")
    s = GovernedSearch(provider=boom)
    out = s.search("anything")
    assert "provider failure" in out["error"]
    assert out["query"] == "anything"


# ── evidence audit + promotion gate ─────────────────────────────────────
def _evidence(status="unaudited"):
    return EvidenceItem(query="asyncio TaskGroup failure",
                        source_url="https://docs.python.org/3/library/asyncio",
                        source_domain="docs.python.org",
                        title="asyncio", extracted_text="TaskGroup cancels...",
                        claims=["TaskGroup cancels sibling tasks on failure"],
                        audit_status=status)


def test_unaudited_evidence_cannot_promote():
    cand = KnowledgeCandidate(
        original_topic="t", normalized_topic="t",
        learned_claims=["c"], evidence_ids=["e1"],
        provenance_urls=["https://docs.python.org"], confidence=0.9)
    bundle = EvidenceBundle(question="q", supporting=[_evidence("unaudited")])
    decision = evaluate_promotion(cand, bundle)
    assert not decision.approved
    assert any("unaudited" in r for r in decision.reasons)


def test_missing_provenance_cannot_promote():
    cand = KnowledgeCandidate(original_topic="t", normalized_topic="t",
                              learned_claims=[], evidence_ids=[],
                              provenance_urls=[], confidence=0.9)
    decision = evaluate_promotion(cand, None)
    assert not decision.approved and "missing provenance" in decision.reasons


def test_low_confidence_and_contradictions_block_promotion():
    cand = KnowledgeCandidate(original_topic="t", normalized_topic="t",
                              learned_claims=["a"], evidence_ids=["e"],
                              provenance_urls=["https://x.org"], confidence=0.2,
                              contradictions=["source B disagrees"])
    assert not evaluate_promotion(cand).approved


def test_audited_candidate_with_provenance_can_promote():
    item = _evidence("pass")
    audit = EvidenceAudit(evidence_id=item.evidence_id, relevant=True,
                          supports_claims=item.claims[:1],
                          confidence=0.85, audit_status="pass")
    audit.applied_to(item)
    assert item.audit_status == "pass"
    cand = KnowledgeCandidate(original_topic="TaskGroup",
                              normalized_topic="asyncio TaskGroup",
                              learned_claims=item.claims,
                              evidence_ids=[item.evidence_id],
                              provenance_urls=[item.source_url],
                              confidence=0.8, audit_summary="audit ok")
    bundle = EvidenceBundle(question="How does TaskGroup handle failure?",
                            supporting=[item], confidence=0.8)
    decision = evaluate_promotion(cand, bundle)
    assert decision.approved, decision.reasons


def test_irrelevant_evidence_rejected_by_audit():
    item = _evidence()
    audit = EvidenceAudit(evidence_id=item.evidence_id, relevant=False,
                          audit_status="rejected", confidence=0.1)
    audit.applied_to(item)
    assert item.audit_status == "rejected"

# -- research tools inside the governed loop ------------------------------
class FakeExecutor:
    def niblit_status(self):
        return {"status": "ok"}


def _loop_with_research(search_fn=None):
    from modules.governed_research import (
        governed_fetch as gf, WEB_FETCH_SCHEMA, WEB_SEARCH_SCHEMA)
    loop = LlmToolLoop(executor=FakeExecutor())
    loop.register_capability(
        "web_search",
        search_fn or (lambda query, max_results=5:
                      {"query": query, "results": [], "count": 0}),
        WEB_SEARCH_SCHEMA)
    loop.register_capability("web_fetch", gf, WEB_FETCH_SCHEMA)
    return loop


def test_research_tool_dispatched_with_observation():
    calls = []

    def search_fn(query, max_results=5):
        calls.append(query)
        return {"query": query, "results": [
            {"title": "TaskGroup", "url": "https://docs.python.org/tg",
             "domain": "docs.python.org", "provider": "fake"}], "count": 1}

    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "call_ws", "type": "function",
                                 "function": {"name": "web_search",
                                              "arguments": json.dumps(
                                                  {"query": "asyncio TaskGroup failure"})}}]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
    loop = _loop_with_research(search_fn)
    scripted = [tool_resp, final_resp]
    loop.requests = []

    def fake_cloud(messages, model, tools=None, tool_choice=None, max_tokens=512):
        loop.requests.append({"messages": list(messages), "tools": tools})
        return scripted.pop(0)
    loop._cloud_chat = fake_cloud

    out = loop.chat([{"role": "user", "content": "research it"}])
    assert calls == ["asyncio TaskGroup failure"]
    assert out["trace"][0]["status"] == "success"
    obs = [m for m in loop.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "docs.python.org" in obs["content"]
    assert "web_search" in loop.allowed_tool_names()


def test_web_fetch_tool_rejects_private_url_via_loop():
    from modules.governed_research import WEB_FETCH_SCHEMA
    loop = _loop_with_research()
    allowed = {**loop._schemas, "web_fetch": WEB_FETCH_SCHEMA}
    name, args = loop._validate_call(
        {"function": {"name": "web_fetch",
                      "arguments": json.dumps({"url": "http://127.0.0.1:8000"})}},
        allowed)
    res = loop._tool_map[name](**args)
    assert "error" in res


def test_unknown_capability_still_rejected():
    loop = _loop_with_research()
    with pytest.raises(ToolCallError):
        loop._validate_call(
            {"function": {"name": "shell_exec", "arguments": "{}"}},
            dict(loop._schemas))
