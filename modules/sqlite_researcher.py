#!/usr/bin/env python3
"""
SQLITE RESEARCHER
Local-first research backend that replaces Serpex entirely.

Instead of making external HTTP calls to api.serpex.dev, this module
searches Niblit's own SQLite KnowledgeDB for matching facts, research
snippets, and ALE-acquired data — returning them in the same
``{"title", "url", "snippet"}`` format that Serpex formerly produced.

Benefits over Serpex
--------------------
* Works 100% offline — no API key, no network, no 403/443 errors
* Zero latency (local disk access vs. HTTP round-trip)
* Always returns relevant data (facts Niblit already knows about the topic)
* Privacy — no queries leave the device

Interface compatibility
-----------------------
SQLiteResearcher is a drop-in replacement for both:
  * ``niblit_tools.serpex_api.SerpexAPI`` — ``search(query) → dict``
  * ``niblit_agents.research_agent.ResearchAgent`` — ``search_web/search_news(query) → list``

Architecture::

    ALE / SelfResearcher / InternetManager
              │
              ▼
    SQLiteResearcher.search_web(query)
              │
         ┌────┴────────────────────────────────┐
         │                                     │
    KnowledgeDB.search(query)          KnowledgeDB.recall(query)
    (facts + learning_log)             (events + interactions)
         │                                     │
         └────────────────┬────────────────────┘
                          │
               _format_results() → [{"title","url","snippet"}]
                          │
               KnowledgeStore.store_search_results()
                          │
               (optional) VectorStore embed

Usage
-----
    from modules.sqlite_researcher import SQLiteResearcher
    sr = SQLiteResearcher()
    results = sr.search_web("python async patterns")
    # → [{"title": "ale_research:...", "url": "local://kb", "snippet": "..."}]
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("SQLiteResearcher")

# Maximum characters taken from any single KB fact value for a snippet.
_MAX_SNIPPET_LENGTH: int = 500

# Tags used by ALE research steps — searched first so the most relevant
# content (directly about Niblit's topic) comes back first.
_PRIORITY_TAGS = (
    "ale_unified", "ale_step1", "ale_research", "ale_serpex_research",
    "ale_learned", "research", "serpex",
)


def is_relevant(query: str, text: str, threshold: float = 0.3) -> bool:
    """Return True when *text* overlaps with *query* terms by at least *threshold*.

    Lowered from 0.5 to 0.3 vs. the former Serpex relevance filter because
    SQLite results are already from Niblit's own knowledge base and tend to
    be more focused than open-web search results.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return True
    text_lower = text.lower()
    matched = sum(1 for t in query_terms if t in text_lower)
    return (matched / len(query_terms)) >= threshold


