#!/usr/bin/env python3
"""
GAP ANALYZER MODULE
Identifies knowledge gaps from the actual KB and suggests learning topics.

Improvements over the original:
- analyze_gaps() now uses knowledge_recall.knowledge_health() (when available)
  to identify low-coverage topics from the real KB instead of hardcoded dicts.
- _find_related_areas() derives relations from KB key patterns rather than a
  static mapping.
- _find_deepening_opportunities() uses TopicConstructor to produce safe,
  search-API-friendly deepening queries.
- auto_fill_gaps() persists results to the KB after researching each gap.
- All methods are safe to call even when the DB or researcher is None.
"""

import logging
import re
from typing import List, Dict, Any, Optional

log = logging.getLogger("GapAnalyzer")

# Minimum knowledge-health coverage score below which a topic is considered
# a "gap".  Aligned with _GAP_COVERAGE_THRESHOLD in autonomous_learning_engine.
_GAP_COVERAGE_THRESHOLD: float = 0.40

# Fallback hardcoded prerequisite map used when KB-awareness is unavailable.
_PREREQUISITES: Dict[str, List[str]] = {
    "machine learning": ["linear algebra", "statistics", "calculus"],
    "deep learning": ["machine learning", "neural networks", "calculus"],
    "quantum computing": ["quantum mechanics", "linear algebra"],
    "data science": ["statistics", "programming", "data structures"],
    "natural language processing": ["machine learning", "linguistics", "statistics"],
    "computer vision": ["machine learning", "linear algebra", "image processing"],
    "reinforcement learning": ["machine learning", "probability", "optimization"],
    "neural networks": ["linear algebra", "calculus", "statistics"],
}


