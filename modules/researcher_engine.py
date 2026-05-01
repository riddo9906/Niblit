# modules/researcher_engine.py
# Advanced research engine for NiblitOS v5

import logging
import os
import re

import requests

log = logging.getLogger("ResearcherEngine")

SERPEX_API_URL = "https://api.serpex.dev/api/search"

# ── canonical memory ──────────────────────────────────────────────────────────
try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]

# ── optional Qdrant client (direct access) ────────────────────────────────────
try:
    from qdrant_client import QdrantClient as _QdrantClient
    _QDRANT_LIB_AVAILABLE = True
except ImportError:
    _QdrantClient = None  # type: ignore[assignment,misc]
    _QDRANT_LIB_AVAILABLE = False


class ResearcherEngine:
    """
    Web research engine with optional Qdrant-backed result caching.

    When ``QDRANT_URL`` is set, a :class:`qdrant_client.QdrantClient` is
    initialised and exposed via :attr:`qdrant_client`.  A
    :class:`modules.vector_store.VectorStore` (which re-uses the same backend)
    is stored as :attr:`vector_store`.

    Research workflow
    -----------------
    1. :meth:`run` checks the vector store for a cached summary of *topic*.
    2. If a sufficiently fresh result is found it is returned immediately.
    3. Otherwise the web is searched via SerpEx → DuckDuckGo fallback.
    4. The new result is stored in the vector store for future calls.
    5. Results are also stored in niblit_memory for cross-module availability.
    """

    def __init__(
        self,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        memory=None,
    ) -> None:
        _url = qdrant_url or os.environ.get("QDRANT_URL", "")
        _key = qdrant_api_key or os.environ.get("QDRANT_API_KEY", "")

        # ── Canonical niblit_memory ───────────────────────────────────────────
        self.memory = memory or _GLOBAL_MEMORY

        # ── Qdrant direct client ──────────────────────────────────────────────
        self.qdrant_client = None
        if _url and _QDRANT_LIB_AVAILABLE and _QdrantClient is not None:
            try:
                kwargs = {"url": _url, "timeout": 10}
                if _key:
                    kwargs["api_key"] = _key
                self.qdrant_client = _QdrantClient(**kwargs)
                log.info(
                    "ResearcherEngine: Qdrant client connected (%s) — collections: %s",
                    _url,
                    ", ".join(c.name for c in self.qdrant_client.get_collections().collections),
                )
            except Exception as exc:
                log.warning("ResearcherEngine: Qdrant connection failed: %s", exc)
                self.qdrant_client = None

        # ── VectorStore (uses same Qdrant backend when available) ─────────────
        self.vector_store = None
        try:
            from modules.vector_store import VectorStore
            self.vector_store = VectorStore(
                collection="niblit_research",
                qdrant_url=_url,
                qdrant_api_key=_key,
            )
        except Exception as exc:
            log.debug("ResearcherEngine: VectorStore unavailable: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────────────

    def clean(self, text):
        return re.sub(r"\s+", " ", text).strip()

    def serpex_search(self, topic: str, api_key: str) -> str | None:
        """Search via SerpEx API and return the best text snippet."""
        params = {
            "q": topic,
            "engine": "auto",
            "category": "web",
            "time_range": "week",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            r = requests.get(SERPEX_API_URL, headers=headers, params=params, timeout=300)
            r.raise_for_status()
            data = r.json()
            items = (
                data.get("organic_results")
                or data.get("results")
                or []
            )
            snippets = []
            # Featured answer box
            box = data.get("answer_box") or data.get("knowledge_graph")
            if isinstance(box, dict):
                text = box.get("description") or box.get("answer") or box.get("snippet", "")
                if text:
                    snippets.append(str(text))
            for item in items[:3]:
                if isinstance(item, dict):
                    text = (
                        item.get("snippet")
                        or item.get("description")
                        or item.get("content")
                        or ""
                    )
                    if text:
                        snippets.append(str(text))
            return " ".join(snippets) if snippets else None
        except Exception:
            return None

    def web_search(self, topic: str) -> str | None:
        """Search the web for *topic* and return the best text snippet found.

        Search priority:
        1. SerpEx (when ``SERPEX_API_KEY`` is set) — highest-quality structured results
        2. DuckDuckGo instant-answer API — free, no key required
        3. Wikipedia summary API — high-authority fallback for factual topics

        Returns *None* when all sources fail or return nothing useful.
        """
        # Try SerpEx first if API key is available
        serpex_key = os.getenv("SERPEX_API_KEY", "")
        if serpex_key:
            result = self.serpex_search(topic, serpex_key)
            if result and len(result.strip()) >= 10:
                return result

        # DuckDuckGo instant-answer API (free, no key)
        try:
            url = f"https://api.duckduckgo.com/?q={requests.utils.quote(topic)}&format=json&no_html=1"
            r = requests.get(url, timeout=10)
            js = r.json()
            abstract = js.get("AbstractText", "")
            if abstract and len(abstract) >= 30:
                return abstract
            # Collect related topic snippets as a fallback
            related_texts = [
                t["Text"]
                for t in js.get("RelatedTopics", [])
                if isinstance(t, dict) and len(t.get("Text", "")) >= 30
            ]
            if related_texts:
                return " ".join(related_texts[:3])
        except Exception:
            pass

        # Wikipedia summary API (reliable free source for factual topics)
        try:
            wiki_search_url = "https://en.wikipedia.org/w/api.php"
            r = requests.get(
                wiki_search_url,
                params={"action": "query", "list": "search", "srsearch": topic, "format": "json"},
                timeout=10,
            )
            hits = r.json().get("query", {}).get("search", [])
            if hits:
                title = hits[0]["title"]
                r2 = requests.get(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/{}".format(
                        requests.utils.quote(title.replace(" ", "_"), safe="")
                    ),
                    timeout=10,
                )
                if r2.status_code == 200:
                    extract = r2.json().get("extract", "")
                    if extract and len(extract) >= 10:
                        return extract
        except Exception:
            pass

        return None

    def _check_cache(self, topic: str) -> str | None:
        """Return a cached summary from the vector store, or None."""
        if self.vector_store is None:
            return None
        try:
            hits = self.vector_store.search(topic, top_k=1)
            if hits and hits[0].get("score", 0) >= 0.85:
                cached = hits[0].get("text", "")
                if cached:
                    log.debug("ResearcherEngine: cache hit for '%s' (score=%.2f)", topic, hits[0]["score"])
                    return cached
        except Exception:
            pass
        return None

    def _store_result(self, topic: str, summary: str) -> None:
        """Persist a research summary to the vector store and niblit_memory."""
        # Vector store
        if self.vector_store is not None and summary:
            try:
                import hashlib
                from datetime import datetime, timezone
                ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                doc_id = f"research:{hashlib.md5(topic.encode()).hexdigest()[:12]}:{ts}"
                # Build short topic label — never store topic slug as payload field.
                try:
                    from modules.qdrant_tools import TopicSummariser as _TS  # type: ignore[import]
                    _topic_label = _TS.summarise(summary, hint=topic)
                except Exception:
                    _topic_label = topic[:80]
                self.vector_store.add(doc_id, summary[:6000], topic=_topic_label)
            except Exception as exc:
                log.debug("ResearcherEngine: failed to store result in VectorStore: %s", exc)

        # niblit_memory canonical store
        if self.memory is not None and summary:
            try:
                key = f"research:{topic[:80]}"
                if hasattr(self.memory, "add_fact"):
                    self.memory.add_fact(key, summary[:500], tags=["research", "web"])
                elif hasattr(self.memory, "store_learning"):
                    self.memory.store_learning({"topic": topic, "summary": summary[:500], "tags": ["research"]})
            except Exception as exc:
                log.debug("ResearcherEngine: niblit_memory store failed: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, topic: str) -> dict:
        """Research *topic* and return ``{"topic": str, "summary": str}``.

        Follows the multi-query retrieval pattern: instead of a single flat
        search, up to 3 aspect queries are tried in sequence (conceptual →
        mechanistic → practical) until a useful snippet is found.  This
        mirrors the strategy used by PhasedResearchEngine.

        The vector-store cache is checked first, and the final result is
        always stored for future lookups.
        """
        # 1. Check vector-store cache
        cached = self._check_cache(topic)
        if cached:
            return {"topic": topic, "summary": cached, "source": "cache"}

        # 2. Build expanded queries — try each until we get useful content.
        #    _expand_topic_queries is imported from phased_research_engine;
        #    if unavailable we fall back to a simple list of [topic].
        try:
            from modules.phased_research_engine import _expand_topic_queries
            queries = _expand_topic_queries(topic)
        except Exception:
            queries = [topic]

        best_result: str | None = None
        for query in queries:
            raw = self.web_search(query)
            if raw:
                cleaned = self.clean(str(raw))
                if len(cleaned) >= 10:
                    best_result = cleaned
                    break

        if not best_result:
            return {"error": "No research results."}

        # 3. Persist to vector store and memory
        self._store_result(topic, best_result)

        return {"topic": topic, "summary": best_result, "source": "web"}

engine = ResearcherEngine()

def run(topic):
    return engine.run(topic)


if __name__ == "__main__":
    print('Running researcher_engine.py')
