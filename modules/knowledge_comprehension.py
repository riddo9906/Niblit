#!/usr/bin/env python3
"""modules/knowledge_comprehension.py — Knowledge Comprehension Layer for Niblit.

This module is the "understanding bridge" that transforms raw research snippets
into durable, structured knowledge Niblit can actually *use*:

  Raw snippets  →  ConceptExtractor  →  scored concepts
  Concepts      →  SelfQuestionGen   →  self-questions
  Self-questions →  SelfTeacher queue →  spaced review
  Best concepts →  topic ledger      →  recall answers it

SECA — Self-Evolving Cognitive Architecture (Upgrade 3)
-------------------------------------------------------
Three additional components are wired in when available:

* **MemoryGraph** (``modules/memory_graph.py``) — Active Retrieval Graph.
  Every snippet is embedded and added as a graph node.  Edges are drawn
  automatically between semantically similar nodes.  Query-time retrieval
  does multi-hop graph expansion + weighted re-ranking instead of flat
  FAISS top-k.

* **RewardModel** (``modules/reward_model.py``) — Self-Critique layer.
  Scores generated answers against source snippets.  Feeds quality
  deltas back to MemoryGraph node scores so well-supported nodes rise
  and unsupported ones sink over time.

* **ConceptSynthesizer** (``modules/concept_synthesizer.py``) — Memory
  Compression.  Periodically clusters raw snippet nodes into compact
  meta-nodes (abstractions), reducing graph size and improving retrieval
  speed at scale.

Design
------
* **Purely additive** — slots in *between* existing modules; nothing is removed
  or rewritten.
* All SECA components are optional — module degrades gracefully when
  unavailable (no sentence-transformers, no numpy, etc.).
* Pure stdlib for concept extraction; SECA components use numpy/faiss/sklearn
  when available.
* Singleton: ``get_knowledge_comprehension()`` returns a shared instance.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("KnowledgeComprehension")

# ─────────────────────────────────────────────────────────────────────────────
# Tuning constants
# ─────────────────────────────────────────────────────────────────────────────

# Minimum number of times a phrase must appear across all snippets combined
# before it is considered a concept worth tracking.
_MIN_PHRASE_FREQ: int = 2

# Minimum number of distinct snippets a phrase must appear in.
_MIN_SNIPPET_COUNT: int = 1

# Maximum number of concepts to surface per topic per cycle (keeps KB lean).
_MAX_CONCEPTS: int = 5

# Maximum number of self-questions generated per concept.
_MAX_QUESTIONS_PER_CONCEPT: int = 3

# Maximum characters written to the ``topic_knowledge`` ledger entry.
_MAX_LEDGER_LEN: int = 600

# Maximum snippet length used for concept extraction (longer slows the regex).
_MAX_SNIPPET_CHARS: int = 600

# Scheduling limits — how many concepts/questions go into the SelfTeacher
# spaced-repetition queue per cycle.  Intentionally smaller than _MAX_CONCEPTS
# and _MAX_QUESTIONS_PER_CONCEPT to keep the queue from growing too fast.
_SCHEDULER_MAX_CONCEPTS: int = 3
_SCHEDULER_MAX_QUESTIONS: int = 2

# ─────────────────────────────────────────────────────────────────────────────
# Noise words — excluded from concept candidates
# ─────────────────────────────────────────────────────────────────────────────

_STOP_WORDS: frozenset = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "with",
    "and", "or", "but", "not", "be", "is", "are", "was", "were", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "shall", "that", "this", "these",
    "those", "it", "its", "as", "by", "if", "then", "so", "than", "about",
    "into", "through", "after", "before", "between", "such", "each",
    "also", "which", "when", "where", "how", "what", "who", "why",
    "there", "their", "they", "we", "you", "your", "our", "more", "some",
    "any", "all", "both", "other", "most", "very", "just", "only",
    "no", "data", "found", "use", "used", "using", "based", "new",
    "like", "make", "makes", "made", "get", "gets", "got", "go", "going",
})

# Shared prefix used to detect "No data found" placeholder snippets throughout
# this module.  Matches the check in niblit_memory/_is_no_data_placeholder().
_NO_DATA_PREFIX: str = "no data found"

# ─────────────────────────────────────────────────────────────────────────────
# Concept extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

# Splits text into tokens: sequences of letters and hyphens.
_TOKEN_RE = re.compile(r"[A-Za-z][a-z\-]*[a-z]|[A-Za-z]{1,2}")

# Technical terms: CamelCase identifiers, ALL_CAPS_ACRONYMS, hyphenated-terms
_TECH_TERM_RE = re.compile(
    r"\b([A-Z][a-z]+[A-Z][A-Za-z]+|[A-Z]{2,8}|[a-z]+-[a-z]+(?:-[a-z]+)*)\b"
)


def _extract_candidates(text: str) -> List[str]:
    """Return a flat list of candidate concept n-grams from *text*.

    Generates unigrams, bigrams, and trigrams from content tokens (stop words
    filtered).  Technical identifiers (CamelCase, acronyms, hyphenated) are
    added as unigrams.  Using explicit n-grams avoids greedy regex span
    collisions so "virtual environments" is counted the same way whether it
    appears as "virtual environments to isolate" or "virtual environments keeps
    project" in different snippets.
    """
    candidates: List[str] = []
    truncated = text[:_MAX_SNIPPET_CHARS]

    # Tokenise: extract all lowercase word tokens (min 3 chars)
    tokens = [
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(truncated)
        if len(m.group(0)) >= 3
    ]

    # Build content-word token list (stop words removed for n-gram building)
    content_tokens = [t for t in tokens if t not in _STOP_WORDS]

    # Unigrams
    for tok in content_tokens:
        if len(tok) >= 4:
            candidates.append(tok)

    # Bigrams and trigrams from consecutive content tokens
    for n in (2, 3):
        for i in range(len(content_tokens) - n + 1):
            phrase = " ".join(content_tokens[i:i + n])
            candidates.append(phrase)

    # Technical identifiers (CamelCase, ALL_CAPS, hyphenated) as unigrams
    for m in _TECH_TERM_RE.finditer(truncated):
        term = m.group(1).lower()
        if len(term) >= 3:
            candidates.append(term)

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# ConceptExtractor
# ─────────────────────────────────────────────────────────────────────────────

class ConceptExtractor:
    """Extract frequency-ranked concepts from a list of research snippets.

    No external dependencies — pure Python stdlib.

    Usage::

        extractor = ConceptExtractor()
        concepts = extractor.extract(["Python uses indentation…", "PEP 8 defines…"])
        # → [Concept("indentation", freq=3, docs=2), Concept("pep 8", freq=2, docs=1), …]
    """

    def extract(
        self,
        snippets: List[str],
        min_freq: int = _MIN_PHRASE_FREQ,
        min_docs: int = _MIN_SNIPPET_COUNT,
        max_concepts: int = _MAX_CONCEPTS,
    ) -> List[Dict[str, Any]]:
        """Return the top-*max_concepts* concepts found across *snippets*.

        Each concept is a dict::

            {
                "phrase": str,   # the concept phrase (lowercase)
                "freq":   int,   # total occurrences across all snippets
                "docs":   int,   # number of distinct snippets containing it
            }

        Concepts are ranked by ``docs`` (doc-frequency) first, then ``freq``.
        """
        if not snippets:
            return []

        phrase_freq: Counter = Counter()
        phrase_docs: Counter = Counter()

        for snippet in snippets:
            text = str(snippet)[:_MAX_SNIPPET_CHARS]
            candidates = _extract_candidates(text)
            # Per-snippet unique set for doc-frequency
            seen_in_doc: set = set()
            for phrase in candidates:
                phrase_freq[phrase] += 1
                if phrase not in seen_in_doc:
                    phrase_docs[phrase] += 1
                    seen_in_doc.add(phrase)

        # Filter by thresholds
        results = [
            {"phrase": p, "freq": phrase_freq[p], "docs": phrase_docs[p]}
            for p in phrase_freq
            if phrase_freq[p] >= min_freq and phrase_docs[p] >= min_docs
        ]

        # Rank: doc-frequency first, then total frequency, then alphabetical
        results.sort(key=lambda c: (-c["docs"], -c["freq"], c["phrase"]))

        return results[:max_concepts]


# ─────────────────────────────────────────────────────────────────────────────
# SelfQuestionGenerator
# ─────────────────────────────────────────────────────────────────────────────

# Question templates ordered from most fundamental to most applied.
_QUESTION_TEMPLATES: List[str] = [
    "What is {concept}?",
    "Why does {concept} matter?",
    "How is {concept} used in practice?",
    "What are examples of {concept}?",
    "What are the key principles of {concept}?",
    "How does {concept} relate to {topic}?",
    "What are common mistakes with {concept}?",
]


class SelfQuestionGenerator:
    """Generate self-study questions for a given concept.

    Questions are concrete templates instantiated with the concept phrase and
    the parent research topic.  No LLM is required — falls back gracefully.
    When an LLM *is* available it can be used to produce a richer set.
    """

    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm

    def generate(
        self,
        concept: str,
        topic: str,
        max_questions: int = _MAX_QUESTIONS_PER_CONCEPT,
    ) -> List[str]:
        """Return up to *max_questions* self-study questions for *concept*.

        Parameters
        ----------
        concept:   The extracted concept phrase (e.g. "virtual environments").
        topic:     The parent research topic (e.g. "python best practices").
        """
        if not concept:
            return []

        questions: List[str] = []

        # Try LLM-generated questions first (richer, context-aware)
        if self.llm and hasattr(self.llm, "query_llm"):
            try:
                prompt = (
                    f"Generate {max_questions} concise study questions about "
                    f"'{concept}' in the context of '{topic}'. "
                    f"Output one question per line, no numbering, no explanations."
                )
                msgs = [{"role": "user", "content": prompt}]
                raw = self.llm.query_llm(msgs, max_tokens=150)
                if raw:
                    for line in str(raw).strip().splitlines():
                        q = line.strip().lstrip("-•1234567890. ")
                        if q.endswith("?") and len(q) > 10:
                            questions.append(q)
                        if len(questions) >= max_questions:
                            break
            except Exception as exc:
                log.debug("[SelfQuestionGen] LLM question generation failed: %s", exc)

        # Fallback / supplement with template questions
        if len(questions) < max_questions:
            for template in _QUESTION_TEMPLATES:
                if len(questions) >= max_questions:
                    break
                q = template.format(concept=concept, topic=topic)
                if q not in questions:
                    questions.append(q)

        return questions[:max_questions]


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeComprehension — orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeComprehension:
    """Orchestrates concept extraction → question generation → ledger update.

    This is the "understanding bridge" that makes raw stored snippets
    actionable.  It runs after each ALE research + reflection pass to:

    1. Extract the most frequent concepts from the raw snippets.
    2. Generate self-questions for each concept.
    3. Schedule those questions in SelfTeacher's spaced-repetition queue.
    4. Write/update the ``topic_knowledge:<topic>`` ledger with a clean
       concept summary so that future ``recall`` queries return useful content.

    SECA components (optional, injected at construction or later):
    * ``memory_graph``       — Active Retrieval Graph for multi-hop retrieval.
    * ``reward_model``       — Self-Critique quality scorer.
    * ``concept_synthesizer`` — Memory compression / abstraction layer.

    All parameters are optional — the module degrades gracefully when
    subsystems are unavailable.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        self_teacher: Optional[Any] = None,
        llm: Optional[Any] = None,
        memory_graph: Optional[Any] = None,
        reward_model: Optional[Any] = None,
        concept_synthesizer: Optional[Any] = None,
    ):
        self.knowledge_db = knowledge_db
        self.self_teacher = self_teacher
        self.llm = llm

        # SECA components
        self.memory_graph = memory_graph
        self.reward_model = reward_model
        self.concept_synthesizer = concept_synthesizer

        self._extractor = ConceptExtractor()
        self._question_gen = SelfQuestionGenerator(llm=llm)

    # ── Public API ────────────────────────────────────────────────────────────

    def process(
        self,
        topic: str,
        snippets: List[str],
        min_freq: int = _MIN_PHRASE_FREQ,
        min_docs: int = _MIN_SNIPPET_COUNT,
    ) -> str:
        """Run the full comprehension pipeline for *topic*.

        Parameters
        ----------
        topic:    The research topic (e.g. "python best practices").
        snippets: Raw research snippet strings collected this cycle.

        Returns
        -------
        A short human-readable summary of what was comprehended, suitable
        for the ALE cycle log.  Never raises.
        """
        if not topic or not snippets:
            return "[Comprehension skipped — no topic or snippets]"

        try:
            return self._process_safe(topic, snippets, min_freq, min_docs)
        except Exception as exc:
            log.debug("[Comprehension] process() error: %s", exc)
            return f"[Comprehension error: {exc}]"

    def search_graph(
        self,
        query: str,
        top_k: int = 5,
        depth: int = 2,
    ) -> List[Dict[str, Any]]:
        """Multi-hop graph search for *query* using the Active Retrieval Graph.

        Falls back to an empty list when the MemoryGraph or embedding model is
        unavailable.  Results are ``{"id", "text", "score", "hops"}`` dicts.
        """
        if self.memory_graph is None:
            return []
        try:
            query_embedding = self._embed_text(query)
            return self.memory_graph.search(
                query_embedding=query_embedding,
                top_k=top_k,
                depth=depth,
            )
        except Exception as exc:
            log.debug("[Comprehension] search_graph() error: %s", exc)
            return []

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _process_safe(
        self,
        topic: str,
        snippets: List[str],
        min_freq: int,
        min_docs: int,
    ) -> str:
        ts = int(time.time())

        # 1. Extract concepts
        concepts = self._extractor.extract(
            snippets, min_freq=min_freq, min_docs=min_docs
        )

        if not concepts:
            # Still write a minimal ledger from the first snippet so recall
            # returns something rather than nothing.
            fallback_text = str(snippets[0])[:_MAX_LEDGER_LEN].strip()
            if fallback_text and not fallback_text.lower().startswith(_NO_DATA_PREFIX):
                self._write_ledger(topic, fallback_text, concepts=[], ts=ts)
                # SECA: embed the fallback snippet into the graph even when no
                # repeated concepts were found.
                self._embed_snippets_to_graph(topic, [fallback_text], ts)
                return (
                    f"Comprehension({topic!r}): no repeated concepts — "
                    f"wrote raw-snippet ledger"
                )
            return f"Comprehension({topic!r}): no concepts extracted, snippets too sparse"

        # 2. Generate self-questions for top concepts
        all_questions: List[Tuple[str, List[str]]] = []
        for c in concepts[:_MAX_CONCEPTS]:
            phrase = c["phrase"]
            questions = self._question_gen.generate(
                concept=phrase, topic=topic
            )
            if questions:
                all_questions.append((phrase, questions))

        # 3. Schedule questions in SelfTeacher's review queue
        scheduled = self._schedule_questions(topic, all_questions, ts)

        # 4. Build a human-readable concept summary for the ledger
        concept_lines = [
            f"• {c['phrase']} (mentioned {c['freq']}× across {c['docs']} snippet(s))"
            for c in concepts
        ]
        ledger_body = (
            f"Key concepts in '{topic}':\n"
            + "\n".join(concept_lines)
        )
        if all_questions:
            first_q_block = all_questions[0][1][0] if all_questions[0][1] else ""
            if first_q_block:
                ledger_body += f"\n\nSelf-study question: {first_q_block}"

        self._write_ledger(topic, ledger_body[:_MAX_LEDGER_LEN], concepts=concepts, ts=ts)

        # 5. Persist concepts as individual KB facts so Metacognition can score them
        self._store_concept_facts(topic, concepts, ts)

        # 6. SECA — embed snippets into the Active Retrieval Graph
        n_embedded = self._embed_snippets_to_graph(topic, snippets, ts)

        # 7. SECA — trigger memory compression when graph has grown enough
        self._maybe_compress()

        # 8. Surface potential contradictions (non-blocking, best-effort)
        self._detect_and_log_contradictions(topic)

        # 9. Quality feedback — score the comprehension ledger against the source
        # snippets and propagate quality deltas to the underlying KB facts.
        # A high-quality comprehension summary reinforces the facts it was built
        # from; a low-quality one (sparse, incoherent) decays them slightly so
        # the ALE re-researches the topic sooner.
        self._apply_quality_feedback(topic, ledger_body, snippets)

        n_concepts = len(concepts)
        n_questions = sum(len(qs) for _, qs in all_questions)
        graph_suffix = f", {n_embedded} embedded" if n_embedded else ""
        log.info(
            "✅ [Comprehension] %r — %d concept(s), %d question(s), %d scheduled%s",
            topic, n_concepts, n_questions, scheduled, graph_suffix,
        )
        return (
            f"Comprehension({topic!r}): "
            f"{n_concepts} concept(s), {n_questions} question(s), "
            f"{scheduled} review(s) scheduled{graph_suffix}"
        )

    def _apply_quality_feedback(
        self,
        topic: str,
        ledger_body: str,
        snippets: List[str],
    ) -> None:
        """Score the comprehension summary and propagate quality to KB facts.

        Uses :mod:`modules.quality_feedback` to reinforce well-supported facts
        or schedule re-research for sparse ones.
        """
        if not self.knowledge_db:
            return
        try:
            from modules.quality_feedback import get_quality_feedback
            qf = get_quality_feedback(reward_model=self.reward_model)
            qf.record_answer_quality(
                query=topic,
                answer=ledger_body,
                knowledge_db=self.knowledge_db,
                snippets=snippets[:5],  # use first 5 as context window
            )
        except Exception as exc:
            log.debug("[Comprehension] quality feedback skipped: %s", exc)

    # ── SECA helpers ──────────────────────────────────────────────────────────

    def _embed_text(self, text: str) -> Optional[List[float]]:
        """Embed *text* using the existing VectorStore embedding service.

        Returns a list[float] embedding or None when the embedding model is
        unavailable.  Uses the module-level singleton from vector_store.py so
        no second model copy is loaded.
        """
        try:
            from modules.vector_store import load_sentence_transformer
            model = load_sentence_transformer()
            if model is None:
                return None
            result = model.encode(text, normalize_embeddings=True)
            if hasattr(result, "tolist"):
                return result.tolist()
            return list(result)
        except Exception as exc:
            log.debug("[Comprehension] _embed_text error: %s", exc)
            return None

    def _embed_snippets_to_graph(
        self,
        topic: str,
        snippets: List[str],
        ts: int,
    ) -> int:
        """Embed each snippet and add it as a node in the Active Retrieval Graph.

        Returns the number of nodes successfully added.  No-op when
        ``self.memory_graph`` is None.
        """
        if self.memory_graph is None:
            return 0
        added = 0
        for i, snippet in enumerate(snippets):
            if not snippet or snippet.lower().startswith(_NO_DATA_PREFIX):
                continue
            try:
                text = snippet[:_MAX_SNIPPET_CHARS]
                # Stable node ID: hash of topic + snippet truncated
                raw_id = f"{topic}:{ts}:{i}:{text[:64]}"
                node_id = "snip:" + hashlib.md5(raw_id.encode()).hexdigest()[:16]
                embedding = self._embed_text(text)
                self.memory_graph.add(node_id=node_id, text=text, embedding=embedding)
                added += 1
            except Exception as exc:
                log.debug("[Comprehension] graph add error (snippet %d): %s", i, exc)
        return added

    def _maybe_compress(self) -> None:
        """Trigger ConceptSynthesizer when enough new graph nodes have accumulated."""
        if self.concept_synthesizer is None or self.memory_graph is None:
            return
        try:
            n_created = self.concept_synthesizer.maybe_synthesize(
                graph=self.memory_graph,
                knowledge_db=self.knowledge_db,
            )
            if n_created:
                log.debug(
                    "[Comprehension] ConceptSynthesizer created %d meta-node(s)",
                    n_created,
                )
        except Exception as exc:
            log.debug("[Comprehension] _maybe_compress error: %s", exc)

    def _write_ledger(
        self,
        topic: str,
        text: str,
        concepts: List[Dict[str, Any]],
        ts: int,
    ) -> None:
        """Write / overwrite the ``topic_knowledge:<topic>`` ledger entry.

        After writing, reinforces any existing facts about this topic so their
        confidence rises (they have been re-confirmed by this research cycle).
        """
        if not self.knowledge_db:
            return
        try:
            topic_tag = topic.split()[0].lower() if topic.split() else "general"
            self.knowledge_db.add_fact(
                f"topic_knowledge:{topic}",
                text,
                tags=["knowledge", "ledger", "comprehension", "autonomous", topic_tag],
            )
            log.debug("[Comprehension] ledger written for %r (%d chars)", topic, len(text))
        except Exception as exc:
            log.debug("[Comprehension] ledger write failed: %s", exc)

        # Reinforce any pre-existing facts about this topic
        self._reinforce_related(topic)

    def _reinforce_related(self, topic: str) -> None:
        """Boost confidence of facts already stored about *topic*.

        When a new research cycle confirms knowledge about a topic, previously
        stored facts about the same subject gain confidence — mirroring how
        repeated exposure strengthens memory in cognitive models.
        """
        if not self.knowledge_db or not hasattr(self.knowledge_db, "reinforce"):
            return
        try:
            # Retrieve related facts via smart recall (falls back to keyword)
            if hasattr(self.knowledge_db, "smart_recall"):
                related = self.knowledge_db.smart_recall(topic, limit=10)
            else:
                related = self.knowledge_db.recall(topic, limit=10)
            for fact in related:
                if isinstance(fact, dict) and fact.get("key"):
                    self.knowledge_db.reinforce(fact["key"], amount=0.05)
        except Exception as exc:
            log.debug("[Comprehension] _reinforce_related error: %s", exc)

    def _detect_and_log_contradictions(self, topic: str) -> None:
        """Surface potential contradictions after learning and log them.

        When two facts about the same topic conflict, a warning is written to
        the KB so Niblit's metacognition layer can schedule re-verification.
        Does nothing when SmartRecall is unavailable.
        """
        if not self.knowledge_db:
            return
        try:
            from modules.knowledge_recall import SmartRecall
            sr = SmartRecall(self.knowledge_db)
            conflicts = sr.find_contradictions(topic, max_pairs=3)
            if not conflicts:
                return
            for fa, fb, score in conflicts:
                ka = str(fa.get("key", ""))[:60]
                kb_ = str(fb.get("key", ""))[:60]
                log.info(
                    "[Comprehension] Potential contradiction (score=%.2f): "
                    "'%s' ↔ '%s'",
                    score, ka, kb_,
                )
                # Store a flag so metacognition can act on it
                self.knowledge_db.add_fact(
                    f"contradiction_flag:{topic}:{int(time.time())}",
                    {
                        "topic": topic,
                        "fact_a_key": ka,
                        "fact_b_key": kb_,
                        "conflict_score": score,
                        "step": "comprehension",
                    },
                    tags=["contradiction", "comprehension", "metacognition"],
                )
        except Exception as exc:
            log.debug("[Comprehension] _detect_and_log_contradictions error: %s", exc)

    def _store_concept_facts(
        self,
        topic: str,
        concepts: List[Dict[str, Any]],
        ts: int,
    ) -> None:
        """Store individual concept dicts for Metacognition / confidence scoring."""
        if not self.knowledge_db or not concepts:
            return
        try:
            topic_tag = topic.split()[0].lower() if topic.split() else "general"
            self.knowledge_db.add_fact(
                f"ale_concepts:{topic.replace(' ', '_')}:{ts}",
                {
                    "topic": topic,
                    "concepts": [
                        {"phrase": c["phrase"], "freq": c["freq"], "docs": c["docs"]}
                        for c in concepts
                    ],
                    "concept_count": len(concepts),
                    "step": "comprehension",
                },
                tags=["concepts", "comprehension", "ale_learned", topic_tag],
            )
        except Exception as exc:
            log.debug("[Comprehension] concept fact store failed: %s", exc)

    def _schedule_questions(
        self,
        topic: str,
        questions_by_concept: List[Tuple[str, List[str]]],
        ts: int,
    ) -> int:
        """Schedule concept questions in SelfTeacher's spaced-repetition queue.

        Returns the number of items successfully scheduled.
        """
        if not self.self_teacher:
            return 0

        scheduled = 0
        for phrase, questions in questions_by_concept[:_SCHEDULER_MAX_CONCEPTS]:
            for q in questions[:_SCHEDULER_MAX_QUESTIONS]:
                try:
                    # Use the question as the "topic" for SelfTeacher so that
                    # when the review comes due, SelfTeacher searches the KB for
                    # an answer (the topic_knowledge ledger will supply one).
                    if hasattr(self.self_teacher, "schedule_for_review"):
                        self.self_teacher.schedule_for_review(q)
                        scheduled += 1
                except Exception as exc:
                    log.debug("[Comprehension] schedule_for_review error: %s", exc)

                # Also store the question in KB for traceability
                if self.knowledge_db:
                    try:
                        topic_tag = topic.split()[0].lower() if topic.split() else "general"
                        self.knowledge_db.add_fact(
                            f"ale_self_question:{topic.replace(' ', '_')}:{ts}_{scheduled}",
                            {
                                "question": q,
                                "concept": phrase,
                                "topic": topic,
                                "step": "comprehension",
                            },
                            tags=["self_question", "comprehension", "ale_learned", topic_tag],
                        )
                    except Exception:
                        pass
        return scheduled


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_comprehension_singleton: Optional[KnowledgeComprehension] = None


