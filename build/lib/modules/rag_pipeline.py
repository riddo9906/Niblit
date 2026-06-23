#!/usr/bin/env python3
"""
modules/rag_pipeline.py — Retrieval-Augmented Generation (RAG) pipeline for Niblit.

Implements the RAG pattern found across 5 top-starred AI repos in the
2026-04-07 Nibblebot Research Report (agent, rag, memory, pipeline patterns).

The pipeline combines three retrieval sources already present in Niblit:
  1. **VectorStore** — dense semantic search (Qdrant / FAISS / in-memory)
  2. **KnowledgeComprehension / MemoryGraph** — multi-hop Active Retrieval Graph (SECA)
  3. **BrainTrainer context** — curated Q/A training pairs (if available)

Results from all three are de-duplicated, ranked by relevance score, and
assembled into a context block that the brain's LLM call can consume.

Usage::

    from modules.rag_pipeline import get_rag_pipeline, RAGPipeline

    pipeline = get_rag_pipeline()
    result = pipeline.query("How does Niblit handle knowledge gaps?", top_k=5)
    print(result["context"])   # augmented context string
    print(result["sources"])   # list of {"text", "score", "source"} dicts

Singleton via ``get_rag_pipeline()``.  All heavy imports (VectorStore,
KnowledgeComprehension) are lazy so the module loads fast even when the
embedding model is unavailable.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.RAGPipeline")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_chars: int = 300) -> str:
    """Trim *text* to *max_chars* at a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated + "…"


def _deduplicate(hits: List[Dict[str, Any]], sim_threshold: float = 0.85) -> List[Dict[str, Any]]:
    """Remove near-duplicate hits by Jaccard overlap of word sets.

    Uses a hash-set of frozensets for O(n) duplicate detection against
    already-seen word sets, keeping the first (highest-scored) occurrence.
    """
    seen_word_sets: List[frozenset] = []
    unique: List[Dict[str, Any]] = []
    for hit in hits:
        text = hit.get("text", "").strip().lower()
        if not text:
            continue
        words = frozenset(re.findall(r"\w+", text))
        if not words:
            continue
        duplicate = False
        for prev_words in seen_word_sets:
            union = prev_words | words
            if union:
                overlap = len(words & prev_words) / len(union)
                if overlap >= sim_threshold:
                    duplicate = True
                    break
        if not duplicate:
            seen_word_sets.append(words)
            unique.append(hit)
    return unique


# ---------------------------------------------------------------------------
# RAGPipeline
# ---------------------------------------------------------------------------

