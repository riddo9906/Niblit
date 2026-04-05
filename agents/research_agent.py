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

Enhancements (additive)
-----------------------
* **RAG pre-check** — before querying external sources, the agent recalls
  existing KB knowledge on the topic.  If sufficient (≥ 5 high-quality facts),
  it skips external fetches and returns cached results (saves quota + latency).
* **Rationale surface** — the output dict now includes a ``rationale`` key
  explaining why each source was used and what was already known, so LLM
  callers can surface reasoning to the user.
* **Deduplication** — new results are compared to cached KB facts; near-
  duplicates (Jaccard ≥ 0.75) are omitted before storage.
* **Gap signal** — when fewer than 3 results are collected, a
  KNOWLEDGE_GAP_DETECTED event is published for the ReflectionAgent to action.
"""

import logging
import time as _time
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("ResearchAgent")

# Cache threshold: if >= this many cached facts exist, skip external fetch
_CACHE_SUFFICIENT = 5
# Dedup Jaccard threshold
_DEDUP_THRESHOLD = 0.75


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
        hybrid_manager: Optional[Any] = None,
        kernel: Optional[Any] = None,
    ) -> None:
        super().__init__("research")

        self._internet = internet_manager
        self._github = github_code_search
        self._stackoverflow = stackoverflow_search
        self._pypi = pypi_search
        self._kb = knowledge_db
        self.hybrid_manager = hybrid_manager
        self.kernel = kernel

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        topic = task.payload.get("topic", "")
        language = task.payload.get("language", "python")
        context = task.payload.get("context", "")
        task_type = task.task_type

        if not topic:
            return {"error": "No topic provided", "results": []}

        results: List[Dict[str, Any]] = []
        rationale: List[str] = []  # additive: surface reasoning to callers

        # ── RAG pre-check (additive) ───────────────────────────────────────────
        # Recall existing KB facts *before* hitting external sources.  If the
        # cache is already sufficient, skip expensive external fetches and return
        # the cached knowledge directly (saves API quota and latency).
        cached_facts = self._recall_cached(topic, top_k=_CACHE_SUFFICIENT)
        if len(cached_facts) >= _CACHE_SUFFICIENT and context != "ale_gap_fill":
            rationale.append(
                f"Cache sufficient ({len(cached_facts)} facts) — skipping external fetch"
            )
            self._log.debug(
                "[ResearchAgent] RAG cache hit for %r (%d facts) — skipping external",
                topic, len(cached_facts),
            )
            output = {
                "topic": topic,
                "results": cached_facts,
                "count": len(cached_facts),
                "source": "rag_cache",
                "rationale": rationale,
            }
            self._publish(event_bus, EventType.RESEARCH_COMPLETED, output)
            return output

        if cached_facts:
            rationale.append(f"Partial cache ({len(cached_facts)} facts) — supplementing with external")
        else:
            rationale.append("No cached facts — performing full external research")

        # Web search
        if self._internet is not None:
            try:
                web_results = self._internet.search(f"{topic} {context}".strip(), max_results=3)
                results.extend(web_results or [])
                rationale.append(f"InternetManager: {len(web_results or [])} results")
            except Exception as exc:
                self._log.debug("internet search failed: %s", exc)
                rationale.append(f"InternetManager: failed ({exc})")

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
                rationale.append(f"GitHubCodeSearch: {len(gh_results or [])} results")
            except Exception as exc:
                self._log.debug("GitHub search failed: %s", exc)

        # Stack Overflow
        if self._stackoverflow is not None:
            try:
                so_results = self._stackoverflow.research_for_code_generation(language, topic, max_results=3)
                results.extend(so_results or [])
                rationale.append(f"StackOverflow: {len(so_results or [])} results")
            except Exception as exc:
                self._log.debug("SO search failed: %s", exc)

        # PyPI
        if self._pypi is not None and language.lower() == "python":
            try:
                pypi_results = self._pypi.research_for_code_generation(language, topic, max_results=3)
                results.extend(pypi_results or [])
                rationale.append(f"PyPI: {len(pypi_results or [])} results")
            except Exception as exc:
                self._log.debug("PyPI search failed: %s", exc)

        # ── Deduplication against cached facts (additive) ────────────────────
        results = self._deduplicate(results, cached_facts)

        # Store in KB
        if self._kb is not None and results:
            ts = int(_time.time() * 1000)
            for i, r in enumerate(results[:5]):
                key = f"ale_research:{topic}:{ts}_{i}"
                text = r.get("text") or r.get("summary", "")[:300]
                if text:
                    try:
                        self._kb.store(key, text, tags=["research", "ale_research"])
                    except Exception:
                        pass

        self._log.info("research(%r) → %d results (rationale: %s)", topic, len(results), rationale[:2])

        # ── HybridQdrantManager upsert (additive) ────────────────────────────────
        if self.hybrid_manager:
            try:
                stored_facts = results
                for fact in (stored_facts if 'stored_facts' in dir() else []):
                    text = str(fact.get("content") or fact.get("value") or fact)[:1000]
                    self.hybrid_manager.upsert(
                        text,
                        {"type": "research", "agent": "ResearchAgent"},
                        collection="niblit_research"
                    )
            except Exception as _hq_e:
                log.debug("[ResearchAgent] hybrid upsert failed: %s", _hq_e)
        if self.kernel:
            try:
                self.kernel.report_success("ResearchAgent", "Research stored")
            except Exception:
                pass

        output = {
            "topic": topic,
            "results": results,
            "count": len(results),
            "source": "external",
            "rationale": rationale,
        }
        self._publish(event_bus, EventType.RESEARCH_COMPLETED, output)

        # ── Gap signal (additive) ─────────────────────────────────────────────
        if len(results) < 3 and len(cached_facts) < 3:
            try:
                event_bus.publish(Event(
                    type=EventType.KNOWLEDGE_GAP_DETECTED,
                    payload={"topic": topic, "results_found": len(results)},
                    source="research_agent",
                ))
            except Exception:
                pass

        return output

    # ── RAG helper methods (additive) ─────────────────────────────────────────

    def _recall_cached(self, topic: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return cached KB facts for *topic* (Jaccard-ranked, no external calls)."""
        facts: List[Dict[str, Any]] = []
        if self._kb is None:
            return facts
        try:
            for method in ("search", "recall", "get_related"):
                fn = getattr(self._kb, method, None)
                if fn:
                    raw = fn(topic, limit=top_k) or []
                    for r in raw:
                        if isinstance(r, dict):
                            facts.append(r)
                        else:
                            facts.append({"text": str(r), "source": "kb_cache"})
                    break
        except Exception as exc:
            self._log.debug("KB recall failed: %s", exc)
        return facts[:top_k]

    @staticmethod
    def _deduplicate(
        new_results: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
        threshold: float = _DEDUP_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """Remove results that are near-duplicates of existing cached facts."""
        if not existing:
            return new_results

        def _tok(text: str) -> set:
            return set(text.lower().split())

        ex_sets = [_tok(str(f.get("text", f.get("summary", str(f))))) for f in existing]

        kept = []
        for r in new_results:
            r_text = str(r.get("text", r.get("summary", "")))
            r_tok = _tok(r_text)
            if not r_tok:
                kept.append(r)
                continue
            dup = False
            for ex in ex_sets:
                if not ex:
                    continue
                inter = len(r_tok & ex)
                union = len(r_tok | ex)
                if union > 0 and inter / union >= threshold:
                    dup = True
                    break
            if not dup:
                kept.append(r)
        return kept

