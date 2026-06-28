#!/usr/bin/env python3
"""
REASONING ENGINE MODULE — Advanced LLM-level reasoning for Niblit.

Capabilities
============
1. **Knowledge graph construction** — keyword + co-occurrence graph from KB facts.
2. **Multi-hop BFS reasoning paths** — traverses graph edges to connect concepts.
3. **Chain-of-Thought (CoT) reasoning** — decomposes a question into sub-steps;
   uses the LLM provider when available, falls back to graph traversal otherwise.
4. **LLM-augmented inference** — sends fact context to LLMProviderManager and
   parses structured inferences from the response.
5. **Confidence scoring** — every inference carries a float [0.0, 1.0] score
   based on supporting-evidence count.
6. **Contradiction detection** — identifies KB facts whose content conflicts.
7. **Abductive reasoning** — scores candidate explanations for an observation.
8. **SECA/MemoryGraph enrichment** — lazy-imports SECA graph to augment reasoning
   with multi-hop retrieval results before LLM calls.

Backward Compatibility
======================
The three original public methods are fully preserved:
  * ``build_knowledge_graph(facts)``
  * ``create_reasoning_chain(start_concept, depth)``
  * ``infer_new_knowledge()``

Singleton
=========
``get_reasoning_engine(knowledge_db)`` — returns a module-level singleton.

Environment
===========
All LLM calls are optional and guarded: when the LLM provider or SECA is
unavailable the engine degrades gracefully to graph-only reasoning.
"""

from __future__ import annotations

import collections
import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("ReasoningEngine")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CoTStep:
    """One step in a chain-of-thought trace."""
    index: int
    question: str
    answer: str
    confidence: float = 1.0


@dataclass
class ChainOfThought:
    """Full CoT trace for a reasoning question."""
    question: str
    steps: List[CoTStep] = field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.0
    source: str = "graph"  # "llm" or "graph"

    def as_text(self) -> str:
        lines = [f"Q: {self.question}", ""]
        for s in self.steps:
            lines.append(f"  Step {s.index}: {s.question}")
            lines.append(f"    → {s.answer}")
        lines += ["", f"Conclusion: {self.conclusion}", f"Confidence: {self.confidence:.2f}"]
        return "\n".join(lines)


