# niblit_tools/scrapy_search.py
"""
Scrapy-based web search engine for Niblit.

Provides :class:`ScrapySearchEngine`, a synchronous wrapper around a Scrapy
spider that scrapes DuckDuckGo HTML search results without requiring any
external API key.

Architecture::

    ScrapySearchEngine.search(query)
         │
         ▼
    subprocess: scrapy runspider _NiblitSearchSpider
         │  (JSON lines written to stdout)
         ▼
    [{"title": ..., "url": ..., "snippet": ...}, ...]

The spider is serialised as a self-contained Python script and executed in a
child process to avoid Twisted-reactor restart limitations.

Usage::

    from niblit_tools.scrapy_search import ScrapySearchEngine
    engine = ScrapySearchEngine()
    results = engine.search("python asyncio", category="web")
    # → {"results": [{"title": ..., "url": ..., "snippet": ...}]}
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, Dict, List

try:
    import scrapy  # noqa: F401
    _SCRAPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCRAPY_AVAILABLE = False

logger = logging.getLogger("Niblit.ScrapySearch")

# ── configurable defaults ────────────────────────────────────────────────────
_DEFAULT_MAX_RESULTS = int(os.getenv("SCRAPY_MAX_RESULTS", "10"))
_DEFAULT_TIMEOUT = int(os.getenv("SCRAPY_TIMEOUT", "20"))  # seconds per search

# ── spider source (injected as a temp file and run via subprocess) ────────────
_SPIDER_SOURCE = textwrap.dedent("""\
    import json
    import sys
    import scrapy
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.log import configure_logging

    configure_logging({{"LOG_ENABLED": False}})

    QUERY    = {query!r}
    CATEGORY = {category!r}
    MAX      = {max_results!r}

    _items = []

    class DuckDuckGoSpider(scrapy.Spider):
        name = "ddg"
        custom_settings = {{
            "LOG_ENABLED": False,
            "ROBOTSTXT_OBEY": False,
            "REQUEST_FINGERPRINTER_IMPLEMENTATION": "2.7",
            "DOWNLOAD_TIMEOUT": 10,
            "USER_AGENT": (
                "Mozilla/5.0 (compatible; Niblit/1.0; "
                "+https://github.com/niblit/niblit)"
            ),
        }}

        def start_requests(self):
            from urllib.parse import urlencode, quote_plus
            if CATEGORY == "news":
                params = urlencode({{"q": QUERY, "ia": "news"}})
                url = f"https://duckduckgo.com/html/?{{params}}"
            else:
                params = urlencode({{"q": QUERY}})
                url = f"https://html.duckduckgo.com/html/?{{params}}"
            yield scrapy.Request(url, callback=self.parse,
                                 errback=self.errback_handler)

        def errback_handler(self, failure):
            pass

        def parse(self, response):
            seen = set()
            count = 0
            # DuckDuckGo HTML result selectors
            for result in response.css("div.result, div.web-result"):
                if count >= MAX:
                    break
                title_el = (result.css("a.result__a") or
                             result.css("h2.result__title a") or
                             result.css("a"))
                title = title_el.css("::text").get(default="").strip()
                url   = title_el.attrib.get("href", "").strip()
                snip  = (result.css("a.result__snippet::text").get() or
                         result.css(".result__snippet::text").get() or
                         result.css("span::text").get() or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                if title or snip:
                    _items.append({{"title": title, "url": url, "snippet": snip}})
                    count += 1

    process = CrawlerProcess()
    process.crawl(DuckDuckGoSpider)
    process.start()

    print(json.dumps(_items))
""")


# ─────────────────────────────────────────────────────────────────────────────
# ScrapySearchEngine
# ─────────────────────────────────────────────────────────────────────────────

class ScrapySearchEngine:
    """Synchronous Scrapy-backed search engine.

    Scrapes DuckDuckGo HTML results — no API key required.  Each call spins up
    a short-lived subprocess to work around Twisted's single-reactor limitation.

    Args:
        max_results: Maximum number of results to return per query.
        timeout:     Per-query subprocess timeout in seconds.
    """

    def __init__(
        self,
        max_results: int = _DEFAULT_MAX_RESULTS,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.max_results = max_results
        self.timeout = timeout

    def is_configured(self) -> bool:
        """Always ``True`` — DuckDuckGo scraping needs no API key or config."""
        return True

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",   # accepted for interface compat, ignored
        time_range: str = "day",  # accepted for interface compat, ignored
    ) -> Dict[str, Any]:
        """Scrape DuckDuckGo for *query* and return a normalised result dict.

        Args:
            query:      Search query string.
            category:   ``"web"`` (default) or ``"news"``.
            engine:     Ignored (kept for interface compatibility).
            time_range: Ignored (kept for interface compatibility).

        Returns:
            ``{"results": [{"title": str, "url": str, "snippet": str}, ...]}``
            or ``{"results": [], "error": str}`` on failure.
        """
        try:
            items = self._run_spider(query, category)
            return {"results": items}
        except Exception as exc:
            logger.error("[ScrapySearch] search failed: %s", exc)
            return {"results": [], "error": str(exc)}

    # ── internals ────────────────────────────────────────────────────────────

    def _run_spider(self, query: str, category: str) -> List[Dict[str, Any]]:
        """Execute the DuckDuckGo spider in a subprocess and return its items."""
        source = _SPIDER_SOURCE.format(
            query=query,
            category=category,
            max_results=self.max_results,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="niblit_spider_",
        ) as tmp:
            tmp.write(source)
            spider_path = tmp.name

        try:
            proc = subprocess.run(
                [sys.executable, spider_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                logger.debug("[ScrapySearch] spider stderr: %s", proc.stderr[:500])

            stdout = proc.stdout.strip()
            if not stdout:
                return []

            # The spider prints one JSON array on the last line
            last_line = stdout.splitlines()[-1]
            items = json.loads(last_line)
            return items if isinstance(items, list) else []
        except subprocess.TimeoutExpired:
            logger.warning("[ScrapySearch] spider timed out after %ds", self.timeout)
            return []
        except json.JSONDecodeError as exc:
            logger.warning("[ScrapySearch] JSON parse failed: %s", exc)
            return []
        finally:
            try:
                os.unlink(spider_path)
            except OSError:
                pass


if __name__ == "__main__":
    print('Running scrapy_search.py')
