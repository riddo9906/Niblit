#!/usr/bin/env python3
"""
modules/graph_rag.py — Deterministic 3-Tiered Graph-RAG Pipeline for Niblit.

Implements the architecture described in:
  "Beyond Vector Search: Building a Deterministic 3-Tiered Graph-RAG System"
  https://machinelearningmastery.com/beyond-vector-search-building-a-deterministic-3-tiered-graph-rag-system/

Architecture
------------
Three retrieval tiers are queried in parallel.  Results are assembled into an
explicitly-labelled context block.  Conflict resolution is delegated entirely to
the LLM via **prompt-enforced priority rules** — no algorithmic routing needed.

Tier 1 — Absolute Graph Facts (Priority 1, highest)
    A lightweight in-memory QuadStore (SPOC: Subject-Predicate-Object-Context).
    Stores verified, immutable ground truths.  Always wins over lower tiers.

Tier 2 — Background Statistics (Priority 2)
    A second QuadStore for aggregated stats / historical data.  Subject to
    Priority 1 override when there is a direct conflict on the same attribute.

Tier 3 — Vector Documents (Priority 3, fallback)
    Dense semantic search via Niblit's existing VectorStore.  Only consulted
    when the knowledge graphs lack a direct answer.

Entity extraction
-----------------
Entities in the user query are extracted and used as strict quad-store lookups
(subject / object queries).  If ``spacy`` is installed the ``en_core_web_sm``
model is used; otherwise a simple heuristic (capitalised tokens) is applied.

Usage::

    from modules.graph_rag import get_graph_rag_pipeline

    pipeline = get_graph_rag_pipeline()

    # Ingest facts
    pipeline.add_fact("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")
    pipeline.add_stat("LeBron James", "avg_points", "28.9", "NBA_2023_stats")

    # Index a document into Tier 3
    pipeline.add_document("doc1", "LeBron James suffered an ankle injury...")

    # Query all tiers
    result = pipeline.query("Who does LeBron James play for?")
    print(result["system_prompt"])   # structured prompt ready for LLM injection
    print(result["context"])         # plain-text fallback context string

Singleton via ``get_graph_rag_pipeline()``.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("Niblit.GraphRAG")

# ---------------------------------------------------------------------------
# QuadStore — lightweight in-memory SPOC knowledge graph
# ---------------------------------------------------------------------------

Quad = Tuple[str, str, str, str]   # (subject, predicate, object, context)


class QuadStore:
    """Lightweight in-memory quad store for SPOC facts.

    All string values are normalised to their original form; lookups are
    case-insensitive on *subject* and *object* to tolerate capitalisation
    differences in NER output.

    Four indexes give constant-time lookup along any single dimension:
        _by_s   — subject → set of quad indices
        _by_p   — predicate → set of quad indices
        _by_o   — object → set of quad indices
        _by_c   — context → set of quad indices
    """

    def __init__(self) -> None:
        self._quads: List[Quad] = []
        self._by_s: Dict[str, set] = {}
        self._by_p: Dict[str, set] = {}
        self._by_o: Dict[str, set] = {}
        self._by_c: Dict[str, set] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(value: str) -> str:
        return value.strip().lower()

    def _index(self, idx: int, quad: Quad) -> None:
        s_key = self._key(quad[0])
        p_key = self._key(quad[1])
        o_key = self._key(quad[2])
        c_key = self._key(quad[3])
        self._by_s.setdefault(s_key, set()).add(idx)
        self._by_p.setdefault(p_key, set()).add(idx)
        self._by_o.setdefault(o_key, set()).add(idx)
        self._by_c.setdefault(c_key, set()).add(idx)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, subject: str, predicate: str, obj: str, context: str = "") -> None:
        """Add a SPOC quad to the store (duplicates are silently ignored)."""
        quad: Quad = (subject, predicate, obj, context)
        # Dedup check
        s_key = self._key(subject)
        if s_key in self._by_s:
            for i in self._by_s[s_key]:
                if self._quads[i] == quad:
                    return
        idx = len(self._quads)
        self._quads.append(quad)
        self._index(idx, quad)

    def query(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
        context: Optional[str] = None,
    ) -> List[Quad]:
        """Return all quads matching the supplied (non-None) dimensions.

        Passing all ``None`` returns every stored quad (full table scan).
        Each additional constraint is intersected for O(k) lookups where k
        is the size of the smallest matching set.
        """
        # Start with full set of indices
        candidates: Optional[set] = None

        def _narrow(key_map: Dict[str, set], value: Optional[str]) -> Optional[set]:
            if value is None:
                return None
            return key_map.get(self._key(value), set())

        for dimension, key_map in [
            (subject, self._by_s),
            (predicate, self._by_p),
            (obj, self._by_o),
            (context, self._by_c),
        ]:
            subset = _narrow(key_map, dimension)
            if subset is not None:
                candidates = subset if candidates is None else candidates & subset

        if candidates is None:
            # No constraints → return everything
            return list(self._quads)

        return [self._quads[i] for i in sorted(candidates)]

    def query_entity(self, entity: str) -> List[Quad]:
        """Return all quads where *entity* appears as subject OR object."""
        by_s = set(self._by_s.get(self._key(entity), set()))
        by_o = set(self._by_o.get(self._key(entity), set()))
        indices = sorted(by_s | by_o)
        return [self._quads[i] for i in indices]

    def count(self) -> int:
        """Return total number of stored quads."""
        return len(self._quads)

    def all_quads(self) -> List[Quad]:
        """Return a shallow copy of all quads."""
        return list(self._quads)


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _extract_entities_spacy(text: str) -> List[str]:
    """Use spaCy NER to extract named entities (if available)."""
    import spacy  # type: ignore[import-untyped]
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        # Model not downloaded — fall back to heuristic
        raise ImportError("spaCy model en_core_web_sm not found")
    doc = nlp(text)
    return list(dict.fromkeys(ent.text for ent in doc.ents))


def _extract_entities_heuristic(text: str) -> List[str]:
    """Heuristic entity extraction: capitalised word sequences (no spaCy needed)."""
    # Match consecutive Capitalised words (proper nouns) of 1-4 tokens
    pattern = re.compile(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b')
    raw = pattern.findall(text)
    # De-duplicate while preserving order
    seen: set = set()
    entities: List[str] = []
    for e in raw:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            entities.append(e)
    return entities


def extract_entities(text: str) -> List[str]:
    """Extract named entities from *text*.

    Attempts spaCy NER first; falls back to a capitalised-token heuristic when
    spaCy or its English model is unavailable.
    """
    try:
        return _extract_entities_spacy(text)
    except Exception:
        return _extract_entities_heuristic(text)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _format_quads(quads: List[Quad]) -> str:
    """Convert quads to readable declarative sentences."""
    lines: List[str] = []
    for q in quads:
        if len(q) >= 4 and q[3]:
            predicate_readable = str(q[1]).replace("_", " ")
            lines.append(f"In {q[3]}, {q[0]} {predicate_readable} {q[2]}.")
        else:
            lines.append(f"{q[0]} {str(q[1]).replace('_', ' ')} {q[2]}.")
    return "\n".join(lines) if lines else "(none)"


def create_system_prompt(
    facts: List[Quad],
    stats: List[Quad],
    vector_docs: List[str],
) -> str:
    """Build the tiered conflict-resolution system prompt.

    Implements the prompt-enforced fusion rules from the article so the LLM
    always defers to Priority 1 over Priority 2, and only falls back to
    Priority 3 when neither graph has a direct answer.

    Parameters
    ----------
    facts :
        Quads from Tier 1 (absolute ground truths).
    stats :
        Quads from Tier 2 (statistical / background data).
    vector_docs :
        Text snippets from Tier 3 (vector document retrieval).
    """
    formatted_facts = _format_quads(facts)
    formatted_stats = _format_quads(stats)
    retrieved_context = " ".join(vector_docs) if vector_docs else "(none)"

    return f"""You are a strict data-retrieval AI. Your ONLY knowledge comes from the text provided below. \
