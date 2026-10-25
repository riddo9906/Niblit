"""modules/research_orchestrator.py - Phase 5B LLM-supervised research cycle.

Orchestrates one bounded research run end to end:

    topic -> LLM topic assessment (strict JSON, bounded retry)
          -> internal-first inspection of the tiered knowledge store
          -> LLM research plan (questions, queries, gaps)
          -> GovernedSearch (real DuckDuckGo provider) + governed_fetch
          -> per-evidence LLM audit (strict JSON, bounded retry)
          -> contradiction retention + bounded follow-up rounds
          -> KnowledgeCandidate -> deterministic promotion gate
          -> (approved only) persistence via TieredKnowledgeSystem
          -> recall proof from the same store
          -> lifecycle events on the EventBus

Governance invariants (structural, not advisory):
- The LLM supervises; every boundary crossing is parsed/validated here.
- Memory writes happen ONLY after evaluate_promotion() approval and ONLY via
  the TieredKnowledgeSystem public API - never direct Qdrant/DB writes.
- Budgets (max_rounds / max_searches / max_fetches) are enforced in this
  module's loop, never delegated to the model.
- Malformed LLM output fails structurally after a bounded retry; it is never
  guessed into shape.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from modules.event_bus import NiblitEvent
from modules.governed_research import (
    WEB_FETCH_SCHEMA,
    WEB_SEARCH_SCHEMA,
    GovernedSearch,
    governed_fetch,
)
from modules.research_contracts import (
    EvidenceAudit,
    EvidenceBundle,
    EvidenceItem,
    InternalFinding,
    KnowledgeCandidate,
    ResearchPlan,
    TopicAssessment,
    evaluate_promotion,
)
from modules.research_provider_adapter import DuckDuckGoSearchProvider

log = logging.getLogger("Niblit.ResearchOrchestrator")

EVENT_SOURCE = "research_orchestrator"
MAX_LLM_RETRIES = 2            # bounded structured-output retry budget
DEFAULT_MAX_SEARCHES = 4
DEFAULT_MAX_FETCHES = 6
DEFAULT_MAX_ROUNDS = 2
FOLLOWUPS_PER_AUDIT = 2
EVIDENCE_EXCERPT_CHARS = 1500
STORED_CONTENT_CAP = 600       # TieredKnowledgeSystem caps content at 600


class ResearchStructuralError(Exception):
    """LLM failed to return valid structured JSON within the retry budget."""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from an LLM reply (fenced or bare)."""
    if not text or not text.strip():
        return None
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_unit_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _as_bounded_int(value: Any, default: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, upper))


# ---------------------------------------------------------------------------
# LLM boundary prompts (strict JSON output contracts)
# ---------------------------------------------------------------------------

TOPIC_SYSTEM_PROMPT = (
    "You are Niblit's research supervisor. Assess the given research topic. "
    "Reply with ONLY a JSON object (no prose, no code fences) shaped exactly:\n"
    '{"normalized_topic": str, "objective": str, "scope": "focused"|"broad", '
    '"subtopics": [str], "key_questions": [str], "terminology": [str], '
    '"ambiguities": [str], "expected_source_types": [str], '
    '"searchability_score": <float 0..1>, "decomposition_required": <bool>}'
)

PLAN_SYSTEM_PROMPT = (
    "You are Niblit's research planner. Given a topic assessment and any "
    "existing internal knowledge, reply with ONLY a JSON object (no prose, "
    "no code fences) shaped exactly:\n"
    '{"questions": [str], "search_queries": [str], '
    '"source_preferences": [str], "knowledge_gaps": [str], '
    '"max_searches": int, "max_fetches": int, "max_rounds": int}'
)

AUDIT_SYSTEM_PROMPT = (
    "You are Niblit's evidence auditor. Audit the supplied evidence against "
    "the research question. Reply with ONLY a JSON object (no prose, no code "
    "fences) shaped exactly:\n"
    '{"relevant": bool, "supports_claims": [str], "unsupported_claims": [str], '
    '"contradictions": [str], "confidence": <float 0..1>, '
    '"requires_followup": bool, "followup_questions": [str]}. '
    "Only claim wording grounded in the evidence text may appear in "
    "supports_claims."
)


