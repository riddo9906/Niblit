#!/usr/bin/env python3
"""
modules/dynamic_topic_manager.py — Hybrid (intfloat/BM25/ColBERT-style) dynamic topic enrichment.

:class:`DynamicTopicManager` generates fresh, non-redundant research topics by
combining multiple enrichment strategies:

1. **Seed expansion** — start from a curated static seed list.
2. **KB mining** — extract noun-phrase candidates from stored facts (lightweight
   heuristic, no heavyweight NLP required).
3. **Vector-store semantic similarity** — when a VectorStore (Qdrant) is
   available, query related topics using dense embeddings (intfloat/e5 style).
4. **BM25-style keyword deduplication** — terms already in the known-topic
   index are penalised so the output remains novel.
5. **Pluggable enrichment sources** — optional callables that return extra
   topic strings (LLM suggestions, trending API, user feed, etc.).

The class is deliberately dependency-light: all heavy imports (sentence-
transformers, rank-bm25) are optional and caught gracefully.

Typical integration in the orchestrator / NiblitCore::

    from modules.dynamic_topic_manager import DynamicTopicManager
    from modules.topic_constructor import TopicConstructor

    dtm = DynamicTopicManager(
        db=self.db,
        topic_constructor=TopicConstructor(),
        vector_store=self.vector_store,      # optional, Qdrant/FAISS/memory
    )
    new_topics = dtm.propose_new_topics(batch_size=10)
    if hasattr(self.autonomous_engine, "update_research_topics"):
        self.autonomous_engine.update_research_topics(new_topics)
"""

import logging
import random
import re
from typing import Any, Callable, List, Optional, Set

log = logging.getLogger("DynamicTopicManager")

# ── optional: sentence-transformers via vector_store's singleton cache ─────────
# Delegate model loading to vector_store.load_sentence_transformer() so that
# all SentenceTransformer instances share the same singleton cache and their
# noisy console output (LOAD REPORT, tqdm progress) is captured/suppressed.
try:
    from modules.vector_store import load_sentence_transformer, get_embedding_model_cache  # type: ignore[import]
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    load_sentence_transformer = None  # type: ignore[assignment,misc]
    get_embedding_model_cache = None  # type: ignore[assignment,misc]

# ── optional: numpy (for vector similarity) ───────────────────────────────────
try:
    import numpy as _np  # type: ignore[import]
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

# ── Default seed topics ───────────────────────────────────────────────────────
_DEFAULT_SEEDS: List[str] = [
    "autonomous AI systems",
    "neurosymbolic reasoning",
    "differentiable memory",
    "sparse attention transformers",
    "continual lifelong learning",
    "self-repairing systems",
    "multi-agent communication",
    "reinforcement learning from feedback",
    "knowledge graph embedding",
    "causal inference machine learning",
    "federated learning privacy",
    "neural architecture search",
    "semantic code generation",
    "agentic workflow orchestration",
    "hybrid retrieval augmented generation",
]

# ── Noun-phrase candidate extraction ─────────────────────────────────────────
# Very lightweight: grab 2–4 consecutive capitalised or title-cased words,
# or lowercase multi-word phrases after common markers ("about", "on", "for").
_CANDIDATE_RE = re.compile(
    r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})'  # Title-case multi-word
    r'|(?:(?:about|on|for|of|with)\s+[a-z][a-z\s]{4,40})',  # "about xyz …"
    re.UNICODE,
)


def _extract_candidates_from_text(text: str, max_per_text: int = 5) -> List[str]:
    """Return up to *max_per_text* candidate topics from *text*."""
    matches = _CANDIDATE_RE.findall(str(text))
    cleaned: List[str] = []
    for m in matches:
        c = m.strip().lstrip("about on for of with").strip()
        if 4 <= len(c) <= 60:
            cleaned.append(c)
        if len(cleaned) >= max_per_text:
            break
    return cleaned


