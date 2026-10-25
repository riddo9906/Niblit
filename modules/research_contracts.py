"""modules/research_contracts.py - Phase 5A supervised-research contracts.

Formal data contracts for LLM-supervised research: topic assessment,
research plan, evidence items/bundles, audits, knowledge candidates, and
the memory promotion gate. Pure data + deterministic gate logic; no I/O.
The LLM supervises; this module never writes authoritative memory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TopicAssessment:
    original_topic: str
    normalized_topic: str
    objective: str = ""
    scope: str = "focused"
    subtopics: List[str] = field(default_factory=list)
    key_questions: List[str] = field(default_factory=list)
    terminology: List[str] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    expected_source_types: List[str] = field(default_factory=list)
    searchability_score: float = 0.0
    decomposition_required: bool = False
    validation_notes: List[str] = field(default_factory=list)


@dataclass
class InternalFinding:
    claim: str
    confidence: float = 0.0
    provenance: str = ""
    stale: bool = False


@dataclass
class ResearchPlan:
    topic_assessment: TopicAssessment
    questions: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    source_preferences: List[str] = field(default_factory=list)
    internal_findings: List[InternalFinding] = field(default_factory=list)
    knowledge_gaps: List[str] = field(default_factory=list)
    max_searches: int = 6
    max_fetches: int = 8
    max_rounds: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items()
               if k not in ("topic_assessment", "internal_findings")},
            "topic_assessment": asdict(self.topic_assessment),
            "internal_findings": [asdict(f) for f in self.internal_findings],
        }


@dataclass
class EvidenceItem:
    query: str
    source_url: str
    source_domain: str = ""
    source_type: str = "web"
    title: str = ""
    extracted_text: str = ""
    retrieved_at: float = field(default_factory=time.time)
    provider: str = ""
    claims: List[str] = field(default_factory=list)
    relevance_score: float = 0.0
    audit_status: str = "unaudited"   # unaudited|pass|rejected
    audit_notes: str = ""
    evidence_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def has_provenance(self) -> bool:
        return bool(self.source_url and self.source_domain and self.retrieved_at)


@dataclass
class EvidenceAudit:
    evidence_id: str
    relevant: bool = False
    supports_claims: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    confidence: float = 0.0
    requires_followup: bool = False
    followup_questions: List[str] = field(default_factory=list)
    audit_status: str = "pending"

    def applied_to(self, item: EvidenceItem) -> None:
        item.audit_status = self.audit_status


@dataclass
class EvidenceBundle:
    question: str
    supporting: List[EvidenceItem] = field(default_factory=list)
    conflicting: List[EvidenceItem] = field(default_factory=list)
    unresolved_gaps: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def audited_items(self) -> List[EvidenceItem]:
        return [i for i in (self.supporting + self.conflicting)
                if i.audit_status == "pass"]


@dataclass
class KnowledgeCandidate:
    original_topic: str
    normalized_topic: str
    learned_claims: List[str]
    evidence_ids: List[str]
    provenance_urls: List[str]
    confidence: float = 0.0
    contradictions: List[str] = field(default_factory=list)
    unresolved_gaps: List[str] = field(default_factory=list)
    audit_summary: str = ""
    candidate_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class PromotionDecision:
    APPROVED = "approved"
    REJECTED = "rejected"

    def __init__(self, approved: bool, reasons: List[str]):
        self.approved = approved
        self.reasons = reasons
        self.status = self.APPROVED if approved else self.REJECTED


def evaluate_promotion(
    candidate: KnowledgeCandidate,
    bundle: Optional[EvidenceBundle] = None,
    min_confidence: float = 0.55,
) -> PromotionDecision:
    """Deterministic memory-promotion gate. The model cannot bypass this:
    approval is derived only from provenance, audit state and confidence."""
    reasons: List[str] = []
    if not candidate.provenance_urls:
        reasons.append("missing provenance")
    if not candidate.evidence_ids:
        reasons.append("no evidence ids")
    if candidate.confidence < min_confidence:
        reasons.append(f"confidence {candidate.confidence:.2f} below {min_confidence}")
    if candidate.contradictions:
        reasons.append("unresolved critical contradiction")
    if bundle is not None:
        audited = [i for i in bundle.supporting if i.audit_status in ("pass",)]
        if not audited:
            reasons.append("no audited-pass evidence")
        un = [i for i in bundle.supporting if i.audit_status == "unaudited"]
        if un:
            reasons.append(f"{len(un)} evidence item(s) unaudited")
        for i in audited:
            if not i.has_provenance():
                reasons.append(f"evidence {i.evidence_id} lacks provenance")
    return PromotionDecision(not reasons, reasons or ["all checks passed"])