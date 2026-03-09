# modules/market_researcher.py
import time
import random
from typing import Optional

try:
    import requests
except Exception:
    requests = None

class MarketResearcher:
    def __init__(self, db: Optional[object]=None):
        self.db = db

    def _fake_trend(self, topic, count=5):
        results = []
        for i in range(count):
            trend = random.choice(["up", "down", "stable"])
            value = round(random.uniform(100, 1000), 2)
            results.append({"topic": topic, "trend": trend, "value": value, "ts": int(time.time())})
        return results

    def analyze_market(self, topic="stocks", limit=5):
        """Try a live data fetch if requests available, else fallback to fake trends."""
        if requests:
            # Placeholder: user can swap for real API endpoints (Alpha Vantage, Yahoo, etc.)
            try:
                q = topic.replace(" ", "+")
                # free fallback search: DuckDuckGo instant answer for topic summary (not prices)
                r = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json", timeout=6)
                if r.ok:
                    data = r.json()
                    summary = data.get("AbstractText") or data.get("Heading") or ""
                    return {"summary": summary, "raw": data}
            except Exception:
                pass
        # fallback simulated data
        results = self._fake_trend(topic, count=limit)
        # store to DB if available
        if self.db and hasattr(self.db, "add_entry"):
            for idx, r in enumerate(results):
                try:
                    self.db.add_entry(f"market:{topic}:{idx}", str(r))
                except Exception:
                    pass
        return results

    def summary(self, topic="stocks"):
        data = self.analyze_market(topic)
        if isinstance(data, dict) and "summary" in data:
            return f"Market summary ({topic}): {data['summary'][:300]}"
        # simulated list
        return f"Market summary ({topic}): " + ", ".join([f"{d['trend']}({d['value']})" for d in data])
if __name__ == "__main__":
    print('Running market_researcher.py')
