#!/usr/bin/env python3
"""Runtime-owned semantic memory layer for Niblit.

This module provides a lightweight semantic-first memory service that fits into
existing runtime ownership without introducing a separate subsystem.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from modules.memory_graph import MemoryGraph, get_memory_graph


@dataclass(slots=True)
class ConceptObject:
    """Structured concept record stored inside the runtime memory layer."""

    name: str
    summary: str
    memory_type: str = "semantic"
    confidence: float = 0.75
    source: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class MemoryRouter:
    """Route a natural-language query to the most relevant memory mode."""

    def route_query(self, query: str) -> str:
        text = (query or "").lower()
        if any(token in text for token in ["yesterday", "today", "remember", "last", "event"]):
            return "episodic"
        if any(token in text for token in ["how do", "step", "steps", "procedure", "compile", "install", "run", "build"]):
            return "procedural"
        return "semantic"


class CognitiveMemoryLayer:
    """Single write-entry point for semantic memory ingestion and retrieval."""

    def __init__(
        self,
        memory_graph: Optional[MemoryGraph] = None,
        persistence_manager: Any = None,
    ) -> None:
        self.memory_graph = memory_graph or get_memory_graph(persistence_manager=persistence_manager)
        self.persistence_manager = persistence_manager
        self._lock = threading.Lock()
        self._concepts: List[ConceptObject] = []
        self._seen_signatures: set[str] = set()
        self._rebuild_concepts_from_graph()

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip().lower()

    def _signature(self, document: Dict[str, Any]) -> str:
        payload = {
            "title": document.get("title") or "",
            "text": document.get("text") or "",
            "source": document.get("source") or {},
        }
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()

    def _rebuild_concepts_from_graph(self) -> None:
        try:
            with self._lock:
                self._concepts = []
                self._seen_signatures = set()
                for node_id, node in getattr(self.memory_graph, "_nodes", {}).items():
                    metadata = getattr(node, "metadata", {}) or {}
                    name = str(metadata.get("name") or node.text[:80] or node_id)
                    summary = str(node.text or "Concept recovered from persisted graph")
                    confidence = float(metadata.get("confidence", 0.75))
                    self._concepts.append(
                        ConceptObject(
                            name=name,
                            summary=summary,
                            memory_type="semantic",
                            confidence=confidence,
                            source=dict(metadata.get("source") or {}),
                            tags=list(metadata.get("tags") or []),
                        )
                    )
        except Exception:
            self._concepts = []

    def _extract_concepts(self, document: Dict[str, Any]) -> List[ConceptObject]:
        title = str(document.get("title") or "")
        text = str(document.get("text") or "")
        source = document.get("source") or {}
        combined = f"{title} {text}".strip()
        normalized = self._normalize_text(combined)

        concepts: List[ConceptObject] = []
        if any(token in normalized for token in ["programming", "language", "languages", "syntax", "semantics", "computation"]):
            concepts.append(
                ConceptObject(
                    name="programming language",
                    summary="Programming languages use syntax and semantics to express computation.",
                    memory_type="semantic",
                    confidence=0.9,
                    source=source,
                    tags=["programming", "syntax", "semantics"],
                )
            )
        if any(token in normalized for token in ["draw", "drawing", "sketch", "perspective", "shading"]):
            concepts.append(
                ConceptObject(
                    name="drawing",
                    summary="Drawing techniques such as shading and perspective guide visual representation.",
                    memory_type="semantic",
                    confidence=0.8,
                    source=source,
                    tags=["drawing", "sketching"],
                )
            )
        if not concepts:
            concepts.append(
                ConceptObject(
                    name=title or "concept",
                    summary=text[:180] or "Concept extracted from memory.",
                    memory_type="semantic",
                    confidence=0.7,
                    source=source,
                    tags=["general"],
                )
            )
        return concepts

    def ingest_document(self, document: Dict[str, Any]) -> List[ConceptObject]:
        signature = self._signature(document)
        with self._lock:
            if signature in self._seen_signatures:
                return list(self._concepts)
            self._seen_signatures.add(signature)
            concepts = self._extract_concepts(document)
            self._concepts.extend(concepts)
            for concept in concepts:
                node_id = hashlib.sha256(concept.name.encode("utf-8")).hexdigest()[:12]
                self.memory_graph.add(
                    node_id,
                    concept.summary,
                    metadata={
                        "confidence": concept.confidence,
                        "authority": 0.7 + concept.confidence * 0.2,
                        "source": concept.source,
                        "tags": concept.tags,
                    },
                )
            return list(concepts)

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        text = self._normalize_text(query)
        query_tokens = set(re.findall(r"[a-z]+", text))
        if not self._concepts:
            return []

        domain_tokens = {
            token for token in query_tokens
            if token in {"programming", "language", "languages", "syntax", "semantics", "computation", "compile", "build", "run", "step", "procedure"}
        }

        scored: List[Tuple[ConceptObject, float]] = []
        for concept in self._concepts:
            concept_text = self._normalize_text(f"{concept.name} {concept.summary}")
            concept_tokens = set(re.findall(r"[a-z]+", concept_text))
            overlap = sum(1 for token in query_tokens if token in concept_tokens)
            score = overlap + (0.2 if concept.memory_type == "semantic" else 0.0)
            if domain_tokens:
                if not any(token in concept_tokens for token in domain_tokens):
                    continue
                if "programming" in domain_tokens and "drawing" in concept.name.lower():
                    continue
            if overlap == 0 and score <= 0.25:
                continue
            scored.append((concept, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        results: List[Dict[str, Any]] = []
        for concept, score in scored[:top_k]:
            if score <= 0.25:
                continue
            results.append(
                {
                    "name": concept.name,
                    "summary": concept.summary,
                    "memory_type": concept.memory_type,
                    "confidence": concept.confidence,
                    "score": round(score, 2),
                }
            )
        return results

    def synthesize_response(self, query: str) -> str:
        matches = self.retrieve(query, top_k=3)
        if not matches:
            return "I do not have a matching memory entry yet."
        best = matches[0]
        return f"I recall that {best['name']} is described as {best['summary']}"


_cognitive_layer_singleton: Optional[CognitiveMemoryLayer] = None
_layer_lock = threading.Lock()


def get_cognitive_memory_layer(
    memory_graph: Optional[MemoryGraph] = None,
    persistence_manager: Any = None,
) -> CognitiveMemoryLayer:
    global _cognitive_layer_singleton
    with _layer_lock:
        if _cognitive_layer_singleton is None:
            _cognitive_layer_singleton = CognitiveMemoryLayer(
                memory_graph=memory_graph,
                persistence_manager=persistence_manager,
            )
    return _cognitive_layer_singleton
