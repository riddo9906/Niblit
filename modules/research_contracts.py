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


def source_identity(url):
    """Known official documentation identities; unknown paths stay unknown."""
    import hashlib
    from urllib.parse import urlsplit
    p = urlsplit(url)
    publisher, product = 'UNKNOWN', 'UNKNOWN'
    if p.hostname == 'learn.microsoft.com' and '/dynamics365/business-central/' in p.path:
        publisher, product = 'Microsoft', 'Dynamics 365 Business Central'
    elif p.hostname == 'raw.githubusercontent.com' and p.path.startswith('/odoo/documentation/'):
        publisher, product = 'Odoo', 'Odoo documentation ' + p.path.split('/')[3]
    elif p.hostname == 'www.odoo.com' and p.path.startswith('/documentation/'):
        publisher, product = 'Odoo', 'Odoo documentation ' + p.path.split('/')[2]
    return {'source_id':hashlib.sha256(url.encode()).hexdigest(), 'url':url,
            'publisher':publisher,'product':product,'scope':'documented_source_observation'}


def attributed_claims(facts):
    """Bounded catalog from canonical facts, never from generated responses."""
    catalog=[]
    for fact in facts[:8]:
        if not isinstance(fact.get('value'),str):continue
        bindings=fact.get('evidence_bindings') or [{**source_identity(fact.get('citation','')),
            'source_hash':fact.get('provenance',{}).get('source_hash'),
            'retrieved_at':fact.get('provenance',{}).get('retrieved_at')}]
        for binding in bindings:
            identity=source_identity(binding.get('url') or binding.get('citation') or '')
            if identity['publisher']=='UNKNOWN':continue
            catalog.append({'claim_id':fact['id'],'excerpt':fact['value'],
                **identity,'source_hash':binding.get('source_hash'),
                'retrieved_at':binding.get('retrieved_at'),'verification':fact.get('verification','unverified')})
    return catalog[:16]


def validate_comparison_proposal(proposal, catalog):
    """Accept source selection only. Free model conclusions cannot pass this gate."""
    if not isinstance(proposal,dict) or set(proposal)!={'claims'}:
        return {'valid':False,'reason':'unsupported_generated_conclusion_or_schema'}
    claims=proposal['claims']
    if not isinstance(claims,list) or not 1<=len(claims)<=8:
        return {'valid':False,'reason':'invalid_claim_selection'}
    selected=[]
    for claim in claims:
        if isinstance(claim,str):
            import re
            if not re.fullmatch(r'E[1-8]',claim) or int(claim[1:])>len(catalog):
                return {'valid':False,'reason':'unknown_evidence_handle'}
            match=catalog[int(claim[1:])-1]
            if match not in selected:selected.append(match)
            continue
        if not isinstance(claim,dict) or set(claim)!={'claim_id','source_id'}:
            return {'valid':False,'reason':'unsupported_claim_fields'}
        matches=[c for c in catalog if c['claim_id']==claim['claim_id'] and c['source_id']==claim['source_id']]
        if not matches:return {'valid':False,'reason':'claim_source_mismatch'}
        if matches[0] not in selected:selected.append(matches[0])
    if {c['publisher'] for c in selected}!={c['publisher'] for c in catalog}:
        return {'valid':False,'reason':'missing_source_scope'}
    return {'valid':True,'reason':'exact_canonical_claim_source_bindings','selected':selected}