You must completely ignore your internal training weights when they conflict with the provided data.

PRIORITY RULES (strict):
1. If [PRIORITY 1 - ABSOLUTE GRAPH FACTS] contains a direct answer, use ONLY that answer. \
Do not supplement, qualify, or cross-reference with Priority 2 or Priority 3 data.
2. Priority 2 data is supplementary background. Never treat Priority 2 team abbreviations or \
statistics as authoritative if Priority 1 states a conflicting fact.
3. Only use Priority 2 if Priority 1 has no relevant answer on the specific attribute asked.
4. If Priority 3 (Vector Documents) provides additional relevant information and neither graph tier \
answers the question, use it. If a higher-priority tier answers, Priority 3 may be used to \
supplement with non-conflicting detail.
5. If none of the sections contain the answer, explicitly say "I do not have enough information." \
Do not guess or hallucinate.

Your output MUST follow these rules:
- Provide only the single authoritative answer based on the priority rules above.
- Do not present multiple conflicting answers.
- Make no mention of the priority tier labels as the source of the data.
- Phrase the answer as one or more complete sentences.

---
[PRIORITY 1 - ABSOLUTE GRAPH FACTS]
{formatted_facts}

[PRIORITY 2 - BACKGROUND STATISTICS (team abbreviations here are NOT authoritative — defer to Priority 1 for factual claims)]
{formatted_stats}