class DynamicTopicManager:
    """Generate novel, non-redundant research topics using hybrid enrichment.

    Parameters
    ----------
    db:
        Any DB-compatible object with a ``list_facts()`` method (KnowledgeDB,
        LocalDB, FusedMemory).  Used for KB mining and deduplication.
    topic_constructor:
        A :class:`~modules.topic_constructor.TopicConstructor` instance.  Used
        to canonicalise and sanitise raw topic strings before returning them.
        If ``None`` the raw string is used as-is.
    vector_store:
        Optional :class:`~modules.vector_store.VectorStore` instance.  When
        provided, semantic-similarity queries are used to discover related
        topics (intfloat/dense-retrieval style).
    seed_topics:
        Static list of starting topic seeds.  Defaults to
        :data:`_DEFAULT_SEEDS`.
    enrichment_sources:
        List of zero-argument callables that each return a ``str`` or
        ``List[str]`` of additional topic candidates (e.g. an LLM call, a
        trending-API call, a user-supplied feed).
    embedding_model:
        Sentence-transformer model name used for dense topic expansion.
        Ignored when sentence-transformers is not installed.
    qdrant_url / qdrant_api_key:
        Qdrant connection settings.  Passed through to VectorStore if a fresh
        one needs to be constructed.
    """

    def __init__(
        self,
        db: Any = None,
        topic_constructor: Any = None,
        vector_store: Any = None,
        seed_topics: Optional[List[str]] = None,
        enrichment_sources: Optional[List[Callable[[], Any]]] = None,
        embedding_model: str = "intfloat/e5-small-v2",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        self.db = db
        self.topic_constructor = topic_constructor
        self.vector_store = vector_store
        self.seed_topics: List[str] = list(seed_topics or _DEFAULT_SEEDS)
        self.enrichment_sources: List[Callable[[], Any]] = list(enrichment_sources or [])
        self.embedding_model = embedding_model
        self.qdrant_url = qdrant_url
        self.qdrant_api_key = qdrant_api_key
        self._st_model: Any = None  # loaded lazily
        log.info("[DynamicTopicManager] Initialized (seed topics: %d)", len(self.seed_topics))

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_researched_set(self, limit: int = 500) -> Set[str]:
        """Return the set of already-researched topic keys from the DB."""
        if self.db is None:
            return set()
        try:
            facts = self.db.list_facts(limit) or []
            return {str(f.get("key", "")).lower() for f in facts if f.get("key")}
        except Exception as exc:
            log.debug("[DynamicTopicManager] _get_researched_set error: %s", exc)
            return set()

    def _mine_kb_candidates(self, limit: int = 200) -> List[str]:
        """Extract candidate topic phrases from KB fact values."""
        if self.db is None:
            return []
        candidates: List[str] = []
        try:
            facts = self.db.list_facts(limit) or []
            for fact in facts:
                value = str(fact.get("value") or fact.get("content") or "")
                candidates.extend(_extract_candidates_from_text(value, max_per_text=3))
        except Exception as exc:
            log.debug("[DynamicTopicManager] _mine_kb_candidates error: %s", exc)
        return candidates

    def _semantic_expansion(self, seed: str, top_k: int = 3) -> List[str]:
        """Query the vector store for topics semantically related to *seed*.

        This provides ColBERT/dense-retrieval style expansion: the seed is
        embedded and the nearest stored facts are retrieved; their key/topic
        fields become additional candidates.
        """
        if self.vector_store is None:
            return []
        try:
            results = self.vector_store.search(seed, top_k=top_k)
            topics: List[str] = []
            for r in results:
                payload = r.get("payload") or {}
                topic = (
                    payload.get("key")
                    or payload.get("topic")
                    or r.get("id", "")
                )
                if topic and isinstance(topic, str):
                    # Un-slug fact IDs like "fact_neural_net" → "neural net"
                    clean = topic.replace("fact_", "").replace("_", " ").strip()
                    if clean:
                        topics.append(clean)
            return topics
        except Exception as exc:
            log.debug("[DynamicTopicManager] _semantic_expansion error: %s", exc)
            return []

    def _bm25_dedup(self, candidates: List[str], known: Set[str]) -> List[str]:
        """BM25-style deduplication: drop candidates whose tokens are all in
        the known-topic index (high overlap → likely already researched)."""
        deduped: List[str] = []
        for c in candidates:
            tokens = set(c.lower().split())
            # Allow if at least one token is not present in any known topic
            known_tokens: Set[str] = set()
            for k in known:
                known_tokens.update(k.split())
            if not tokens.issubset(known_tokens):
                deduped.append(c)
        return deduped

    def _canonicalise(self, raw: str) -> Optional[str]:
        """Sanitise a raw topic string via TopicConstructor if available."""
        if self.topic_constructor is not None:
            try:
                result = self.topic_constructor.build(raw)
                return result if result else None
            except Exception as exc:
                log.debug("[DynamicTopicManager] topic_constructor.build error: %s", exc)
        # Fallback: simple lowercase strip
        c = raw.strip().lower()
        return c if len(c) >= 3 else None

    def _run_enrichment_sources(self) -> List[str]:
        """Call each pluggable enrichment source and collect candidates."""
        extras: List[str] = []
        for src in self.enrichment_sources:
            try:
                result = src()
                if isinstance(result, str):
                    extras.append(result)
                elif isinstance(result, (list, tuple, set)):
                    extras.extend(str(r) for r in result)
            except Exception as exc:
                log.debug("[DynamicTopicManager] enrichment source error: %s", exc)
        return extras

    # ── Public API ─────────────────────────────────────────────────────────────

    def propose_new_topics(self, batch_size: int = 10) -> List[str]:
        """Return up to *batch_size* novel, canonicalised research topics.

        The pipeline:
        1. Collect candidates from seeds + KB mining + semantic expansion +
           pluggable enrichment sources.
        2. BM25-style deduplication against already-researched topics.
        3. Canonicalise via TopicConstructor.
        4. Shuffle and return up to *batch_size* results.
        """
        known = self._get_researched_set()

        # --- 1. Seed topics
        candidates: List[str] = list(self.seed_topics)

        # --- 2. KB mining (lightweight noun-phrase heuristic)
        candidates.extend(self._mine_kb_candidates())

        # --- 3. Semantic expansion (dense retrieval / intfloat style)
        sample_seeds = random.sample(self.seed_topics, min(3, len(self.seed_topics)))
        for seed in sample_seeds:
            candidates.extend(self._semantic_expansion(seed, top_k=3))

        # --- 4. Pluggable enrichment sources (LLM, trending, etc.)
        candidates.extend(self._run_enrichment_sources())

        # --- 5. BM25-style dedup against known topics
        candidates = self._bm25_dedup(candidates, known)

        # --- 6. Canonicalise + deduplicate final list
        seen: Set[str] = set()
        result: List[str] = []
        random.shuffle(candidates)
        for raw in candidates:
            canonical = self._canonicalise(raw)
            if not canonical:
                continue
            if canonical in seen or canonical in known:
                continue
            seen.add(canonical)
            result.append(canonical)
            if len(result) >= batch_size:
                break

        log.info("[DynamicTopicManager] Proposed %d new topics (from %d candidates)",
                 len(result), len(candidates))
        return result

    def add_seed(self, topic: str) -> None:
        """Append *topic* to the static seed list."""
        if topic and topic not in self.seed_topics:
            self.seed_topics.append(topic)

    def add_enrichment_source(self, fn: Callable[[], Any]) -> None:
        """Register a callable that provides additional topic candidates."""
        self.enrichment_sources.append(fn)


if __name__ == "__main__":
    print('Running dynamic_topic_manager.py')