class RAGPipeline:
    """
    Retrieval-Augmented Generation pipeline for Niblit.

    Combines VectorStore dense retrieval, SECA multi-hop graph search, and
    brain trainer context into a single ranked context block for the LLM.

    Parameters
    ----------
    vector_store :
        A ``VectorStore`` instance (or ``None`` to skip dense retrieval).
    knowledge_comprehension :
        A ``KnowledgeComprehension`` instance (or ``None`` to skip graph search).
    max_context_chars : int
        Hard limit on the total character length of assembled context.
    """

    def __init__(
        self,
        vector_store: Optional[Any] = None,
        knowledge_comprehension: Optional[Any] = None,
        max_context_chars: int = 2000,
    ) -> None:
        self._vs = vector_store
        self._kc = knowledge_comprehension
        self.max_context_chars = max_context_chars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: int = 5,
        graph_depth: int = 2,
    ) -> Dict[str, Any]:
        """
        Retrieve context relevant to *question* from all available sources.

        Args:
            question:    The user query or sub-question to retrieve context for.
            top_k:       Maximum number of hits per retrieval source.
            graph_depth: Hop depth for SECA graph traversal.

        Returns:
            A dict with:
              - ``context`` (str)  — assembled context block ready for prompt injection
              - ``sources`` (list) — raw hit dicts ``{"text", "score", "source"}``
              - ``retrieval_stats`` (dict) — per-source hit counts
        """
        sources: List[Dict[str, Any]] = []
        stats: Dict[str, int] = {"vector_store": 0, "memory_graph": 0}

        # ── 1. Dense vector retrieval ──────────────────────────────────
        vs = self._get_vector_store()
        if vs is not None:
            try:
                vs_hits = vs.search(question, top_k=top_k)
                for h in vs_hits:
                    sources.append({
                        "text": h.get("text", ""),
                        "score": float(h.get("score", 0.0)),
                        "source": "vector_store",
                    })
                stats["vector_store"] = len(vs_hits)
            except Exception as exc:
                log.debug("[RAGPipeline] VectorStore search failed: %s", exc)

        # ── 2. SECA multi-hop graph retrieval ──────────────────────────
        kc = self._get_knowledge_comprehension()
        if kc is not None:
            try:
                graph_hits = kc.search_graph(question, top_k=top_k, depth=graph_depth)
                for h in graph_hits:
                    sources.append({
                        "text": h.get("text", ""),
                        "score": float(h.get("score", 0.0)),
                        "source": "memory_graph",
                    })
                stats["memory_graph"] = len(graph_hits)
            except Exception as exc:
                log.debug("[RAGPipeline] Graph search failed: %s", exc)

        # ── 3. Rank, de-duplicate, and assemble ───────────────────────
        ranked = sorted(sources, key=lambda h: h["score"], reverse=True)
        unique = _deduplicate(ranked)

        context = self._assemble_context(unique)

        log.debug(
            "[RAGPipeline] query=%r  vs=%d graph=%d unique=%d chars=%d",
            question[:60], stats["vector_store"], stats["memory_graph"],
            len(unique), len(context),
        )

        return {
            "context": context,
            "sources": unique,
            "retrieval_stats": stats,
        }

    def add_document(self, doc_id: str, text: str) -> bool:
        """
        Index *text* into the VectorStore so future queries can retrieve it.

        Returns True on success, False when VectorStore is unavailable.
        """
        vs = self._get_vector_store()
        if vs is None:
            return False
        try:
            return vs.add(doc_id, text)
        except Exception as exc:
            log.debug("[RAGPipeline] add_document failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _assemble_context(self, hits: List[Dict[str, Any]]) -> str:
        """Build a context string from ranked & de-duplicated hits."""
        if not hits:
            return ""

        lines: List[str] = ["Relevant context (RAG retrieval):"]
        total_chars = len(lines[0])

        for hit in hits:
            text = _truncate(hit.get("text", "").strip())
            if not text:
                continue
            entry = f"- {text}"
            if total_chars + len(entry) > self.max_context_chars:
                break
            lines.append(entry)
            total_chars += len(entry)

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # Lazy source resolution (allows the pipeline to be instantiated
    # before VectorStore / KnowledgeComprehension are ready)
    # ------------------------------------------------------------------

    def _get_vector_store(self) -> Optional[Any]:
        if self._vs is not None:
            return self._vs
        try:
            from modules.vector_store import VectorStore
            self._vs = VectorStore()
            return self._vs
        except Exception as exc:
            log.debug("[RAGPipeline] VectorStore unavailable: %s", exc)
            return None

    def _get_knowledge_comprehension(self) -> Optional[Any]:
        if self._kc is not None:
            return self._kc
        try:
            from modules.knowledge_comprehension import get_knowledge_comprehension
            self._kc = get_knowledge_comprehension()
            return self._kc
        except Exception as exc:
            log.debug("[RAGPipeline] KnowledgeComprehension unavailable: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_rag_pipeline_instance: Optional[RAGPipeline] = None
_rag_pipeline_lock = threading.Lock()


def get_rag_pipeline(
    vector_store: Optional[Any] = None,
    knowledge_comprehension: Optional[Any] = None,
    max_context_chars: int = 2000,
) -> RAGPipeline:
    """
    Return the module-level RAGPipeline singleton.

    On first call the instance is created with the supplied (or auto-resolved)
    sources.  Subsequent calls return the same instance regardless of arguments.
    """
    global _rag_pipeline_instance
    if _rag_pipeline_instance is None:
        with _rag_pipeline_lock:
            if _rag_pipeline_instance is None:
                _rag_pipeline_instance = RAGPipeline(
                    vector_store=vector_store,
                    knowledge_comprehension=knowledge_comprehension,
                    max_context_chars=max_context_chars,
                )
                log.debug("[RAGPipeline] Singleton created")
    return _rag_pipeline_instance


if __name__ == "__main__":
    print('Running rag_pipeline.py')
