# modules/researcher_engine.py
# Advanced research engine for NiblitOS v5

import logging
import os
import re

import requests

log = logging.getLogger("ResearcherEngine")

SERPEX_API_URL = "https://api.serpex.dev/api/search"

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
    """

    def __init__(
        self,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        _url = qdrant_url or os.environ.get("QDRANT_URL", "")
        _key = qdrant_api_key or os.environ.get("QDRANT_API_KEY", "")

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
            r = requests.get(SERPEX_API_URL, headers=headers, params=params, timeout=10)
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

    def web_search(self, topic):
        # Try SerpEx first if API key is available
        serpex_key = os.getenv("SERPEX_API_KEY", "")
        if serpex_key:
            result = self.serpex_search(topic, serpex_key)
            if result:
                return result

        # Fallback: DuckDuckGo
        try:
            url = f"https://api.duckduckgo.com/?q={topic}&format=json"
            r = requests.get(url, timeout=10)
            js = r.json()
            return js.get("AbstractText") or js.get("RelatedTopics", [])
        except Exception:
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
        """Persist a research summary to the vector store."""
        if self.vector_store is None or not summary:
            return
        try:
            import hashlib
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            doc_id = f"research:{hashlib.md5(topic.encode()).hexdigest()[:12]}:{ts}"
            self.vector_store.add(doc_id, summary[:1000])
        except Exception as exc:
            log.debug("ResearcherEngine: failed to store result: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, topic):
        """Research *topic* and return ``{"topic": str, "summary": str}``.

        Checks the vector store for a cached result first.  New results are
        stored in the vector store for future lookups.
        """
        # 1. Check vector-store cache
        cached = self._check_cache(topic)
        if cached:
            return {"topic": topic, "summary": cached, "source": "cache"}

        # 2. Live web search
        result = self.web_search(topic)
        if not result:
            return {"error": "No research results."}

        cleaned = self.clean(str(result))

        # 3. Persist to vector store
        self._store_result(topic, cleaned)

        return {"topic": topic, "summary": cleaned, "source": "web"}

engine = ResearcherEngine()

def run(topic):
    return engine.run(topic)


if __name__ == "__main__":
    print('Running researcher_engine.py')
