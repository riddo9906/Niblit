#!/usr/bin/env python3
# modules/internet_manager.py
"""
InternetManager - lightweight Termux-friendly internet utilities.

Provides:
 - is_online()
 - ping(host)
 - get_latency(host, tries)
 - fetch_url(url) -> dict{status_code, text}
 - search_web(query) -> list[str]
 - search(query) -> alias to search_web
 - info() -> dict
 - status() -> brief string
"""
import time
import requests
import html
import re
from typing import List, Dict, Any

DDG_API = "https://api.duckduckgo.com/"
WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"

class InternetManager:
    def __init__(self, db=None, timeout: int = 6):
        """
        db: optional DB object (will be used for logging)
        timeout: HTTP timeout in seconds
        """
        self.timeout = timeout
        self.db = db

    # --------------------------
    # Basic checks & info
    # --------------------------
    def is_online(self) -> bool:
        try:
            r = requests.get("https://api.ipify.org?format=json", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    def info(self) -> Dict[str, Any]:
        return {
            "online": self.is_online(),
            "timeout": self.timeout,
            "provider": "duckduckgo+wiki",
        }

    def status(self) -> str:
        i = self.info()
        return f"online={i.get('online')} timeout={i.get('timeout')} provider={i.get('provider')}"

    # --------------------------
    # Ping / latency
    # --------------------------
    def ping(self, host: str = "https://duckduckgo.com") -> Dict[str, Any]:
        try:
            start = time.time()
            r = requests.get(host, timeout=self.timeout)
            latency = int((time.time() - start) * 1000)
            out = {"ok": r.ok, "status_code": r.status_code, "latency_ms": latency, "url": host}
            if self.db and hasattr(self.db, "add_fact"):
                try:
                    self.db.add_fact("net:ping", out, tags=["net"])
                except Exception:
                    pass
            return out
        except Exception as e:
            return {"ok": False, "error": str(e), "url": host}

    def get_latency(self, host: str = "https://duckduckgo.com", tries: int = 2) -> Any:
        latencies = []
        for _ in range(max(1, tries)):
            r = self.ping(host)
            if r.get("ok"):
                latencies.append(r.get("latency_ms", 9999))
        return min(latencies) if latencies else None

    # --------------------------
    # Fetch a URL (lightweight)
    # --------------------------
    def fetch_url(self, url: str, max_len: int = 4000) -> Dict[str, Any]:
        try:
            r = requests.get(url, timeout=self.timeout)
            text = r.text or ""
            text = re.sub(r'\s+', ' ', html.unescape(text))
            snippet = text[:max_len]
            return {"status_code": r.status_code, "text": snippet, "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

    # --------------------------
    # DuckDuckGo Instant Answer + Wikipedia fallback
    # --------------------------
    def _ddg_instant(self, query: str) -> List[str]:
        try:
            params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
            r = requests.get(DDG_API, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            results = []
            if data.get("AbstractText"):
                results.append(data.get("AbstractText"))
            if data.get("Answer"):
                results.append(str(data.get("Answer")))
            if data.get("RelatedTopics"):
                for t in data["RelatedTopics"][:6]:
                    if isinstance(t, dict):
                        txt = t.get("Text") or t.get("Result") or ""
                        if txt:
                            results.append(txt)
            if not results and data.get("Results"):
                for res in data.get("Results", [])[:5]:
                    if isinstance(res, dict):
                        txt = res.get("Text") or res.get("Result") or ""
                        if txt:
                            results.append(txt)
            return results
        except Exception:
            return []

    def _wiki_summary(self, query: str) -> List[str]:
        try:
            q = query.strip().replace(" ", "_")
            r = requests.get(WIKI_API.format(q), timeout=self.timeout)
            if r.status_code == 200:
                js = r.json()
                if js.get("extract"):
                    txt = js.get("extract")
                    sents = re.split(r'(?<=[.!?])\s+', txt)
                    return sents[:3]
            return []
        except Exception:
            return []

    def search_web(self, query: str, max_results: int = 5) -> List[str]:
        """
        High-level search:
         - try DuckDuckGo instant JSON
         - fallback to Wikipedia summary if sparse
         - return cleaned list of snippets
        """
        if not query:
            return []

        out = []
        try:
            out.extend(self._ddg_instant(query))
            if len(out) < 2:
                out.extend(self._wiki_summary(query))
        except Exception:
            pass

        if not out:
            out = [f"No instant answers for '{query}'. Try a web search."]

        cleaned = []
        for t in out:
            if not t:
                continue
            s = re.sub(r'\s+', ' ', html.unescape(str(t))).strip()
            if s and s not in cleaned:
                cleaned.append(s)
            if len(cleaned) >= max_results:
                break

        # optional logging to DB
        if self.db and hasattr(self.db, "add_fact"):
            try:
                self.db.add_fact("net:search", {"query": query, "results_count": len(cleaned)}, tags=["net", "search"])
            except Exception:
                pass

        return cleaned

    # alias used by other modules / core (compatibility)
    def search(self, query: str, max_results: int = 5) -> List[str]:
        return self.search_web(query, max_results=max_results)