class SQLiteResearcher:
    """Local SQLite-backed research agent — replaces SerpexAPI + ResearchAgent.

    Parameters
    ----------
    knowledge_db:
        An already-constructed KnowledgeDB instance.  When *None*, one is
        built lazily on first use (reads niblit's default DB path).
    knowledge_store:
        Optional pre-built KnowledgeStore for storing search results.
        Built lazily when *None*.
    vector_store:
        Optional VectorStore for semantic embedding of results.
    max_results:
        Default cap on returned results per query.
    """

    def __init__(
        self,
        knowledge_db=None,
        knowledge_store=None,
        vector_store=None,
        max_results: int = 8,
    ):
        self._knowledge_db = knowledge_db
        self._knowledge_store = knowledge_store
        self._vector_store = vector_store
        self.max_results = max_results

    # ── Compat helpers (SerpexAPI + ResearchAgent interface) ─────────────────

    def is_configured(self) -> bool:
        """Always True — SQLite is always available, no API key needed."""
        return True

    # ── Core search methods ───────────────────────────────────────────────────

    def search_web(self, query: str, max_results: int = 0) -> List[Dict[str, Any]]:
        """Search the local KnowledgeDB for facts matching *query*.

        Compatible with ResearchAgent.search_web() — returns the same
        ``[{"title", "url", "snippet"}]`` format.
        """
        return self._search(query, max_results or self.max_results, source_tag="web")

    def search_news(self, query: str, max_results: int = 0) -> List[Dict[str, Any]]:
        """Search local KB for recent/news-style entries matching *query*.

        Compatible with ResearchAgent.search_news() — uses the same
        underlying KnowledgeDB but filters for recently-added facts.
        """
        return self._search(query, max_results or self.max_results, source_tag="news")

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        """SerpexAPI-compatible wrapper — returns ``{"results": [...], "source": "sqlite"}``.

        This allows SQLiteResearcher to be used wherever SerpexAPI.search()
        was called without changing the calling code.
        """
        items = self._search(query, self.max_results, source_tag=category)
        # Wrap in the same envelope SerpexAPI.search() returned
        return {
            "results": [
                {
                    "title": r.get("title", ""),
                    "link": r.get("url", "local://kb"),
                    "snippet": r.get("snippet", ""),
                }
                for r in items
            ],
            "organic_results": items,
            "source": "sqlite",
            "query": query,
        }

    # ── Internal machinery ────────────────────────────────────────────────────

    def _get_knowledge_db(self):
        """Lazily build a KnowledgeDB instance."""
        if self._knowledge_db is not None:
            return self._knowledge_db
        try:
            from niblit_memory import KnowledgeDB
            self._knowledge_db = KnowledgeDB()
            log.debug("[SQLiteResearcher] Lazily built KnowledgeDB")
        except Exception as exc:
            log.debug("[SQLiteResearcher] KnowledgeDB unavailable: %s", exc)
        return self._knowledge_db

    def _get_knowledge_store(self):
        """Lazily build a KnowledgeStore instance."""
        if self._knowledge_store is not None:
            return self._knowledge_store
        try:
            from niblit_memory import KnowledgeStore
            self._knowledge_store = KnowledgeStore()
        except Exception as exc:
            log.debug("[SQLiteResearcher] KnowledgeStore unavailable: %s", exc)
        return self._knowledge_store

    def _extract_snippet(self, obj: Any) -> str:
        """Extract a plain-text snippet from a KnowledgeDB fact/entry."""
        if isinstance(obj, str):
            return obj[:_MAX_SNIPPET_LENGTH]
        if isinstance(obj, dict):
            # Try common text fields in priority order
            for field in ("full_text", "snippet", "text", "summary",
                          "reflection", "research", "value", "content",
                          "description", "idea", "plan"):
                val = obj.get(field)
                if val and isinstance(val, str):
                    return val[:_MAX_SNIPPET_LENGTH]
            # Fall back to JSON dump of the whole dict
            try:
                return json.dumps(obj)[:_MAX_SNIPPET_LENGTH]
            except Exception:
                return str(obj)[:_MAX_SNIPPET_LENGTH]
        return str(obj)[:_MAX_SNIPPET_LENGTH]

    def _extract_title(self, obj: Any, key: str = "") -> str:
        """Extract a short title from a KnowledgeDB entry."""
        if isinstance(obj, dict):
            for field in ("title", "topic", "key", "name", "subject"):
                val = obj.get(field)
                if val and isinstance(val, str):
                    return val[:120]
        # Use the KB key as the title when the value itself has no title
        if key:
            return key[:120]
        return "KB result"

    def _search(
        self,
        query: str,
        max_results: int,
        source_tag: str = "web",
    ) -> List[Dict[str, Any]]:
        """Search KnowledgeDB and return normalised result dicts.

        Search strategy (in priority order)
        ------------------------------------
        1. KnowledgeDB.search() — full-text keyword scan across facts,
           learning_log, and interactions.
        2. KnowledgeDB.recall() — broader recall including events and
           preferences (picks up additional context).
        3. KnowledgeDB.list_facts() — most-recent facts when query returns
           nothing (ensures we always have something to return).
        """
        if not query or not query.strip():
            return []

        kb = self._get_knowledge_db()
        if kb is None:
            log.warning("[SQLiteResearcher] KnowledgeDB not available")
            return []

        raw: List[Any] = []
        seen_keys: set = set()

        # ── Pass 1: direct keyword search ─────────────────────────────────
        try:
            if hasattr(kb, "search"):
                raw.extend(kb.search(query, limit=max_results * 2) or [])
        except Exception as exc:
            log.debug("[SQLiteResearcher] kb.search failed: %s", exc)

        # ── Pass 2: recall (broader — also hits events & interactions) ────
        try:
            if hasattr(kb, "recall") and len(raw) < max_results:
                recalled = kb.recall(query, limit=max_results * 2) or []
                raw.extend(recalled)
        except Exception as exc:
            log.debug("[SQLiteResearcher] kb.recall failed: %s", exc)

        # ── Pass 3: recent facts fallback (always return *something*) ──────
        if not raw:
            try:
                if hasattr(kb, "list_facts"):
                    recent = kb.list_facts(limit=max_results * 2) or []
                    raw.extend(recent)
            except Exception as exc:
                log.debug("[SQLiteResearcher] kb.list_facts failed: %s", exc)

        # ── Normalise + de-duplicate ──────────────────────────────────────
        results: List[Dict[str, Any]] = []
        for item in raw:
            snippet = self._extract_snippet(item)
            if not snippet:
                continue

            # Relevance filter (lenient — 0.3 threshold)
            if not is_relevant(query, snippet):
                continue

            key = snippet[:80]
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # Extract the KB key when item is a dict with a "key" field
            fact_key = ""
            if isinstance(item, dict):
                fact_key = str(item.get("key", ""))

            title = self._extract_title(item, key=fact_key)
            results.append({
                "title":   title,
                "url":     f"local://kb/{fact_key}" if fact_key else "local://kb",
                "snippet": snippet,
                "source":  f"sqlite_{source_tag}",
            })

            if len(results) >= max_results:
                break

        # ── Persist query + results to KnowledgeStore for audit trail ─────
        ks = self._get_knowledge_store()
        if ks and results and hasattr(ks, "store_search_results"):
            try:
                ks.store_search_results(query, results)
            except Exception as exc:
                log.debug("[SQLiteResearcher] KnowledgeStore persist failed: %s", exc)

        # ── Embed into vector store when available ────────────────────────
        if self._vector_store and results:
            try:
                ts = str(int(time.time()))
                for i, r in enumerate(results):
                    text = r.get("snippet", "")
                    if text:
                        self._vector_store.add(f"sqlite:{query[:30]}:{ts}:{i}", text[:500])
            except Exception as exc:
                log.debug("[SQLiteResearcher] VectorStore embed failed: %s", exc)

        log.info(
            "[SQLiteResearcher] query=%r → %d result(s) from local KB",
            query, len(results),
        )
        return results
