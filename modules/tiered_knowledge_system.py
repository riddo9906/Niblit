"""
Tiered Knowledge System
=======================

Manages a four-stage knowledge-acquisition pipeline that Niblit works through
sequentially.  A tier only advances when ALL its topics have been researched
with at least ``_MIN_FACTS_PER_TOPIC`` supporting KB entries (confidence 100%).
Once the tier advances, all previously stored entries remain in the KB and are
fully recallable via ``recall_knowledge(topic)``.

Tier order
----------
Foundation (0)
    Must-know factual information for any cognitive-enhanced application.
    Sources: internal knowledge + Wikipedia.

Basic (1)
    Everyday general knowledge.
    Sources: Wikipedia, Google, DuckDuckGo (Scrapy).

Intermediate (2)
    Deeper software/engineering knowledge.
    Sources: DuckDuckGo, Google, Searchcode, StackOverflow.

Advanced (3)
    Expert/technical knowledge.
    Sources: GitHub REST API, Serpex, Qdrant, DuckDuckGo, Google.

The tier never regresses.  When ``tier_confidence()`` returns ``1.0`` for the
current tier and there are still higher tiers available, ``_advance_tier()``
is called automatically.

Structured recall
-----------------
Every fact is stored with tags of the form::

    ["tiered_knowledge", "tier_<name>", "topic_<slug>", "ale_learned"]

so that ``recall_knowledge(topic)`` can retrieve all entries for a topic
across any tier without needing a full-table scan.

Singleton
---------
Use ``get_tiered_knowledge_system(knowledge_db)`` to obtain the process-wide
singleton.  The instance lazily binds ``knowledge_db`` the first time a
non-None value is passed.
"""

from __future__ import annotations

import logging
import time
from enum import IntEnum
from typing import Any, Dict, List, Optional

log = logging.getLogger("TieredKnowledgeSystem")

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class KnowledgeTier(IntEnum):
    FOUNDATION   = 0
    BASIC        = 1
    INTERMEDIATE = 2
    ADVANCED     = 3


_TIER_NAMES: Dict[KnowledgeTier, str] = {
    KnowledgeTier.FOUNDATION:   "Foundation",
    KnowledgeTier.BASIC:        "Basic",
    KnowledgeTier.INTERMEDIATE: "Intermediate",
    KnowledgeTier.ADVANCED:     "Advanced",
}

# Minimum KB facts stored per topic before that topic is considered covered.
_MIN_FACTS_PER_TOPIC: int = 3

# ---------------------------------------------------------------------------
# Per-tier research sources
# ---------------------------------------------------------------------------

#: Which backend identifiers to prefer at each tier.
#: ALE's ``_autonomous_tiered_research()`` maps these to real getter methods.
TIER_SOURCES: Dict[KnowledgeTier, List[str]] = {
    KnowledgeTier.FOUNDATION:   ["internal", "wikipedia"],
    KnowledgeTier.BASIC:        ["wikipedia", "duckduckgo", "google"],
    KnowledgeTier.INTERMEDIATE: ["duckduckgo", "google", "searchcode", "stackoverflow"],
    KnowledgeTier.ADVANCED:     ["github_api", "serpex", "qdrant", "duckduckgo", "google"],
}

# ---------------------------------------------------------------------------
# Per-tier topic lists
# ---------------------------------------------------------------------------