[PRIORITY 3 - VECTOR DOCUMENTS]
{retrieved_context}
---
"""


# ---------------------------------------------------------------------------
# GraphRAGPipeline
# ---------------------------------------------------------------------------

class GraphRAGPipeline:
    """Deterministic 3-Tiered Graph-RAG Pipeline.

    Parameters
    ----------
    vector_store :
        A Niblit ``VectorStore`` instance (or ``None`` to skip Tier 3).
    max_tier3_docs : int
        Maximum number of vector documents to include in Tier 3.
    """

    def __init__(
        self,
        vector_store: Optional[Any] = None,
        max_tier3_docs: int = 5,
    ) -> None:
        self._tier1: QuadStore = QuadStore()   # absolute facts
        self._tier2: QuadStore = QuadStore()   # background statistics
        self._vs = vector_store
        self.max_tier3_docs = max_tier3_docs

    # ------------------------------------------------------------------
    # Ingestion API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        context: str = "",
    ) -> None:
        """Add a verified atomic fact to Tier 1 (absolute truth)."""
        self._tier1.add(subject, predicate, obj, context)
        log.debug("[GraphRAG] Tier1 fact added: %s %s %s [%s]", subject, predicate, obj, context)

    def add_stat(
        self,
        subject: str,
        predicate: str,
        obj: str,
        context: str = "",
    ) -> None:
        """Add a background statistic to Tier 2."""
        self._tier2.add(subject, predicate, obj, context)
        log.debug("[GraphRAG] Tier2 stat added: %s %s %s [%s]", subject, predicate, obj, context)

    def add_document(self, doc_id: str, text: str) -> bool:
        """Index *text* into Tier 3 (VectorStore)."""
        vs = self._get_vector_store()
        if vs is None:
            return False
        try:
            return bool(vs.add(doc_id, text))
        except Exception as exc:
            log.debug("[GraphRAG] VectorStore add failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def query(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """Query all three tiers and return structured retrieval results.

        Returns a dict with:
          - ``system_prompt`` (str) — ready-to-inject tiered conflict-resolution prompt
          - ``context``       (str) — plain-text fallback context (for non-LLM use)
          - ``tier1_hits``    (list[Quad]) — Tier 1 quads retrieved
          - ``tier2_hits``    (list[Quad]) — Tier 2 quads retrieved
          - ``tier3_docs``    (list[str])  — Tier 3 document snippets
          - ``entities``      (list[str])  — extracted entities
          - ``retrieval_stats`` (dict)     — per-tier hit counts
        """
        entities = extract_entities(question)
        log.debug("[GraphRAG] query=%r entities=%s", question[:80], entities)

        # ── Tier 1: absolute facts ────────────────────────────────────
        tier1_hits: List[Quad] = []
        for entity in entities:
            tier1_hits.extend(self._tier1.query_entity(entity))
        tier1_hits = list(dict.fromkeys(tier1_hits))  # deduplicate

        # ── Tier 2: background statistics ────────────────────────────
        tier2_hits: List[Quad] = []
        for entity in entities:
            tier2_hits.extend(self._tier2.query_entity(entity))
        tier2_hits = list(dict.fromkeys(tier2_hits))

        # ── Tier 3: dense vector retrieval ───────────────────────────
        tier3_docs: List[str] = []
        vs = self._get_vector_store()
        if vs is not None:
            try:
                hits = vs.search(question, top_k=top_k)
                tier3_docs = [
                    h.get("text", "") for h in hits if h.get("text", "").strip()
                ][: self.max_tier3_docs]
            except Exception as exc:
                log.debug("[GraphRAG] VectorStore search failed: %s", exc)

        # ── Assemble outputs ─────────────────────────────────────────
        system_prompt = create_system_prompt(tier1_hits, tier2_hits, tier3_docs)
        context = self._build_plain_context(tier1_hits, tier2_hits, tier3_docs)

        stats = {
            "tier1": len(tier1_hits),
            "tier2": len(tier2_hits),
            "tier3": len(tier3_docs),
            "entities": len(entities),
        }
        log.debug("[GraphRAG] retrieval_stats=%s", stats)

        return {
            "system_prompt": system_prompt,
            "context": context,
            "tier1_hits": tier1_hits,
            "tier2_hits": tier2_hits,
            "tier3_docs": tier3_docs,
            "entities": entities,
            "retrieval_stats": stats,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return a summary dict suitable for CLI display."""
        return {
            "tier1_count": self._tier1.count(),
            "tier2_count": self._tier2.count(),
            "tier3_available": self._get_vector_store() is not None,
        }

    def status_summary(self) -> str:
        """One-line status string."""
        s = self.status()
        tier3 = "✅" if s["tier3_available"] else "❌"
        return (
            f"Graph-RAG | T1 (facts): {s['tier1_count']} quads | "
            f"T2 (stats): {s['tier2_count']} quads | "
            f"T3 (vectors): {tier3}"
        )

    def get_facts(self) -> List[Quad]:
        """Return all Priority-1 (absolute facts) quads."""
        return self._tier1.all_quads()

    def get_stats(self) -> List[Quad]:
        """Return all Priority-2 (background statistics) quads."""
        return self._tier2.all_quads()

    # ------------------------------------------------------------------

    def _build_plain_context(
        self,
        tier1: List[Quad],
        tier2: List[Quad],
        tier3: List[str],
    ) -> str:
        """Build a plain-text context block as a fallback for non-LLM usage."""
        sections: List[str] = []
        if tier1:
            sections.append("[Graph Facts]\n" + _format_quads(tier1))
        if tier2:
            sections.append("[Background Stats]\n" + _format_quads(tier2))
        if tier3:
            sections.append("[Vector Documents]\n" + " ".join(tier3[:3]))
        return "\n\n".join(sections) + "\n" if sections else ""

    def _get_vector_store(self) -> Optional[Any]:
        if self._vs is not None:
            return self._vs
        try:
            from modules.vector_store import VectorStore
            self._vs = VectorStore()
            return self._vs
        except Exception as exc:
            log.debug("[GraphRAG] VectorStore unavailable: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[GraphRAGPipeline] = None
_lock = threading.Lock()


def get_graph_rag_pipeline(
    vector_store: Optional[Any] = None,
    max_tier3_docs: int = 5,
) -> GraphRAGPipeline:
    """Return the process-wide GraphRAGPipeline singleton.

    The instance is created lazily on the first call.  Subsequent calls return
    the same instance regardless of arguments.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = GraphRAGPipeline(
                    vector_store=vector_store,
                    max_tier3_docs=max_tier3_docs,
                )
                log.debug("[GraphRAG] Singleton created")
    return _instance


if __name__ == "__main__":
    print("Running graph_rag.py")
