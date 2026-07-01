#!/usr/bin/env python3
"""
niblit_memory/knowledge_logger.py — Knowledge-Centric Logger for Niblit.

KnowledgeLogger is the primary interface for recording *what was learned*
rather than *what happened at runtime*.

Pipeline
--------
1. Collect raw observations (text snippets, research results, document chunks).
2. Deduplicate — remove near-identical observations.
3. Extract key facts — sentences containing factual assertions.
4. Extract concepts — recurring noun phrases and technical terms.
5. Infer relationships — co-occurring concepts in the same sentence.
6. Generate a concise summary — the top factual sentence plus key concepts.
7. Build a KnowledgeRecord.
8. Store it via KnowledgeDB.add_fact (with ``knowledge_record`` tag).
9. Link it into the MemoryGraph (when available).

The raw runtime data is deliberately NOT stored as primary long-term memory.
It can be written to a separate operational log for debugging.

Usage::

    from niblit_memory.knowledge_logger import KnowledgeLogger

    logger = KnowledgeLogger(knowledge_db=my_db)
    record = logger.log(
        topic="Niblit memory graph",
        observations=[
            "The Niblit memory graph persists semantic concepts independently of runtime state.",
            "Immediate persistence prevents concept loss after restart.",
        ],
        source="architecture_session_2024",
        confidence=0.9,
    )
    print(record.human_readable())
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List

from niblit_memory.knowledge_record import KnowledgeRecord, make_knowledge_record

log = logging.getLogger("KnowledgeLogger")

# ── Tuning constants ──────────────────────────────────────────────────────────

# Jaccard similarity threshold above which two observations are considered
# near-duplicates and the second is dropped.
_DEDUP_THRESHOLD: float = 0.70

# Maximum number of key facts to include in a single KnowledgeRecord.
_MAX_KEY_FACTS: int = 10

# Maximum number of concepts to include in a single KnowledgeRecord.
_MAX_CONCEPTS: int = 15

# Maximum length of the generated summary string.
_MAX_SUMMARY_LEN: int = 500

# Minimum observation length (chars) to consider for processing.
_MIN_OBS_LEN: int = 15

# Stop-words excluded from concept extraction.
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
})

# Sentence-ending punctuation pattern.
_SENT_END_RE = re.compile(r"(?<=[.!?])\s+")
# Factual assertion markers (sentences containing these are likely key facts).
_FACT_MARKERS_RE = re.compile(
    r"\b(is|are|was|were|can|will|does|allows|enables|requires|provides|"
    r"supports|prevents|stores|persists|returns|creates|builds|uses|defines)\b",
    re.IGNORECASE,
)
# Technical term pattern: CamelCase, ALL_CAPS, or hyphenated.
_TECH_TERM_RE = re.compile(
    r"\b([A-Z][a-z]+[A-Z][A-Za-z]+|[A-Z]{2,8}|[a-z]+-[a-z]+(?:-[a-z]+)*)\b"
)
# Content word tokeniser.
_TOKEN_RE = re.compile(r"[A-Za-z][a-z\-]*[a-z]|[A-Za-z]{2,2}")


def _jaccard(a: str, b: str) -> float:
    """Return the Jaccard similarity between two texts (word-level)."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _fingerprint(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode()).hexdigest()[:12]


