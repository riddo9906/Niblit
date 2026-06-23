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
            json.dump(data, f, indent=2)
    except OSError as exc:
        log.warning("serpapi_counter: could not save usage file: %s", exc)


def _get_current_month_key() -> str:
    """Return a YYYY-MM string for the current calendar month."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


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

# Optional: pip install ddgs
try:
    from ddgs import DDGS
    DDGS_ENABLED = True
except ImportError:
    try:
        from duckduckgo_search import DDGS  # legacy fallback (pre-rename)
        DDGS_ENABLED = True
    except ImportError:
        DDGS = None  # type: ignore[assignment,misc]
        DDGS_ENABLED = False

if DDGS_ENABLED:
    # Suppress expected INFO-level "Error in engine duckduckgo: TimeoutException" messages
    # that the ddgs library emits when cloud IPs are blocked by DuckDuckGo's HTML endpoint.
    # These timeouts are handled gracefully by the caller; the log noise is not useful.
    import logging as _logging
    _logging.getLogger("ddgs").setLevel(_logging.WARNING)

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
    # Use a realistic browser UA to reduce bot-detection false-positives.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Minimum number of characters a snippet must contain to be worth keeping.
# Shorter strings are typically navigation links, headings, or bare titles.
_MIN_SNIPPET_LEN: int = 15

# Source quality tier — lower value = higher quality.
# Used by _rank_by_source_quality() to sort results before returning them.
_SOURCE_QUALITY: dict = {
    "serpex_featured": 0,
    "serpapi_featured": 0,
    "serpex": 1,
    "serpapi": 1,
    "wikipedia": 2,
    "duckduckgo": 3,
    "google_ai": 3,
    "searchcode": 3,
    "google": 4,
}


def _deduplicate_results(results: list) -> list:
    """Remove duplicate and near-duplicate search results.

    Two-stage deduplication:
    1. **URL dedup** — if the same URL appears more than once, keep only
       the first occurrence (which tends to have the richer snippet).
    2. **Text-overlap dedup** — if a new result shares ≥ 65 % of its tokens
       with an already-accepted result, it is a near-duplicate and is dropped.
       This removes "echo" results where different sources quote the same
       paragraph verbatim.

    Entries whose text is shorter than *_MIN_SNIPPET_LEN* are always dropped
    as they carry too little information to be useful.
    """
    seen_urls: set = set()
    accepted_texts: list = []
    out: list = []

    for entry in results:
        text = (entry.get("text") or "").strip()
        url = (entry.get("url") or "").strip()

        if not text or len(text) < _MIN_SNIPPET_LEN:
            continue

        # URL-level dedup
        if url and url in seen_urls:
            continue

        # Token-overlap dedup
        text_tokens = set(text.lower().split())
        if not text_tokens:
            continue
        is_duplicate = False
        for kept_text in accepted_texts:
            kept_tokens = set(kept_text.lower().split())
            if not kept_tokens:
                continue
            overlap = len(text_tokens & kept_tokens) / max(len(text_tokens), len(kept_tokens))
            if overlap >= 0.65:
                is_duplicate = True
                break
        if is_duplicate:
            continue

        if url:
            seen_urls.add(url)
        accepted_texts.append(text)
        out.append(entry)

    return out


def _rank_by_source_quality(results: list) -> list:
    """Sort results so the highest-quality sources appear first.

    Uses the *_SOURCE_QUALITY* tier map.  Results from the same tier are
    kept in their original order (stable sort) so that within-tier ordering
    established by the search backends is preserved.
    """
    return sorted(results, key=lambda r: _SOURCE_QUALITY.get(r.get("source", ""), 5))


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
                    with DDGS(timeout=10) as ddgs:
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
                        # Fetch Google AI snippet box (fast — just parse the SERP HTML)
                        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
                        r_snip = requests.get(search_url, headers=HEADERS, timeout=10)
                        if r_snip.status_code == 200:
                            soup = BeautifulSoup(r_snip.text, "html.parser")
                            snippet_divs = soup.find_all("div", class_=re.compile(r"(ayqGOc|xpdopen)"))
                            for div in snippet_divs:
                                snippet_text = div.get_text(separator=" ", strip=True)
                                if snippet_text and snippet_text not in ai_snippets:
                                    ai_snippets.append(snippet_text)

                    # Lightweight page-content fetch: use a short timeout and extract
                    # only the FIRST meaningful paragraph rather than the entire page.
                    # This avoids the slow/blocked full-page scraping while still
                    # surfacing a useful on-topic snippet from each result.
                    google_urls = list(google_search(query, num_results=max_results))
                    for url in google_urls[:max_results]:
                        if not BS4_AVAILABLE:
                            break
                        try:
                            page = requests.get(url, timeout=5, headers=HEADERS)
                            if page.status_code == 200:
                                soup = BeautifulSoup(page.text, "html.parser")
                                first_p = next(
                                    (
                                        p.get_text(" ", strip=True)
                                        for p in soup.find_all("p")
                                        if len(p.get_text(strip=True)) >= _MIN_SNIPPET_LEN
                                    ),
                                    "",
                                )
                                if first_p:
                                    results.append({
                                        "source": "google",
                                        "text": first_p[:400],
                                        "url": url,
                                    })
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
            # Drop entries that ended up too short after cleaning
            if entry["text"] and len(entry["text"]) >= _MIN_SNIPPET_LEN:
                cleaned_results.append(entry)

        # ───────── DEDUPLICATE + RANK BY SOURCE QUALITY ─────────
        # Remove near-duplicate entries and sort so the most authoritative
        # sources (SerpEx > SerpAPI > Wikipedia > DuckDuckGo > Google) appear
        # first — matching the quality-ordered retrieval strategy used by
        # the phased research pipeline.
        cleaned_results = _deduplicate_results(cleaned_results)
        cleaned_results = _rank_by_source_quality(cleaned_results)

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
                        if text and len(text) >= _MIN_SNIPPET_LEN:
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

        # ───────── LLM REWRITE (top result only) ─────────
        # Only rewrite the single best result to avoid O(n) LLM calls.
        # All other results are returned with their cleaned text as-is.
        if use_llm and self.llm and cleaned_results:
            try:
                top = cleaned_results[0]
                rewritten = self.llm.generate(
                    f"Rewrite the following information in clear, concise, factual words:\n{top['text']}",
                    max_tokens=300,
                )
                if rewritten:
                    top["text"] = rewritten
            except Exception:
                pass

        return cleaned_results


# ─────────────────────────────
if __name__ == "__main__":
    im = InternetManager()
    for res in im.search("queued learning"):
        print(res)