#: Topics that MUST be fully covered at each tier before Niblit advances.
TIER_TOPICS: Dict[KnowledgeTier, List[str]] = {
    # ── Foundation ─────────────────────────────────────────────────────────
    # Core facts every cognitive AI must understand before learning anything
    # more specific.  Deliberately narrow so the tier completes quickly.
    KnowledgeTier.FOUNDATION: [
        "what is artificial intelligence",
        "what is machine learning",
        "what is a neural network",
        "what is natural language processing",
        "what is Python programming",
        "what is data storage and retrieval",
        "what is an API",
        "what is the internet",
        "what is a database",
        "what is software",
        "logical reasoning and inference",
        "mathematics for computing",
        "basic computer science concepts",
    ],
    # ── Basic ───────────────────────────────────────────────────────────────
    # Solid foundational software-engineering knowledge.
    KnowledgeTier.BASIC: [
        "programming fundamentals",
        "algorithms and data structures",
        "object oriented programming",
        "functional programming",
        "web development basics",
        "networking fundamentals",
        "operating system concepts",
        "version control with git",
        "software testing",
        "debugging techniques",
        "common design patterns",
        "REST API design",
        "JSON and data formats",
        "command line basics",
        "cloud computing basics",
    ],
    # ── Intermediate ────────────────────────────────────────────────────────
    # Deeper AI and systems knowledge.
    KnowledgeTier.INTERMEDIATE: [
        "deep learning architectures",
        "transformer models and attention",
        "reinforcement learning",
        "knowledge graphs",
        "vector databases",
        "distributed systems",
        "microservices architecture",
        "continuous integration and deployment",
        "security best practices",
        "performance optimization",
        "database query optimization",
        "event driven architecture",
        "graph algorithms",
        "natural language generation",
        "embeddings and semantic search",
    ],
    # ── Advanced ────────────────────────────────────────────────────────────
    # Cutting-edge, specialised topics for a self-improving AI system.
    KnowledgeTier.ADVANCED: [
        "large language model fine-tuning",
        "retrieval augmented generation",
        "agentic AI systems",
        "self-improving AI architectures",
        "autonomous learning systems",
        "advanced knowledge representation",
        "multi-agent coordination",
        "constitutional AI alignment",
        "sparse and dense retrieval",
        "chain of thought prompting",
        "code generation and synthesis",
        "binary analysis and reverse engineering",
        "kernel development",
        "firmware embedded systems",
        "AI safety and interpretability",
    ],
}

# ---------------------------------------------------------------------------
# TieredKnowledgeSystem class
# ---------------------------------------------------------------------------

