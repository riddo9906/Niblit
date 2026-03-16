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
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("ReflectionAgent")


class ReflectionAgent(BaseAgent):
    """
    Performs pattern extraction and knowledge consolidation.

    Args:
        knowledge_db:  modules.knowledge_db.KnowledgeDB instance.
        brain_trainer: niblit_brain.BrainTrainer instance.
    """

    HANDLED_TASK_TYPES = ["reflection", "learn", "consolidate_knowledge"]

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        brain_trainer: Optional[Any] = None,
    ) -> None:
        super().__init__("reflection")
        self._kb = knowledge_db
        self._brain = brain_trainer

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        goal = task.payload.get("goal", "")
        results = task.payload.get("results", [])
        logs = task.payload.get("logs", [])
        topic = task.payload.get("topic", goal)

        patterns = self._extract_patterns(results, logs)
        stored = self._store_patterns(patterns, topic)
        self._update_brain(patterns, topic)

        output = {
            "topic": topic,
            "patterns_extracted": len(patterns),
            "patterns_stored": stored,
        }
        self._publish(event_bus, EventType.REFLECTION_COMPLETED, output)
        self._log.info("reflection(%r) → %d patterns", topic[:40], len(patterns))
        return output

    # ── helpers ───────────────────────────────────────────────────────────────

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
