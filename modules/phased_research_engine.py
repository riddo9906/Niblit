#!/usr/bin/env python3
"""
modules/phased_research_engine.py — Sequential research for Niblit.

Research now begins with an internal-first "Local Knowledge Partner" stage
(Phase 0) before any external search is attempted.  External phases are only
triggered when internal recall falls below the confidence threshold or when
explicit freshness/verification is required.

Phase 0 — Local Knowledge Partner (internal sources first, no I/O budget)
    Recalls from niblit_memory / KnowledgeDB, TieredKnowledgeSystem, and
    RuntimeRouterV2 → LocalBrain.  Returns a concept explanation, approach
    comparison, optimisation suggestions, and log/test-failure interpretation
    sourced entirely from local reasoning.

Phase 1 — Basic Understanding (DuckDuckGo + Google/Internet, 45 s)
    Fast, lightweight search to build initial topic comprehension.
    Skipped when Phase 0 confidence exceeds INTERNAL_CONFIDENCE_THRESHOLD.
    Results are stored as structured KB facts (ale_phase1_research:*) and
    pushed to GraphRAGPipeline Tier 2 (background knowledge).

Phase 2 — Deep Knowledge (SerpAPI + Serpex + Qdrant, 45 s)
    Gap-driven enrichment.  Only runs when Phase 1 found something and when
    the topic confidence is below the threshold.
    Results are stored as ale_phase2_research:* and pushed to Tier 1.

Phase 3 — Code Generation (GitHub REST API, 30 s)
    Runs ONLY when _is_code_topic() returns True.  Searches GitHub for
    real, idiomatic code examples and stores them as runnable code
    artefacts (ale_code_research:*) — not documentation summaries.

For every completed topic a ``ResearchMemoryArtifact`` is emitted and
persisted in both KB and governed memory so ALE, code generation, and
validation flows can retrieve confidence-ranked prior knowledge.

Integration
-----------
* Wired as ``self.phased_research_engine`` in niblit_core._init_optional_services()
* ALE ``_phased_research()`` calls engine.research(topic) instead of ``_unified_research``
* LanguageModule is used to structure plain-text snippets into factual sentences
* GraphRAGBridge pipes structured facts to the tiered knowledge graph

Singleton via get_phased_research_engine().
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, copy_context
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_phase_scope = ContextVar("niblit_research_phase_scope", default=None)


class ResearchCancelled(RuntimeError):
    """A research owner or phase deadline cancelled further work."""


def research_checkpoint(timeout=None):
    """Check cooperative cancellation and bound I/O inside a research phase."""
    scope = _phase_scope.get()
    if scope is None:
        return timeout
    owner, cancelled, deadline = scope
    remaining = deadline - time.monotonic()
    if cancelled.is_set() or (owner is not None and owner.is_set()) or remaining <= 0:
        raise ResearchCancelled("Research phase cancelled")
    return min(timeout, 10.0, max(0.1, remaining)) if timeout is not None else None


# ---------------------------------------------------------------------------
# Internal-first confidence thresholds
# ---------------------------------------------------------------------------

# When Phase 0 internal recall confidence reaches this value, Phase 1
# (external basic search) is skipped entirely.
INTERNAL_CONFIDENCE_THRESHOLD: float = float(
    __import__("os").environ.get("NIBLIT_INTERNAL_CONFIDENCE_THRESHOLD", "0.75")
)

# When internal confidence exceeds this value Phase 2 (deep external) is also
# skipped, so only Phase 3 (code) may still run for code topics.
DEEP_SKIP_THRESHOLD: float = float(
    __import__("os").environ.get("NIBLIT_DEEP_SKIP_THRESHOLD", "0.85")
)

log = logging.getLogger("Niblit.PhasedResearch")

# ---------------------------------------------------------------------------
# Stop words — filtered out when building gap queries from Phase 1 snippets
# so only meaningful domain terms surface as sub-topics.
# ---------------------------------------------------------------------------
_STOP_WORDS: frozenset = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "this", "that", "it", "its", "and", "or",
    "but", "not", "so", "as", "if", "which", "who", "what", "how", "when",
    "where", "why", "can", "also", "very", "such", "more", "than", "all",
    "any", "most", "some", "each", "use", "used", "using", "about", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "then", "there", "here", "just", "only", "same", "both", "few", "other",
    "because", "while", "although", "however", "therefore", "thus",
    "their", "they", "them", "these", "those", "you", "we", "our", "your",
    "his", "her", "its", "my", "me", "he", "she", "i", "us",
})

# Generic topic suffixes that are stripped when generating sub-queries to
# avoid compounding vague qualifiers (e.g. "python best practices examples").
_GENERIC_TOPIC_SUFFIXES = (
    " overview", " introduction", " intro", " basics", " fundamentals",
    " best practices", " guide", " tutorial", " explained", " definition",
    " meaning", " what is",
)

# ---------------------------------------------------------------------------
# Code-topic keywords
# Topics whose name contains any of these are treated as code/software topics
# and get Phase 3 (GitHub) treatment in addition to Phase 1 and Phase 2.
# ---------------------------------------------------------------------------
_CODE_KEYWORDS = frozenset({
    "python", "javascript", "java", "typescript", "golang", "rust", "cpp",
    "c++", "c#", "ruby", "php", "swift", "kotlin", "scala", "bash", "shell",
    "sql", "html", "css", "react", "vue", "angular", "django", "flask",
    "fastapi", "spring", "express", "nodejs", "node", "npm",
    "docker", "kubernetes", "terraform", "ansible", "devops", "cicd", "ci_cd",
    "api", "rest", "graphql", "websocket", "grpc", "microservice",
    "algorithm", "data structure", "sorting", "recursion", "binary tree",
    "linked list", "hash table", "dynamic programming",
    "machine learning", "neural network", "deep learning", "tensorflow",
    "pytorch", "sklearn", "pandas", "numpy", "matplotlib",
    "programming", "coding", "software", "framework", "library", "package",
    "class", "function", "method", "loop", "recursion", "inheritance",
    "polymorphism", "encapsulation", "design pattern", "oop",
    "embedded", "firmware", "microcontroller", "arduino", "raspberry pi",
    "containerization", "virtualisation", "database", "mongodb", "postgres",
    "redis", "elasticsearch", "kafka", "rabbitmq",
    "git", "github", "gitlab", "version control", "deployment",
    "unit test", "pytest", "unittest", "mock", "tdd",
    "async", "concurrency", "thread", "process", "coroutine",
    "encryption", "cryptography", "security", "authentication", "jwt",
    "web scraping", "crawler", "beautifulsoup", "selenium", "playwright",
})


# ---------------------------------------------------------------------------
# Query-expansion helpers
# These implement the "multi-query retrieval" pattern used by production RAG
# systems (LlamaIndex, LangChain) adapted for keyword-search contexts where
# we don't have an LLM available to generate hypothetical documents.
# ---------------------------------------------------------------------------

def _expand_topic_queries(topic: str) -> List[str]:
    """Generate up to 3 focused search queries from a single topic string.

    Rather than searching the bare topic (which returns generic overview pages),
    this produces queries that target three distinct knowledge facets:

    1. Conceptual understanding  — "what is X" / "X overview"
    2. Mechanism / process       — "how X works" / "X explained in depth"
    3. Practical application     — "X examples and use cases"

    This mirrors the multi-query retrieval strategy recommended by LlamaIndex
    and the step-back prompting technique: by breaking a broad topic into
    complementary angles, Phase 1 retrieves a richer, more diverse set of
    snippets instead of five variations of the same summary paragraph.

    The topic base is normalised by stripping common generic suffixes so we
    don't produce compounds like "python best practices examples" when the
    caller already passed "python best practices" as the topic.
    """
    t = topic.strip()
    if not t:
        return [topic]

    # Strip trailing generic qualifiers only when doing so leaves a base with
    # at least 2 words.  Stripping from "python best practices" would leave
    # just "python" (1 word) which is too broad — in that case keep the full
    # topic so the expanded queries remain specific.
    base = t.lower()
    for suffix in _GENERIC_TOPIC_SUFFIXES:
        if base.endswith(suffix):
            candidate = base[: -len(suffix)].strip()
            if len(candidate.split()) >= 2:
                base = candidate
            break
    base = base if base else t.lower()

    words = base.split()
    if len(words) <= 2:
        # 1-2 word topics: generate broad → specific → example queries to cover
        # multiple facets. "machine learning" becomes "what is machine learning",
        # "machine learning how it works", "machine learning examples and use cases".
        return [
            f"what is {base}",
            f"{base} how it works",
            f"{base} examples and use cases",
        ]

    # Longer topic already carries specificity — focus on three angles without
    # repeating the generic qualifier that was stripped above.
    return [
        f"{base} overview",
        f"{base} practical examples",
        f"{base} in depth",
    ]


def _gap_queries_from_snippets(
    topic: str, snippets: List[str], max_gaps: int = 2
) -> List[str]:
    """Derive targeted gap-filling queries from Phase 1 findings.

    Extracts the most frequent meaningful terms from Phase 1 snippets that are
    NOT already represented in the topic string.  These become Phase 2 sub-queries
    so each phase genuinely extends knowledge rather than re-fetching the same
    top-level overview.

    Example::

        topic    = "python async"
        snippets = ["asyncio event loop runs coroutines ...",
                    "await keyword suspends coroutine execution ..."]
        → gap queries: ["python async event loop", "python async coroutines"]

    This mirrors the "contextual retrieval" / gap-filling strategy used in
    advanced RAG pipelines (HuggingFace RAG paper, LlamaIndex sub-question
    decomposition) adapted for keyword search without an LLM.
    """
    if not snippets:
        return []

    topic_words = set(re.sub(r"[^\w\s]", " ", topic.lower()).split()) - _STOP_WORDS

    # Count term frequency across all Phase 1 snippets
    term_freq: Dict[str, int] = {}
    for snippet in snippets:
        for word in re.sub(r"[^\w\s]", " ", snippet.lower()).split():
            if (
                len(word) >= 4
                and word not in _STOP_WORDS
                and word not in topic_words
                and not word.isdigit()
            ):
                term_freq[word] = term_freq.get(word, 0) + 1

    # Minimum frequency threshold: require at least 2 occurrences when Phase 1
    # returned ≥ 4 snippets (enough signal to filter noise), but fall back to
    # 1 occurrence when Phase 1 was sparse — so gap queries are still generated
    # even from a small snippet set.
    min_freq = 2 if len(snippets) >= 4 else 1
    frequent = [w for w, c in term_freq.items() if c >= min_freq]
    top_terms = sorted(frequent, key=lambda w: term_freq[w], reverse=True)

    gap_queries: List[str] = []
    for term in top_terms:
        if len(gap_queries) >= max_gaps:
            break
        gap_queries.append(f"{topic} {term}")

    return gap_queries


def _score_snippet_quality(snippet: str, topic: str) -> float:
    """Score a snippet by relevance and information density.

    Used to rank collected snippets before storage so the highest-quality
    content lands in Tier 1 and the weakest is discarded.

    Scoring components:
    - **Term overlap** (0–0.5): fraction of substantive topic words present.
    - **Length score** (0–0.3): normalized snippet length capped at 500 chars.
    - **Sentence bonus** (0–0.2): bonus when snippet contains multiple sentences
      (signals a prose paragraph rather than a bare title or navigation link).
    """
    if not snippet:
        return 0.0

    text = snippet.lower()
    topic_words = (
        set(re.sub(r"[^\w\s]", " ", topic.lower()).split()) - _STOP_WORDS
    )
    if not topic_words:
        topic_words = set(topic.lower().split())

    # Term overlap score
    overlap = sum(1 for w in topic_words if w in text) / max(len(topic_words), 1)

    # Length score (normalized, capped at 500 chars)
    length_score = min(len(snippet), 500) / 500.0

    # Sentence structure bonus
    sentence_bonus = 0.2 if len(snippet) > 100 and ". " in snippet else 0.0

    return overlap * 0.5 + length_score * 0.3 + sentence_bonus


# ---------------------------------------------------------------------------
# Result data class
# ---------------------------------------------------------------------------

@dataclass
class PhaseResult:
    """Results from a single research phase."""
    phase: int
    topic: str
    snippets: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    facts_stored: int = 0
    duration_s: float = 0.0
    error: Optional[str] = None
    # Confidence score (0-1) derived from source quality for this phase's results.
    confidence_score: float = 0.5
    # Category of evidence: "internal", "external", or "mixed".
    source_type: str = "external"

    @property
    def success(self) -> bool:
        return bool(self.snippets) and self.error is None

    @property
    def best_snippet(self) -> Optional[str]:
        return self.snippets[0] if self.snippets else None


@dataclass
class ResearchMemoryArtifact:
    """Standardised knowledge record produced for every completed research topic.

    Emitted after all phases complete and persisted in both KB and governed
    memory so ALE, code generation, and validation flows can retrieve
    confidence-ranked prior knowledge without repeating external lookups.
    """
    topic: str
    summary: str = ""
    explanation: str = ""
    references: List[str] = field(default_factory=list)
    semantic_links: List[str] = field(default_factory=list)
    confidence_score: float = 0.5
    source_type: str = "mixed"
    follow_up_topics: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))
    phases_run: List[int] = field(default_factory=list)
    total_facts: int = 0

    # Operational completion and substantive learning are independent.
    outcome: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "explanation": self.explanation,
            "references": self.references,
            "semantic_links": self.semantic_links,
            "confidence_score": self.confidence_score,
            "source_type": self.source_type,
            "follow_up_topics": self.follow_up_topics,
            "created_at": self.created_at,
            "phases_run": self.phases_run,
            "total_facts": self.total_facts,
            "outcome": self.outcome,
        }


@dataclass
class PhasedResearchResult:
    """Combined result of all research phases for one topic."""
    topic: str
    phases_run: List[int] = field(default_factory=list)
    phase_results: Dict[int, PhaseResult] = field(default_factory=dict)
    total_facts: int = 0
    total_duration_s: float = 0.0
    is_code_topic: bool = False
    # Aggregated confidence score across all phases (weighted by source quality).
    confidence_score: float = 0.5
    # True when Phase 0 internal recall provided sufficient coverage.
    internal_hit: bool = False
    # Standardised artifact persisted to KB + governed memory after completion.
    artifact: Optional[ResearchMemoryArtifact] = None

    def summary(self) -> str:
        phase_labels = {0: "Internal", 1: "Basic", 2: "Advanced", 3: "Code"}
        parts = []
        for ph in self.phases_run:
            r = self.phase_results.get(ph)
            if r and r.success:
                parts.append(
                    f"P{ph}({phase_labels.get(ph, ph)}: {len(r.snippets)} snippets, "
                    f"{r.duration_s:.0f}s, conf={r.confidence_score:.2f})"
                )
            else:
                parts.append(f"P{ph}(skipped)")
        outcome = self.artifact.outcome if self.artifact else {}
        return (
            f"[PhasedResearch] {self.topic!r} — "
            + " → ".join(parts)
            + f" | {self.total_facts} records stored | outcome={outcome.get('status', 'not_evaluated')} | confidence={self.confidence_score:.2f}"
        )


# ---------------------------------------------------------------------------
# PhasedResearchEngine
# ---------------------------------------------------------------------------

class PhasedResearchEngine:
    """Sequential 3-phase research engine.

    Parameters
    ----------
    knowledge_db :
        KnowledgeDB for storing phase results.
    graph_rag_bridge :
        GraphRAGBridge for Tier 1/2 ingestion.
    language_module :
        LanguageModule for structuring snippets into factual sentences.
    internet :
        InternetManager (Google/web search).
    scrapy_agent :
        ScrapyResearchAgent (DuckDuckGo).
    serpex_agent :
        SerpexAgent or compatible with search_web(topic).
    github_code_search :
        GitHubCodeSearch with search_repos()/research_for_code_generation().
    serpapi :
        SerpAPISearch or compatible (optional, used in Phase 2 when available).
    """

    # Phase timeout budgets in seconds
    PHASE0_TIMEOUT: float = 30.0
    PHASE1_TIMEOUT: float = 300.0
    PHASE2_TIMEOUT: float = 300.0
    PHASE3_TIMEOUT: float = 300.0

    # Minimum snippet length to be worth storing
    MIN_SNIPPET_LEN: int = 30

    # Maximum snippets to keep per phase
    MAX_SNIPPETS_PER_PHASE: int = 5

    def __init__(
        self,
        knowledge_db: Any = None,
        graph_rag_bridge: Any = None,
        language_module: Any = None,
        internet: Any = None,
        scrapy_agent: Any = None,
        serpex_agent: Any = None,
        github_code_search: Any = None,
        serpapi: Any = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self._grb = graph_rag_bridge
        self._lm = language_module
        self.internet = internet
        self.scrapy_agent = scrapy_agent
        self.serpex_agent = serpex_agent
        self.github_code_search = github_code_search
        self.serpapi = serpapi
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def research(
        self,
        topic: str,
        skip_phase2: bool = False,
        skip_phase3: bool = False,
        *,
        cancel_event=None,
    ) -> PhasedResearchResult:
        """Research *topic* through up to 4 sequential phases (0-3).

        Phase 0 (Local Knowledge Partner) always runs first.  External phases
        are skipped when internal recall confidence exceeds the configured
        threshold, reducing unnecessary web traffic for already-known topics.

        Parameters
        ----------
        topic :
            The research topic (e.g. "photosynthesis", "docker containerization").
        skip_phase2 :
            Force-skip Phase 2 (used for lightweight lookups).
        skip_phase3 :
            Force-skip Phase 3 (e.g. when GitHub is unavailable).

        Returns
        -------
        PhasedResearchResult
        """
        topic = topic.strip()
        result = PhasedResearchResult(
            topic=topic,
            is_code_topic=_is_code_topic(topic),
        )
        t0 = time.monotonic()

        # ── Phase 0: Local Knowledge Partner (internal sources first) ────
        p0 = self._run_phase_with_timeout(
            phase=0,
            topic=topic,
            fn=self._phase0_internal,
            timeout=self.PHASE0_TIMEOUT,
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            return result
        result.phases_run.append(0)
        result.phase_results[0] = p0
        if p0.facts_stored:
            result.total_facts += p0.facts_stored

        # Propagate internal hit flag and confidence for downstream decisions
        result.internal_hit = p0.success
        result.confidence_score = p0.confidence_score

        # ── Phase 1: Basic Understanding (conditional) ────────────────────
        # Skip when internal recall is highly confident to save external calls.
        skip_p1 = result.confidence_score >= INTERNAL_CONFIDENCE_THRESHOLD
        if skip_p1:
            log.info(
                "[PhasedResearch] Phase 1 skipped — internal confidence %.2f ≥ %.2f",
                result.confidence_score, INTERNAL_CONFIDENCE_THRESHOLD,
            )
        else:
            p1 = self._run_phase_with_timeout(
                phase=1,
                topic=topic,
                fn=self._phase1_basic,
                timeout=self.PHASE1_TIMEOUT,
                cancel_event=cancel_event,
            )
            if cancel_event is not None and cancel_event.is_set():
                return result
            result.phases_run.append(1)
            result.phase_results[1] = p1
            if p1.facts_stored:
                result.total_facts += p1.facts_stored
            if p1.confidence_score > result.confidence_score:
                result.confidence_score = p1.confidence_score

        # ── Phase 2: Deep Knowledge (conditional) ─────────────────────────
        # Run whenever confidence is below the deep-skip threshold — whether
        # Phase 1 ran or was skipped.  Uses Phase 1 results as context if
        # available, otherwise falls back to Phase 0 results.
        _p1_result = result.phase_results.get(1) or result.phase_results.get(0)
        _p1_ran = 1 in result.phases_run
        if not skip_phase2 and result.confidence_score < DEEP_SKIP_THRESHOLD:
            p2 = self._run_phase_with_timeout(
                phase=2,
                topic=topic,
                fn=lambda t: self._phase2_advanced(t, _p1_result),
                timeout=self.PHASE2_TIMEOUT,
                cancel_event=cancel_event,
            )
            if cancel_event is not None and cancel_event.is_set():
                return result
            result.phases_run.append(2)
            result.phase_results[2] = p2
            if p2.facts_stored:
                result.total_facts += p2.facts_stored
            if p2.confidence_score > result.confidence_score:
                result.confidence_score = p2.confidence_score
        else:
            reason = (
                "skip_phase2=True" if skip_phase2
                else f"confidence {result.confidence_score:.2f} ≥ deep_skip_threshold"
            )
            log.debug("[PhasedResearch] Phase 2 skipped (%s)", reason)

        # ── Phase 3: Code Generation (code-topic-only, conditional) ───────
        _p2_result = result.phase_results.get(2)
        if result.is_code_topic and not skip_phase3:
            p3 = self._run_phase_with_timeout(
                phase=3,
                topic=topic,
                fn=lambda t: self._phase3_code(t, _p1_result, _p2_result),
                timeout=self.PHASE3_TIMEOUT,
                cancel_event=cancel_event,
            )
            if cancel_event is not None and cancel_event.is_set():
                return result
            result.phases_run.append(3)
            result.phase_results[3] = p3
            if p3.facts_stored:
                result.total_facts += p3.facts_stored
        else:
            reason = "code-topic=False" if not result.is_code_topic else "skip_phase3=True"
            log.debug("[PhasedResearch] Phase 3 skipped (%s)", reason)

        result.total_duration_s = time.monotonic() - t0

        if cancel_event is not None and cancel_event.is_set():
            return result

        # ── Emit research artifact ─────────────────────────────────────────
        result.artifact = self._build_research_artifact(result)
        self._persist_research_artifact(result.artifact)

        log.info("✅ %s", result.summary())
        return result

    # ------------------------------------------------------------------
    # Phase 0: Local Knowledge Partner
    # ------------------------------------------------------------------

    def research_governed(self, request, *, loop, gateway, scope, control=None):
        """Bounded structured-source entry to the existing research engine.

        Legacy model synthesis/automatic phase persistence are deliberately not
        invoked: recalled claims are context, not new independent evidence.
        This first supported profile acquires scalar JSON declarations only.
        """
        if request.get('profile') == 'public_sources':
            return self._research_public_sources(request, loop=loop, gateway=gateway, scope=scope, control=control)
        import hashlib, json, re, uuid, math
        if not isinstance(request.get('objective'),str) or not isinstance(request.get('subject'),str):
            raise ValueError('objective and subject must be text')
        objective = request['objective'].strip()
        subject = request['subject'].strip()
        sources = request.get('sources', [])
        allowed_request_actions = request.get('permitted_actions', [])
        if not isinstance(allowed_request_actions,list) or any(not isinstance(action,str) for action in allowed_request_actions):
            raise ValueError('permitted actions must be a list of names')
        actions = set(allowed_request_actions)
        seconds = request.get('max_seconds', 10)
        calls = request.get('max_research_calls', 1)
        cap = request.get('max_accepted_records', 4)
        if (not 3 <= len(objective) <= 500 or not 3 <= len(subject) <= 120 or
            not isinstance(sources,list) or not 1 <= len(sources) <= 4 or
            type(seconds) is not int or not 1 <= seconds <= 30 or
            type(calls) is not int or not 0 <= calls <= 4 or
            type(cap) is not int or not 1 <= cap <= 8 or
            not {'recall','read_workspace','store_observations'}.issubset(actions) or
            actions - {'recall','read_workspace','store_observations'}):
            raise ValueError('invalid bounded learning request')
        gateway.require('read', **scope)
        gateway.require('ingest', **scope)
        started = time.monotonic()
        deadline = started + seconds
        receipt = {'schema_version':'governed-learning/1','event_id':uuid.uuid4().hex,
                   'objective':objective,'subject':subject,'accepted':[],'rejected':[],
                   'unresolved':[],'tool_calls':[],'research_calls':0,'model_calls':0,
                   'verification':'source_observations_only','status':'running'}
        # Existing canonical retrieval runs before any acquisition. Never feed
        # old summaries into extraction as if they were new sources.
        try:
            recalled = gateway.retrieve(objective, **scope, limit=4)
            receipt['prior_evidence_ids'] = [h['id'] for h in recalled['results']]
            receipt['retrieval_issues'] = recalled['issues']
            known = set()
            for hit in recalled['results']:
                try:
                    prior = json.loads(hit['content'])
                    if prior.get('subject')==subject:known.add(prior.get('field'))
                except (ValueError,AttributeError):
                    pass
            requested = {field for source in sources if isinstance(source,dict) and isinstance(source.get('fields'),list)
                         for field in source.get('fields',[]) if isinstance(field,str)}
            receipt['knowledge_gaps'] = sorted(requested-known)
            receipt['acquisition_reason'] = 'fill_structured_gaps' if receipt['knowledge_gaps'] else 'revalidate_current_source'
        except Exception as exc:
            receipt['unresolved'].append('recall_failed:'+type(exc).__name__)
            receipt['status']='failed'
            return receipt
        for source in sources:
            if len(receipt['accepted']) >= cap:
                receipt['unresolved'].append('accepted_record_budget_exhausted');break
            if time.monotonic() >= deadline or receipt['research_calls'] >= calls:
                receipt['unresolved'].append('time_or_research_budget_exhausted')
                break
            if not isinstance(source,dict) or source.get('kind') != 'workspace_json':
                receipt['rejected'].append({'reason':'unsupported_source; reflections/inference are not evidence'})
                continue
            path = source.get('path','')
            fields = source.get('fields',[])
            if (not isinstance(path,str) or not path.endswith('.json') or
                not isinstance(fields,list) or not 1 <= len(fields) <= 8 or
                any(not isinstance(f,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,60}', f) or
                    re.search(r'secret|password|token|credential|key|auth|summary|reflection|confidence',f,re.I) for f in fields)):
                receipt['rejected'].append({'reason':'unsupported_or_sensitive_fields'})
                continue
            tokens = set(re.findall(r'\w+',objective.casefold()))
            if not tokens.intersection(set(re.findall(r'\w+',path.casefold())) | {f.casefold() for f in fields}):
                receipt['rejected'].append({'reason':'source_not_relevant_to_objective'})
                continue
            receipt['research_calls'] += 1
            observation = loop.invoke('workspace_read', {'path':path,'max_chars':12000})
            receipt['tool_calls'].append({'tool':'workspace_read','arguments':{'path':path,'max_chars':12000},
                'status':observation.get('status'),'duration_ms':observation.get('duration_ms'),
                'permission_decision':'passed_or_not_required' if observation.get('status')=='success' else 'not_established'})
            data = observation.get('result') or {}
            receipt['tool_calls'][-1]['source_status']='error' if data.get('error') or observation.get('status')!='success' else 'read'
            if observation.get('status') != 'success' or data.get('error') or data.get('truncated'):
                receipt['unresolved'].append('source_unavailable_denied_or_truncated')
                continue
            if time.monotonic() >= deadline:
                receipt['unresolved'].append('deadline_exceeded_no_source_accepted');break
            try:
                text = data['content']
                def unique_pairs(pairs):
                    result = {}
                    for key,value in pairs:
                        if key in result:raise ValueError('duplicate JSON field')
                        result[key]=value
                    return result
                def invalid_number(value):
                    raise ValueError('nonfinite JSON number')
                parsed = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_number)
                if not isinstance(parsed,dict):raise ValueError('object required')
            except (KeyError,ValueError,TypeError):
                receipt['rejected'].append({'reason':'malformed_or_unsupported_source_json'});continue
            provenance = parsed.get('provenance', {})
            if not isinstance(provenance,dict):provenance={}
            excluded_sources = {'reflection','inference','generated_reflection','local_model_reflection','user_input','assistant_response','generated_summary'}
            if (parsed.get('generated') or provenance.get('generated') or
                    parsed.get('source_type') in excluded_sources or provenance.get('source_type') in excluded_sources):
                receipt['rejected'].append({'reason':'generated_material_not_independent_evidence'});continue
            source_hash = hashlib.sha256(text.encode()).hexdigest()
            for field in fields:
                if len(receipt['accepted']) >= cap or time.monotonic() >= deadline:
                    receipt['unresolved'].append('accepted_record_or_time_budget_exhausted');break
                value = parsed.get(field)
                if (type(value) not in (str,int,float,bool) or len(str(value)) > 300 or
                        isinstance(value,float) and not math.isfinite(value)):
                    receipt['rejected'].append({'field':field,'reason':'missing_or_unsupported_scalar'});continue
                try:
                    result = gateway.observe_learning(**scope,subject=subject,selector=field,value=value,
                        citation='workspace://'+path+'#field='+field,source_hash=source_hash,event_id=receipt['event_id'],
                        cancelled=lambda:time.monotonic() >= deadline)
                    target = 'accepted' if result['accepted'] else 'unresolved'
                    if result['accepted']:result.update(field=field,value=value)
                    receipt[target].append(result)
                except Exception as exc:
                    receipt['unresolved'].append('storage_or_projection_failed:'+type(exc).__name__)
        receipt['status'] = 'completed' if receipt['accepted'] and not receipt['unresolved'] else 'partial' if receipt['accepted'] else 'inconclusive'
        receipt['new_records'] = sum(item['status']=='new' for item in receipt['accepted'])
        receipt['repeated_observations'] = sum(item['status']=='repeated' for item in receipt['accepted'])
        receipt['knowledge_changed'] = receipt['new_records'] > 0
        receipt['reflection'] = {'source_type':'generated_reflection',
            'text':f"{len(receipt['accepted'])} source observations recorded; {len(receipt['rejected'])} rejected; {len(receipt['unresolved'])} unresolved.",
            'independent_evidence':False}
        receipt['elapsed_seconds'] = round(time.monotonic()-started,3)
        with gateway.db() as db:
            gateway.audit(db,'learning.completed',receipt['event_id'],namespace=scope['namespace'],
                          principal=scope['principal'],receipt=receipt)
        return receipt

    def _learning_tool(self, loop, name, arguments, control):
        if control:
            with control.gate:
                if control.cancelled.is_set():return {'status':'cancelled','result':{}}
                if not control.stage('tool:'+name):return {'status':'cancelled','result':{}}
        result=loop.invoke(name,arguments)
        if control:
            with control.gate:
                control.calls[-1]['returned_at']=time.time()
                control.stage('returned:'+name)
        return result

    def _research_public_sources(self, request, *, loop, gateway, scope, control=None):
        """Approved-source extractive research using the existing learning ledger.

        Quotations are source observations, not independently verified universal
        facts. No model output or recalled summary is fed back as new evidence.
        Source-slot revisions are held; semantic contradiction detection remains
        a separate review requirement, never guessed from a confidence score.
        """
        import hashlib, json, os, re, uuid
        from urllib.parse import urlsplit
        objective, subject = request.get('objective'), request.get('subject')
        sources = request.get('sources')
        seconds, calls, cap = (request.get(k) for k in ('max_seconds','max_research_calls','max_accepted_records'))
        approved = {d.strip().lower() for d in os.getenv('NIBLIT_RESEARCH_ALLOWED_DOMAINS','').split(',') if d.strip()}
        if (not isinstance(objective,str) or not 3 <= len(objective) <= 500 or
            not isinstance(subject,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,120}',subject) or
            not isinstance(sources,list) or not 1 <= len(sources) <= 4 or
            type(seconds) is not int or not 1 <= seconds <= 30 or
            type(calls) is not int or not 0 <= calls <= 4 or
            type(cap) is not int or not 1 <= cap <= 8 or
            request.get('permitted_actions') != ['recall','fetch_public','store_observations']):
            raise ValueError('invalid public research budget or actions')
        urls = []
        discover = sources == [{'kind':'public_search'}]
        if not approved:raise PermissionError('no public research domains approved')
        for source in sources:
            if discover:break
            if not isinstance(source,dict) or source.get('kind') != 'public_web':
                raise ValueError('public_web sources required')
            url = source.get('url','')
            if not isinstance(url,str) or len(url)>1500:raise ValueError('invalid source URL')
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.username or parsed.password or
                parsed.port not in (None,443) or parsed.fragment or parsed.hostname not in approved):
                raise PermissionError('source is not an explicitly approved public HTTPS domain')
            if url not in urls:urls.append(url)
        gateway.require('read', **scope); gateway.require('ingest', **scope)
        started = time.monotonic(); deadline = started + seconds
        receipt = {'schema_version':'governed-learning/2','event_id':uuid.uuid4().hex,
            'objective':objective,'subject':subject,'profile':'public_sources',
            'accepted':[],'rejected':[],'unresolved':[],'sources':[], 'tool_calls':[],
            'research_calls':0,'model_calls':0,'verification':'attributed_source_observations',
            'hypotheses':[],'follow_up_questions':[],
            'limitations':['Extractive source review; not general autonomous research',
                'Topic overlap is a relevance signal, not factual verification',
                'Source-slot changes are held; arbitrary semantic contradictions require review',
                'Publication dates and hardware-retail-specific applicability may be unknown']}
        receipt['job_id']=control.job_id if control else None
        if control:control.result=receipt
        receipt['commit_policy']='Only validated source observations completed before cancellation are retained; cancellation is not successful learning.'
        def stopped():
            return time.monotonic()>=deadline or bool(control and control.cancelled.is_set())
        try:
            prior = gateway.learning_facts(subject, **scope)
            related = gateway.retrieve(objective, **scope, limit=4)
            receipt['related_evidence_ids'] = [item['id'] for item in related['results']]
            receipt['retrieval_issues'] = related['issues']
            receipt['prior_evidence_ids'] = [f['id'] for f in prior['facts']]
        except Exception as exc:
            receipt['unresolved'].append('recall_failed:'+type(exc).__name__)
            prior = {'facts':[]}
        receipt['plan'] = {'sources':urls,'max_seconds':seconds,'max_research_calls':calls,
            'max_accepted_records':cap,'max_source_bytes':400000,
            'gap':'Acquire source-backed observations' if not prior['facts'] else 'Revalidate prior source observations'}
        if discover and not receipt['unresolved'] and calls and not stopped():
            query=objective+' site:'+sorted(approved)[0]
            result=self._learning_tool(loop,'web_search',{'query':query,'max_results':8},control)
            receipt['research_calls']+=1
            if result.get('status')=='cancelled':receipt['research_calls']-=1
            receipt['tool_calls'].append({'tool':'web_search','arguments':{'query':query,'max_results':8},
                'status':result.get('status'),'duration_ms':result.get('duration_ms'),
                'permission_decision':'passed_or_not_required' if result.get('status')=='success' else 'denied_or_unavailable'})
            receipt['discovery'] = result.get('result') or {'error':'search_unavailable'}
            for hit in (result.get('result') or {}).get('results',[]):
                url=hit.get('url',''); parsed=urlsplit(url)
                if parsed.scheme=='https' and parsed.hostname in approved and not parsed.username and not parsed.password and parsed.port in (None,443) and not parsed.fragment:
                    if url not in urls:urls.append(url)
            urls[:]=urls[:min(3,calls-1)]
            if not urls:receipt['unresolved'].append('no_approved_sources_discovered')
        stop = {'research','learn','using','from','this','that','with','what','which','their','about','explain','works','useful','findings','sources','compare'}
        terms = {t[:6] for t in re.findall(r'[a-z]{4,}',objective.lower()) if t not in stop}
        if not receipt['unresolved']:
            for url in urls:
                if stopped() or receipt['research_calls'] >= calls or len(receipt['accepted'])>=cap:
                    receipt['unresolved'].append('execution_budget_exhausted');break
                args={'url':url,'allowed_domains':sorted(approved),
                      'timeout':min(10,max(.1,deadline-time.monotonic())),'max_bytes':400000}
                receipt['research_calls'] += 1
                observed = self._learning_tool(loop,'web_fetch',args,control)
                if observed.get('status')=='cancelled':receipt['research_calls']-=1
                receipt['tool_calls'].append({'tool':'web_fetch','arguments':args,
                    'status':observed.get('status'),'duration_ms':observed.get('duration_ms'),
                    'permission_decision':'passed_or_not_required' if observed.get('status')=='success' else 'denied_or_unavailable'})
                result = observed.get('result') or {}; evidence = result.get('evidence') or {}
                if stopped():
                    receipt['unresolved'].append('cancelled_or_deadline_after_inflight_io');break
                if observed.get('status')!='success' or result.get('error') or not evidence.get('source_hash'):
                    receipt['unresolved'].append({'url':url,'reason':result.get('error','fetch_unavailable_or_denied')});continue
                text = evidence.get('extracted_text','')
                receipt['sources'].append({k:evidence.get(k) for k in ('source_url','source_domain','retrieved_at','source_hash','content_type','text_truncated')})
                receipt['sources'][-1].update(publication_date='UNKNOWN',independence_group=evidence.get('source_domain'))
                candidates = []
                for line in text.splitlines():
                    for sentence in re.split(r'(?<=[.!?])\s+',line):
                        sentence = ' '.join(sentence.split())
                        overlap = sum(t in sentence.lower() for t in terms)
                        if (60<=len(sentence)<=300 and overlap>=2 and sentence.endswith('.') and
                            re.search(r'\b(?:is|are|must|should|can|use|records|post|do|before|after|may|might|equals)\b',sentence,re.I) and
                            not re.search(r'ignore .*instructions|system prompt|as an ai|generated (?:summary|reflection)|this (?:module|article)|microsoft learn|:alt:|to learn more|for more information|see also',sentence,re.I)):
                            candidates.append((overlap,sentence))
                selected = list(dict.fromkeys(s for _,s in sorted(candidates,key=lambda x:(-x[0],x[1]))))[:2]
                if not selected:receipt['rejected'].append({'url':url,'reason':'no_substantive_relevant_source_excerpt'})
                for index,quote in enumerate(selected):
                    if stopped() or len(receipt['accepted'])>=cap:
                        receipt['unresolved'].append('execution_budget_exhausted');break
                    selector='source_'+hashlib.sha256(url.encode()).hexdigest()[:16]+'_finding_'+str(index)
                    citation=evidence['source_url']
                    try:
                        from contextlib import nullcontext
                        from modules.research_contracts import source_identity
                        with control.gate if control else nullcontext():
                            if stopped():break
                            if control and not control.stage('commit_validated_observation'):break
                            saved=gateway.observe_learning(**scope,subject=subject,selector=selector,value=quote,
                                citation=citation,source_hash=evidence['source_hash'],event_id=receipt['event_id'],
                                cancelled=stopped,
                                evidence_metadata={'source_kind':'public_web',**source_identity(citation),
                                    'source_url':citation,'excerpt':quote,
                                    'retrieved_at':evidence['retrieved_at'],'evidence_id':evidence['evidence_id'],
                                    'publication_date':'UNKNOWN','quality':'approved_domain_exact_excerpt'})
                        if saved['accepted']:
                            saved.update(field=selector,value=quote,support='exact_source_excerpt')
                            receipt['accepted'].append(saved)
                        else:receipt['unresolved'].append(saved)
                    except Exception as exc:receipt['unresolved'].append('storage_failed:'+type(exc).__name__)
        receipt['status']='completed' if receipt['accepted'] and not receipt['unresolved'] else 'partial' if receipt['accepted'] else 'inconclusive'
        if control and control.cancelled.is_set():receipt['status']='cancelled'
        elif time.monotonic()>=deadline:receipt['status']='timed_out'
        receipt['new_records']=sum(i['status']=='new' for i in receipt['accepted'])
        receipt['repeated_observations']=sum(i['status']=='repeated' for i in receipt['accepted'])
        receipt['knowledge_changed']=bool(receipt['new_records'])
        receipt['elapsed_seconds']=round(time.monotonic()-started,3)
        with gateway.db() as db:
            gateway.audit(db,'learning.'+('cancelled' if receipt['status']=='cancelled' else 'timed_out' if receipt['status']=='timed_out' else 'completed'),receipt['event_id'],**scope,receipt=receipt)
        return receipt

    def _phase0_internal(self, topic: str) -> PhaseResult:
        """Phase 0: Internal-first local knowledge recall.

        Queries all local knowledge sources in priority order:

        1. KnowledgeDB recall (niblit_memory) — fastest; returns previously
           stored research facts tagged ``ale_learned`` or ``ale_phase*``.
        2. TieredKnowledgeSystem.recall_knowledge() — structured tier-tagged
           knowledge accumulated across learning cycles.
        3. RuntimeRouterV2 → LocalBrain inference — synthesises a concept
           explanation, approach comparison, optimisation suggestions, and
           log/test-failure interpretation from the local GGUF model.

        The phase confidence is scored based on how many local sources
        returned relevant content:
          - 3 sources hit → 0.90
          - 2 sources hit → 0.80
          - 1 source hit  → 0.70
          - 0 sources hit → 0.10 (external phases should run)
        """
        t0 = time.monotonic()
        pr = PhaseResult(phase=0, topic=topic, source_type="internal")

        sources_hit: int = 0

        # ── 1. KnowledgeDB recall ────────────────────────────────────────
        if self.knowledge_db:
            try:
                recalled = None
                if hasattr(self.knowledge_db, "recall"):
                    recalled = self.knowledge_db.recall(topic, limit=5)
                elif hasattr(self.knowledge_db, "search"):
                    recalled = self.knowledge_db.search(topic, limit=5)

                if recalled:
                    texts: List[str] = []
                    for item in (recalled if isinstance(recalled, list) else [recalled]):
                        text = ""
                        if isinstance(item, dict):
                            text = (
                                str(item.get("content") or item.get("value")
                                    or item.get("text") or item.get("summary") or "")[:500]
                            )
                        elif isinstance(item, str):
                            text = item[:500]
                        if text and len(text.strip()) >= 20:
                            texts.append(text.strip())

                    for t in texts[:3]:
                        if t not in pr.snippets:
                            pr.snippets.append(t)
                            pr.sources.append("niblit_memory")

                    if texts:
                        sources_hit += 1
                        log.debug("[Phase0] KB recall: %d snippets for %r", len(texts), topic)
            except Exception as exc:
                log.debug("[Phase0] KB recall failed: %s", exc)

        # ── 2. TieredKnowledgeSystem.recall_knowledge() ──────────────────
        try:
            from modules.tiered_knowledge_system import get_tiered_knowledge_system
            tks = get_tiered_knowledge_system(knowledge_db=self.knowledge_db)
            tks_text = tks.recall_knowledge(topic) if tks else None
            if tks_text and len(str(tks_text).strip()) >= 20:
                snippet = str(tks_text).strip()[:600]
                if snippet not in pr.snippets:
                    pr.snippets.append(snippet)
                    pr.sources.append("tiered_knowledge")
                sources_hit += 1
                log.debug("[Phase0] TieredKnowledgeSystem hit for %r", topic)
        except Exception as exc:
            log.debug("[Phase0] TieredKnowledgeSystem recall failed: %s", exc)

        # ── 3. RuntimeRouterV2 → LocalBrain synthesis ───────────────────
        # Ask the local model to synthesise: concept explanation, approach
        # comparison, optimisation suggestions, and error/log interpretation.
        try:
            from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2
            router = NiblitUnifiedRuntimeRouterV2()
            prior_ctx = "\n".join(pr.snippets[:2])[:600] if pr.snippets else ""
            prompt = (
                f"Topic: {topic}\n\n"
                f"Prior knowledge:\n{prior_ctx}\n\n"
                f"Provide a concise structured response covering:\n"
                f"1. Concept explanation (2-3 sentences)\n"
                f"2. Common approaches or variants\n"
                f"3. Key optimisation considerations\n"
                f"4. How to interpret failures or errors related to this topic\n"
                f"Keep the total response under 300 words."
            )
            synthesis = router.generate(prompt, max_tokens=350) if prior_ctx else ""
            if synthesis and len(synthesis.strip()) >= 40:
                snippet = synthesis.strip()[:700]
                if snippet not in pr.snippets:
                    pr.snippets.append(snippet)
                    pr.sources.append("local_brain")
                log.debug("[Phase0] LocalBrain synthesis generated for %r", topic)
        except Exception as exc:
            log.debug("[Phase0] LocalBrain synthesis failed: %s", exc)

        # ── Confidence scoring ────────────────────────────────────────────
        confidence_map = {0: 0.10, 1: 0.70, 2: 0.80, 3: 0.90}
        pr.confidence_score = confidence_map.get(sources_hit, 0.10)

        # ── Store Phase 0 results ─────────────────────────────────────────
        research_checkpoint()
        pr.facts_stored = self._store_phase_results(pr, tier="internal")
        pr.duration_s = time.monotonic() - t0
        log.info(
            "🧠 [Phase0/Internal] %r — %d sources, %d snippets, conf=%.2f (%.1fs)",
            topic, sources_hit, len(pr.snippets), pr.confidence_score, pr.duration_s,
        )
        return pr

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _phase1_basic(self, topic: str) -> PhaseResult:
        """Phase 1: Basic understanding via expanded queries to Internet + DuckDuckGo.

        Goal: collect 2–5 short, factual snippets covering *multiple knowledge
        facets* of the topic.  A single flat query (the bare topic string) tends
        to return five variations of the same overview paragraph, so Phase 1 now
        issues up to 3 focused aspect queries generated by ``_expand_topic_queries``:

        1. Conceptual  — "what is X" or "X overview"
        2. Mechanistic — "X how it works"
        3. Practical   — "X examples and use cases"

        This mirrors the multi-query retrieval pattern recommended by LlamaIndex
        and the step-back prompting technique: diverse queries produce a richer,
        more complementary set of snippets for Phase 2 to build on.

        Sources tried in order:
        1. Internet (Google/Bing via InternetManager) — Wikipedia-biased results
           give the cleanest, most factual baseline.
        2. ScrapyResearchAgent (DuckDuckGo) — used for any query that internet
           failed to answer (rather than only as a global fallback).
        """
        t0 = time.monotonic()
        pr = PhaseResult(phase=1, topic=topic)

        # Generate 3 focused aspect queries instead of a single flat search
        queries = _expand_topic_queries(topic)
        log.debug("[Phase1] Expanded queries for %r: %s", topic, queries)

        internet = self._get_internet()
        scrapy = self._get_scrapy()

        for query in queries:
            if len(pr.snippets) >= self.MAX_SNIPPETS_PER_PHASE:
                break

            # ── Try internet first for this query ─────────────────────────
            fetched_this_query: List[str] = []
            if internet:
                try:
                    result = internet.search(query)
                    fetched_this_query = self._extract_snippets(result)
                    log.debug("[Phase1] Internet(%r): %d snippets", query, len(fetched_this_query))
                except Exception as e:
                    log.debug("[Phase1] Internet failed for %r: %s", query, e)

            # ── DuckDuckGo fallback when internet returned nothing ─────────
            if not fetched_this_query and scrapy:
                try:
                    result = scrapy.search_web(query)
                    fetched_this_query = self._extract_snippets(result)
                    log.debug("[Phase1] DuckDuckGo(%r): %d snippets", query, len(fetched_this_query))
                except Exception as e:
                    log.debug("[Phase1] DuckDuckGo failed for %r: %s", query, e)

            # Add new (non-duplicate) snippets
            src = "internet" if internet else "duckduckgo"
            for s in fetched_this_query[:3]:
                if s not in pr.snippets and len(pr.snippets) < self.MAX_SNIPPETS_PER_PHASE:
                    pr.snippets.append(s)
                    pr.sources.append(src)

        # Rank collected snippets by quality before storing so the best content
        # lands in Tier 2 and weaker snippets are trimmed at the MAX boundary.
        if len(pr.snippets) > 1:
            paired = sorted(
                zip(pr.snippets, pr.sources),
                key=lambda pair: _score_snippet_quality(pair[0], topic),
                reverse=True,
            )
            pr.snippets, pr.sources = [p[0] for p in paired], [p[1] for p in paired]

        # ── Store Phase 1 results in KB + GraphRAG ─────────────────────
        research_checkpoint()
        pr.facts_stored = self._store_phase_results(pr, tier="tier2")
        # External basic sources carry moderate confidence
        pr.confidence_score = 0.65 if pr.snippets else 0.20
        pr.source_type = "external"
        pr.duration_s = time.monotonic() - t0
        return pr

    def _phase2_advanced(self, topic: str, p1: PhaseResult) -> PhaseResult:
        """Phase 2: Gap-driven deep knowledge via SerpAPI + Serpex + Qdrant.

        Phase 2 now follows a two-strategy approach:

        **Strategy A — Gap queries (primary)**:
        ``_gap_queries_from_snippets`` analyses what Phase 1 already found and
        identifies the most frequently mentioned sub-terms that were NOT in the
        original topic.  These become targeted Phase 2 search queries so the
        research genuinely *extends* what is known rather than re-fetching the
        same overview.

        **Strategy B — Advanced sources (secondary)**:
        SerpAPI → Serpex → Qdrant vector recall → Internet fallback, all
        searching the original topic when gap queries didn't fill the Phase 2
        slots.

        Phase 2 snippets are also quality-scored and sorted before storage so
        the highest-value content reaches Tier 1.
        """
        t0 = time.monotonic()
        pr = PhaseResult(phase=2, topic=topic)

        # Build a "what we already know" context to avoid duplicates
        known = " ".join(p1.snippets)[:500]

        # ── Strategy A: gap-driven queries from Phase 1 findings ─────────
        # Derive up to 2 sub-aspect queries from the most frequent meaningful
        # terms in Phase 1 snippets that are NOT already in the topic name.
        gap_queries = _gap_queries_from_snippets(topic, p1.snippets, max_gaps=2)
        if gap_queries:
            log.debug("[Phase2] Gap queries for %r: %s", topic, gap_queries)
            internet = self._get_internet()
            scrapy = self._get_scrapy()
            for gq in gap_queries:
                research_checkpoint()
                if len(pr.snippets) >= self.MAX_SNIPPETS_PER_PHASE:
                    break
                fetched: List[str] = []
                if internet:
                    try:
                        fetched = self._extract_snippets(internet.search(gq))
                        log.debug("[Phase2] Gap-internet(%r): %d", gq, len(fetched))
                    except Exception as e:
                        log.debug("[Phase2] Gap-internet failed for %r: %s", gq, e)
                if not fetched and scrapy:
                    try:
                        fetched = self._extract_snippets(scrapy.search_web(gq))
                        log.debug("[Phase2] Gap-scrapy(%r): %d", gq, len(fetched))
                    except Exception as e:
                        log.debug("[Phase2] Gap-scrapy failed for %r: %s", gq, e)
                for s in fetched[:3]:
                    if s not in known and s not in pr.snippets:
                        pr.snippets.append(s)
                        pr.sources.append("gap_query")

        research_checkpoint()
        # ── Strategy B: authoritative sources on the original topic ──────

        # ── 2a. SerpAPI ──────────────────────────────────────────────
        if len(pr.snippets) < self.MAX_SNIPPETS_PER_PHASE:
            serpapi = self._get_serpapi()
            if serpapi:
                try:
                    results = serpapi.search(topic, max_results=5) or []
                    if not isinstance(results, list):
                        results = [results] if results else []
                    for item in results[:5]:
                        snippet = self._item_to_text(item)
                        if snippet and snippet not in known and snippet not in pr.snippets:
                            pr.snippets.append(snippet)
                            pr.sources.append("serpapi")
                    log.debug("[Phase2] SerpAPI: %d results", len(results))
                except Exception as e:
                    log.debug("[Phase2] SerpAPI failed: %s", e)

        research_checkpoint()
        # ── 2b. Serpex ───────────────────────────────────────────────
        if len(pr.snippets) < 3:
            serpex = self._get_serpex()
            if serpex:
                try:
                    results = serpex.search_web(topic) or []
                    if not isinstance(results, list):
                        results = [results] if results else []
                    for item in results[:4]:
                        snippet = self._item_to_text(item)
                        if snippet and snippet not in known and snippet not in pr.snippets:
                            pr.snippets.append(snippet)
                            pr.sources.append("serpex")
                    log.debug("[Phase2] Serpex: %d results", len(results))
                except Exception as e:
                    log.debug("[Phase2] Serpex failed: %s", e)

        research_checkpoint()
        # ── 2c. Qdrant / HybridManager vector recall ─────────────────
        if len(pr.snippets) < 2:
            hybrid = self._get_hybrid_manager()
            if hybrid:
                try:
                    hits = hybrid.search(topic, top_k=3) or []
                    for hit in hits[:3]:
                        text = self._item_to_text(hit)
                        if text and text not in known and text not in pr.snippets:
                            pr.snippets.append(text)
                            pr.sources.append("qdrant")
                    log.debug("[Phase2] Qdrant: %d hits", len(hits))
                except Exception as e:
                    log.debug("[Phase2] Qdrant failed: %s", e)

        # ── 2d. Internet as Phase 2 fallback when all else fails ─────
        if not pr.snippets:
            internet = self._get_internet()
            if internet:
                try:
                    results = internet.search(f"{topic} detailed explanation")
                    snippets = self._extract_snippets(results)
                    for s in snippets[:3]:
                        if s not in known and s not in pr.snippets:
                            pr.snippets.append(s)
                            pr.sources.append("internet_phase2")
                except Exception as e:
                    log.debug("[Phase2] Internet fallback failed: %s", e)

        # Rank by quality before storing — best snippets go to Tier 1
        if len(pr.snippets) > 1:
            paired = sorted(
                zip(pr.snippets, pr.sources),
                key=lambda pair: _score_snippet_quality(pair[0], topic),
                reverse=True,
            )
            pr.snippets, pr.sources = [p[0] for p in paired], [p[1] for p in paired]

        # ── Store Phase 2 results in Tier 1 ─────────────────────────
        research_checkpoint()
        pr.facts_stored = self._store_phase_results(pr, tier="tier1")
        # Authoritative external sources get higher confidence
        pr.confidence_score = 0.78 if pr.snippets else 0.30
        pr.source_type = "external"
        pr.duration_s = time.monotonic() - t0
        return pr

    def _phase3_code(
        self,
        topic: str,
        p1: PhaseResult,
        p2: Optional[PhaseResult],
    ) -> PhaseResult:
        """Phase 3: Real code from GitHub REST API (code topics only).

        Uses GitHub's code search + repository search to find real, runnable
        code examples.  Results are stored as code artefacts with tags that
        mark them for the CodeGenerator to pick up.

        Only runs when _is_code_topic(topic) is True.
        """
        t0 = time.monotonic()
        pr = PhaseResult(phase=3, topic=topic)

        gcs = self._get_github_code_search()
        if not gcs:
            pr.error = "github_code_search unavailable"
            pr.duration_s = time.monotonic() - t0
            return pr

        # ── 3a. Code search via GitHub ──────────────────────────────
        try:
            if hasattr(gcs, "research_for_code_generation"):
                results = gcs.research_for_code_generation(topic, max_results=5) or []
            elif hasattr(gcs, "search_repos"):
                results = gcs.search_repos(topic, max_results=5) or []
            else:
                results = []

            for item in results[:self.MAX_SNIPPETS_PER_PHASE]:
                snippet = self._item_to_text(item)
                if snippet and len(snippet) >= self.MIN_SNIPPET_LEN:
                    pr.snippets.append(snippet)
                    pr.sources.append("github_api")

            log.debug("[Phase3] GitHub: %d code snippets", len(pr.snippets))

        except Exception as e:
            log.debug("[Phase3] GitHub code search failed: %s", e)
            pr.error = str(e)

        # ── Store Phase 3 code artefacts ────────────────────────────
        research_checkpoint()
        pr.facts_stored = self._store_phase_results(pr, tier="code")
        pr.confidence_score = 0.72 if pr.snippets else 0.20
        pr.source_type = "external"
        pr.duration_s = time.monotonic() - t0
        return pr

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _store_phase_results(self, pr: PhaseResult, tier: str) -> int:
        """Store phase snippets in KnowledgeDB and GraphRAGPipeline.

        Parameters
        ----------
        pr :
            The PhaseResult to store.
        tier :
            "internal", "tier1", "tier2", or "code" — controls storage target
            and tags.

        Returns
        -------
        int
            Number of facts stored.
        """
        stored = 0
        lm = self._get_language_module()
        topic = pr.topic
        ts = int(time.time())

        # Recalled material is already stored; unaudited model synthesis is
        # interpretation, not new source knowledge.
        phase0_skip_sources = frozenset({"niblit_memory", "tiered_knowledge", "local_brain"})

        for i, snippet in enumerate(pr.snippets[:self.MAX_SNIPPETS_PER_PHASE]):
            research_checkpoint()
            if len(snippet.strip()) < self.MIN_SNIPPET_LEN:
                continue
            source = pr.sources[i] if i < len(pr.sources) else "unknown"

            # For Phase 0, skip already-stored recall sources to avoid duplication
            if tier == "internal" and source in phase0_skip_sources:
                continue
            from modules.research_contracts import learning_outcome
            if not learning_outcome(topic, [{'content': snippet, 'citation': source}])['learning_succeeded']:
                continue

            # Optionally format through LanguageModule for cleaner text
            clean_snippet = snippet
            if lm:
                try:
                    q_type = lm.detect_question_type(f"what is {topic}")
                    if q_type == "definition":
                        formatted = lm.format_factual_answer(f"what is {topic}", [{"value": snippet}])
                        if formatted and len(formatted) > 20:
                            clean_snippet = formatted
                except Exception:
                    pass

            key_prefix = {
                "internal": "ale_internal_research",
                "tier1": "ale_phase2_research",
                "tier2": "ale_phase1_research",
                "code": "ale_code_research",
            }.get(tier, "ale_phased_research")

            phase_label = {0: "internal", 1: "basic", 2: "advanced", 3: "code"}.get(pr.phase, str(pr.phase))

            # Store in KnowledgeDB
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"{key_prefix}:{topic.replace(' ', '_')}:{ts}_{i}",
                        {
                            "topic": topic,
                            "content": clean_snippet[:600],
                            "phase": pr.phase,
                            "tier": tier,
                            "source": source,
                            "source_type": pr.source_type,
                            "confidence_score": pr.confidence_score,
                            "phase_label": phase_label,
                            "last_observed_at": ts,
                            "verification_status": "tentative",
                        },
                        tags=[
                            "ale_learned",
                            f"phase_{pr.phase}",
                            tier,
                            pr.source_type,
                            topic.split()[0].lower()[:20],
                        ],
                    )
                    stored += 1
                except Exception as e:
                    log.debug("[PhasedResearch] KB store failed: %s", e)

            # Push to GraphRAGPipeline
            if self._grb:
                try:
                    grp = getattr(self._grb, "_grp", None)
                    if grp:
                        if tier == "tier1":
                            grp.add_fact(
                                topic,
                                "has_knowledge",
                                clean_snippet[:300],
                                "phase2_advanced",
                            )
                        elif tier == "code":
                            grp.add_document(
                                f"code:{topic}:{ts}",
                                clean_snippet,
                            )
                        elif tier == "internal":
                            grp.add_fact(
                                topic,
                                "has_internal_knowledge",
                                clean_snippet[:300],
                                "phase0_internal",
                            )
                        else:
                            grp.add_document(
                                f"phase1:{topic}:{ts}",
                                clean_snippet,
                            )
                except Exception as e:
                    log.debug("[PhasedResearch] GraphRAG push failed: %s", e)

        return stored

    # ------------------------------------------------------------------
    # Research artifact helpers
    # ------------------------------------------------------------------

    def _build_research_artifact(self, result: PhasedResearchResult) -> ResearchMemoryArtifact:
        """Construct a ResearchMemoryArtifact from all completed phase results."""
        topic = result.topic
        all_snippets: List[str] = []
        all_sources: List[str] = []
        evidence = []
        errors = []
        for ph in result.phases_run:
            pr = result.phase_results.get(ph)
            if pr and pr.error:
                errors.append(f"phase_{ph}:failed")
            if pr and pr.snippets:
                for index, snippet in enumerate(pr.snippets):
                    source = pr.sources[index] if index < len(pr.sources) else ""
                    evidence.append({'content': snippet, 'citation': source,
                                     'source_type': 'model_synthesis' if source == 'local_brain' or ph == 3 else 'source_claim'})

        from modules.research_contracts import learning_outcome
        outcome = learning_outcome(topic, evidence, errors=errors)
        outcome['research_attempts'] = [
            {'phase': ph, 'sources': list(result.phase_results[ph].sources),
             'returned_snippets': len(result.phase_results[ph].snippets),
             'failed': bool(result.phase_results[ph].error)}
            for ph in result.phases_run if ph in result.phase_results]
        all_snippets = [f['excerpt'] for f in outcome['findings']]
        all_sources = [f['citation'] for f in outcome['findings']]

        # Summary: first snippet or assembled text
        summary = all_snippets[0][:240] if all_snippets else f"No substantive findings for {topic}; {outcome['status']}"
        explanation = "\n\n".join(all_snippets[:3])[:800] if len(all_snippets) > 1 else summary

        # Derive follow-up topics from frequent non-topic terms
        follow_up = _gap_queries_from_snippets(topic, all_snippets, max_gaps=3)

        # Determine aggregate source type
        source_types = set(
            result.phase_results[ph].source_type
            for ph in result.phases_run
            if ph in result.phase_results
        )
        if source_types == {"internal"}:
            source_type = "internal"
        elif "external" in source_types and "internal" in source_types:
            source_type = "mixed"
        else:
            source_type = "external"

        return ResearchMemoryArtifact(
            topic=topic,
            summary=summary,
            explanation=explanation,
            references=list(dict.fromkeys(all_sources)),
            semantic_links=follow_up,
            confidence_score=result.confidence_score if all_snippets else 0.0,
            source_type=source_type,
            follow_up_topics=follow_up,
            phases_run=list(result.phases_run),
            total_facts=result.total_facts,
            outcome=outcome,
        )

    def _persist_research_artifact(self, artifact: ResearchMemoryArtifact) -> None:
        """Persist a ResearchMemoryArtifact to KB and governed memory."""
        if not self.knowledge_db:
            return
        topic_slug = artifact.topic.replace(" ", "_")
        ts = artifact.created_at
        try:
            self.knowledge_db.add_fact(
                f"research_artifact:{topic_slug}:{ts}",
                artifact.to_dict(),
                tags=[
                    "research_artifact",
                    "ale_learned" if artifact.outcome.get('learning_succeeded') else "investigation_no_findings",
                    artifact.source_type,
                    topic_slug.split("_")[0][:20],
                ],
            )
        except Exception as exc:
            log.debug("[PhasedResearch] Artifact persist failed: %s", exc)

        # Best-effort: also normalise through governed memory contract
        try:
            from shared.governance_contract.memory_contracts import normalize_memory_payload
            payload = normalize_memory_payload(
                artifact.to_dict(),
                text=artifact.explanation or artifact.summary,
                memory_type="semantic_memory",
                authority="phased_research_engine",
            )
            # Enrich with intelligence fields
            payload["confidence_score"] = artifact.confidence_score
            payload["source_type"] = artifact.source_type
            payload["last_observed_at"] = ts
            payload["verification_status"] = artifact.outcome.get('status', 'inconclusive')
            payload["related_concepts"] = artifact.semantic_links
            self.knowledge_db.add_fact(
                f"governed_research:{topic_slug}:{ts}",
                payload,
                tags=["governed", "research_artifact", "ale_learned" if artifact.outcome.get('learning_succeeded') else "investigation_no_findings"],
            )
        except Exception as exc:
            log.debug("[PhasedResearch] Governed artifact persist failed: %s", exc)

    # ------------------------------------------------------------------
    # Timeout wrapper
    # ------------------------------------------------------------------

    def _run_phase_with_timeout(
        self,
        phase: int,
        topic: str,
        fn,
        timeout: float,
        *,
        cancel_event=None,
    ) -> PhaseResult:
        """Cancel the phase cooperatively and join its owned executor."""
        import concurrent.futures

        result_box: List[PhaseResult] = []
        error_box: List[str] = []
        cancelled = threading.Event()
        t0 = time.monotonic()
        deadline = t0 + timeout

        def _worker():
            marker = _phase_scope.set((cancel_event, cancelled, deadline))
            try:
                research_checkpoint()
                result_box.append(fn(topic))
            except Exception as exc:
                error_box.append(str(exc))
            finally:
                _phase_scope.reset(marker)

        reason = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="NiblitResearchPhase") as executor:
            future = executor.submit(copy_context().run, _worker)
            while not future.done():
                if cancel_event is not None and cancel_event.is_set():
                    reason = "owner cancelled research"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = f"timeout after {timeout}s"
                    break
                try:
                    future.result(timeout=min(0.1, remaining))
                except concurrent.futures.TimeoutError:
                    continue
            if reason:
                cancelled.set()
                future.cancel()

        if reason:
            log.info("Research executor stopped for phase %s after %.2fs (%s)", phase, time.monotonic()-t0, reason)
            return PhaseResult(phase=phase, topic=topic, error=reason, duration_s=time.monotonic()-t0)

        if error_box:
            log.debug("[PhasedResearch Phase %d] error: %s", phase, error_box[0])
            pr = PhaseResult(phase=phase, topic=topic, error=error_box[0])
            pr.duration_s = time.monotonic() - t0
            return pr

        if result_box:
            result_box[0].duration_s = time.monotonic() - t0
            return result_box[0]

        pr = PhaseResult(phase=phase, topic=topic, error="no result returned")
        pr.duration_s = time.monotonic() - t0
        return pr

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    def _get_internet(self) -> Optional[Any]:
        if self.internet:
            return self.internet
        try:
            from modules.internet_manager import get_internet_manager
            self.internet = get_internet_manager()
        except Exception:
            pass
        return self.internet

    def _get_scrapy(self) -> Optional[Any]:
        if self.scrapy_agent:
            return self.scrapy_agent
        try:
            import niblit_agents  # type: ignore[import]
            if hasattr(niblit_agents, "ScrapyResearchAgent"):
                self.scrapy_agent = niblit_agents.ScrapyResearchAgent()
        except Exception:
            pass
        return self.scrapy_agent

    def _get_serpex(self) -> Optional[Any]:
        if self.serpex_agent:
            return self.serpex_agent
        try:
            import niblit_agents  # type: ignore[import]
            if hasattr(niblit_agents, "SerpexAgent"):
                self.serpex_agent = niblit_agents.SerpexAgent()
        except Exception:
            pass
        return self.serpex_agent

    def _get_serpapi(self) -> Optional[Any]:
        return self.serpapi  # caller must inject if available

    def _get_github_code_search(self) -> Optional[Any]:
        if self.github_code_search:
            return self.github_code_search
        try:
            from modules.github_code_search import GitHubCodeSearch
            self.github_code_search = GitHubCodeSearch()
        except Exception:
            pass
        return self.github_code_search

    def _get_hybrid_manager(self) -> Optional[Any]:
        """Get the Qdrant HybridManager if available."""
        try:
            from modules.hybrid_qdrant_manager import get_hybrid_manager
            return get_hybrid_manager()
        except Exception:
            return None

    def _get_language_module(self) -> Optional[Any]:
        if self._lm:
            return self._lm
        try:
            from modules.language_module import get_language_module
            self._lm = get_language_module()
        except Exception:
            pass
        return self._lm

    # ------------------------------------------------------------------
    # Text-extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_snippets(raw: Any) -> List[str]:
        """Convert a raw search result into a list of clean text strings."""
        if not raw:
            return []
        if isinstance(raw, str):
            if len(raw.strip()) >= 30:
                return [raw.strip()[:500]]
            return []
        if isinstance(raw, dict):
            text = (
                raw.get("snippet") or raw.get("text") or raw.get("content")
                or raw.get("summary") or raw.get("description") or ""
            )
            return PhasedResearchEngine._extract_snippets(text)
        if isinstance(raw, list):
            results = []
            for item in raw:
                results.extend(PhasedResearchEngine._extract_snippets(item))
            return results
        return [str(raw).strip()[:500]] if str(raw).strip() else []

    @staticmethod
    def _item_to_text(item: Any) -> Optional[str]:
        """Extract a single best text string from a search result item."""
        if not item:
            return None
        if isinstance(item, str):
            stripped = item.strip()
            return stripped[:500] if len(stripped) >= 30 else None
        if isinstance(item, dict):
            for key in ("snippet", "text", "content", "summary",
                        "description", "code", "body"):
                val = item.get(key, "")
                if isinstance(val, str) and len(val.strip()) >= 30:
                    return val.strip()[:500]
        return None


# ---------------------------------------------------------------------------
# Public helper — topic classification
# ---------------------------------------------------------------------------

def _is_code_topic(topic: str) -> bool:
    """Return True when *topic* is code/software-related."""
    t = topic.lower()
    # Check direct keyword membership
    if t in _CODE_KEYWORDS:
        return True
    # Check if any code keyword appears as a word in the topic
    words = set(re.sub(r"[^\w\s]", " ", t).split())
    return bool(words & _CODE_KEYWORDS)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[PhasedResearchEngine] = None
_singleton_lock = threading.Lock()


def get_phased_research_engine(
    knowledge_db: Any = None,
    graph_rag_bridge: Any = None,
    language_module: Any = None,
    internet: Any = None,
    scrapy_agent: Any = None,
    serpex_agent: Any = None,
    github_code_search: Any = None,
    serpapi: Any = None,
) -> PhasedResearchEngine:
    """Return (and lazily create) the process-wide PhasedResearchEngine singleton."""
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = PhasedResearchEngine(
                    knowledge_db=knowledge_db,
                    graph_rag_bridge=graph_rag_bridge,
                    language_module=language_module,
                    internet=internet,
                    scrapy_agent=scrapy_agent,
                    serpex_agent=serpex_agent,
                    github_code_search=github_code_search,
                    serpapi=serpapi,
                )
                log.debug("[PhasedResearch] Singleton created")
    else:
        # Late-bind provided dependencies if the instance has None
        with _singleton_lock:
            if knowledge_db is not None and _instance.knowledge_db is None:
                _instance.knowledge_db = knowledge_db
            if graph_rag_bridge is not None and _instance._grb is None:
                _instance._grb = graph_rag_bridge
            if language_module is not None and _instance._lm is None:
                _instance._lm = language_module
            if internet is not None and _instance.internet is None:
                _instance.internet = internet
            if serpex_agent is not None and _instance.serpex_agent is None:
                _instance.serpex_agent = serpex_agent
            if github_code_search is not None and _instance.github_code_search is None:
                _instance.github_code_search = github_code_search
    return _instance


if __name__ == "__main__":
    print("phased_research_engine OK")
    print("is_code_topic('docker containerization'):", _is_code_topic("docker containerization"))
    print("is_code_topic('firmware embedded'):", _is_code_topic("firmware embedded"))
    print("is_code_topic('photosynthesis'):", _is_code_topic("photosynthesis"))
    print("is_code_topic('python sorting algorithm'):", _is_code_topic("python sorting algorithm"))
