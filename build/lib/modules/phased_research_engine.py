#!/usr/bin/env python3
"""
modules/phased_research_engine.py — Sequential 3-phase research for Niblit.

Research happens in three phases, each building on the previous.  A topic is
never thrown at all search backends at once (which causes timeouts); instead
each phase has its own timeout budget and the results of each phase are
structured into the knowledge pipeline before the next phase begins.

Phase 1 — Basic Understanding (DuckDuckGo + Google/Internet, 45 s)
    Fast, lightweight search to build initial topic comprehension.
    Results are stored as structured KB facts (ale_phase1_research:*) and
    pushed to GraphRAGPipeline Tier 2 (background knowledge).

Phase 2 — Deep Knowledge (SerpAPI + Serpex + Qdrant, 45 s)
    Advanced enrichment using richer sources.  Only runs when Phase 1
    found something and when the topic confidence is below the threshold.
    Results are stored as ale_phase2_research:* and pushed to Tier 1.

Phase 3 — Code Generation (GitHub REST API, 30 s)
    Runs ONLY when _is_code_topic() returns True.  Searches GitHub for
    real, idiomatic code examples and stores them as runnable code
    artefacts (ale_code_research:*) — not documentation summaries.

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
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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

    @property
    def success(self) -> bool:
        return bool(self.snippets) and self.error is None

    @property
    def best_snippet(self) -> Optional[str]:
        return self.snippets[0] if self.snippets else None


@dataclass
class PhasedResearchResult:
    """Combined result of all research phases for one topic."""
    topic: str
    phases_run: List[int] = field(default_factory=list)
    phase_results: Dict[int, PhaseResult] = field(default_factory=dict)
    total_facts: int = 0
    total_duration_s: float = 0.0
    is_code_topic: bool = False

    def summary(self) -> str:
        phase_labels = {1: "Basic", 2: "Advanced", 3: "Code"}
        parts = []
        for ph in self.phases_run:
            r = self.phase_results.get(ph)
            if r and r.success:
                parts.append(
                    f"P{ph}({phase_labels.get(ph, ph)}: {len(r.snippets)} snippets, "
                    f"{r.duration_s:.0f}s)"
                )
            else:
                parts.append(f"P{ph}(skipped)")
        return (
            f"[PhasedResearch] {self.topic!r} — "
            + " → ".join(parts)
            + f" | {self.total_facts} facts stored"
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
    ) -> PhasedResearchResult:
        """Research *topic* through up to 3 sequential phases.

        Each phase builds on the previous: Phase 2 only runs if Phase 1
        found something; Phase 3 only runs for code/software topics.

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

        # ── Phase 1: Basic Understanding ──────────────────────────────────
        p1 = self._run_phase_with_timeout(
            phase=1,
            topic=topic,
            fn=self._phase1_basic,
            timeout=self.PHASE1_TIMEOUT,
        )
        result.phases_run.append(1)
        result.phase_results[1] = p1
        if p1.facts_stored:
            result.total_facts += p1.facts_stored

        # ── Phase 2: Deep Knowledge (conditional) ─────────────────────────
        # Only run if Phase 1 found real content and we're not skipping.
        if not skip_phase2:
            p2 = self._run_phase_with_timeout(
                phase=2,
                topic=topic,
                fn=lambda t: self._phase2_advanced(t, p1),
                timeout=self.PHASE2_TIMEOUT,
            )
            result.phases_run.append(2)
            result.phase_results[2] = p2
            if p2.facts_stored:
                result.total_facts += p2.facts_stored
        else:
            log.debug("[PhasedResearch] Phase 2 skipped (skip_phase2=True)")

        # ── Phase 3: Code Generation (code-topic-only, conditional) ───────
        if result.is_code_topic and not skip_phase3:
            p3 = self._run_phase_with_timeout(
                phase=3,
                topic=topic,
                fn=lambda t: self._phase3_code(t, p1, p2 if not skip_phase2 else None),
                timeout=self.PHASE3_TIMEOUT,
            )
            result.phases_run.append(3)
            result.phase_results[3] = p3
            if p3.facts_stored:
                result.total_facts += p3.facts_stored
        else:
            reason = "code-topic=False" if not result.is_code_topic else "skip_phase3=True"
            log.debug("[PhasedResearch] Phase 3 skipped (%s)", reason)

        result.total_duration_s = time.monotonic() - t0
        log.info("✅ %s", result.summary())
        return result

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
        pr.facts_stored = self._store_phase_results(pr, tier="tier2")
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
        pr.facts_stored = self._store_phase_results(pr, tier="tier1")
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
        pr.facts_stored = self._store_phase_results(pr, tier="code")
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
            "tier1", "tier2", or "code" — controls storage target and tags.

        Returns
        -------
        int
            Number of facts stored.
        """
        stored = 0
        lm = self._get_language_module()
        topic = pr.topic
        ts = int(time.time())

        for i, snippet in enumerate(pr.snippets[:self.MAX_SNIPPETS_PER_PHASE]):
            if len(snippet.strip()) < self.MIN_SNIPPET_LEN:
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

            source = pr.sources[i] if i < len(pr.sources) else "unknown"
            key_prefix = {
                "tier1": "ale_phase2_research",
                "tier2": "ale_phase1_research",
                "code": "ale_code_research",
            }.get(tier, "ale_phased_research")

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
                            "phase_label": {1: "basic", 2: "advanced", 3: "code"}[pr.phase],
                        },
                        tags=[
                            "ale_learned",
                            f"phase_{pr.phase}",
                            tier,
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
                                f"phase2_advanced",
                            )
                        elif tier == "code":
                            grp.add_document(
                                f"code:{topic}:{ts}",
                                clean_snippet,
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
    # Timeout wrapper
    # ------------------------------------------------------------------

    def _run_phase_with_timeout(
        self,
        phase: int,
        topic: str,
        fn,
        timeout: float,
    ) -> PhaseResult:
        """Run *fn(topic)* in a daemon thread with a per-phase timeout."""
        import concurrent.futures

        result_box: List[PhaseResult] = []
        error_box: List[str] = []

        def _worker():
            try:
                result_box.append(fn(topic))
            except Exception as e:
                error_box.append(str(e))

        t0 = time.monotonic()
        label = {1: "Basic", 2: "Advanced", 3: "Code"}.get(phase, str(phase))
        log.info("🔍 [PhasedResearch Phase %d/%s] Topic: %r (%.0fs budget)", phase, label, topic, timeout)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_worker)
            try:
                future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                log.warning(
                    "⏱️ [PhasedResearch Phase %d] '%s' timed out after %.0fs — partial results kept",
                    phase, topic, timeout,
                )
                pr = PhaseResult(phase=phase, topic=topic, error=f"timeout after {timeout}s")
                pr.duration_s = time.monotonic() - t0
                return pr
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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
