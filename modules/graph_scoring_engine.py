#!/usr/bin/env python3
"""Graph-based evidence ranking for reasoning and retrieval.

This module sits between MemoryGraph and ReasoningEngine and converts raw graph
structure into ranked evidence candidates for downstream reasoning. It preserves
existing runtime ownership and does not replace the graph itself.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("GraphScoringEngine")

_STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but",
    "in", "on", "at", "to", "for", "of", "with", "from", "by", "this",
    "that", "it", "its", "be", "been", "has", "have", "had", "not", "no",
    "as", "so", "if", "then", "than", "more", "also", "can", "will",
    "their", "they", "we", "you", "our", "your", "all", "any", "which",
}

_NEGATION_WORDS: Set[str] = {"not", "never", "cannot", "no", "none", "false", "absent", "off"}


class GraphScoringEngine:
    """Score and rank graph evidence for reasoning workflows."""

    def __init__(self, memory_graph: Any = None) -> None:
        self.memory_graph = memory_graph

    def rank_candidates(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return ranked nodes for a query, using graph and metadata signals."""
        if self.memory_graph is None:
            return []

        try:
            nodes = getattr(self.memory_graph, "_nodes", None) or {}
        except Exception:
            return []

        if not nodes:
            return []

        query_terms = self._extract_terms(query)
        if not query_terms:
            query_terms = self._extract_terms(query.lower())

        scored: List[Tuple[str, float, Dict[str, Any]]] = []
        for node_id, node in nodes.items():
            try:
                text = str(getattr(node, "text", "") or "")
                if not text:
                    continue

                score, reasons = self._score_node(node, query_terms, text)
                if score <= 0.0:
                    continue

                scored.append(
                    (
                        node_id,
                        score,
                        {
                            "node_id": node_id,
                            "text": text,
                            "final_score": round(score, 3),
                            "reasons": reasons,
                        },
                    )
                )
            except Exception:
                continue

        scored.sort(key=lambda item: item[1], reverse=True)
        ranked = [entry[2] for entry in scored[: max(1, top_k)]]
        return ranked

    def _score_node(self, node: Any, query_terms: Set[str], text: str) -> Tuple[float, Dict[str, Any]]:
        node_terms = self._extract_terms(text)
        overlap = self._jaccard(query_terms, node_terms)

        node_confidence = self._coerce_float(getattr(node, "score", None), default=0.5)
        authority = self._coerce_float(self._metadata_value(node, "authority"), default=0.5)
        metadata_confidence = self._coerce_float(self._metadata_value(node, "confidence"), default=node_confidence)

        link_strength = 0.0
        if getattr(node, "links", None):
            link_strength = sum(float(weight) for weight in node.links.values() if self._is_number(weight)) / max(1, len(node.links))

        usage_bonus = min(0.1, max(0.0, getattr(node, "usage", 0) / 20.0))
        recency_bonus = 0.0
        if getattr(node, "last_used", 0):
            recency_bonus = 0.05

        contradiction_penalty = 0.0
        if self._looks_contradictory(text, query_terms):
            contradiction_penalty = 0.75

        if metadata_confidence <= 0.0:
            metadata_confidence = 0.1

        score = (
            0.45 * overlap
            + 0.20 * metadata_confidence
            + 0.15 * authority
            + 0.10 * link_strength
            + 0.05 * usage_bonus
            + 0.05 * recency_bonus
        )
        score = max(0.0, score - contradiction_penalty)
        if score > 0.0 and overlap <= 0.0 and metadata_confidence < 0.4:
            score *= 0.3

        reasons = {
            "overlap": round(overlap, 3),
            "metadata_confidence": round(metadata_confidence, 3),
            "authority": round(authority, 3),
            "link_strength": round(link_strength, 3),
            "contradiction_penalty": round(contradiction_penalty, 3),
        }
        return score, reasons

    def _extract_terms(self, text: str) -> Set[str]:
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(text).lower())
        return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}

    def _jaccard(self, left: Set[str], right: Set[str]) -> float:
        if not left and not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    def _metadata_value(self, node: Any, key: str) -> Any:
        metadata = getattr(node, "metadata", None)
        if isinstance(metadata, dict):
            return metadata.get(key)
        return None

    def _looks_contradictory(self, text: str, query_terms: Set[str]) -> bool:
        lowered = str(text).lower()
        if not query_terms:
            return False
        if any(word in lowered for word in _NEGATION_WORDS):
            return True
        return False

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _is_number(self, value: Any) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False
