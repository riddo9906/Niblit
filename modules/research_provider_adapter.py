"""NIBLIT PHASE 5B — TASK 1: REAL SEARCH PROVIDER ADAPTER.

Bridges Niblit's existing key-free research engine
(`modules.researcher_engine.ResearcherEngine.web_search_hits`, the Phase 5B
structured variant of the same SerpEx -> DuckDuckGo -> Wikipedia chain used
by `web_search`) into the stable Phase 5A GovernedSearch result contract.

Design rules honored:
- NO new crawler / second search architecture (thin normalization boundary).
- Provider identity is preserved on every result.
- Results are strictly bounded.
- Nothing here touches memory or persistence.
- Failures are surfaced, never silently converted to fake success.
- Legacy summary-only engines degrade honestly: URL-less summaries are
  dropped (no fabricated provenance), never promoted into fake hits.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

PROVIDER_NAME = "duckduckgo"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def normalize_hit(raw: Any, query: str, rank: int,
                  retrieved_at: Optional[str] = None) -> Dict[str, Any]:
    """Normalize one provider hit (dict or attribute object) into the contract shape."""
    hit: Dict[str, Any]
    if isinstance(raw, dict):
        hit = dict(raw)
    else:
        hit = {}
        for attr in ("title", "name", "url", "href", "link", "snippet", "body",
                     "summary", "description", "source"):
            if hasattr(raw, attr):
                hit[attr] = getattr(raw, attr)

    timestamp = retrieved_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "query": query,
        "title": _as_text(hit.get("title") or hit.get("name")),
        "url": _as_text(hit.get("url") or hit.get("href") or hit.get("link")),
        "snippet": _as_text(hit.get("snippet") or hit.get("body")
                            or hit.get("summary") or hit.get("description")),
        "provider": PROVIDER_NAME,
        "source": hit.get("source") or PROVIDER_NAME,
        "rank": hit["rank"] if isinstance(hit.get("rank"), int) else rank,
        "retrieved_at": timestamp,
    }


class DuckDuckGoSearchProvider:
    """GovernedSearch-compatible provider over the existing research engine."""

    name = PROVIDER_NAME

    def __init__(self, max_results_default: int = 5) -> None:
        self.max_results_default = int(max_results_default)
        self._engine: Any = None

    def _resolve_engine(self) -> Any:
        """Instantiate the real engine once (key-free; Qdrant optional)."""
        if self._engine is None:
            from modules.researcher_engine import ResearcherEngine

            self._engine = ResearcherEngine()
        return self._engine

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Run the real provider. Raises on provider failure (callers decide policy)."""
        limit = int(max_results or self.max_results_default)
        if not query or not query.strip():
            raise ValueError("empty_search_query")

        engine = self._resolve_engine()
        raw_results = None
        hits_fn = getattr(engine, "web_search_hits", None)
        if callable(hits_fn):
            raw_results = hits_fn(query.strip(), limit)
        if raw_results is None:
            # Legacy summary-only engine: degrade honestly to a single
            # URL-less hit; GovernedSearch drops it and callers see the gap.
            summary = engine.web_search(query.strip())
            raw_results = [{"title": query.strip()[:120], "url": "",
                            "snippet": summary or ""}]

        if not raw_results:
            return []

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        results: List[Dict[str, Any]] = []
        rank = 1
        for raw in list(raw_results)[:limit]:
            normalized = normalize_hit(raw, query.strip(), rank, timestamp)
            if normalized["url"]:
                results.append(normalized)
                rank += 1
        return results[:limit]
