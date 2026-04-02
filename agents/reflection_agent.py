#!/usr/bin/env python3
"""
agents/reflection_agent.py — Learning and reflection agent.

Handles ``task_type="reflection"`` tasks.  Extracts patterns from execution
logs and research results, updates the knowledge base, and feeds the
BrainTrainer so that learned knowledge persists across cycles.

Architecture role (Phase 2)
---------------------------
    TestingAgent → TaskQueue → ReflectionAgent
                                      │
                               KnowledgeDB + BrainTrainer

Enhancements (additive)
-----------------------
* **RAG deduplication** — before storing a new pattern, the agent performs a
  similarity look-up in the KnowledgeDB / VectorStore.  Near-duplicate facts
  (similarity ≥ 0.85) are skipped so the knowledge base stays clean.
* **Gap detection** — after each reflection cycle, the agent checks whether
  the knowledge base covers the topic at all.  If coverage is low, it pushes
  a "fill_knowledge_gap" notification for the ALE to action.
* **Contradiction flagging** — patterns that contradict stored facts (opposite
  sentiment on the same entity) are tagged ``contradiction`` so review agents
  can surface them.
* **Self-task generation** — when gaps or errors are detected the agent submits
  a new research task to the shared task queue so the system is self-completing.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("ReflectionAgent")

# Similarity threshold for deduplication (0 = keep all, 1 = only exact matches)
_DEDUP_THRESHOLD = 0.85
# Minimum stored facts about a topic before we consider coverage "adequate"
_MIN_COVERAGE_FACTS = 3


class ReflectionAgent(BaseAgent):
    """
    Performs pattern extraction, RAG-deduplication, and knowledge consolidation.

    Args:
        knowledge_db:  modules.knowledge_db.KnowledgeDB instance.
        brain_trainer: niblit_brain.BrainTrainer instance.
        vector_store:  Optional VectorStore / FusedStorage for semantic dedup.
        task_queue:    Optional TaskQueue so new research tasks can be created.
    """

    HANDLED_TASK_TYPES = ["reflection", "learn", "consolidate_knowledge"]

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        brain_trainer: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        task_queue: Optional[Any] = None,
    ) -> None:
        super().__init__("reflection")
        self._kb = knowledge_db
        self._brain = brain_trainer
        self._vector_store = vector_store  # optional: for RAG dedup
        self._task_queue = task_queue      # optional: for self-task generation

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        goal = task.payload.get("goal", "")
        results = task.payload.get("results", [])
        logs = task.payload.get("logs", [])
        topic = task.payload.get("topic", goal)

        # ── RAG context enrichment (additive) ─────────────────────────────────
        # Pull top-k existing knowledge on this topic *before* extracting
        # patterns so we can: (a) skip near-duplicates, (b) detect gaps.
        existing_facts = self._recall_related(topic, top_k=10)

        patterns = self._extract_patterns(results, logs)
        # Deduplicate against existing KB facts (additive enhancement)
        patterns = self._deduplicate(patterns, existing_facts)
        stored = self._store_patterns(patterns, topic)
        self._update_brain(patterns, topic)

        # ── Gap and contradiction detection (additive) ────────────────────────
        gap_detected = len(existing_facts) < _MIN_COVERAGE_FACTS and stored == 0
        contradictions = self._flag_contradictions(patterns, existing_facts)

        # ── Self-task generation (additive) ──────────────────────────────────
        if gap_detected:
            self._submit_gap_task(topic, event_bus)
        if contradictions:
            self._publish_contradiction_event(contradictions, topic, event_bus)

        output = {
            "topic": topic,
            "patterns_extracted": len(patterns),
            "patterns_stored": stored,
            "gap_detected": gap_detected,
            "contradictions": len(contradictions),
            "existing_facts_recalled": len(existing_facts),
        }
        self._publish(event_bus, EventType.REFLECTION_COMPLETED, output)
        self._log.info(
            "reflection(%r) → %d patterns stored, gap=%s, contradictions=%d",
            topic[:40], stored, gap_detected, len(contradictions),
        )
        return output

    # ── RAG: recall related knowledge (additive) ─────────────────────────────

    def _recall_related(self, topic: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Return top-k stored facts related to *topic*.

        Tries VectorStore semantic search first; falls back to KnowledgeDB
        keyword search so RAG works even without Qdrant configured.
        """
        facts: List[Dict[str, Any]] = []

        # 1 — VectorStore semantic recall
        if self._vector_store is not None:
            try:
                vs_results = self._vector_store.search(topic, top_k=top_k)
                if vs_results:
                    for r in vs_results:
                        if isinstance(r, dict):
                            facts.append(r)
                        elif hasattr(r, "__dict__"):
                            facts.append(r.__dict__)
            except Exception as exc:
                self._log.debug("VectorStore recall failed: %s", exc)

        # 2 — KnowledgeDB keyword recall (fallback / supplement)
        if self._kb is not None and len(facts) < top_k:
            try:
                for method in ("search", "recall", "get_related"):
                    fn = getattr(self._kb, method, None)
                    if fn is not None:
                        kb_res = fn(topic, limit=top_k - len(facts))
                        if kb_res:
                            for r in (kb_res if isinstance(kb_res, list) else []):
                                facts.append({"text": str(r), "source": "kb"})
                        break
            except Exception as exc:
                self._log.debug("KnowledgeDB recall failed: %s", exc)

        return facts[:top_k]

    # ── deduplication (additive) ──────────────────────────────────────────────

    def _deduplicate(
        self,
        patterns: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove patterns that are semantically near-duplicate of *existing* facts.

        Uses simple token-overlap Jaccard similarity (no heavy NLP required).
        Patterns are kept when similarity to ALL existing facts < threshold.
        """
        if not existing:
            return patterns

        def _tokens(text: str) -> set:
            return set(text.lower().split())

        existing_token_sets = [
            _tokens(str(f.get("text", f.get("summary", str(f)))))
            for f in existing
        ]

        kept = []
        for p in patterns:
            p_tokens = _tokens(p.get("text", ""))
            if not p_tokens:
                kept.append(p)
                continue
            duplicate = False
            for ex_tokens in existing_token_sets:
                if not ex_tokens:
                    continue
                intersection = len(p_tokens & ex_tokens)
                union = len(p_tokens | ex_tokens)
                jaccard = intersection / union if union else 0.0
                if jaccard >= _DEDUP_THRESHOLD:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(p)

        removed = len(patterns) - len(kept)
        if removed:
            self._log.debug("[ReflectionAgent] dedup removed %d near-duplicate(s)", removed)
        return kept

    # ── contradiction detection (additive) ───────────────────────────────────

    @staticmethod
    def _flag_contradictions(
        patterns: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Flag patterns that may contradict stored facts.

        Very lightweight heuristic: looks for antonym pairs in the same
        sentence context (e.g., "is fast" vs "is slow") without NLP libs.
        """
        _ANTONYM_PAIRS = [
            ("fast", "slow"), ("good", "bad"), ("increase", "decrease"),
            ("positive", "negative"), ("buy", "sell"), ("up", "down"),
            ("better", "worse"), ("success", "fail"), ("profit", "loss"),
        ]
        contradictions = []
        for p in patterns:
            p_text = p.get("text", "").lower()
            for ex in existing:
                ex_text = str(ex.get("text", ex.get("summary", ""))).lower()
                for a, b in _ANTONYM_PAIRS:
                    if a in p_text and b in ex_text and ex_text[:60] in p_text[:60]:
                        contradictions.append({
                            "new": p_text[:100],
                            "existing": ex_text[:100],
                            "antonym_pair": (a, b),
                        })
        return contradictions

    # ── self-task generation (additive) ──────────────────────────────────────

    def _submit_gap_task(self, topic: str, event_bus: EventBus) -> None:
        """Submit a new 'research' task to fill a detected knowledge gap.

        If a TaskQueue is wired in, enqueues the task directly.  Otherwise
        publishes a KNOWLEDGE_GAP_DETECTED event so subscribers can act.
        """
        self._log.info(
            "[ReflectionAgent] Knowledge gap detected for '%s' — submitting research task",
            topic,
        )
        if self._task_queue is not None:
            try:
                self._task_queue.enqueue_simple(
                    "research",
                    payload={"topic": topic, "context": "fill knowledge gap"},
                    source="reflection_agent_gap_detection",
                )
                return
            except Exception as exc:
                self._log.debug("Gap task enqueue failed: %s", exc)

        # Fallback: publish an event so other subscribers can handle it
        try:
            event_bus.publish(Event(
                type=EventType.KNOWLEDGE_GAP_DETECTED,
                payload={"topic": topic},
                source="reflection_agent",
            ))
        except Exception:
            pass

    def _publish_contradiction_event(
        self,
        contradictions: List[Dict[str, Any]],
        topic: str,
        event_bus: EventBus,
    ) -> None:
        """Publish a CONTRADICTION_DETECTED event for review agents."""
        try:
            event_bus.publish(Event(
                type=EventType.CONTRADICTION_DETECTED,
                payload={"topic": topic, "contradictions": contradictions[:3]},
                source="reflection_agent",
            ))
        except Exception:
            pass

    # ── original helpers (unchanged) ──────────────────────────────────────────

    @staticmethod
    def _extract_patterns(
        results: List[Any], logs: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract useful patterns from task results and execution logs."""
        patterns = []

        for r in results:
            if not isinstance(r, dict):
                continue
            text = r.get("text") or r.get("summary") or r.get("code", "")
            source = r.get("source", "unknown")
            if text and len(text) > 20:
                patterns.append({
                    "type": "research_snippet",
                    "text": text[:300],
                    "source": source,
                })

        for line in logs:
            if isinstance(line, str) and "ERROR" in line.upper():
                patterns.append({
                    "type": "error_pattern",
                    "text": line[:200],
                    "source": "execution_log",
                })

        return patterns

    def _store_patterns(self, patterns: List[Dict[str, Any]], topic: str) -> int:
        """Persist patterns to the knowledge base."""
        if self._kb is None or not patterns:
            return 0
        stored = 0
        ts = int(time.time() * 1000)
        for i, p in enumerate(patterns):
            key = f"ale_learned:{topic}:{ts}_{i}"
            try:
                self._kb.store(key, p["text"], tags=["learned", "reflection"])
                stored += 1
            except Exception:
                pass
        return stored

    def _update_brain(self, patterns: List[Dict[str, Any]], topic: str) -> None:
        """Feed patterns into BrainTrainer for cognitive integration."""
        if self._brain is None or not patterns:
            return
        combined = " ".join(p["text"] for p in patterns[:5])
        try:
            self._brain.ingest_research(topic, combined)
        except Exception as exc:
            self._log.debug("brain update failed: %s", exc)
