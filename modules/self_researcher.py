#!/usr/bin/env python3
# modules/self_researcher.py

from datetime import datetime
import math
import html
import re

class SelfResearcher:
    def __init__(self, db, modules_registry=None, research_engine=None, llm_adapter=None,
                 max_history=100, relevance_threshold=0.7):
        self.db = db
        self.registry = modules_registry or {}

        # Internal Internet holder (dynamic wiring support)
        self._internet = None
        if "internet" in self.registry:
            self._internet = self.registry["internet"]
        elif hasattr(db, "internet"):
            self._internet = db.internet

        # Optional modules
        self.engine = research_engine
        self.llm = llm_adapter

        # Memory / history
        self.history = []
        self.responses = []   # ← PATCH: store responses separately
        self.max_history = max_history
        self.relevance_threshold = relevance_threshold

    # ─────────────────────────────────────────────
    # INTERNET PROPERTY (dynamic injection supported)
    @property
    def internet(self):
        return self._internet

    @internet.setter
    def internet(self, value):
        self._internet = value

    # ─────────────────────────────────────────────
    def _compute_similarity(self, vec1, vec2):
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    # ─────────────────────────────────────────────
    def _update_history(self, query, results):
        timestamp = datetime.utcnow().isoformat()
        embedding = self.llm.embed(query) if self.llm else None

        entry = {
            "query": query,
            "results": results,
            "timestamp": timestamp,
            "embedding": embedding
        }

        self.history.append(entry)

        # PATCH: store responses separately
        self.responses.append({
            "query": query,
            "response": results,
            "timestamp": timestamp
        })

        if len(self.history) > self.max_history:
            self.history.pop(0)

        if len(self.responses) > self.max_history:
            self.responses.pop(0)

    # ─────────────────────────────────────────────
    def _check_history(self, query):
        if not self.llm:
            return []
        query_embedding = self.llm.embed(query)
        relevant = []
        for entry in reversed(self.history):
            sim = self._compute_similarity(query_embedding, entry.get("embedding"))
            if sim >= self.relevance_threshold:
                relevant.extend(entry["results"])
        return relevant

    # ─────────────────────────────────────────────
    # MAIN SEARCH — INTEGRATED WITH INTERNET MANAGER + LLM
    # ─────────────────────────────────────────────
    def search(self, query, max_results=5, use_llm=True, learn_in_background=True,
               use_history=True, synthesize=True):
        if not query:
            return []

        collected_results = []

        # 1️⃣ HISTORY
        if use_history:
            collected_results.extend(self._check_history(query))

        # 2️⃣ ENGINE
        if self.engine:
            try:
                r = self.engine.run(query)
                if isinstance(r, dict):
                    r = r.get("summary")
                if r:
                    collected_results.append(r)
            except Exception:
                pass

        # 3️⃣ INTERNET (DuckDuckGo + Wikipedia + Google + Google AI)
        if self.internet:
            try:
                web_results = self.internet.search(query, max_results=max_results * 3)
                if web_results:
                    collected_results.extend(web_results)
            except Exception:
                pass

        # Remove duplicates
        collected_results = list(dict.fromkeys(collected_results))

        # 4️⃣ SYNTHESIZE MULTIPLE SOURCES USING LLM
        if synthesize and collected_results and use_llm and self.llm:
            try:
                combined_text = " ".join(collected_results)
                synthesized = self.llm.generate(
                    f"Using these multiple sources, provide a coherent, factual, and concise answer to the query:\n{combined_text}",
                    max_tokens=400
                )
                if synthesized:
                    collected_results = [synthesized]
            except Exception:
                pass

        # 5️⃣ FALLBACK
        if not collected_results:
            collected_results = [f"No research data found for '{query}'"]

        # 6️⃣ AUTO-LEARN WEB RESULTS
        try:
            for r in collected_results[:max_results]:
                self.db.add_fact(
                    f"research:{query}",
                    r,
                    tags=["research", "web"]
                )

                # PATCH: store response explicitly
                try:
                    self.db.add_fact(
                        f"research_response:{query}",
                        r,
                        tags=["research", "response"]
                    )
                except Exception:
                    pass

        except Exception:
            pass

        # 7️⃣ UPDATE HISTORY
        self._update_history(query, collected_results[:max_results])

        # 8️⃣ BACKGROUND LEARNING
        if learn_in_background and self.llm:
            try:
                for r in collected_results:
                    self.llm.background_learning(r)
            except Exception:
                pass

        return collected_results[:max_results]

    # ─────────────────────────────────────────────
    @property
    def recent_queries(self):
        return [h["query"] for h in self.history[-self.max_history:]]

    @property
    def memory_summary(self):
        return [{"query": h["query"], "timestamp": h["timestamp"]} for h in self.history]

    # PATCH: expose stored responses
    @property
    def stored_responses(self):
        return self.responses


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running self_researcher.py")
