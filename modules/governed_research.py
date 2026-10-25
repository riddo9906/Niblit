"""modules/governed_research.py - Phase 5A governed web.search / web.fetch.

Wraps existing search authorities behind one stable LLM-facing contract and
provides a bounded, SSRF-safe fetch. Provenance survives; nothing here writes
memory. Failures are structured, never raised raw into the reasoning loop.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from modules.research_contracts import EvidenceItem

log = logging.getLogger("Niblit.GovernedResearch")

MAX_FETCH_BYTES = int(os.environ.get("NIBLIT_RESEARCH_MAX_FETCH_BYTES", "400000"))
FETCH_TIMEOUT = float(os.environ.get("NIBLIT_RESEARCH_FETCH_TIMEOUT", "20"))


def _url_allowed(url: str) -> tuple:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "unparsable url"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme {parsed.scheme!r} not allowed"
    host = parsed.hostname or ""
    if not host:
        return False, "missing host"
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return False, f"dns resolution failed: {exc}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False, f"host resolves to non-public address ({ip})"
    return True, ""


def governed_fetch(url: str, max_bytes: int = MAX_FETCH_BYTES,
                   timeout: float = FETCH_TIMEOUT) -> Dict[str, Any]:
    """Fetch public HTTP(S) text with SSRF/size/timeout guards. Structured
    failures; provenance (url/domain/timestamp/evidence_id) on success."""
    allowed, reason = _url_allowed(url)
    if not allowed:
        return {"error": reason, "url": url}
    req = urllib.request.Request(
        url, headers={"User-Agent": "NiblitResearch/1.0", "Accept": "text/*"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if not any(t in ctype for t in ("text/", "json", "xml")):
                return {"error": f"unsupported content-type {ctype!r}", "url": url}
            final_url = resp.geturl()
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return {"error": f"content exceeds {max_bytes} bytes", "url": url}
            text = data.decode(resp.headers.get_content_charset() or "utf-8",
                               errors="replace")
    except urllib.error.HTTPError as exc:
        return {"error": f"http {exc.code}", "url": url}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": f"network failure: {exc}", "url": url}

    domain = urlparse(final_url).hostname or ""
    item = EvidenceItem(query="", source_url=final_url, source_domain=domain,
                        extracted_text=text[:20000], provider="governed_fetch")
    return {
        "evidence": {"evidence_id": item.evidence_id,
                     "source_url": item.source_url,
                     "source_domain": item.source_domain,
                     "retrieved_at": item.retrieved_at,
                     "extracted_text": item.extracted_text},
        "bytes": len(text), "duration_ms": round((time.time() - t0) * 1000, 1),
    }


class GovernedSearch:
    """Stable web.search contract over pluggable providers."""

    def __init__(self, permission_check=None, provider=None):
        self.permission_check = permission_check
        self._provider = provider  # callable(query, max_results) -> list[dict]

    def _resolve_provider(self):
        if self._provider is not None:
            return self._provider
        for mod, attr in (("modules.pypi_search", "search_pypi"),
                          ("modules.researcher_engine", "search")):
            try:
                module = __import__(mod, fromlist=[attr])
                fn = getattr(module, attr)
                if callable(fn):
                    return lambda q, n: [
                        {"title": r.get("name") or r.get("title", ""),
                         "url": r.get("url") or r.get("package_url", ""),
                         "provider": mod} for r in (fn(q) or [])[:n]
                        if isinstance(r, dict)]
            except Exception:
                continue
        return None

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not query.strip():
            return {"error": "empty query"}
        max_results = min(int(max_results), 10)
        if self.permission_check is not None and not self.permission_check("web.search"):
            return {"error": "permission denied for web.search", "query": query}
        provider = self._resolve_provider()
        if provider is None:
            return {"error": "no search provider available", "query": query}
        t0 = time.time()
        try:
            raw = provider(query, max_results)
        except Exception as exc:
            return {"error": f"provider failure: {exc}", "query": query}
        results: List[Dict[str, Any]] = []
        for r in (raw or [])[:max_results]:
            if isinstance(r, dict) and r.get("url"):
                results.append({
                    "title": str(r.get("title", ""))[:200],
                    "url": r["url"],
                    "domain": urlparse(r["url"]).hostname or "",
                    "provider": str(r.get("provider", "unknown")),
                })
        log.info("[GovernedResearch] search %r -> %d results", query[:80], len(results))
        return {"query": query, "results": results, "count": len(results),
                "duration_ms": round((time.time() - t0) * 1000, 1)}

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public internet via Niblit's governed research "
            "capability. Read-only; structured results with provenance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
}


WEB_FETCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Fetch text content of a public http(s) URL selected from search "
            "evidence. Read-only; provenance preserved."
        ),
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
}
