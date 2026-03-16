# modules/researcher_engine.py
# Advanced research engine for NiblitOS v5

import os
import requests
import re

SERPEX_API_URL = "https://api.serpex.dev/api/search"


class ResearcherEngine:

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

    def run(self, topic):
        result = self.web_search(topic)
        if not result:
            return {"error": "No research results."}

        cleaned = self.clean(str(result))
        return {"topic": topic, "summary": cleaned}

engine = ResearcherEngine()

def run(topic):
    return engine.run(topic)


if __name__ == "__main__":
    print('Running researcher_engine.py')