@dataclass
class ReasoningPath:
    """A multi-hop path through the knowledge graph."""
    start: str
    goal: str
    hops: List[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class Inference:
    """A single inferred statement with supporting evidence."""
    statement: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class Contradiction:
    """A detected contradiction between two facts."""
    fact_a_key: str
    fact_a_value: str
    fact_b_key: str
    fact_b_value: str
    shared_concept: str
    score: float = 0.5


@dataclass
class Abduction:
    """Abductive inference: best explanation for an observation."""
    observation: str
    best_explanation: str
    candidates: List[Tuple[str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but",
    "in", "on", "at", "to", "for", "of", "with", "from", "by", "this",
    "that", "it", "its", "be", "been", "has", "have", "had", "not", "no",
    "as", "so", "if", "then", "than", "more", "also", "can", "will",
    "their", "they", "we", "you", "our", "your", "all", "any", "which",
}

# Simple negation markers for contradiction detection
_NEGATION_PAIRS: List[Tuple[str, str]] = [
    ("does not", "does"),
    ("cannot", "can"),
    ("never", "always"),
    ("false", "true"),
    ("disabled", "enabled"),
    ("off", "on"),
    ("absent", "present"),
    ("fail", "succeed"),
    ("error", "success"),
]


def _extract_concepts(text: str) -> Set[str]:
    """Extract meaningful keywords from text, filtering stopwords."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", str(text).lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 3}


def _concept_overlap(a: str, b: str) -> float:
    """Jaccard similarity between concept sets of two strings."""
    ca = _extract_concepts(a)
    cb = _extract_concepts(b)
    if not ca and not cb:
        return 0.0
    intersection = len(ca & cb)
    union = len(ca | cb)
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ReasoningEngine:
    """Advanced multi-step reasoning engine for Niblit.

    Integrates with:
      * LLMProviderManager for chain-of-thought and LLM-augmented inference.
      * SECA MemoryGraph for multi-hop graph enrichment.
      * KnowledgeDB for fact retrieval and storage.
    """

    def __init__(
        self,
        knowledge_db: Any = None,
        memory_graph: Any = None,
        persistence_manager: Any = None,
        graph_scoring_engine: Any = None,
    ) -> None:
        self.db = knowledge_db
        self.memory_graph = memory_graph
        self.persistence_manager = persistence_manager
        self.graph_scoring_engine = graph_scoring_engine
        if self.graph_scoring_engine is None:
            try:
                from modules.graph_scoring_engine import GraphScoringEngine
                self.graph_scoring_engine = GraphScoringEngine(memory_graph=memory_graph)
            except Exception:
                self.graph_scoring_engine = None
        # Legacy attributes — preserved for backward compatibility
        self.graph: Dict[str, List[str]] = {}
        self.reasoning_chains: List[List[str]] = []
        # Extended state
        self._inferences: List[Inference] = []
        self._last_reasoning_trace: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._sync_graph_from_memory_graph()

    # =========================================================================
    # ── Public API (backward compatible) ─────────────────────────────────────
    # =========================================================================

    def build_knowledge_graph(self, facts: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """Build a keyword co-occurrence graph from facts.

        Backward-compatible with the original API.  Also updates internal
        state used by the new reasoning methods.
        """
        log.debug("[REASONING] Building knowledge graph from %d facts", len(facts))

        if not facts:
            self._sync_graph_from_memory_graph()
            return self.graph

        concept_to_facts: Dict[str, List[int]] = collections.defaultdict(list)

        # Index which facts each concept appears in
        for idx, fact in enumerate(facts):
            key_text = str(fact.get("key", ""))
            val_text = str(fact.get("value", ""))
            for concept in _extract_concepts(key_text) | _extract_concepts(val_text):
                concept_to_facts[concept].append(idx)

        # Build edges: two concepts are connected if they appear in the same fact
        graph: Dict[str, Set[str]] = collections.defaultdict(set)
        for concept, fact_indices in concept_to_facts.items():
            for fi in fact_indices:
                fact = facts[fi]
                key_text = str(fact.get("key", ""))
                val_text = str(fact.get("value", ""))
                for co_concept in _extract_concepts(key_text) | _extract_concepts(val_text):
                    if co_concept != concept:
                        graph[concept].add(co_concept)

        # Convert to lists, sorted by edge count (most-connected first)
        with self._lock:
            self.graph = {
                c: sorted(list(related), key=lambda x: -len(graph.get(x, set())))
                for c, related in graph.items()
                if related
            }

        if not self.graph:
            self._sync_graph_from_memory_graph()

        log.debug("[REASONING] Graph: %d concepts, %d edges",
                  len(self.graph),
                  sum(len(v) for v in self.graph.values()))
        return self.graph

    def create_reasoning_chain(self, start_concept: str, depth: int = 3) -> List[str]:
        """Follow the knowledge graph from *start_concept* up to *depth* hops.

        Backward-compatible with the original API.  Internally, this now calls
        the richer ``reason_paths`` BFS and returns the best path as a list.
        """
        log.debug("[REASONING] Creating chain from '%s' (depth=%d)", start_concept, depth)

        # Fast path: delegate to multi-hop BFS
        paths = self.reason_paths(start_concept, goal=None, max_hops=depth)
        if paths:
            chain = paths[0].hops
            with self._lock:
                self.reasoning_chains.append(chain)
            log.debug("[REASONING] Chain: %s", " → ".join(chain))
            return chain

        # Fallback: linear walk (original behaviour)
        chain = [start_concept]
        current = start_concept
        for _ in range(depth):
            neighbours = self.graph.get(current, [])
            for nxt in neighbours:
                if nxt not in chain:
                    chain.append(nxt)
                    current = nxt
                    break
        with self._lock:
            self.reasoning_chains.append(chain)
        log.debug("[REASONING] Chain (fallback): %s", " → ".join(chain))
        return chain

    def infer_new_knowledge(self) -> List[str]:
        """Derive inferences from the knowledge graph with confidence scores.

        Backward-compatible: returns a plain list of strings.  Richer typed
        results are available via ``infer_with_llm()`` or ``_build_inferences()``.
        """
        log.debug("[REASONING] Inferring new knowledge")

        typed_inferences = self._build_inferences()
        # Sort by confidence descending
        typed_inferences.sort(key=lambda i: -i.confidence)

        with self._lock:
            self._inferences = typed_inferences

        statements = [inf.statement for inf in typed_inferences]
        log.debug("[REASONING] Generated %d inferences", len(statements))
        return statements

    # =========================================================================
    # ── New Advanced Methods ──────────────────────────────────────────────────
    # =========================================================================

    def chain_of_thought(
        self,
        question: str,
        facts: Optional[List[Dict[str, str]]] = None,
        max_steps: int = 5,
    ) -> ChainOfThought:
        """Decompose *question* into a step-by-step chain-of-thought trace.

        When the LLM provider is available the full question → sub-questions →
        conclusion flow is LLM-driven.  Without an LLM the engine performs
        graph traversal to approximate the reasoning trace.

        Args:
            question:  The reasoning question to answer.
            facts:     Optional supplementary facts (list of key/value dicts).
            max_steps: Maximum reasoning steps.

        Returns:
            :class:`ChainOfThought` with steps and a scored conclusion.
        """
        log.debug("[REASONING] chain_of_thought: %s", question[:80])

        cot = ChainOfThought(question=question)

        # Build / refresh graph if facts provided
        if facts:
            self.build_knowledge_graph(facts)

        # Attempt LLM-driven CoT first
        llm_result = self._llm_chain_of_thought(question, facts or [], max_steps)
        if llm_result:
            cot.steps = llm_result["steps"]
            cot.conclusion = llm_result["conclusion"]
            cot.confidence = llm_result["confidence"]
            cot.source = "llm"
            return cot

        self._sync_graph_from_memory_graph()

        # Graph-based fallback CoT
        concepts = list(_extract_concepts(question))
        if not concepts:
            cot.conclusion = f"No graph concepts found for: {question}"
            cot.confidence = 0.0
            return cot

        ranked_evidence = []
        if self.graph_scoring_engine is not None:
            try:
                ranked_evidence = self.graph_scoring_engine.rank_candidates(question, top_k=max_steps)
            except Exception as exc:
                log.debug("[REASONING] ranked evidence unavailable: %s", exc)

        step_idx = 1
        visited: Set[str] = set()
        if ranked_evidence:
            for item in ranked_evidence[:max_steps]:
                node_text = str(item.get("text", ""))
                node_id = str(item.get("node_id", ""))
                if not node_text:
                    continue
                step = CoTStep(
                    index=step_idx,
                    question=f"What evidence supports '{node_id}'?",
                    answer=node_text[:180],
                    confidence=max(0.2, float(item.get("final_score", 0.2))),
                )
                cot.steps.append(step)
                visited.add(node_id)
                step_idx += 1
        else:
            for concept in concepts[:max_steps]:
                neighbours = self.graph.get(concept, [])[:4]
                if not neighbours:
                    continue
                step = CoTStep(
                    index=step_idx,
                    question=f"What is related to '{concept}'?",
                    answer=f"{concept} connects to: {', '.join(neighbours)}",
                    confidence=min(1.0, len(neighbours) / 5),
                )
                cot.steps.append(step)
                visited.update(neighbours)
                step_idx += 1
                if step_idx > max_steps:
                    break

        all_related = sorted(visited)[:8]
        if all_related:
            cot.conclusion = (
                f"For '{question}': key concepts are {', '.join(all_related[:5])}."
            )
            cot.confidence = min(0.9, 0.2 + 0.1 * len(cot.steps) + 0.05 * min(4, len(all_related)))
        else:
            cot.conclusion = f"Insufficient knowledge graph data for: {question}"
            cot.confidence = 0.1

        cot.source = "graph"
        return cot

    def build_reasoning_trace(
        self,
        question: str,
        facts: Optional[List[Dict[str, str]]] = None,
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        """Build a structured, internal-only reasoning trace for the synthesis layer."""
        cot = self.chain_of_thought(question, facts=facts, max_steps=max_steps)
        trace = {
            "question": question,
            "summary": cot.conclusion or "",
            "confidence": cot.confidence,
            "steps": [
                {
                    "question": step.question,
                    "answer": step.answer,
                    "confidence": step.confidence,
                }
                for step in cot.steps
            ],
            "source": cot.source,
        }
        self._last_reasoning_trace = trace
        return trace

    def reason_paths(
        self,
        start: str,
        goal: Optional[str] = None,
        max_hops: int = 5,
        top_k: int = 3,
    ) -> List[ReasoningPath]:
        """BFS over the knowledge graph to find paths from *start* toward *goal*.

        If *goal* is None the method returns the top-*k* longest reachable paths
        from *start*.

        Args:
            start:    Starting concept.
            goal:     Target concept (optional).
            max_hops: Maximum number of hops per path.
            top_k:    Maximum number of paths to return.

        Returns:
            List of :class:`ReasoningPath` sorted by score (descending).
        """
        # BFS
        # Queue entries: (path_so_far, current_node)
        queue: collections.deque = collections.deque()
        queue.append(([start], start))
        completed: List[ReasoningPath] = []

        while queue:
            path, current = queue.popleft()
            if len(path) > max_hops + 1:
                continue

            neighbours = self.graph.get(current, [])
            reached_goal = goal is not None and current == goal

            if reached_goal or (goal is None and len(path) >= 2):
                # Score: longer path = higher reach; goal match = bonus
                score = len(path) / max(max_hops, 1)
                if reached_goal:
                    score = 1.0
                # Adjust by average connectivity of nodes on path
                avg_conn = sum(len(self.graph.get(n, [])) for n in path) / max(len(path), 1)
                score = score * min(1.0, math.log1p(avg_conn) / math.log1p(10))
                rp = ReasoningPath(
                    start=start,
                    goal=goal or path[-1],
                    hops=list(path),
                    score=round(score, 3),
                )
                completed.append(rp)

            if reached_goal:
                continue  # don't expand beyond goal

            for nxt in neighbours[:6]:  # cap branching factor
                if nxt not in path:  # no cycles
                    queue.append((path + [nxt], nxt))

        # Deduplicate and return top-k by score
        seen: Set[str] = set()
        unique: List[ReasoningPath] = []
        for rp in sorted(completed, key=lambda x: -x.score):
            key = "→".join(rp.hops)
            if key not in seen:
                seen.add(key)
                unique.append(rp)
            if len(unique) >= top_k:
                break

        return unique

    def infer_with_llm(
        self,
        question: str,
        facts: Optional[List[Dict[str, str]]] = None,
        max_inferences: int = 5,
    ) -> List[Inference]:
        """Use the LLM provider to generate typed inferences from *facts*.

        Falls back to graph-based inference when the LLM is unavailable.

        Args:
            question:        Framing question for the LLM.
            facts:           Supplementary facts to reason over.
            max_inferences:  Maximum number of inferences to return.

        Returns:
            List of :class:`Inference` sorted by confidence.
        """
        log.debug("[REASONING] infer_with_llm: %s", question[:80])

        # Build graph context
        if facts:
            self.build_knowledge_graph(facts)

        # SECA multi-hop enrichment (optional)
        seca_snippets: List[str] = []
        try:
            from modules.knowledge_comprehension import get_knowledge_comprehension
            kc = get_knowledge_comprehension()
            hits = kc.search_graph(question, top_k=3, depth=2)
            seca_snippets = [h.get("text", "") for h in hits if h.get("text")]
        except Exception as exc:
            log.debug("[REASONING] SECA enrichment skipped: %s", exc)

        # Attempt LLM inference
        llm_inferences = self._llm_infer(question, facts or [], seca_snippets, max_inferences)
        if llm_inferences:
            return llm_inferences

        # Fallback to graph-based inference
        return self._build_inferences()[:max_inferences]

    def detect_contradictions(
        self,
        facts: Optional[List[Dict[str, str]]] = None,
        threshold: float = 0.35,
    ) -> List[Contradiction]:
        """Scan facts for potential contradictions.

        Two facts are considered contradictory when they share at least one
        concept AND one of them contains a negation of a word found in the
        other.

        Args:
            facts:     Facts to scan.  Uses recent KB facts if None.
            threshold: Minimum concept-overlap Jaccard score to consider
                       a pair as potentially contradictory.

        Returns:
            List of :class:`Contradiction` sorted by score (descending).
        """
        if not facts:
            facts = self._load_facts(50)

        contradictions: List[Contradiction] = []

        for i, fa in enumerate(facts):
            val_a = str(fa.get("value", ""))
            key_a = str(fa.get("key", ""))
            for fb in facts[i + 1:]:
                val_b = str(fb.get("value", ""))
                key_b = str(fb.get("key", ""))

                # Overlap check
                overlap = _concept_overlap(val_a, val_b)
                if overlap < threshold:
                    continue

                # Negation check
                shared = _extract_concepts(val_a) & _extract_concepts(val_b)
                if not shared:
                    continue

                negation_score = 0.0
                for neg_word, pos_word in _NEGATION_PAIRS:
                    a_neg = neg_word in val_a.lower()
                    b_pos = pos_word in val_b.lower() and neg_word not in val_b.lower()
                    b_neg = neg_word in val_b.lower()
                    a_pos = pos_word in val_a.lower() and neg_word not in val_a.lower()
                    if (a_neg and b_pos) or (b_neg and a_pos):
                        negation_score = max(negation_score, overlap)

                if negation_score > 0:
                    contradictions.append(Contradiction(
                        fact_a_key=key_a,
                        fact_a_value=val_a[:200],
                        fact_b_key=key_b,
                        fact_b_value=val_b[:200],
                        shared_concept=next(iter(shared), "unknown"),
                        score=round(negation_score, 3),
                    ))

        contradictions.sort(key=lambda c: -c.score)
        log.debug("[REASONING] Detected %d potential contradictions", len(contradictions))
        return contradictions

    def abduce(
        self,
        observation: str,
        candidates: Optional[List[str]] = None,
    ) -> Abduction:
        """Select the best explanation (abduction) for *observation*.

        Scores each candidate by concept overlap with the observation and,
        when the graph is populated, by how many graph neighbours the candidate
        shares with the observation's concepts.

        Args:
            observation: The observation to explain.
            candidates:  Candidate explanations.  If None, derives candidates
                         from neighbours of concepts in the observation.

        Returns:
            :class:`Abduction` with ranked candidate list.
        """
        obs_concepts = _extract_concepts(observation)

        if not candidates:
            # Auto-generate candidates from graph neighbours of observation concepts
            candidate_set: Set[str] = set()
            for c in obs_concepts:
                for nbr in self.graph.get(c, [])[:5]:
                    candidate_set.add(nbr)
            candidates = list(candidate_set)[:10]

        if not candidates:
            return Abduction(
                observation=observation,
                best_explanation="Insufficient knowledge to generate explanation.",
                candidates=[],
            )

        scored: List[Tuple[str, float]] = []
        for cand in candidates:
            cand_concepts = _extract_concepts(cand)
            # Base score: concept overlap
            base = _concept_overlap(observation, cand)
            # Boost: shared graph neighbours
            graph_boost = 0.0
            for oc in obs_concepts:
                nbrs = set(self.graph.get(oc, []))
                for cc in cand_concepts:
                    if cc in nbrs:
                        graph_boost += 0.1
            total = min(1.0, base + graph_boost)
            scored.append((cand, round(total, 3)))

        scored.sort(key=lambda x: -x[1])
        best = scored[0][0] if scored else "Unknown"

        return Abduction(
            observation=observation,
            best_explanation=best,
            candidates=scored,
        )

    def score_inference(self, statement: str, facts: Optional[List[Dict]] = None) -> float:
        """Score an inference statement [0.0, 1.0] based on supporting facts.

        Uses log-scale normalisation so the score grows quickly with initial
        evidence but saturates gracefully as evidence accumulates.  Specifically:
        ``log1p(support) / log1p(len(facts))`` keeps the result in [0, 1]
        regardless of dataset size, while rewarding early corroboration more
        than redundant confirmation.
        """
        if not facts:
            facts = self._load_facts(100)

        stmt_concepts = _extract_concepts(statement)
        if not stmt_concepts:
            return 0.0

        support = 0
        for fact in facts:
            fact_text = str(fact.get("value", "")) + " " + str(fact.get("key", ""))
            fact_concepts = _extract_concepts(fact_text)
            if stmt_concepts & fact_concepts:
                support += 1

        # Normalise: log-scale relative to facts count
        return round(min(1.0, math.log1p(support) / math.log1p(max(len(facts), 1))), 3)

    # =========================================================================
    # ── Persistence (unchanged API) ───────────────────────────────────────────
    # =========================================================================

    def export_graph(self, indent: int = 2) -> str:
        """Serialise the knowledge graph to a JSON string."""
        return json.dumps(self.graph, indent=indent, default=str)

    def import_graph(self, json_str: str) -> bool:
        """Load a previously exported knowledge graph from a JSON string."""
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                with self._lock:
                    self.graph = data
                log.debug("[REASONING] Imported graph with %d concepts", len(self.graph))
                return True
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("[REASONING] import_graph failed: %s", exc)
        return False

    # =========================================================================
    # ── Internal helpers ──────────────────────────────────────────────────────
    # =========================================================================

    def _sync_graph_from_memory_graph(self) -> None:
        """Hydrate the reasoning graph from the shared MemoryGraph when available."""
        if self.memory_graph is None:
            try:
                from modules.memory_graph import get_memory_graph
                self.memory_graph = get_memory_graph()
            except Exception:
                return

        if self.graph_scoring_engine is None:
            try:
                from modules.graph_scoring_engine import GraphScoringEngine
                self.graph_scoring_engine = GraphScoringEngine(memory_graph=self.memory_graph)
            except Exception:
                self.graph_scoring_engine = None

        try:
            nodes = getattr(self.memory_graph, "_nodes", None)
            if not nodes:
                return

            adjacency: Dict[str, Set[str]] = collections.defaultdict(set)
            for node in nodes.values():
                text = str(getattr(node, "text", "") or "")
                concepts = list(_extract_concepts(text))
                if len(concepts) < 2:
                    continue
                for concept in concepts:
                    adjacency[concept].update(c for c in concepts if c != concept)

            with self._lock:
                for concept, related in adjacency.items():
                    existing = set(self.graph.get(concept, []))
                    existing.update(related)
                    self.graph[concept] = sorted(existing)
                if not self.graph:
                    self.graph = {}
        except Exception as exc:
            log.debug("[REASONING] memory graph sync failed: %s", exc)

    def _build_inferences(self) -> List[Inference]:
        """Derive confidence-scored inferences from the current graph."""
        inferences: List[Inference] = []
        for concept, related in self.graph.items():
            if not related:
                continue
            # Transitive inference: concept → A → B implies concept relates to B
            for direct in related[:3]:
                second_hop = [n for n in self.graph.get(direct, [])[:3] if n != concept]
                if second_hop:
                    stmt = (
                        f"'{concept}' is connected to '{direct}', "
                        f"which relates to {', '.join(repr(x) for x in second_hop[:2])}"
                    )
                else:
                    stmt = f"'{concept}' connects to: {', '.join(repr(r) for r in related[:3])}"
                evidence = [concept, direct] + second_hop
                confidence = min(1.0, (len(related) + len(second_hop)) / 10.0)
                inferences.append(Inference(
                    statement=stmt,
                    evidence=evidence,
                    confidence=round(confidence, 3),
                ))
        return inferences

    def _load_facts(self, limit: int = 50) -> List[Dict[str, str]]:
        """Load recent facts from KnowledgeDB."""
        if not self.db or not hasattr(self.db, "list_facts"):
            return []
        try:
            raw = self.db.list_facts(limit) or []
            result = []
            for f in raw:
                if isinstance(f, dict):
                    result.append({"key": str(f.get("key", "")), "value": str(f.get("value", ""))})
                elif isinstance(f, (list, tuple)) and len(f) >= 2:
                    result.append({"key": str(f[0]), "value": str(f[1])})
            return result
        except Exception as exc:
            log.debug("[REASONING] _load_facts failed: %s", exc)
            return []

    def _get_llm(self) -> Optional[Any]:
        """Lazily resolve the LLMProviderManager singleton."""
        try:
            from modules.llm_provider_manager import get_llm_provider_manager
            return get_llm_provider_manager()
        except Exception as exc:
            log.debug("[REASONING] LLMProviderManager unavailable: %s", exc)
            return None

    def _llm_chain_of_thought(
        self,
        question: str,
        facts: List[Dict[str, str]],
        max_steps: int,
    ) -> Optional[Dict[str, Any]]:
        """Ask the LLM to produce a structured CoT response.

        Returns a dict {steps, conclusion, confidence} or None on failure.
        """
        llm = self._get_llm()
        if llm is None:
            return None

        fact_lines = "\n".join(
            f"- {f['key']}: {str(f['value'])[:100]}"
            for f in facts[:10]
        )
        seca_ctx = ""
        try:
            from modules.knowledge_comprehension import get_knowledge_comprehension
            kc = get_knowledge_comprehension()
            hits = kc.search_graph(question, top_k=3, depth=1)
            seca_ctx = "\n".join(h.get("text", "")[:150] for h in hits if h.get("text"))
        except Exception:
            pass

        prompt = (
            f"You are a reasoning engine for Niblit, an autonomous AI system.\n\n"
            f"Question: {question}\n\n"
            f"Known facts (most recent):\n{fact_lines or '(none)'}\n\n"
            + (f"Context from knowledge graph:\n{seca_ctx}\n\n" if seca_ctx else "")
            + f"Think step by step (up to {max_steps} steps). "
            f"Each step: [Step N] sub-question / answer. "
            f"End with [Conclusion] one sentence. "
            f"End with [Confidence] a number 0.0-1.0.\n"
        )

        try:
            raw = llm.ask(prompt, max_tokens=512)
        except Exception as exc:
            log.debug("[REASONING] LLM CoT call failed: %s", exc)
            return None

        if not raw or not isinstance(raw, str):
            return None

        return self._parse_cot_response(raw, max_steps)

    def _parse_cot_response(self, raw: str, max_steps: int) -> Dict[str, Any]:
        """Parse LLM CoT output into structured steps + conclusion."""
        steps: List[CoTStep] = []
        conclusion = ""
        confidence = 0.5

        step_pattern = re.compile(
            r"\[Step\s*(\d+)\]\s*(.*?)(?=\[Step\s*\d+\]|\[Conclusion\]|\[Confidence\]|$)",
            re.DOTALL | re.IGNORECASE,
        )
        for m in step_pattern.finditer(raw):
            idx = int(m.group(1))
            content = m.group(2).strip()
            # Try to split sub-question / answer at newline or slash
            parts = re.split(r"\n|/", content, maxsplit=1)
            q_part = parts[0].strip()
            a_part = parts[1].strip() if len(parts) > 1 else q_part
            steps.append(CoTStep(index=idx, question=q_part, answer=a_part))
            if len(steps) >= max_steps:
                break

        conc_match = re.search(r"\[Conclusion\]\s*(.*?)(?=\[|$)", raw, re.DOTALL | re.IGNORECASE)
        if conc_match:
            conclusion = conc_match.group(1).strip()[:400]

        conf_match = re.search(r"\[Confidence\]\s*([\d.]+)", raw, re.IGNORECASE)
        if conf_match:
            try:
                confidence = max(0.0, min(1.0, float(conf_match.group(1))))
            except ValueError:
                pass

        if not conclusion and steps:
            conclusion = steps[-1].answer

        return {"steps": steps, "conclusion": conclusion, "confidence": confidence}

    def _llm_infer(
        self,
        question: str,
        facts: List[Dict[str, str]],
        seca_snippets: List[str],
        max_inferences: int,
    ) -> List[Inference]:
        """Ask the LLM to generate N numbered inferences about *question*."""
        llm = self._get_llm()
        if llm is None:
            return []

        fact_lines = "\n".join(
            f"- {f['key']}: {str(f['value'])[:80]}"
            for f in facts[:8]
        )
        seca_block = (
            "Related knowledge:\n" + "\n".join(f"- {s[:120]}" for s in seca_snippets[:3]) + "\n"
            if seca_snippets else ""
        )

        prompt = (
            f"You are Niblit's inference engine. Given facts about '{question}', "
            f"generate {max_inferences} concise inferences. "
            f"Format: [N] <inference statement> [conf:<0.0-1.0>]\n\n"
            f"Facts:\n{fact_lines or '(none)'}\n\n"
            f"{seca_block}"
            f"Output only the numbered inferences, one per line."
        )

        try:
            raw = llm.ask(prompt, max_tokens=400)
        except Exception as exc:
            log.debug("[REASONING] LLM infer call failed: %s", exc)
            return []

        if not raw or not isinstance(raw, str):
            return []

        return self._parse_inferences(raw, facts)

    def _parse_inferences(
        self,
        raw: str,
        facts: List[Dict[str, str]],
    ) -> List[Inference]:
        """Parse numbered LLM inference output."""
        inferences: List[Inference] = []
        pattern = re.compile(
            r"\[(\d+)\]\s*(.*?)(?:\[conf:([\d.]+)\])?(?=\[\d+\]|$)",
            re.DOTALL,
        )
        for m in pattern.finditer(raw):
            stmt = m.group(2).strip()
            if not stmt:
                continue
            conf_str = m.group(3)
            try:
                conf = float(conf_str) if conf_str else None
            except ValueError:
                conf = None
            if conf is None:
                conf = self.score_inference(stmt, facts)
            inferences.append(Inference(
                statement=stmt[:300],
                confidence=round(max(0.0, min(1.0, conf)), 3),
            ))
        return inferences

    # =========================================================================
    # ── Legacy private helpers (kept for compatibility) ───────────────────────
    # =========================================================================

    def _extract_concepts_compat(self, text: Any) -> Set[str]:
        """Backward-compat alias — delegates to module-level ``_extract_concepts``."""
        return _extract_concepts(str(text))

    # Keep the old name as an alias so external callers are not broken
    _extract_concepts = _extract_concepts_compat  # type: ignore[assignment]

    def _find_related(self, concept: str, facts: List[Dict]) -> Set[str]:
        """Legacy helper — find concepts co-occurring with *concept* in facts."""
        related: Set[str] = set()
        concept_lower = concept.lower()
        for fact in facts:
            value = str(fact.get("value", "")).lower()
            if concept_lower in value:
                related.update(_extract_concepts(str(fact.get("key", ""))))
        return related


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[ReasoningEngine] = None
_INSTANCE_LOCK = threading.Lock()


def get_reasoning_engine(knowledge_db: Any = None, memory_graph: Any = None, persistence_manager: Any = None) -> ReasoningEngine:
    """Return the module-level singleton :class:`ReasoningEngine`.

    If *knowledge_db* is provided on first call it is bound to the instance.
    If *memory_graph* is provided it is wired into the shared engine state.
    """
    global _INSTANCE  # noqa: PLW0603
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ReasoningEngine(knowledge_db=knowledge_db, memory_graph=memory_graph, persistence_manager=persistence_manager)
    else:
        if knowledge_db is not None:
            _INSTANCE.db = knowledge_db
        if memory_graph is not None:
            _INSTANCE.memory_graph = memory_graph
            getattr(_INSTANCE, "_sync_graph_from_memory_graph")()
    return _INSTANCE


if __name__ == "__main__":
    print('Running reasoning_engine.py')
