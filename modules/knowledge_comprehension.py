#!/usr/bin/env python3
"""modules/knowledge_comprehension.py — Knowledge Comprehension Layer for Niblit.

This module is the "understanding bridge" that transforms raw research snippets
into durable, structured knowledge Niblit can actually *use*:

  Raw snippets  →  ConceptExtractor  →  scored concepts
  Concepts      →  SelfQuestionGen   →  self-questions
  Self-questions →  SelfTeacher queue →  spaced review
  Best concepts →  topic ledger      →  recall answers it

Design
------
* **Pure stdlib** — no spaCy, no NLTK, no new pip dependencies.  Uses regex
  and simple frequency analysis to extract candidate concepts.
* **Purely additive** — slots in *between* existing modules; nothing is removed
  or rewritten.
* **Complementary loop:**
  1. ALE research step collects raw snippets.
  2. Reflection step stores them as ``ale_learned`` facts.
  3. **Comprehension step** (new) extracts concepts from those snippets and:
     a. Writes/updates the ``topic_knowledge:<topic>`` ledger so ``recall``
        always returns useful content.
     b. Schedules the top concepts as self-questions in SelfTeacher's spaced-
        repetition review queue, so the *next* idle cycle reviews them.
  4. Metacognition step uses the enriched ledger to raise the topic's
     confidence score from "uncertain" to "medium" or "high".

Integration points
------------------
* Called from ALE ``_autonomous_reflection`` after the ledger is written,
  so comprehension always has fresh data.
* Called from ``SelfTeacher.teach()`` so user-triggered study also runs the
  comprehension pass.
* Singleton: ``get_knowledge_comprehension()`` returns a shared instance.
"""

from __future__ import annotations

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

    All parameters are optional — the module degrades gracefully when
    subsystems are unavailable.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        self_teacher: Optional[Any] = None,
        llm: Optional[Any] = None,
    ):
        self.knowledge_db = knowledge_db
        self.self_teacher = self_teacher
        self.llm = llm

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
            if fallback_text and not fallback_text.lower().startswith("no data found"):
                self._write_ledger(topic, fallback_text, concepts=[], ts=ts)
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

        n_concepts = len(concepts)
        n_questions = sum(len(qs) for _, qs in all_questions)
        log.info(
            "✅ [Comprehension] %r — %d concept(s), %d question(s), %d scheduled",
            topic, n_concepts, n_questions, scheduled,
        )
        return (
            f"Comprehension({topic!r}): "
            f"{n_concepts} concept(s), {n_questions} question(s), "
            f"{scheduled} review(s) scheduled"
        )

    def _write_ledger(
        self,
        topic: str,
        text: str,
        concepts: List[Dict[str, Any]],
        ts: int,
    ) -> None:
        """Write / overwrite the ``topic_knowledge:<topic>`` ledger entry."""
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
) -> KnowledgeComprehension:
    """Return the global :class:`KnowledgeComprehension` singleton.

    Lazily creates on first call.  Subsequent calls update missing fields
    (``knowledge_db``, ``self_teacher``, ``llm``) if they were unavailable
    at construction time — this lets the module be imported early and
    fully wired up later.
    """
    global _comprehension_singleton
    if _comprehension_singleton is None:
        _comprehension_singleton = KnowledgeComprehension(
            knowledge_db=knowledge_db,
            self_teacher=self_teacher,
            llm=llm,
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
    return _comprehension_singleton