@dataclass
class ResearchRunResult:
    """Everything one research run produced; also the artifact payload."""

    topic: str
    assessment: TopicAssessment
    plan: ResearchPlan
    evidence: List[EvidenceItem]
    bundle: EvidenceBundle
    candidate: KnowledgeCandidate
    decision: Any                     # PromotionDecision
    stored: Optional[str]
    recall: Optional[Dict[str, Any]]
    events: List[Dict[str, Any]]
    usage: Dict[str, int]
    errors: List[str] = field(default_factory=list)

    def artifact(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "assessment": asdict(self.assessment),
            "plan": self.plan.to_dict(),
            "evidence": [asdict(item) for item in self.evidence],
            "bundle": {
                "question": self.bundle.question,
                "supporting_evidence_ids": [
                    i.evidence_id for i in self.bundle.supporting],
                "conflicting_evidence_ids": [
                    i.evidence_id for i in self.bundle.conflicting],
                "unresolved_gaps": self.bundle.unresolved_gaps,
                "confidence": self.bundle.confidence,
            },
            "candidate": asdict(self.candidate),
            "promotion": {"status": self.decision.status,
                          "reasons": self.decision.reasons},
            "stored": self.stored,
            "recall": self.recall,
            "events": self.events,
            "usage": self.usage,
            "errors": self.errors,
        }