class TieredKnowledgeSystem:
    """Sequential knowledge-tier manager.

    Usage::

        tks = get_tiered_knowledge_system(knowledge_db)

        # Check what to research next
        topic = tks.next_uncovered_topic()
        sources = tks.get_sources()

        # After gathering and storing the research:
        tks.store_knowledge(topic, content, source="wikipedia")

        # Retrieve stored knowledge for context injection:
        ctx = tks.recall_knowledge("what is artificial intelligence")
    """

    def __init__(self, knowledge_db: Any = None) -> None:
        self.knowledge_db = knowledge_db
        self._current_tier: KnowledgeTier = KnowledgeTier.FOUNDATION
        # topic_key (lower-case) → number of KB facts stored for that topic
        self._topic_fact_counts: Dict[str, int] = {}
        self._load_state()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_topic_key(topic: str) -> str:
        """Return a canonical lower-case key for *topic* used in all internal dicts."""
        return topic.strip().lower()

    @staticmethod
    def _make_topic_slug(topic: str) -> str:
        """Return a compact slug (first 40 chars, spaces → underscores) for KB keys and tags."""
        return topic.replace(" ", "_")[:40]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    _STATE_KEY = "tiered_knowledge_state"

    def _load_state(self) -> None:
        if not self.knowledge_db:
            return
        try:
            state = self.knowledge_db.get(self._STATE_KEY)
            if isinstance(state, dict):
                tier_val = int(state.get("current_tier", 0))
                self._current_tier = KnowledgeTier(
                    min(tier_val, int(KnowledgeTier.ADVANCED))
                )
                self._topic_fact_counts = {
                    str(k): int(v)
                    for k, v in state.get("topic_fact_counts", {}).items()
                }
                log.info(
                    "[TieredKnowledge] Loaded state: tier=%s, topics tracked=%d",
                    _TIER_NAMES[self._current_tier],
                    len(self._topic_fact_counts),
                )
        except Exception as exc:
            log.debug("[TieredKnowledge] State load failed: %s", exc)

    def _save_state(self) -> None:
        if not self.knowledge_db:
            return
        try:
            self.knowledge_db.set(self._STATE_KEY, {
                "current_tier":       int(self._current_tier),
                "topic_fact_counts":  dict(self._topic_fact_counts),
                "ts":                 int(time.time()),
            })
        except Exception as exc:
            log.debug("[TieredKnowledge] State save failed: %s", exc)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def current_tier(self) -> KnowledgeTier:
        """Current active KnowledgeTier (read-only)."""
        return self._current_tier

    @property
    def current_tier_name(self) -> str:
        """Human-readable name for the current tier."""
        return _TIER_NAMES[self._current_tier]

    def get_sources(self, tier: Optional[KnowledgeTier] = None) -> List[str]:
        """Return the list of source-backend identifiers for *tier* (current if None)."""
        return list(TIER_SOURCES.get(tier or self._current_tier, []))

    def get_topics(self, tier: Optional[KnowledgeTier] = None) -> List[str]:
        """Return the full topic list for *tier* (current if None)."""
        return list(TIER_TOPICS.get(tier or self._current_tier, []))

    # ------------------------------------------------------------------
    # Confidence and advancement
    # ------------------------------------------------------------------

    def tier_confidence(self, tier: Optional[KnowledgeTier] = None) -> float:
        """Return [0.0, 1.0] coverage confidence for *tier* (current if None).

        Confidence = fraction of tier topics with ≥ ``_MIN_FACTS_PER_TOPIC``
        stored KB facts.
        """
        target = tier or self._current_tier
        topics = TIER_TOPICS.get(target, [])
        if not topics:
            return 1.0
        covered = sum(
            1 for t in topics
            if self._topic_fact_counts.get(self._normalize_topic_key(t), 0) >= _MIN_FACTS_PER_TOPIC
        )
        return covered / len(topics)

    def record_topic_researched(self, topic: str, facts_added: int = 1) -> None:
        """Increment the fact count for *topic* and check for tier advancement.

        Call this every time new facts are stored for a topic so the system
        can track progress toward 100% tier confidence.
        """
        key = self._normalize_topic_key(topic)
        self._topic_fact_counts[key] = self._topic_fact_counts.get(key, 0) + facts_added
        self._save_state()
        # Advance to the next tier when 100% confidence is achieved
        conf = self.tier_confidence()
        if conf >= 1.0 and self._current_tier < KnowledgeTier.ADVANCED:
            self._advance_tier()

    def _advance_tier(self) -> None:
        """Move to the next tier and log the advancement."""
        old_name = _TIER_NAMES[self._current_tier]
        self._current_tier = KnowledgeTier(int(self._current_tier) + 1)
        new_name = _TIER_NAMES[self._current_tier]
        log.info(
            "🎓 [TieredKnowledge] Tier advanced: %s → %s (100%% confidence achieved)",
            old_name, new_name,
        )
        if self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"tier_advancement:{int(time.time())}",
                    {
                        "from_tier": old_name,
                        "to_tier":   new_name,
                        "ts":        int(time.time()),
                    },
                    tags=["tier_advancement", "knowledge_tier", "ale_milestone"],
                )
                self.knowledge_db.log_event(
                    f"Knowledge tier advanced: {old_name} → {new_name}"
                )
            except Exception as exc:
                log.debug("[TieredKnowledge] KB advancement write failed: %s", exc)
        self._save_state()

    # ------------------------------------------------------------------
    # Structured storage and recall
    # ------------------------------------------------------------------

    def store_knowledge(
        self,
        topic:   str,
        content: str,
        source:  str = "unknown",
        tier:    Optional[KnowledgeTier] = None,
    ) -> None:
        """Store *content* for *topic* with tier-specific tags.

        The stored fact is tagged with:
        * ``tiered_knowledge``        — generic tier-system marker
        * ``tier_<tier_name_lower>``  — e.g. ``tier_foundation``
        * ``topic_<slug>``            — first 40 chars of the topic slug
        * ``ale_learned``             — standard ALE marker

        These tags enable fast ``recall_knowledge()`` look-ups without
        scanning the whole KB.
        """
        target_tier = tier or self._current_tier
        tier_name   = _TIER_NAMES[target_tier]
        if not self.knowledge_db:
            return
        try:
            topic_slug = self._make_topic_slug(topic)
            key = f"tier:{tier_name.lower()}:{topic_slug}:{int(time.time())}"
            self.knowledge_db.add_fact(
                key,
                {
                    "topic":   topic,
                    "content": content[:600],
                    "tier":    tier_name,
                    "source":  source,
                    "ts":      int(time.time()),
                },
                tags=[
                    "tiered_knowledge",
                    f"tier_{tier_name.lower()}",
                    f"topic_{topic_slug}",
                    "ale_learned",
                ],
            )
            self.record_topic_researched(topic)
        except Exception as exc:
            log.debug("[TieredKnowledge] store_knowledge failed: %s", exc)

    def recall_knowledge(self, topic: str) -> Optional[str]:
        """Return a formatted string with all stored KB entries for *topic*.

        Searches by the ``topic_<slug>`` tag first; falls back to a key
        prefix scan when tag-based search is not supported by the KB backend.
        Returns ``None`` if no relevant entries are found.
        """
        if not self.knowledge_db:
            return None
        try:
            topic_slug = self._make_topic_slug(topic)
            tag        = f"topic_{topic_slug}"
            facts: List[Any] = []

            if hasattr(self.knowledge_db, "search_by_tag"):
                facts = self.knowledge_db.search_by_tag(tag) or []
            elif hasattr(self.knowledge_db, "list_facts"):
                all_facts = self.knowledge_db.list_facts(300) or []
                needle = topic_slug.lower()
                facts = [
                    f for f in all_facts
                    if isinstance(f, dict) and needle in str(f.get("key", "")).lower()
                ]

            if not facts:
                return None

            parts: List[str] = []
            for f in facts[:6]:
                if isinstance(f, dict):
                    v = f.get("value", f)
                    if isinstance(v, dict):
                        parts.append(
                            f"[{v.get('tier','?')}|{v.get('source','?')}] "
                            f"{v.get('content','')[:250]}"
                        )
                    else:
                        parts.append(str(v)[:250])
            return "\n".join(parts) if parts else None
        except Exception as exc:
            log.debug("[TieredKnowledge] recall_knowledge failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Topic selection helpers for ALE
    # ------------------------------------------------------------------

    def next_uncovered_topic(self) -> Optional[str]:
        """Return the next topic in the current tier that still needs research.

        Returns ``None`` when all topics in the current tier are fully covered
        (i.e. the tier confidence is 1.0).
        """
        for topic in TIER_TOPICS.get(self._current_tier, []):
            if self._topic_fact_counts.get(self._normalize_topic_key(topic), 0) < _MIN_FACTS_PER_TOPIC:
                return topic
        return None

    def all_tiers_complete(self) -> bool:
        """Return True when the Advanced tier confidence is also 1.0."""
        return (
            self._current_tier == KnowledgeTier.ADVANCED
            and self.tier_confidence(KnowledgeTier.ADVANCED) >= 1.0
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status_summary(self) -> str:
        """One-line status string suitable for log messages and CLI status."""
        conf   = self.tier_confidence()
        topics = TIER_TOPICS.get(self._current_tier, [])
        covered = sum(
            1 for t in topics
            if self._topic_fact_counts.get(self._normalize_topic_key(t), 0) >= _MIN_FACTS_PER_TOPIC
        )
        return (
            f"KnowledgeTier={self.current_tier_name} | "
            f"Confidence={conf:.0%} ({covered}/{len(topics)} topics covered)"
        )

    def full_report(self) -> Dict[str, Any]:
        """Return a dict with confidence for every tier, for status/debug output."""
        return {
            "current_tier": self.current_tier_name,
            "tiers": {
                _TIER_NAMES[t]: {
                    "confidence": round(self.tier_confidence(t), 3),
                    "sources":    TIER_SOURCES[t],
                    "topics_total":   len(TIER_TOPICS[t]),
                    "topics_covered": sum(
                        1 for top in TIER_TOPICS[t]
                        if self._topic_fact_counts.get(self._normalize_topic_key(top), 0)
                        >= _MIN_FACTS_PER_TOPIC
                    ),
                }
                for t in KnowledgeTier
            },
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_instance: Optional[TieredKnowledgeSystem] = None


def get_tiered_knowledge_system(
    knowledge_db: Any = None,
) -> TieredKnowledgeSystem:
    """Return the process-wide TieredKnowledgeSystem singleton.

    Creates it on first call.  If *knowledge_db* is provided and the
    existing instance has no DB yet, the DB is attached and state is loaded.
    """
    global _instance
    if _instance is None:
        _instance = TieredKnowledgeSystem(knowledge_db=knowledge_db)
    elif knowledge_db is not None and _instance.knowledge_db is None:
        _instance.knowledge_db = knowledge_db
        _instance._load_state()
    return _instance


if __name__ == "__main__":
    print('Running tiered_knowledge_system.py')
