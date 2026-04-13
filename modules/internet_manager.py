#!/usr/bin/env python3
# modules/internet_manager.py

import os
import json
import logging
import requests
import re
import html

log = logging.getLogger(__name__)

# ── SerpAPI monthly search quota ─────────────────────────────────────────────
SERPAPI_MONTHLY_LIMIT: int = 250
# Counter state is persisted in this file (same directory as this module)
_SERPAPI_COUNTER_FILE = os.path.join(os.path.dirname(__file__), "serpapi_usage.json")


def _load_serpapi_counter() -> dict:
    """Load the SerpAPI usage counter from disk, or return a fresh record."""
    try:
        with open(_SERPAPI_COUNTER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_serpapi_counter(data: dict) -> None:
    """Persist the SerpAPI usage counter to disk."""
    try:
        with open(_SERPAPI_COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as exc:
        log.warning("serpapi_counter: could not save usage file: %s", exc)


def _get_current_month_key() -> str:
    """Return a YYYY-MM string for the current calendar month."""
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m")


def _serpapi_check_and_increment() -> bool:
    """Return True and increment the counter if below the monthly limit.

    Returns False (without incrementing) when the limit has been reached,
    and resets the counter automatically when the calendar month changes.
    """
    month_key = _get_current_month_key()
    data = _load_serpapi_counter()
    # Reset counter on a new month
    if data.get("month") != month_key:
        data = {"month": month_key, "count": 0}
    count = data.get("count", 0)
    if count >= SERPAPI_MONTHLY_LIMIT:
        log.warning(
            "serpapi_counter: monthly limit of %d searches reached for %s — "
            "SerpAPI calls are disabled until next month.",
            SERPAPI_MONTHLY_LIMIT,
            month_key,
        )
        return False
    data["count"] = count + 1
    _save_serpapi_counter(data)
    return True


try:
    from bs4 import BeautifulSoup  # for extracting text from HTML
    BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BS4_AVAILABLE = False

# Optional: pip install googlesearch-python
try:
    from googlesearch import search as google_search
    GOOGLE_ENABLED = True
except ImportError:
    GOOGLE_ENABLED = False

# Optional: pip install ddgs  (formerly duckduckgo-search; package renamed)
try:
    from ddgs import DDGS  # new package name (ddgs)
    DDGS_ENABLED = True
except ImportError:
    try:
        from duckduckgo_search import DDGS  # legacy fallback
        DDGS_ENABLED = True
    except ImportError:
        DDGS = None  # type: ignore[assignment,misc]
        DDGS_ENABLED = False

# Optional: pip install google-search-results
try:
    from serpapi import GoogleSearch as SerpApiGoogleSearch
    SERPAPI_ENABLED = True
except ImportError:
    SerpApiGoogleSearch = None  # type: ignore[assignment,misc]
    SERPAPI_ENABLED = False

DDG_API = "https://api.duckduckgo.com/"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
SERPEX_API_URL = "https://api.serpex.dev/api/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Niblit/1.0)"
}


class InternetManager:
    def __init__(self, db=None, llm_adapter=None, timeout=300, serpex_api_key=None,
                 semantic_agent=None, searchcode_search=None, serpapi_api_key=None):
        self.db = db
        self.llm = llm_adapter
        self.timeout = timeout
        # SerpEx key: explicit param > env var (loaded from .env by orchestrator)
        self.serpex_api_key: str = serpex_api_key or os.getenv("SERPEX_API_KEY", "")
        # SerpAPI key: explicit param > env var
        self.serpapi_api_key: str = serpapi_api_key or os.getenv("SERPAPI_API_KEY", "")
        # Optional semantic storage backend (injected by niblit_core)
        self.semantic_agent = semantic_agent
        # Optional Searchcode backend (injected by niblit_core)
        self.searchcode_search = searchcode_search

    # ─────────────────────────────
    def is_online(self):
        try:
            r = requests.get("https://api.ipify.org?format=json", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    # ─────────────────────────────
    # SERPEX SEARCH
    # Primary search when SERPEX_API_KEY is configured.
    def _serpex_search(
        self,
        query: str,
        max_results: int = 5,
        category: str = "web",
        time_range: str = "week",
    ):
        """Call the SerpEx search API and return a list of result dicts.

        Args:
            query:       Search query string.
            max_results: Maximum number of results to return.
            category:    ``"web"`` or ``"news"``.  News searches always
                         return the latest content and ignore *time_range*.
            time_range:  ``"day"``, ``"week"``, or ``"month"`` (web only).

        Returns:
            List of ``{"source": str, "text": str, "url": str|None}`` dicts,
            or an empty list if the request fails or no key is configured.
        """
        if not self.serpex_api_key:
            return []

        params = {
            "q": query,
            "engine": "auto" if category == "web" else "google",
            "category": category,
        }
        if category == "web":
            params["time_range"] = time_range

        headers = {
            "Authorization": f"Bearer {self.serpex_api_key}",
        }

        try:
            response = requests.get(
                SERPEX_API_URL,
                headers=headers,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        results = []
        # SerpEx returns results in an "organic_results" or "results" list
        raw_list = (
            data.get("organic_results")
            or data.get("results")
            or data.get("news_results")
            or []
        )
        # Also check a top-level "answer_box" / "knowledge_graph"
        for top_key in ("answer_box", "knowledge_graph"):
            box = data.get(top_key)
            if isinstance(box, dict):
                text = box.get("description") or box.get("answer") or box.get("snippet", "")
                if text:
                    results.append({"source": "serpex_featured", "text": str(text), "url": None})

        for item in raw_list[:max_results]:
            if not isinstance(item, dict):
                continue
            text = (
                item.get("snippet")
                or item.get("description")
                or item.get("content")
                or item.get("text")
                or ""
            )
            url = item.get("link") or item.get("url")
            title = item.get("title", "")
            if title and text:
                text = f"{title}: {text}"
            elif title:
                text = title
            if text:
                results.append({"source": "serpex", "text": str(text), "url": url})

        return results

    # ─────────────────────────────
    # SERPAPI SEARCH
    # Uses the google-search-results package + SERPAPI_API_KEY.
    def _serpapi_search(self, query: str, max_results: int = 5):
        """Search via SerpAPI (https://serpapi.com) and return result dicts.

        Requires ``google-search-results`` package and ``SERPAPI_API_KEY`` env var
        (or ``serpapi_api_key`` constructor parameter).

        Returns:
            List of ``{"source": str, "text": str, "url": str|None}`` dicts,
            or an empty list on failure / missing key / package not installed.
        """
        if not SERPAPI_ENABLED or not self.serpapi_api_key:
            return []

        if not _serpapi_check_and_increment():
            return []

        try:
            params = {
                "q": query,
                "api_key": self.serpapi_api_key,
                "num": max_results,
                "hl": "en",
            }
            search_obj = SerpApiGoogleSearch(params)
            data = search_obj.get_dict()
        except Exception:
            return []

        results = []
        # Featured / answer box
        answer = (
            data.get("answer_box", {}).get("answer")
            or data.get("answer_box", {}).get("snippet")
            or data.get("knowledge_graph", {}).get("description")
        )
        if answer:
            results.append({"source": "serpapi_featured", "text": str(answer), "url": None})

        for item in data.get("organic_results", [])[:max_results]:
            if not isinstance(item, dict):
                continue
            text = item.get("snippet") or item.get("title") or ""
            if text:
                results.append({
                    "source": "serpapi",
                    "text": str(text),
                    "url": item.get("link"),
                })

        return results

    # ─────────────────────────────
    # SMART SEARCH
    # Returns structured results with source, text, and optional url
    def search(self, query, max_results=5, use_llm=True):
        results = []

        # ───────── SERPEX (primary — used when SERPEX_API_KEY is set) ─────────
        if self.serpex_api_key:
            try:
                serpex_results = self._serpex_search(
                    query, max_results=max_results, category="web"
                )
                if serpex_results:
                    results.extend(serpex_results)
            except Exception:
                pass

            # Also fetch news for richer context
            try:
                news_results = self._serpex_search(
                    query, max_results=max(2, max_results // 2), category="news"
                )
                if news_results:
                    results.extend(news_results)
            except Exception:
                pass

        # ───────── SERPAPI (secondary — used when SERPAPI_API_KEY is set) ─────────
        if not results and self.serpapi_api_key:
            try:
                serpapi_results = self._serpapi_search(query, max_results=max_results)
                if serpapi_results:
                    results.extend(serpapi_results)
            except Exception:
                pass

        # ───────── DUCKDUCKGO (fallback when no paid API key) ─────────
        if not results:
            # Prefer duckduckgo-search package (returns real multi-result search)
            if DDGS_ENABLED:
                try:
                    with DDGS() as ddgs:
                        ddg_hits = ddgs.text(query, max_results=max_results)
                    for hit in (ddg_hits or []):
                        # duckduckgo-search ≥6 returns 'body'; older versions
                        # used 'snippet'. Check both for forward/backward compat.
                        text = hit.get("body") or hit.get("snippet") or ""
                        if text:
                            results.append({
                                "source": "duckduckgo",
                                "text": text,
                                "url": hit.get("href"),
                            })
                except Exception:
                    pass

            # Fallback: DDG instant-answer JSON API (no package required)
            if not results:
                try:
                    r = requests.get(
                        DDG_API,
                        params={"q": query, "format": "json", "no_html": 1},
                        timeout=self.timeout
                    )
                    js = r.json()
                    if js.get("AbstractText"):
                        results.append({"source": "duckduckgo", "text": js["AbstractText"], "url": None})
                    for t in js.get("RelatedTopics", []):
                        if isinstance(t, dict) and t.get("Text"):
                            results.append({"source": "duckduckgo", "text": t["Text"], "url": None})
                except Exception:
                    pass

            # ───────── WIKIPEDIA (fallback) ─────────
            try:
                # Search API
                r = requests.get(
                    WIKI_SEARCH,
                    params={"action": "query", "list": "search", "srsearch": query, "format": "json"},
                    headers=HEADERS,
                    timeout=self.timeout
                )
                js = r.json()
                search_hits = js.get("query", {}).get("search", [])
                if search_hits:
                    title = search_hits[0]["title"]
                    # Summary API
                    r2 = requests.get(WIKI_SUMMARY.format(title.replace(" ", "_")), headers=HEADERS, timeout=self.timeout)
                    if r2.status_code == 200:
                        js2 = r2.json()
                        if js2.get("extract"):
                            results.append({
                                "source": "wikipedia",
                                "text": js2["extract"],
                                "url": js2.get("content_urls", {}).get("desktop", {}).get("page")
                            })
            except Exception:
                pass

            # ───────── GOOGLE + MULTI AI SNIPPETS (fallback) ─────────
            if GOOGLE_ENABLED:
                ai_snippets = []
                try:
                    if BS4_AVAILABLE:
                        # Fetch main Google AI snippet
                        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
                        r_snip = requests.get(search_url, headers=HEADERS, timeout=self.timeout)
                        if r_snip.status_code == 200:
                            soup = BeautifulSoup(r_snip.text, "html.parser")
                            snippet_divs = soup.find_all("div", class_=re.compile(r"(ayqGOc|xpdopen)"))
                            for div in snippet_divs:
                                snippet_text = div.get_text(separator=" ", strip=True)
                                if snippet_text and snippet_text not in ai_snippets:
                                    ai_snippets.append(snippet_text)

                        # Collect content from multiple Google URLs
                        google_urls = list(google_search(query, num_results=max_results * 5))
                        for url in google_urls:
                            try:
                                page = requests.get(url, timeout=self.timeout, headers=HEADERS)
                                if page.status_code == 200:
                                    soup = BeautifulSoup(page.text, "html.parser")
                                    page_text = ' '.join(p.get_text(separator=' ') for p in soup.find_all('p'))
                                    if page_text:
                                        results.append({"source": "google", "text": page_text, "url": url})
                            except Exception:
                                continue
                except Exception:
                    pass

                # Add AI snippets as individual entries
                for snippet in ai_snippets:
                    results.append({"source": "google_ai", "text": snippet, "url": None})

        # ───────── CLEAN SENTENCES ─────────
        cleaned_results = []
        for entry in results:
            sentences = re.split(r'(?<=[.!?])\s+', entry["text"])
            unique_sentences = []
            for s in sentences:
                s_clean = re.sub(r"\s+", " ", html.unescape(s)).strip()
                if s_clean and s_clean not in unique_sentences:
                    unique_sentences.append(s_clean)
            # Limit number of sentences per entry
            entry["text"] = " ".join(unique_sentences[:max_results])
            cleaned_results.append(entry)

        # ───────── SEARCHCODE (code-aware supplement) ─────────
        # When a searchcode backend is available, augment with real code examples.
        if self.searchcode_search and not getattr(self.searchcode_search, "_unavailable", False):
            try:
                sc_results = self.searchcode_search.search_code(query, per_page=3)
                if sc_results:
                    for item in sc_results:
                        text = item.get("snippet") or item.get("text") or ""
                        if not text and "lines" in item:
                            lines = item.get("lines", {})
                            if isinstance(lines, dict):
                                text = " ".join(str(v) for v in lines.values())[:400]
                        if text:
                            cleaned_results.append({
                                "source": "searchcode",
                                "text": text,
                                "url": item.get("url", ""),
                            })
            except Exception:
                pass

        # ───────── SEMANTIC STORAGE ─────────
        # Persist collected results into the vector store so future queries
        # can retrieve them semantically.
        if self.semantic_agent and cleaned_results:
            try:
                self.semantic_agent.store_knowledge(
                    [{"snippet": r["text"], "title": r.get("source", ""), "url": r.get("url")}
                     for r in cleaned_results if r.get("text")],
                    source="internet_manager",
                    query=query,
                )
            except Exception:
                pass

        # ───────── LLM REWRITE ─────────
        if use_llm and self.llm:
            try:
                for entry in cleaned_results:
                    rewritten = self.llm.generate(
                        f"Rewrite the following information in clear, concise, factual words:\n{entry['text']}",
                        max_tokens=300
                    )
                    if rewritten:
                        entry["text"] = rewritten
            except Exception:
                pass

        return cleaned_results


# ─────────────────────────────
if __name__ == "__main__":
    im = InternetManager()
    for res in im.search("queued learning"):
        print(res)