class KnowledgeLogger:
    """
    Transforms raw observations into structured KnowledgeRecords.

    Args:
        knowledge_db:  Optional KnowledgeDB instance.  When provided,
                       ``store_record`` persists the record as a fact.
        memory_graph:  Optional MemoryGraph instance.  When provided,
                       ``store_record`` embeds the summary as a graph node.
    """

    def __init__(
        self,
        knowledge_db: Any | None = None,
        memory_graph: Any | None = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self.memory_graph = memory_graph

    # ── Public API ────────────────────────────────────────────────────────────

    def log(
        self,
        topic: str,
        observations: List[str],
        *,
        source: str = "",
        confidence: float = 0.7,
        tags: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
        store: bool = True,
    ) -> KnowledgeRecord:
        """Create a KnowledgeRecord from *observations* and optionally store it.

        Args:
            topic:        Short topic label.
            observations: Raw text snippets / research results to process.
            source:       Original source identifier (file path, URL, etc.).
            confidence:   Initial confidence level 0.0–1.0.
            tags:         Additional classification tags.
            metadata:     Arbitrary extra data to attach.
            store:        Whether to persist the record (default True).

        Returns:
            The created KnowledgeRecord.
        """
        record = self.create_record(
            topic=topic,
            observations=observations,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
        )
        if store:
            self.store_record(record)
        return record

    def create_record(
        self,
        topic: str,
        observations: List[str],
        *,
        source: str = "",
        confidence: float = 0.7,
        tags: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> KnowledgeRecord:
        """Build a KnowledgeRecord from raw observations without storing it.

        The pipeline is:
        1. Filter and deduplicate observations.
        2. Extract key facts (factual sentences).
        3. Extract concept phrases.
        4. Infer concept relationships.
        5. Generate summary.
        """
        cleaned = self._filter_observations(observations)
        deduped = self._deduplicate(cleaned)

        key_facts = self._extract_key_facts(deduped)
        concepts = self._extract_concepts(deduped)
        relationships = self._infer_relationships(deduped, concepts)
        summary = self._generate_summary(topic, deduped, key_facts, concepts)

        record_tags = list(tags or [])
        if "knowledge_record" not in record_tags:
            record_tags.append("knowledge_record")

        return make_knowledge_record(
            topic=topic,
            summary=summary,
            key_facts=key_facts,
            concepts_learned=concepts,
            relationships=relationships,
            confidence=confidence,
            sources=[source] if source else [],
            tags=record_tags,
            metadata=metadata or {},
            raw_observations=deduped,
        )

    def store_record(self, record: KnowledgeRecord) -> None:
        """Persist *record* to KnowledgeDB and optionally to MemoryGraph.

        The record is stored as a structured fact (not as a raw runtime event).
        """
        if self.knowledge_db is not None and hasattr(self.knowledge_db, "add_fact"):
            key = f"knowledge_record:{record.topic}:{record.id[:8]}"
            self.knowledge_db.add_fact(
                key,
                record.to_dict(),
                tags=record.tags,
            )
            log.debug("[KnowledgeLogger] Stored record: %s", key)

        if self.memory_graph is not None:
            self._link_to_graph(record)

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _filter_observations(self, observations: List[str]) -> List[str]:
        """Remove empty, too-short, or placeholder observations."""
        result: List[str] = []
        no_data_re = re.compile(r"no data found", re.IGNORECASE)
        for obs in observations:
            text = str(obs or "").strip()
            if len(text) < _MIN_OBS_LEN:
                continue
            if no_data_re.search(text):
                continue
            result.append(text)
        return result

    def _deduplicate(self, observations: List[str]) -> List[str]:
        """Remove near-duplicate observations using Jaccard similarity."""
        unique: List[str] = []
        fps: List[str] = []
        for obs in observations:
            fp = _fingerprint(obs)
            if fp in fps:
                continue
            is_dup = any(
                _jaccard(obs, kept) >= _DEDUP_THRESHOLD for kept in unique
            )
            if not is_dup:
                unique.append(obs)
                fps.append(fp)
        return unique

    def _extract_key_facts(self, observations: List[str]) -> List[str]:
        """Extract sentences that contain factual assertions."""
        facts: List[str] = []
        seen: set[str] = set()
        for obs in observations:
            sentences = _SENT_END_RE.split(obs)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) < _MIN_OBS_LEN:
                    continue
                if not _FACT_MARKERS_RE.search(sent):
                    continue
                norm = sent.lower()
                if norm in seen:
                    continue
                seen.add(norm)
                facts.append(sent)
                if len(facts) >= _MAX_KEY_FACTS:
                    return facts
        return facts

    def _extract_concepts(self, observations: List[str]) -> List[str]:
        """Extract recurring concept phrases from observations."""

        phrase_docs: Dict[str, set] = {}

        for idx, obs in enumerate(observations):
            truncated = obs[:600]
            tokens = [
                m.group(0).lower()
                for m in _TOKEN_RE.finditer(truncated)
                if len(m.group(0)) >= 3
            ]
            content = [t for t in tokens if t not in _STOP_WORDS]

            # Unigrams (≥4 chars)
            for tok in content:
                if len(tok) >= 4:
                    phrase_docs.setdefault(tok, set()).add(idx)

            # Bigrams and trigrams
            for n in (2, 3):
                for i in range(len(content) - n + 1):
                    phrase = " ".join(content[i:i + n])
                    phrase_docs.setdefault(phrase, set()).add(idx)

            # Technical terms
            for m in _TECH_TERM_RE.finditer(truncated):
                term = m.group(1).lower()
                if len(term) >= 3:
                    phrase_docs.setdefault(term, set()).add(idx)

        # Rank by document frequency, then phrase length (longer = more specific)
        ranked = sorted(
            phrase_docs.items(),
            key=lambda kv: (len(kv[1]), len(kv[0])),
            reverse=True,
        )
        concepts: List[str] = []
        seen: set[str] = set()
        for phrase, _ in ranked:
            if phrase in seen:
                continue
            # Skip if it's a strict substring of an already included concept
            if any(phrase in kept and phrase != kept for kept in concepts):
                continue
            seen.add(phrase)
            concepts.append(phrase)
            if len(concepts) >= _MAX_CONCEPTS:
                break
        return concepts

    def _infer_relationships(
        self, observations: List[str], concepts: List[str]
    ) -> List[Dict[str, str]]:
        """Infer concept relationships from co-occurrence within sentences."""
        relationships: List[Dict[str, str]] = []
        seen_pairs: set[tuple] = set()
        concept_set = set(concepts[:_MAX_CONCEPTS])

        for obs in observations:
            sentences = _SENT_END_RE.split(obs)
            for sent in sentences:
                lower_sent = sent.lower()
                present = [c for c in concept_set if c in lower_sent]
                if len(present) < 2:
                    continue
                for i in range(len(present)):
                    for j in range(i + 1, len(present)):
                        a, b = present[i], present[j]
                        pair = (min(a, b), max(a, b))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        rel_type = self._classify_relationship(sent, a, b)
                        relationships.append(
                            {"from": a, "to": b, "type": rel_type}
                        )
        return relationships

    @staticmethod
    def _classify_relationship(sentence: str, concept_a: str, concept_b: str) -> str:
        """Classify the relationship type based on verb patterns in the sentence."""
        lower = sentence.lower()
        if re.search(r"\b(enables?|allows?|makes? possible)\b", lower):
            return "enables"
        if re.search(r"\b(requires?|depends? on|needs?)\b", lower):
            return "requires"
        if re.search(r"\b(is a|are a|is an|are an|type of|kind of)\b", lower):
            return "is_a"
        if re.search(r"\b(uses?|utilises?|employs?)\b", lower):
            return "uses"
        if re.search(r"\b(stores?|persists?|saves?|records?)\b", lower):
            return "stores"
        if re.search(r"\b(prevents?|avoids?|stops?)\b", lower):
            return "prevents"
        return "related_to"

    def _generate_summary(
        self,
        topic: str,
        observations: List[str],
        key_facts: List[str],
        concepts: List[str],
    ) -> str:
        """Generate a concise factual summary of the observations."""
        parts: List[str] = []

        # Lead with the best key fact if available
        if key_facts:
            parts.append(key_facts[0])
        elif observations:
            # Fall back to a truncated first observation
            parts.append(observations[0][:_MAX_SUMMARY_LEN])

        # Add top concepts if the summary is short
        if concepts and len(" ".join(parts)) < 200:
            top_concepts = ", ".join(concepts[:5])
            parts.append(f"Key concepts: {top_concepts}.")

        summary = " ".join(parts).strip()
        return summary[:_MAX_SUMMARY_LEN]

    def _link_to_graph(self, record: KnowledgeRecord) -> None:
        """Embed the record summary into the MemoryGraph as a knowledge node."""
        try:
            graph = self.memory_graph
            if graph is None or not hasattr(graph, "add"):
                return
            node_id = f"kr:{record.topic}:{record.id[:8]}"
            graph.add(node_id, record.summary or record.topic)
            log.debug("[KnowledgeLogger] Linked to graph: %s", node_id)
        except Exception as exc:
            log.debug("[KnowledgeLogger] graph link failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_logger_singleton: KnowledgeLogger | None = None
_logger_lock = __import__("threading").Lock()


def get_knowledge_logger(
    knowledge_db: Any | None = None,
    memory_graph: Any | None = None,
) -> KnowledgeLogger:
    """Return the process-wide KnowledgeLogger singleton.

    On first call the singleton is created with the supplied *knowledge_db*
    and *memory_graph*.  Subsequent calls ignore the arguments and return the
    existing instance.
    """
    global _logger_singleton
    with _logger_lock:
        if _logger_singleton is None:
            _logger_singleton = KnowledgeLogger(
                knowledge_db=knowledge_db,
                memory_graph=memory_graph,
            )
    return _logger_singleton


if __name__ == "__main__":
    print("Running niblit_memory/knowledge_logger.py")
