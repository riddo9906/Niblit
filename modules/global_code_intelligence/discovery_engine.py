#!/usr/bin/env python3
"""
modules/global_code_intelligence/discovery_engine.py

Detect emerging technologies by monitoring adoption velocity across the
global code ecosystem.

Process::

    scan repositories  (EcosystemScanner)
      ↓
    detect rapid adoption (star growth, topic clustering)
      ↓
    cluster related technologies
      ↓
    flag emerging trends

The engine maintains a rolling snapshot of technology adoption and computes
velocity (growth rate) between snapshots.

Usage::

    from modules.global_code_intelligence.discovery_engine import DiscoveryEngine
    engine = DiscoveryEngine()
    engine.record_snapshot(ecosystem_scanner_records)
    trends = engine.detect_trends(min_velocity=0.3)
    report = engine.generate_report()
"""

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

log = logging.getLogger("DiscoveryEngine")

# Minimum star count to be considered "significant"
_MIN_STARS = 50
# Minimum fractional growth rate to flag as "emerging"
_MIN_VELOCITY_THRESHOLD = 0.2

class DiscoveryEngine:
    """
    Track technology adoption velocity and identify emerging trends.
    """

    def __init__(self) -> None:
        # snapshots: list of {timestamp, topic_stars: {topic → total_stars}}
        self._snapshots: List[Dict[str, Any]] = []
        # Known breakthrough discoveries
        self._discoveries: List[Dict[str, Any]] = []

    # ── public API ────────────────────────────────────────────────────────────

    def record_snapshot(
        self, records: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Record a snapshot of current ecosystem adoption.

        *records* is a list from EcosystemScanner.

        Returns a dict of topic → cumulative stars for this snapshot.
        """
        topic_stars: Dict[str, int] = defaultdict(int)
        for rec in records:
            stars = rec.get("stars", 0)
            for topic in rec.get("topics", []):
                topic_stars[topic.lower()] += stars
            # Also count by language/domain
            lang = rec.get("language", "").lower()
            if lang:
                topic_stars[lang] += stars
            domain = rec.get("domain", "").lower()
            if domain:
                topic_stars[domain] += stars

        self._snapshots.append({
            "timestamp": time.time(),
            "topic_stars": dict(topic_stars),
        })
        log.debug("DiscoveryEngine: snapshot recorded (%d topics)", len(topic_stars))
        return dict(topic_stars)

    def detect_trends(
        self,
        min_velocity: float = _MIN_VELOCITY_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """
        Compare the two most recent snapshots and return topics with high
        growth velocity.

        Returns a list of dicts: {topic, old_stars, new_stars, velocity}.
        """
        if len(self._snapshots) < 2:
            log.info("DiscoveryEngine: need at least 2 snapshots to detect trends")
            return []

        old = self._snapshots[-2]["topic_stars"]
        new = self._snapshots[-1]["topic_stars"]

        trends: List[Dict[str, Any]] = []
        all_topics = set(old) | set(new)

        for topic in all_topics:
            old_stars = old.get(topic, 0)
            new_stars = new.get(topic, 0)
            if old_stars < _MIN_STARS and new_stars < _MIN_STARS:
                continue
            if old_stars == 0:
                velocity = 1.0 if new_stars > 0 else 0.0
            else:
                velocity = (new_stars - old_stars) / old_stars

            if velocity >= min_velocity:
                trends.append({
                    "topic": topic,
                    "old_stars": old_stars,
                    "new_stars": new_stars,
                    "velocity": round(velocity, 3),
                })

        trends.sort(key=lambda x: x["velocity"], reverse=True)
        return trends

    def detect_breakthroughs(
        self,
        results: List[Dict[str, Any]],
        threshold: float = 0.5,
    ) -> Optional[Dict[str, Any]]:
        """
        Check whether any result exceeds a performance threshold.

        Used by the SEADL DiscoveryEngine to flag algorithmic breakthroughs.

        Returns a discovery dict or None.
        """
        best = max(results, key=lambda r: r.get("performance", 0.0), default=None)
        if best and best.get("performance", 0.0) >= threshold:
            discovery = {
                "type": "breakthrough",
                "result": best,
                "threshold": threshold,
                "timestamp": time.time(),
            }
            self._discoveries.append(discovery)
            log.info("DiscoveryEngine: breakthrough detected — performance=%.3f", best["performance"])
            return discovery
        return None

    def cluster_topics(
        self, records: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        Group technologies into clusters based on co-occurrence in repositories.

        Returns {cluster_seed: [related_technologies]}.
        """
        co: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for rec in records:
            topics = [t.lower() for t in rec.get("topics", [])]
            lang = rec.get("language", "").lower()
            if lang:
                topics.append(lang)
            for i, a in enumerate(topics):
                for b in topics[i + 1:]:
                    co[a][b] += 1
                    co[b][a] += 1

        clusters: Dict[str, List[str]] = {}
        for topic, related_counts in co.items():
            top_related = sorted(related_counts, key=lambda k: related_counts[k], reverse=True)[:5]
            clusters[topic] = top_related

        return clusters

    def emerging_technologies(
        self, min_velocity: float = _MIN_VELOCITY_THRESHOLD
    ) -> List[str]:
        """Return names of emerging technologies (list of topic strings)."""
        return [t["topic"] for t in self.detect_trends(min_velocity=min_velocity)]

    def generate_report(self) -> Dict[str, Any]:
        """Generate a human-readable discovery report."""
        trends = self.detect_trends()
        return {
            "snapshot_count": len(self._snapshots),
            "discoveries": len(self._discoveries),
            "top_trends": trends[:10],
            "emerging": [t["topic"] for t in trends[:5]],
        }

    def stats(self) -> Dict[str, int]:
        return {
            "snapshots": len(self._snapshots),
            "discoveries": len(self._discoveries),
        }