def get_knowledge_comprehension(
    knowledge_db: Optional[Any] = None,
    self_teacher: Optional[Any] = None,
    llm: Optional[Any] = None,
    memory_graph: Optional[Any] = None,
    reward_model: Optional[Any] = None,
    concept_synthesizer: Optional[Any] = None,
) -> KnowledgeComprehension:
    """Return the global :class:`KnowledgeComprehension` singleton.

    Lazily creates on first call.  Subsequent calls update missing fields
    (``knowledge_db``, ``self_teacher``, ``llm``, and the three SECA
    components) if they were unavailable at construction time — this lets the
    module be imported early and fully wired up later.

    SECA components are also auto-bootstrapped from their own singletons when
    not explicitly provided, so callers don't need to import them manually.
    """
    global _comprehension_singleton

    # Auto-bootstrap SECA components from their own singletons when not given
    if memory_graph is None:
        try:
            from modules.memory_graph import get_memory_graph
            memory_graph = get_memory_graph()
        except Exception:
            pass
    if reward_model is None:
        try:
            from modules.reward_model import get_reward_model
            reward_model = get_reward_model()
        except Exception:
            pass
    if concept_synthesizer is None:
        try:
            from modules.concept_synthesizer import get_concept_synthesizer
            concept_synthesizer = get_concept_synthesizer()
        except Exception:
            pass

    if _comprehension_singleton is None:
        _comprehension_singleton = KnowledgeComprehension(
            knowledge_db=knowledge_db,
            self_teacher=self_teacher,
            llm=llm,
            memory_graph=memory_graph,
            reward_model=reward_model,
            concept_synthesizer=concept_synthesizer,
        )
    else:
        # Fill in any newly-available dependencies
        if knowledge_db is not None and _comprehension_singleton.knowledge_db is None:
            _comprehension_singleton.knowledge_db = knowledge_db
        if self_teacher is not None and _comprehension_singleton.self_teacher is None:
            _comprehension_singleton.self_teacher = self_teacher
        if llm is not None and _comprehension_singleton.llm is None:
            _comprehension_singleton.llm = llm
            _comprehension_singleton._question_gen.llm = llm
        if memory_graph is not None and _comprehension_singleton.memory_graph is None:
            _comprehension_singleton.memory_graph = memory_graph
        if reward_model is not None and _comprehension_singleton.reward_model is None:
            _comprehension_singleton.reward_model = reward_model
        if concept_synthesizer is not None and _comprehension_singleton.concept_synthesizer is None:
            _comprehension_singleton.concept_synthesizer = concept_synthesizer
    return _comprehension_singleton


if __name__ == "__main__":
    print('Running knowledge_comprehension.py')
