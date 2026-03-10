#!/usr/bin/env python3
# SLSA — Structured Live Sense Artifact Generator

import time
import threading
import logging
import re
import requests
from datetime import datetime
from typing import Dict, Optional
from modules.db import LocalDB
from modules.internet_manager import InternetManager

log = logging.getLogger("SLSA")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
LIVE_WEATHER = "https://api.open-meteo.com/v1/forecast"
SEMANTIC_KEYS = ["definition", "structure", "function", "origin", "evolution", "context"]
DEFAULT_TOPICS = ["car", "computer", "phone"]


class SLSAGenerator:
    """Continuous semantic emergence engine integrated with DB."""

    def __init__(self, interval=30, db_path="niblit.db", topics=None, internet=None):
        self.interval = interval
        self.stop_event = threading.Event()  # Thread-safe stop signal
        self.db = LocalDB(db_path)
        self.topics = topics or DEFAULT_TOPICS
        self.internet = internet or InternetManager(db=self.db)

    # ───────── RAW DATA COLLECTION ─────────
    def fetch_wikipedia(self, topic: str) -> Optional[Dict]:
        if self.stop_event.is_set():
            return None

        try:
            r = requests.get(WIKI_SUMMARY.format(topic.replace(" ", "_")), timeout=8)
            if r.status_code == 200:
                js = r.json()
                return {
                    "title": js.get("title"),
                    "description": js.get("description"),
                    "extract": js.get("extract"),
                    "url": js.get("content_urls", {}).get("desktop", {}).get("page"),
                }
            elif r.status_code == 403:
                log.debug(f"[WIKI] REST 403, fallback for '{topic}'")
        except Exception as e:
            log.debug(f"[WIKI] REST error: {e}")

        # Fallback to InternetManager search
        try:
            results = self.internet.search(topic, max_results=3, use_llm=False)
            for res in results:
                if res.get("source") == "wikipedia":
                    return {
                        "title": topic,
                        "description": res["text"][:200] if res.get("text") else "",
                        "extract": res.get("text", ""),
                        "url": res.get("url"),
                    }
        except Exception as e:
            log.debug(f"[WIKI] InternetManager fallback error: {e}")

        return None

    def fetch_live_weather(self) -> Optional[Dict]:
        if self.stop_event.is_set():
            return None
        try:
            params = {"latitude": -33.9, "longitude": 18.4, "current_weather": True}
            r = requests.get(LIVE_WEATHER, params=params, timeout=6)
            if r.status_code == 200:
                return r.json().get("current_weather")
        except Exception as e:
            log.debug(f"[LIVE] Error: {e}")
        return None

    # ───────── STRUCTURING ─────────
    def normalize(self, text: str) -> str:
        return re.sub(r'\s+', ' ', text or '').strip()

    def semantic_structure(self, topic: str, wiki: Dict, live: Dict, structured_search=None) -> Dict:
        text = self.normalize(wiki.get("extract", ""))
        lower = text.lower()
        artifact = {
            "concept": topic,
            "definition": None,
            "structure": None,
            "function": None,
            "origin": None,
            "evolution": None,
            "context": None,
            "live_context": live,
            "structured_search": structured_search or [],
            "timestamp": datetime.utcnow().isoformat()
        }

        if wiki.get("description"):
            artifact["definition"] = self.normalize(wiki["description"])
        if any(k in lower for k in ["engine", "components", "consists", "parts"]):
            artifact["structure"] = text[:400]
        if any(k in lower for k in ["used for", "purpose", "designed to"]):
            artifact["function"] = text[:400]
        if any(k in lower for k in ["invented", "origin", "first developed"]):
            artifact["origin"] = text[:400]
        if any(k in lower for k in ["evolved", "development", "modern"]):
            artifact["evolution"] = text[:400]
        if any(k in lower for k in ["society", "people", "daily life", "industry"]):
            artifact["context"] = text[:400]

        return artifact

    def is_complete(self, artifact: Dict) -> bool:
        return all(artifact.get(k) for k in SEMANTIC_KEYS)

    def already_known(self, concept: str) -> bool:
        for fact in self.db.list_facts():
            if fact.get("key") == concept:
                return True
        return False

    # ───────── REINFORCEMENT ─────────
    def reinforce_from_db(self):
        for fact in self.db.list_facts():
            artifact = fact.get("value")
            if artifact and isinstance(artifact, dict):
                if "concept" not in artifact:
                    artifact["concept"] = fact.get("key", "unknown")
                self.db.add_entry("slsa_reinforce", {"topic": artifact["concept"], "ts": time.time()})
                self.feed_modules(artifact)
                log.debug(f"[REINFORCE] {artifact['concept']} reinforced")

    # ───────── MODULE FEED ─────────
    def feed_modules(self, artifact: Dict):
        self.db.add_entry("slsa_module_feed", {"concept": artifact["concept"], "artifact": artifact, "ts": time.time()})
        log.debug(f"[MODULE FEED] {artifact['concept']} sent to modules")

    # ───────── GENERATION CYCLE ─────────
    def generate_cycle(self, topic: str):
        if self.stop_event.is_set():
            return

        structured_results = None
        if self.internet and not self.stop_event.is_set():
            structured_results = self.internet.search(topic)

        if self.stop_event.is_set():
            return
        wiki = self.fetch_wikipedia(topic)
        if self.stop_event.is_set() or not wiki:
            return

        live = self.fetch_live_weather()
        if self.stop_event.is_set():
            return

        self.db.add_entry(
            "slsa_exposure",
            {"topic": topic, "wiki": bool(wiki), "live": bool(live), "ts": time.time()},
        )

        artifact = self.semantic_structure(topic, wiki, live, structured_search=structured_results)
        if self.is_complete(artifact) and not self.already_known(topic):
            self.db.add_fact(key=topic, value=artifact, tags=["slsa", "semantic", "factual"])
            log.info(f"[ARTIFACT EMERGED] {topic}")
            log.info(f"[DEFINITION] {artifact['definition']}")
            self.feed_modules(artifact)

    # ───────── BACKGROUND LOOP ─────────
    def run(self):
        log.info("[SLSA] Generator online")
        self.reinforce_from_db()

        while not self.stop_event.is_set():
            try:
                for topic in self.topics:
                    if self.stop_event.is_set():
                        break
                    self.generate_cycle(topic)
            except Exception as e:
                log.error(f"[SLSA ERROR] {e}")

            # Sleep in 1-second increments for responsive stopping
            sleep_time = 0
            while sleep_time < self.interval and not self.stop_event.is_set():
                time.sleep(1)
                sleep_time += 1

        log.info("[SLSA] Generator fully stopped")

    # ───────── STOP ─────────
    def stop(self):
        self.stop_event.set()


# ───────── START SLSA ─────────
def start_slsa(topics=None):
    engine = SLSAGenerator(interval=20, topics=topics)
    t = threading.Thread(target=engine.run, daemon=True)
    t.start()
    return engine, t


if __name__ == "__main__":
    print("Running slsa_generator_full.py")
    engine, thread = start_slsa()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
