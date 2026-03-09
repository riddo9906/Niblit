# modules/researcher_engine.py
# Advanced research engine for NiblitOS v5

import requests
import re

class ResearcherEngine:

    def clean(self, text):
        return re.sub(r"\s+", " ", text).strip()

    def web_search(self, topic):
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