class GapAnalyzer:
    """Identify knowledge gaps and suggest learning topics."""

    def __init__(self, knowledge_db, researcher, topic_constructor=None):
        self.db = knowledge_db
        self.researcher = researcher
        self.topic_constructor = topic_constructor
        self.known_topics: set = set()
        self.gap_suggestions: Dict[str, List[str]] = {}

    def analyze_gaps(self, researched_topics: List[str]) -> Dict[str, List[str]]:
        """Analyze knowledge gaps from researched topics.

        Uses KB health scores (via knowledge_recall) when available.  Falls
        back to heuristic analysis when the KB or recall module is unavailable.
        """
        log.info("🔍 [GAP] Analyzing gaps from %d topics", len(researched_topics))

        gaps: Dict[str, List[str]] = {
            "missing_prerequisites": [],
            "related_areas": [],
            "deepening_opportunities": [],
            "low_coverage_topics": [],
        }

        # --- KB-aware gap detection -------------------------------------------
        low_coverage = self._find_low_coverage_topics(researched_topics)
        gaps["low_coverage_topics"] = low_coverage

        # --- Heuristic analysis -----------------------------------------------
        for topic in researched_topics:
            prereqs = self._find_missing_prerequisites(topic)
            gaps["missing_prerequisites"].extend(prereqs)

            related = self._find_related_areas(topic)
            gaps["related_areas"].extend(related)

            deep = self._find_deepening_opportunities(topic)
            gaps["deepening_opportunities"].extend(deep)

        # Remove duplicates while preserving order
        for key in gaps:
            seen: set = set()
            deduped = []
            for item in gaps[key]:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            gaps[key] = deduped

        total = sum(len(v) for v in gaps.values())
        log.info("✅ [GAP] Found %d gaps", total)
        self.gap_suggestions = gaps
        return gaps

    def auto_fill_gaps(self, max_topics: int = 5) -> List[str]:
        """Research and fill identified gaps, persisting results to the KB."""
        log.info("🚀 [GAP] Auto-filling gaps")

        all_gaps: List[str] = []
        # Prioritise low-coverage gaps first, then prerequisites
        for key in ("low_coverage_topics", "missing_prerequisites", "related_areas",
                    "deepening_opportunities"):
            all_gaps.extend(self.gap_suggestions.get(key, []))

        topics_to_research = all_gaps[:max_topics]

        for topic in topics_to_research:
            log.info("📚 [GAP] Researching gap: %s", topic)
            try:
                result = None
                if hasattr(self.researcher, "search"):
                    result = self.researcher.search(topic)
                elif hasattr(self.researcher, "research"):
                    result = self.researcher.research(topic)

                # Persist a gap-filled KB fact
                if result:
                    self._persist(f"gap_filled:{topic}", {
                        "topic": topic,
                        "snippet": str(result)[:300],
                    })
            except Exception as exc:
                log.debug("Gap research failed for '%s': %s", topic, exc)

        log.info("✅ [GAP] Filled %d gaps", len(topics_to_research))
        return topics_to_research

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _find_low_coverage_topics(self, topics: List[str]) -> List[str]:
        """Return topics whose KB health coverage score is below the threshold.

        Uses ``knowledge_recall.knowledge_health()`` when available.
        """
        low: List[str] = []
        try:
            from modules.knowledge_recall import get_smart_recall
            recall = get_smart_recall(self.db)
            for topic in topics:
                health = recall.knowledge_health(topic)
                coverage = health.get("coverage_score", 1.0)
                if coverage < _GAP_COVERAGE_THRESHOLD:
                    low.append(topic)
        except Exception:
            pass
        return low

    def _find_missing_prerequisites(self, topic: str) -> List[str]:
        """Find prerequisite topics that are not yet covered in the KB."""
        prereqs = _PREREQUISITES.get(topic.lower(), [])

        # Also look for topics whose keys share a direct dependency token
        if not prereqs and self.db is not None:
            try:
                topic_lower = topic.lower()
                # Check if the topic has any stored facts at all
                results = []
                if hasattr(self.db, "smart_recall"):
                    results = self.db.smart_recall(topic_lower, limit=1)
                if not results:
                    # No facts found → treat parent as a prerequisite gap
                    words = topic_lower.split()
                    if len(words) > 1:
                        prereqs = [words[0]]
            except Exception:
                pass
        return prereqs

    def _find_related_areas(self, topic: str) -> List[str]:
        """Find domains related to *topic* by scanning KB key patterns."""
        related: List[str] = []
        topic_tokens = set(topic.lower().split())

        if self.db is not None:
            try:
                facts = self.db.list_facts(100) if hasattr(self.db, "list_facts") else []
                for fact in facts:
                    key = str(fact.get("key", ""))
                    # Extract the domain prefix before the first colon
                    domain = key.split(":")[0] if ":" in key else key
                    domain_tokens = set(re.sub(r"[_\-]", " ", domain).lower().split())
                    # Related if token overlap exists but is not identical
                    overlap = topic_tokens & domain_tokens
                    if overlap and domain_tokens != topic_tokens and len(domain) >= 3:
                        clean = domain.replace("_", " ").strip()
                        if clean not in related:
                            related.append(clean)
                        if len(related) >= 5:
                            break
            except Exception:
                pass

        return related[:5]

    def _find_deepening_opportunities(self, topic: str) -> List[str]:
        """Return safe, search-API-friendly deepening queries for *topic*."""
        suffixes = [
            "advanced techniques",
            "real world applications",
            "latest research",
            "best practices",
            "implementation examples",
        ]
        topics = []
        for suffix in suffixes:
            raw = f"{topic} {suffix}"
            if self.topic_constructor is not None:
                try:
                    safe = self.topic_constructor.build(raw)
                    topics.append(safe)
                    continue
                except Exception:
                    pass
            # Fallback: basic truncation to 60 chars
            topics.append(raw[:60])
        return topics

    def _persist(self, key: str, data: Any) -> None:
        """Persist a gap fact to the KB."""
        if self.db is None:
            return
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, data, tags=["gap_analysis"])
            elif hasattr(self.db, "store_learning"):
                self.db.store_learning({"key": key, "data": data, "tags": ["gap_analysis"]})
        except Exception as exc:
            log.debug("[GapAnalyzer] KB persist failed: %s", exc)


if __name__ == "__main__":
    print('Running gap_analyzer.py')

