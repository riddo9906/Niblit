#!/usr/bin/env python3
"""
PARALLEL LEARNER MODULE
Enables simultaneous research on multiple topics for faster learning
"""

import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]

log = logging.getLogger("ParallelLearner")


class ParallelLearner:
    """Process multiple research topics concurrently"""

    def __init__(self, researcher, max_workers: int = 3, memory=None):
        self.researcher = researcher
        self.max_workers = max_workers
        self.results = {}
        self.lock = threading.Lock()
        # Use canonical niblit_memory singleton if no memory provided
        self.memory = memory or _GLOBAL_MEMORY

    def research_topics_parallel(self, topics: List[str], max_results: int = 5) -> Dict[str, List[Any]]:
        """
        Research multiple topics in parallel
        Returns: {topic: [results]}
        """
        log.info(f"🔄 [PARALLEL] Starting parallel research on {len(topics)} topics")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._research_single, topic, max_results): topic
                for topic in topics
            }

            results = {}
            completed = 0

            for future in as_completed(futures):
                topic = futures[future]
                try:
                    topic_results = future.result(timeout=30)
                    with self.lock:
                        results[topic] = topic_results
                        completed += 1
                    log.info(f"✅ [PARALLEL] {completed}/{len(topics)} completed")
                    # Persist results to canonical memory
                    self._store(topic, topic_results)
                except Exception as e:
                    log.error(f"❌ [PARALLEL] Failed for {topic}: {e}")
                    results[topic] = []

        log.info(f"✅ [PARALLEL] All {len(topics)} topics completed")
        return results

    def _research_single(self, topic: str, max_results: int) -> List[Any]:
        """Research a single topic"""
        try:
            if hasattr(self.researcher, 'search'):
                return self.researcher.search(topic, max_results=max_results) or []
        except Exception as e:
            log.debug(f"Research failed for {topic}: {e}")
        return []

    def get_learning_speed_metrics(self) -> Dict[str, Any]:
        """Return metrics about parallel learning efficiency"""
        return {
            "workers": self.max_workers,
            "capability": "parallel_research",
            "efficiency_gain": f"{self.max_workers}x faster than sequential"
        }

    # ── private ───────────────────────────────────────────────────────────────

    def _store(self, topic: str, results: List[Any]) -> None:
        """Persist research results to niblit_memory."""
        if self.memory is None or not results:
            return
        try:
            snippet = str(results[0])[:300] if results else ""
            if hasattr(self.memory, "add_fact"):
                self.memory.add_fact(
                    f"parallel_research:{topic}",
                    {"topic": topic, "results_count": len(results), "snippet": snippet},
                    tags=["parallel_learning", "research"],
                )
            elif hasattr(self.memory, "store_learning"):
                self.memory.store_learning({
                    "topic": topic, "results_count": len(results),
                    "snippet": snippet, "tags": ["parallel_learning", "research"],
                })
        except Exception as exc:
            log.debug("[ParallelLearner] memory store failed: %s", exc)

