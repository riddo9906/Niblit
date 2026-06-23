#!/usr/bin/env python3
"""
modules/slsa_generator.py — Structured Live Sense Artifact (SLSA) Generator for Niblit.

Generates structured semantic artifacts by collecting data from multiple sources
(Wikipedia REST API, PhasedResearchEngine, InternetManager) and storing enriched
KB facts for every topic it studies.

Data-collection pipeline
────────────────────────
1. Wikipedia REST summary  → definition, structure, function, origin, evolution,
                             context  (semantic_structure)
2. PhasedResearchEngine    → deep research via DuckDuckGo + SerpAPI + GitHub
                             (used when available; adds phase1/phase2/phase3 data)
3. InternetManager         → fallback search when Wikipedia REST returns 403

All artifacts are stored via ``db.add_fact()`` with the ``slsa`` tag so they are
immediately visible to KB-driven response logic.

Usage::

    from modules.slsa_generator import SLSAGenerator

    gen = SLSAGenerator(db=knowledge_db)
    gen.generate("artificial intelligence")        # single-shot
    gen.run()                                      # continuous background loop
    gen.stop()
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.SLSAGenerator")

# Wikipedia REST API endpoint
_WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
# Open-Meteo current weather (Cape Town default; harmless if unreachable)
_LIVE_WEATHER = "https://api.open-meteo.com/v1/forecast"

SEMANTIC_KEYS = ["definition", "structure", "function", "origin", "evolution", "context"]

DEFAULT_TOPICS = [
    "artificial intelligence",
    "machine learning",
    "python programming",
    "neural network",
    "computer science",
]


# ─────────────────────────────────────────────────────────────────────────────
# SLSAGenerator
# ─────────────────────────────────────────────────────────────────────────────

class SLSAGenerator:
    """Structured Live Sense Artifact generator.

    Continuously researches topics, builds semantic artifacts from multiple
    data sources, and stores them in the KnowledgeDB.

    Args:
        db:              KnowledgeDB (or any object with ``add_fact`` /
                         ``list_facts``).  Required.
        topics:          List of seed topics to study.  Defaults to
                         ``DEFAULT_TOPICS``.
        interval:        Seconds between full topic cycles (default 60).
        internet:        Optional ``InternetManager`` for fallback search.
        phased_research: Optional ``PhasedResearchEngine`` for deep research.
    """

    def __init__(
        self,
        db: Any,
        topics: Optional[List[str]] = None,
        interval: int = 60,
        internet: Any = None,
        phased_research: Any = None,
    ) -> None:
        self.db = db
        self.topics: List[str] = list(topics or DEFAULT_TOPICS)
        self.interval = interval
        self.stop_event = threading.Event()
        self._stats: Dict[str, int] = {
            "cycles": 0,
            "artifacts_stored": 0,
            "wiki_hits": 0,
            "research_hits": 0,
        }

        # Optional heavy modules — loaded lazily if not injected
        self._internet = internet
        self._phased_research = phased_research

        log.debug("[SLSA] Initialized with %d topic(s), interval=%ds", len(self.topics), interval)

    # ─────────────────────────────────────────────────────────────────────────
    # DATA COLLECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _internet_manager(self) -> Any:
        """Return the InternetManager, loading it lazily if needed."""
        if self._internet is not None:
            return self._internet
        try:
            from modules.internet_manager import InternetManager  # pylint: disable=import-outside-toplevel
            self._internet = InternetManager(db=self.db)
        except Exception as exc:
            log.debug("[SLSA] InternetManager unavailable: %s", exc)
        return self._internet

    def _phased_engine(self) -> Any:
        """Return the PhasedResearchEngine singleton, loading it lazily."""
        if self._phased_research is not None:
            return self._phased_research
        try:
            from modules.phased_research_engine import get_phased_research_engine  # pylint: disable=import-outside-toplevel
            self._phased_research = get_phased_research_engine()
        except Exception as exc:
            log.debug("[SLSA] PhasedResearchEngine unavailable: %s", exc)
        return self._phased_research

    def fetch_wikipedia(self, topic: str) -> Optional[Dict]:
        """Fetch a Wikipedia REST summary for *topic*.

        Falls back to InternetManager search when the REST endpoint returns
        a non-200 status or raises an exception.
        """
        if self.stop_event.is_set():
            return None

        try:
            import requests  # optional dep; harmless if unavailable  # pylint: disable=import-outside-toplevel
            url = _WIKI_SUMMARY.format(topic.replace(" ", "_"))
            resp = requests.get(url, timeout=300)
            if resp.status_code == 200:
                js = resp.json()
                self._stats["wiki_hits"] += 1
                return {
                    "title": js.get("title"),
                    "description": js.get("description"),
                    "extract": js.get("extract", ""),
                    "url": js.get("content_urls", {}).get("desktop", {}).get("page"),
                }
            log.debug("[SLSA] Wikipedia REST %d for '%s'", resp.status_code, topic)
        except Exception as exc:
            log.debug("[SLSA] Wikipedia REST error: %s", exc)

        # Fallback: InternetManager search
        im = self._internet_manager()
        if im:
            try:
                results = im.search(topic, max_results=3, use_llm=False) or []
                for res in results:
                    if isinstance(res, dict) and res.get("text"):
                        return {
                            "title": topic,
                            "description": str(res["text"])[:200],
                            "extract": str(res.get("text", "")),
                            "url": res.get("url"),
                        }
            except Exception as exc:
                log.debug("[SLSA] InternetManager fallback error: %s", exc)

        return None

    def fetch_phased_research(self, topic: str) -> Optional[Dict]:
        """Run PhasedResearchEngine on *topic* to gather deep research data.

        Returns a dict with keys ``phase1``, ``phase2``, ``phase3`` (each a
        list of text snippets), or None when the engine is unavailable.
        """
        if self.stop_event.is_set():
            return None
        engine = self._phased_engine()
        if not engine:
            return None
        try:
            result = engine.research(topic, skip_phase3=True)
            collected: Dict[str, List[str]] = {"phase1": [], "phase2": [], "phase3": []}
            for phase_key in ("phase1", "phase2", "phase3"):
                phase_obj = getattr(result, phase_key, None)
                if phase_obj:
                    texts = getattr(phase_obj, "texts", None) or []
                    collected[phase_key] = [str(t)[:300] for t in texts[:5]]
            total = sum(len(v) for v in collected.values())
            if total > 0:
                self._stats["research_hits"] += 1
                log.debug("[SLSA] Phased research for '%s': %d snippets", topic, total)
                return collected
        except Exception as exc:
            log.debug("[SLSA] PhasedResearchEngine error for '%s': %s", topic, exc)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # ARTIFACT STRUCTURING
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Collapse whitespace in *text*."""
        return re.sub(r"\s+", " ", text or "").strip()

    def semantic_structure(
        self,
        topic: str,
        wiki: Dict,
        research: Optional[Dict] = None,
    ) -> Dict:
        """Build a structured semantic artifact from collected data.

        Parameters
        ----------
        topic:    The concept being studied.
        wiki:     Dict from ``fetch_wikipedia()``.
        research: Dict from ``fetch_phased_research()`` (optional).
        """
        text = self._normalize(wiki.get("extract", ""))
        lower = text.lower()

        artifact: Dict[str, Any] = {
            "concept": topic,
            "definition": None,
            "structure": None,
            "function": None,
            "origin": None,
            "evolution": None,
            "context": None,
            "research_snippets": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # ── Extract semantic fields from Wikipedia text ──────────────────────
        if wiki.get("description"):
            artifact["definition"] = self._normalize(wiki["description"])
        if any(k in lower for k in ("engine", "components", "consists", "parts", "made of")):
            artifact["structure"] = text[:400]
        if any(k in lower for k in ("used for", "purpose", "designed to", "enables")):
            artifact["function"] = text[:400]
        if any(k in lower for k in ("invented", "origin", "first developed", "created by")):
            artifact["origin"] = text[:400]
        if any(k in lower for k in ("evolved", "development", "modern", "advances")):
            artifact["evolution"] = text[:400]
        if any(k in lower for k in ("society", "people", "daily life", "industry", "widely")):
            artifact["context"] = text[:400]

        # ── Fill gaps from phased research ───────────────────────────────────
        if research:
            snippets: List[str] = []
            for phase_key in ("phase1", "phase2", "phase3"):
                snippets.extend(research.get(phase_key) or [])

            artifact["research_snippets"] = snippets[:10]

            # Use research text to backfill missing semantic fields
            combined = " ".join(snippets).lower()
            if not artifact["definition"] and snippets:
                artifact["definition"] = snippets[0][:300]
            if not artifact["function"] and any(k in combined for k in ("used for", "purpose")):
                artifact["function"] = snippets[0][:300]
            if not artifact["origin"] and any(k in combined for k in ("invented", "created")):
                artifact["origin"] = snippets[0][:300]

        return artifact

    def is_complete(self, artifact: Dict) -> bool:
        """Return True when all required semantic fields are populated."""
        return all(artifact.get(k) for k in SEMANTIC_KEYS)

    def already_known(self, concept: str) -> bool:
        """Return True when a ``slsa:`` fact already exists for *concept*."""
        if not self.db or not hasattr(self.db, "list_facts"):
            return False
        try:
            for fact in (self.db.list_facts(200) or []):
                if isinstance(fact, dict) and fact.get("key") == f"slsa:{concept}":
                    return True
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # KB STORAGE
    # ─────────────────────────────────────────────────────────────────────────

    def _store_artifact(self, artifact: Dict) -> None:
        """Persist the artifact to KnowledgeDB."""
        concept = artifact.get("concept", "unknown")
        key = f"slsa:{concept}"
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, artifact, tags=["slsa", "semantic", "factual"])
                self._stats["artifacts_stored"] += 1
                log.info("[SLSA] Stored artifact for '%s'", concept)
        except Exception as exc:
            log.debug("[SLSA] Store failed for '%s': %s", concept, exc)

    def _store_partial(self, artifact: Dict) -> None:
        """Store an incomplete artifact with the ``slsa_partial`` tag."""
        concept = artifact.get("concept", "unknown")
        key = f"slsa_partial:{concept}:{int(time.time())}"
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, artifact, tags=["slsa", "partial", "semantic"])
                log.debug("[SLSA] Stored partial artifact for '%s'", concept)
        except Exception as exc:
            log.debug("[SLSA] Partial store failed: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # GENERATION — SINGLE-SHOT
    # ─────────────────────────────────────────────────────────────────────────

    def generate(self, topic: str = "default", steps: int = 4) -> str:
        """Generate and store a semantic artifact for *topic*.

        This is the public single-shot API compatible with the original
        ``SLSAGenerator.generate()`` stub.

        Args:
            topic: The concept to research and structure.
            steps: Ignored (kept for backward-compatibility); depth is
                   determined by data-source availability instead.

        Returns:
            A human-readable summary string of what was learned.
        """
        if self.stop_event.is_set():
            return f"[SLSA] Stopped — cannot generate for '{topic}'"

        wiki = self.fetch_wikipedia(topic)
        research = self.fetch_phased_research(topic)

        if not wiki and not research:
            out = (
                f"Step 1: queued '{topic}' for deep research\n"
                f"Step 2: Wikipedia and research engines unavailable\n"
                f"Step 3: stored gap-learning request in KB\n"
                f"Step 4: will retry next cycle"
            )
            # Still store a minimal placeholder so callers see progress
            if hasattr(self.db, "add_fact"):
                try:
                    self.db.add_fact(
                        f"slsa:{topic}",
                        {"concept": topic, "status": "pending", "timestamp": datetime.now(timezone.utc).isoformat()},
                        tags=["slsa", "pending"],
                    )
                except Exception:
                    pass
            return out

        artifact = self.semantic_structure(topic, wiki or {}, research)
        if self.is_complete(artifact):
            self._store_artifact(artifact)
            fields_found = [k for k in SEMANTIC_KEYS if artifact.get(k)]
            return "\n".join(
                [f"Step {i+1}: extracted '{k}' for '{topic}'" for i, k in enumerate(fields_found)]
            )
        else:
            self._store_partial(artifact)
            filled = [k for k in SEMANTIC_KEYS if artifact.get(k)]
            missing = [k for k in SEMANTIC_KEYS if not artifact.get(k)]
            return (
                f"Partial artifact for '{topic}': "
                f"found={filled}, missing={missing}"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # CONTINUOUS BACKGROUND LOOP
    # ─────────────────────────────────────────────────────────────────────────

    def generate_cycle(self, topic: str) -> None:
        """Single cycle: collect data → build artifact → store if complete."""
        if self.stop_event.is_set():
            return

        wiki = self.fetch_wikipedia(topic)
        if self.stop_event.is_set():
            return

        research = self.fetch_phased_research(topic)
        if self.stop_event.is_set():
            return

        if not wiki and not research:
            log.debug("[SLSA] No data collected for '%s' — skipping", topic)
            return

        artifact = self.semantic_structure(topic, wiki or {}, research)

        if self.is_complete(artifact) and not self.already_known(topic):
            self._store_artifact(artifact)
            log.info("[SLSA] Complete artifact emerged for '%s'", topic)
        elif not self.already_known(topic):
            self._store_partial(artifact)
            log.debug("[SLSA] Partial artifact stored for '%s'", topic)

    def run(self) -> None:
        """Run the continuous background generation loop."""
        log.info("[SLSA] Generator online (%d topics)", len(self.topics))
        self._stats["cycles"] = 0

        while not self.stop_event.is_set():
            for topic in list(self.topics):
                if self.stop_event.is_set():
                    break
                try:
                    self.generate_cycle(topic)
                except Exception as exc:
                    log.error("[SLSA] Cycle error for '%s': %s", topic, exc)

            self._stats["cycles"] += 1

            # Interruptible sleep
            deadline = time.time() + self.interval
            while time.time() < deadline and not self.stop_event.is_set():
                time.sleep(1.0)

        log.info("[SLSA] Generator stopped after %d cycle(s)", self._stats["cycles"])

    def stop(self) -> None:
        """Signal the background loop to stop."""
        self.stop_event.set()

    def add_topic(self, topic: str) -> None:
        """Add a new topic to the running generation list."""
        if topic not in self.topics:
            self.topics.append(topic)
            log.debug("[SLSA] Added topic '%s'", topic)

    def get_stats(self) -> Dict[str, int]:
        """Return current generation statistics."""
        return dict(self._stats)


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE LAUNCHER
# ─────────────────────────────────────────────────────────────────────────────

def start_slsa(
    db: Any = None,
    topics: Optional[List[str]] = None,
    interval: int = 60,
    internet: Any = None,
    phased_research: Any = None,
) -> "tuple[SLSAGenerator, threading.Thread]":
    """Create a SLSAGenerator and start its background thread.

    Returns (engine, thread).
    """
    engine = SLSAGenerator(
        db=db,
        topics=topics,
        interval=interval,
        internet=internet,
        phased_research=phased_research,
    )
    thread = threading.Thread(target=engine.run, name="SLSAGeneratorThread", daemon=True)
    thread.start()
    return engine, thread


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.DEBUG, format="%(message)s")

    class _MockDB:
        def __init__(self):
            self._facts = {}
        def add_fact(self, key, value, tags=None):
            self._facts[key] = value
            print(f"  DB.add_fact({key!r}, tags={tags})")
        def list_facts(self, limit=100):
            return [{"key": k, "value": v} for k, v in self._facts.items()]

    print("=== SLSAGenerator self-test ===")
    _db = _MockDB()
    _gen = SLSAGenerator(db=_db, topics=["python", "robot"])
    print("\n-- generate('python') --")
    _out = _gen.generate("python")
    print(_out)
    print("\nStats:", _gen.get_stats())
    print("\nSLSAGenerator OK")