class ResearchOrchestrator:
    """Bounded LLM-supervised research cycle over governed retrieval."""

    def __init__(self, loop: Any, knowledge_store: Any = None,
                 event_bus: Any = None, search: Optional[GovernedSearch] = None,
                 max_searches: int = DEFAULT_MAX_SEARCHES,
                 max_fetches: int = DEFAULT_MAX_FETCHES,
                 max_rounds: int = DEFAULT_MAX_ROUNDS,
                 min_confidence: float = 0.55,
                 results_per_query: int = 3) -> None:
        self.loop = loop
        self.knowledge_store = knowledge_store
        self.event_bus = event_bus
        self.search = search if search is not None else GovernedSearch(
            provider=DuckDuckGoSearchProvider().search)
        self.max_searches = max(1, int(max_searches))
        self.max_fetches = max(1, int(max_fetches))
        self.max_rounds = max(1, int(max_rounds))
        self.min_confidence = float(min_confidence)
        self.results_per_query = max(1, int(results_per_query))
        self.events: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self._searches_used = 0
        self._fetches_used = 0
        self._rounds_used = 0
        self._chat_calls = 0

    # -- event lifecycle ----------------------------------------------------
    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {"type": event_type, "source": EVENT_SOURCE,
                  "payload": payload, "timestamp": time.time()}
        self.events.append(record)
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(NiblitEvent(
                type=event_type, source=EVENT_SOURCE, payload=payload))
        except Exception as exc:  # event failures never abort research
            log.warning("[Research] publish failed for %s: %s",
                        event_type, exc)

    # -- structured LLM boundary ---------------------------------------------
    def _ask_json(self, system_prompt: str,
                  user_payload: str) -> Dict[str, Any]:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload}]
        attempts: List[str] = []
        for _ in range(MAX_LLM_RETRIES + 1):
            self._chat_calls += 1
            response = self.loop.chat(messages)
            text = response.get("text") or ""
            data = _extract_json(text)
            if data is not None:
                return data
            attempts.append(text[:300])
            messages.append({"role": "assistant", "content": text[:4000]})
            messages.append({"role": "user", "content":
                             "That was not valid JSON. Reply again with ONLY "
                             "the JSON object. No prose, no code fences."})
        raise ResearchStructuralError(
            f"malformed structured output after {MAX_LLM_RETRIES + 1} "
            f"attempts; last={attempts}")

    # -- step 1: topic assessment ---------------------------------------------
    def assess_topic(self, topic: str) -> TopicAssessment:
        data = self._ask_json(TOPIC_SYSTEM_PROMPT, topic)
        normalized = (str(data.get("normalized_topic") or topic).strip()
                      or topic)
        assessment = TopicAssessment(
            original_topic=topic,        # original preserved verbatim
            normalized_topic=normalized,
            objective=str(data.get("objective") or ""),
            scope=str(data.get("scope") or "focused"),
            subtopics=_as_str_list(data.get("subtopics")),
            key_questions=_as_str_list(data.get("key_questions")),
            terminology=_as_str_list(data.get("terminology")),
            ambiguities=_as_str_list(data.get("ambiguities")),
            expected_source_types=_as_str_list(
                data.get("expected_source_types")),
            searchability_score=_as_unit_float(
                data.get("searchability_score")),
            decomposition_required=bool(data.get("decomposition_required")),
        )
        self._emit("research.topic_assessed", {
            "original": topic, "normalized": normalized,
            "searchability_score": assessment.searchability_score})
        return assessment

    # -- step 2: internal-first ------------------------------------------------
    def internal_first(self,
                       assessment: TopicAssessment) -> List[InternalFinding]:
        """Inspect the tiered knowledge store BEFORE any web retrieval."""
        findings: List[InternalFinding] = []
        topic = assessment.normalized_topic or assessment.original_topic
        store = self.knowledge_store
        recall_fn = getattr(store, "recall_knowledge", None) if store else None
        if callable(recall_fn):
            try:
                internal_text = recall_fn(topic)
            except Exception as exc:
                self.errors.append(f"internal recall failed: {exc}")
                internal_text = None
            if internal_text:
                findings.append(InternalFinding(
                    claim=str(internal_text)[:400],
                    confidence=0.6,
                    provenance="tiered_knowledge_system",
                    stale=False,
                ))
        self._emit("research.internal_first",
                   {"topic": topic, "findings": len(findings)})
        return findings

    # -- step 3: plan -----------------------------------------------------------
    def plan_research(self, assessment: TopicAssessment,
                      findings: List[InternalFinding]) -> ResearchPlan:
        user_payload = json.dumps({
            "assessment": {
                "original_topic": assessment.original_topic,
                "normalized_topic": assessment.normalized_topic,
                "objective": assessment.objective,
                "key_questions": assessment.key_questions,
                "subtopics": assessment.subtopics,
            },
            "internal_knowledge": [f.claim for f in findings],
        }, ensure_ascii=False)
        data = self._ask_json(PLAN_SYSTEM_PROMPT, user_payload)
        questions = (_as_str_list(data.get("questions"))
                     or assessment.key_questions)
        queries = _as_str_list(data.get("search_queries"))
        if not queries:
            queries = [assessment.normalized_topic]
        gaps = _as_str_list(data.get("knowledge_gaps"))
        if not findings:
            gaps.append("no internal knowledge on this topic "
                        "(internal-first miss)")
        plan = ResearchPlan(
            topic_assessment=assessment,
            questions=list(questions),
            search_queries=queries,
            source_preferences=_as_str_list(data.get("source_preferences")),
            internal_findings=list(findings),
            knowledge_gaps=gaps,
            max_searches=_as_bounded_int(data.get("max_searches"),
                                         self.max_searches,
                                         self.max_searches),
            max_fetches=_as_bounded_int(data.get("max_fetches"),
                                        self.max_fetches,
                                        self.max_fetches),
            max_rounds=_as_bounded_int(data.get("max_rounds"),
                                       self.max_rounds,
                                       self.max_rounds),
        )
        self._emit("research.plan_created", {
            "queries": plan.search_queries, "gaps": plan.knowledge_gaps,
            "budgets": {"searches": plan.max_searches,
                        "fetches": plan.max_fetches,
                        "rounds": plan.max_rounds}})
        return plan

    # -- step 4: governed retrieval ----------------------------------------------
    def _gather(self, plan: ResearchPlan,
                queries: List[str]) -> List[EvidenceItem]:
        items: List[EvidenceItem] = []
        for query in queries:
            if self._searches_used >= plan.max_searches:
                self.errors.append("search budget exhausted")
                break
            self._searches_used += 1
            outcome = self.search.search(query,
                                         max_results=self.results_per_query)
            if outcome.get("error"):
                self.errors.append(
                    f"search failed for {query!r}: {outcome['error']}")
                continue
            for hit in outcome.get("results", []):
                if self._fetches_used >= plan.max_fetches:
                    self.errors.append("fetch budget exhausted")
                    return items
                self._fetches_used += 1
                fetched = governed_fetch(hit["url"])
                text = ""
                if isinstance(fetched.get("evidence"), dict):
                    text = str(
                        fetched["evidence"].get("extracted_text") or "")
                else:
                    self.errors.append(
                        f"fetch failed for {hit['url']}: "
                        f"{fetched.get('error')}")
                items.append(EvidenceItem(
                    query=query,
                    source_url=hit["url"],
                    source_domain=hit.get("domain", ""),
                    title=hit.get("title", ""),
                    extracted_text=text[:20000],
                    provider=hit.get("provider", "duckduckgo"),
                ))
        return items

    # -- step 5: per-evidence LLM audit --------------------------------------------
    def audit_evidence(self, item: EvidenceItem,
                       question: str) -> EvidenceAudit:
        user_payload = json.dumps({
            "question": question,
            "evidence": {
                "title": item.title,
                "url": item.source_url,
                "domain": item.source_domain,
                "text_excerpt": item.extracted_text[:EVIDENCE_EXCERPT_CHARS],
            },
        }, ensure_ascii=False)
        data = self._ask_json(AUDIT_SYSTEM_PROMPT, user_payload)
        audit = EvidenceAudit(
            evidence_id=item.evidence_id,
            relevant=bool(data.get("relevant")),
            supports_claims=_as_str_list(data.get("supports_claims")),
            unsupported_claims=_as_str_list(
                data.get("unsupported_claims")),
            contradictions=_as_str_list(data.get("contradictions")),
            confidence=_as_unit_float(data.get("confidence")),
            requires_followup=bool(data.get("requires_followup")),
            followup_questions=_as_str_list(
                data.get("followup_questions"))[:FOLLOWUPS_PER_AUDIT],
        )
        audit.audit_status = "pass" if audit.relevant else "rejected"
        audit.applied_to(item)
        item.claims = list(audit.supports_claims)
        item.audit_notes = "; ".join(audit.unsupported_claims)[:500]
        self._emit("research.evidence_audited", {
            "evidence_id": item.evidence_id, "url": item.source_url,
            "status": item.audit_status, "confidence": audit.confidence,
            "contradictions": len(audit.contradictions)})
        return audit

    # -- persistence (promotion-gated only) ------------------------------------
    def _persist(self, candidate: KnowledgeCandidate) -> Optional[str]:
        """Store approved knowledge ONLY through the tiered KB public API."""
        store_fn = getattr(self.knowledge_store, "store_knowledge", None)
        if not callable(store_fn):
            self.errors.append("knowledge store lacks store_knowledge")
            return None
        claims = "; ".join(candidate.learned_claims)[:400]
        sources = ", ".join(candidate.provenance_urls[:3])
        content = f"{claims} [sources: {sources}]"[:STORED_CONTENT_CAP]
        try:
            store_fn(candidate.normalized_topic, content,
                     source="research_orchestrator")
        except Exception as exc:
            self.errors.append(f"store_knowledge failed: {exc}")
            return None
        return candidate.candidate_id

    def _recall_proof(self, topic: str,
                      candidate: KnowledgeCandidate) -> Dict[str, Any]:
        """Verify the just-stored entry is actually retrievable."""
        recall_fn = getattr(self.knowledge_store, "recall_knowledge", None)
        if not callable(recall_fn):
            return {"verified": False,
                    "reason": "store lacks recall_knowledge"}
        try:
            recalled = recall_fn(topic)
        except Exception as exc:
            return {"verified": False, "reason": f"recall failed: {exc}"}
        if not recalled:
            return {"verified": False, "reason": "recall returned nothing",
                    "excerpt": None}
        lowered = str(recalled).lower()
        claim_hit = None
        for claim in candidate.learned_claims:
            probe = claim.strip().lower()[:80]
            if probe and probe in lowered:
                claim_hit = claim
                break
        return {"verified": claim_hit is not None, "claim_hit": claim_hit,
                "excerpt": str(recalled)[:200]}

    # -- the bounded cycle ------------------------------------------------------
    def run(self, topic: str) -> ResearchRunResult:
        """Execute one full bounded LLM-supervised research cycle."""
        self.events = []
        self.errors = []
        self._searches_used = self._fetches_used = self._rounds_used = 0
        self._chat_calls = 0
        self._emit("research.started", {"topic": topic})

        assessment = self.assess_topic(topic)
        findings = self.internal_first(assessment)
        plan = self.plan_research(assessment, findings)
        question = (assessment.key_questions[0] if assessment.key_questions
                    else assessment.normalized_topic)

        all_items: List[EvidenceItem] = []
        supporting: List[EvidenceItem] = []
        conflicting: List[EvidenceItem] = []
        contradictions: List[str] = []
        gaps = list(plan.knowledge_gaps)
        pass_confidences: List[float] = []
        followups: List[str] = []

        for round_no in range(1, plan.max_rounds + 1):
            self._rounds_used = round_no
            queries = plan.search_queries if round_no == 1 else followups
            if not queries:
                break
            items = self._gather(plan, queries)
            if not items:
                if round_no == 1:
                    gaps.append("no retrievable evidence for planned queries")
                break
            followups = []
            for item in items:
                audit = self.audit_evidence(item, question)
                all_items.append(item)
                contradictions.extend(audit.contradictions)
                if audit.audit_status == "pass":
                    supporting.append(item)
                    pass_confidences.append(audit.confidence)
                if audit.contradictions:
                    conflicting.append(item)
                if audit.requires_followup and round_no < plan.max_rounds:
                    followups.extend(audit.followup_questions)
            if not followups:
                break

        bundle = EvidenceBundle(
            question=question,
            supporting=supporting,
            conflicting=conflicting,
            unresolved_gaps=gaps,
            confidence=(round(sum(pass_confidences)
                              / len(pass_confidences), 3)
                        if pass_confidences else 0.0),
        )
        claims: List[str] = []
        evidence_ids: List[str] = []
        urls: List[str] = []
        for item in supporting:
            claims.extend(item.claims)
            evidence_ids.append(item.evidence_id)
            if item.source_url:
                urls.append(item.source_url)
        candidate = KnowledgeCandidate(
            original_topic=assessment.original_topic,
            normalized_topic=assessment.normalized_topic,
            learned_claims=claims,
            evidence_ids=evidence_ids,
            provenance_urls=sorted(set(urls)),
            confidence=bundle.confidence,
            contradictions=sorted(set(contradictions)),
            unresolved_gaps=gaps,
            audit_summary=(f"{len(supporting)}/{len(all_items)} evidence "
                           f"items audited-pass"),
        )
        decision = evaluate_promotion(candidate, bundle, self.min_confidence)
        self._emit(
            "memory.promotion.approved" if decision.approved
            else "memory.promotion.rejected",
            {"candidate_id": candidate.candidate_id,
             "reasons": decision.reasons})

        stored: Optional[str] = None
        recall: Optional[Dict[str, Any]] = None
        if decision.approved and self.knowledge_store is not None:
            stored = self._persist(candidate)
            recall = self._recall_proof(candidate.normalized_topic, candidate)
            self._emit("memory.recalled", {
                "topic": candidate.normalized_topic,
                "verified": bool(recall and recall.get("verified"))})

        self._emit("research.completed", {
            "topic": topic, "approved": decision.approved,
            "rounds": self._rounds_used, "searches": self._searches_used,
            "fetches": self._fetches_used,
            "evidence_total": len(all_items)})
        return ResearchRunResult(
            topic=topic, assessment=assessment, plan=plan,
            evidence=all_items, bundle=bundle, candidate=candidate,
            decision=decision, stored=stored, recall=recall,
            events=list(self.events),
            usage={"rounds": self._rounds_used,
                   "searches": self._searches_used,
                   "fetches": self._fetches_used,
                   "llm_chat_calls": self._chat_calls},
            errors=list(self.errors))


def register_research_tools(loop: Any) -> GovernedSearch:
    """Wire web_search (real DuckDuckGo adapter) + web_fetch into the loop.

    Uses the Phase 5A governed schemas and the loop's actual
    register_capability(name, fn, schema) signature. No other capability is
    registered here; execution authority stays with NiblitToolExecutor.
    """
    provider = DuckDuckGoSearchProvider()
    search = GovernedSearch(provider=provider.search)

    def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
        return search.search(query, max_results=max_results)

    def web_fetch(url: str) -> Dict[str, Any]:
        return governed_fetch(url)

    loop.register_capability("web_search", web_search, WEB_SEARCH_SCHEMA)
    loop.register_capability("web_fetch", web_fetch, WEB_FETCH_SCHEMA)
    return search
