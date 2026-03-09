#!/usr/bin/env python3
# modules/internet_manager.py

import requests
import re
import html
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

DDG_API = "https://api.duckduckgo.com/"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Niblit/1.0)"
}


class InternetManager:
    def __init__(self, db=None, llm_adapter=None, timeout=6):
        self.db = db
        self.llm = llm_adapter
        self.timeout = timeout

    # ─────────────────────────────
    def is_online(self):
        try:
            r = requests.get("https://api.ipify.org?format=json", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    # ─────────────────────────────
    # SMART SEARCH
    # Returns structured results with source, text, and optional url
    def search(self, query, max_results=5, use_llm=True):
        results = []

        # ───────── DUCKDUCKGO ─────────
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

        # ───────── WIKIPEDIA ─────────
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

        # ───────── GOOGLE + MULTI AI SNIPPETS ─────────
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
