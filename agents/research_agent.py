#!/usr/bin/env python3
"""
agents/research_agent.py — Autonomous research agent.

Handles ``task_type="research"`` tasks.  Uses the available search backends
(SerpEx, GitHub Code Search, Stack Overflow, PyPI) to collect information and
stores results in the knowledge base.

Architecture role (Phase 2)
---------------------------
    Planner → TaskQueue → Orchestrator → ResearchAgent
                                               │
                              ┌────────────────┼──────────────────┐
                              │                │                  │
                         SerpEx/DDG    GitHubCodeSearch  StackOverflow
"""

import logging
from typing import Any, Dict, List, Optional

from base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("ResearchAgent")


class ResearchAgent(BaseAgent):
    """
    Collects information from multiple sources and stores it.

    Args:
        internet_manager:     modules.internet_manager.InternetManager instance.
        github_code_search:   modules.github_code_search.GitHubCodeSearch instance.
        stackoverflow_search: modules.stackoverflow_search.StackOverflowSearch instance.
        pypi_search:          modules.pypi_search.PyPISearch instance.
        knowledge_db:         modules.knowledge_db.KnowledgeDB instance for storage.
    """

    HANDLED_TASK_TYPES = ["research", "code_research", "pattern_discovery", "training_data"]

    def __init__(
        self,
        internet_manager: Optional[Any] = None,
        github_code_search: Optional[Any] = None,
        stackoverflow_search: Optional[Any] = None,
        pypi_search: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
    ) -> None:
        super().__init__("research")
        self._internet = internet_manager
        self._github = github_code_search
        self._stackoverflow = stackoverflow_search
        self._pypi = pypi_search
        self._kb = knowledge_db

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        topic = task.payload.get("topic", "")
        language = task.payload.get("language", "python")
        context = task.payload.get("context", "")
        task_type = task.task_type

        if not topic:
            return {"error": "No topic provided", "results": []}

        results: List[Dict[str, Any]] = []

        # Web search
        if self._internet is not None:
            try:
                web_results = self._internet.search(f"{topic} {context}".strip(), max_results=3)
                results.extend(web_results or [])
            except Exception as exc:
                self._log.debug("internet search failed: %s", exc)

        # GitHub Code Search
        if self._github is not None and self._github.is_available():
            try:
                if task_type == "pattern_discovery":
                    gh_results = self._github.discover_patterns(language, topic, max_results=3)
                elif task_type == "training_data":
                    gh_results = self._github.find_training_data(topic, max_results=3)
                else:
                    gh_results = self._github.research_for_code_generation(language, topic, max_results=3)
                results.extend(gh_results or [])
            except Exception as exc:
                self._log.debug("GitHub search failed: %s", exc)

        # Stack Overflow
        if self._stackoverflow is not None:
            try:
                so_results = self._stackoverflow.research_for_code_generation(language, topic, max_results=3)
                results.extend(so_results or [])
            except Exception as exc:
                self._log.debug("SO search failed: %s", exc)

        # PyPI
        if self._pypi is not None and language.lower() == "python":
            try:
                pypi_results = self._pypi.research_for_code_generation(language, topic, max_results=3)
                results.extend(pypi_results or [])
            except Exception as exc:
                self._log.debug("PyPI search failed: %s", exc)

        # Store in KB
        if self._kb is not None and results:
            import time as _time
            ts = int(_time.time() * 1000)
            for i, r in enumerate(results[:5]):
                key = f"ale_research:{topic}:{ts}_{i}"
                text = r.get("text") or r.get("summary", "")[:300]
                if text:
                    try:
                        self._kb.store(key, text, tags=["research", "ale_research"])
                    except Exception:
                        pass

        self._log.info("research(%r) → %d results", topic, len(results))

        output = {"topic": topic, "results": results, "count": len(results)}
        self._publish(event_bus, EventType.RESEARCH_COMPLETED, output)
        return output