def render_source_comparison(catalog, validation):
    """Render only canonical excerpts and bounded, explicitly evidenced comparisons."""
    import re
    preferred=validation.get('selected',[]) if validation['valid'] else []
    selected=preferred+[c for c in catalog if c not in preferred]
    lines=['Source-grounded comparison — observations from the cited documents, not universal business rules.']
    if not validation['valid']:
        lines.append('I could not validate a complete generated comparison. These source-backed findings are a partial answer; unsupported conclusions have been omitted.')
    publishers=sorted({c['publisher'] for c in selected})
    for publisher in publishers:
        lines.append('\n'+publisher+':')
        seen=set()
        for claim in [c for c in selected if c['publisher']==publisher]:
            if claim['claim_id'] in seen:continue
            seen.add(claim['claim_id'])
            lines.append(f"- {claim['product']}: {claim['excerpt']} [claim {claim['claim_id']}; source {claim['source_id']}; {claim['url']}]")
    # A narrow comparison about the excerpts themselves, not inferred equivalent
    # workflows. Each publisher must have a supporting count/adjustment excerpt.
    support=[]
    for publisher in publishers:
        match=next((c for c in selected if c['publisher']==publisher and
                    re.search(r'count|quantit',c['excerpt'],re.I) and re.search(r'adjust',c['excerpt'],re.I)),None)
        if match:support.append(match)
    if len(publishers)>1 and len(support)==len(publishers):
        lines.append('\nSupported similarity: each cited source set discusses count/quantity adjustments. This does not establish identical procedures. ['+'; '.join(c['claim_id'] for c in support)+']')
    else:lines.append('\nShared procedure: UNKNOWN — the selected evidence does not establish one.')
    for claim in selected:
        for action in re.findall(r'\buse the ([A-Z][A-Za-z ]{1,60}?) action\b',claim['excerpt']):
            others=[p for p in publishers if p!=claim['publisher'] and not any(action in c['excerpt'] for c in selected if c['publisher']==p)]
            lines.append(f"\nSource-specific action: {action} is documented here for {claim['publisher']} / {claim['product']} [{claim['claim_id']}]." +
                         (' For '+', '.join(others)+', that named action is UNKNOWN from the retrieved evidence.' if others else ''))
    lines.append('\nUnknown: unquoted procedure details, organization policy and universal applicability. Verification describes source observations, not independent proof of every source claim.')
    return '\n'.join(lines)


def learning_outcome(topic, evidence, *, errors=None, interpretation=""):
    """Versioned, conservative outcome shared by existing ALE research paths.

    Source excerpts are observations, not proof of every assertion in them.
    Generated questions, placeholders and model synthesis are never findings.
    No I/O, promotion, generation or execution authority lives in this helper.
    """
    import hashlib
    import re
    findings = []
    seen = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "").strip()
        citation = str(item.get("citation") or "").strip()
        kind = item.get("source_type", "source_claim")
        if not citation or len(text) < 20 or kind in {"local_brain", "model_synthesis", "hypothesis", "question", "learning_outcome"}:
            continue
        if re.match(r"^(?:\(?no (?:research findings|data found|external data|findings)|research on\b|unknown\b)", text, re.I):
            continue
        # Legacy reflection payloads may embed a placeholder inside a dict repr.
        if "(no research findings)" in text and kind != "workspace_read":
            continue
        if text.endswith("?"):
            continue
        key = hashlib.sha256((citation + "\n" + text).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        findings.append({"id": key, "excerpt": text[:1800], "citation": citation,
                         "source_type": kind, "verification": "verified" if item.get("verification") == "verified" else "tentative",
                         "evidence_id": item.get("id"), "source_hash": item.get("source_hash"),
                         "scope": "source_observation; semantic truth not independently established"})
    errors = list(errors or [])
    unsupported=any('UnsupportedLocalResearchTopic' in str(error) for error in errors)
    status = ("verified_findings" if findings and all(f["verification"] == "verified" for f in findings)
              else "tentative_findings" if findings else "inconclusive_research" if unsupported
              else "retrieval_failure" if errors else "completed_no_findings")
    return {"schema_version": "learning-outcome/1", "outcome_id": str(uuid.uuid4()),
            "topic": topic, "created_at": time.time(), "status": status,
            "investigation_completed": True, "learning_succeeded": bool(findings),
            "findings": findings, "hypotheses": [], "follow_up_questions": [],
            "interpretation": interpretation, "interpretation_verified": False,
            "errors": errors, "next_action": ("Validate source observations against a related task and retain provenance" if findings
                else "This local study does not cover the topic; request an appropriate approved research source" if unsupported
                else "Restore the failed retrieval capability and retry the same objective" if errors
                else "Consult an approved primary source for this objective; no knowledge was established")}


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
    native_cognition: Dict[str, Any] = field(default_factory=dict)
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
