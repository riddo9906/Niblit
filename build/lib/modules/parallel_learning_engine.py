#!/usr/bin/env python3
"""
PARALLEL LEARNING ENGINE
Enables Niblit to research multiple topics simultaneously instead of sequentially.

Improvements over the original:
- running_tasks no longer stores Future objects (memory leak for long runs).
  Task metadata is lightweight: topic, status, start_time, and error only.
- Completed-task list is capped at _MAX_COMPLETED_HISTORY (100 entries) to
  prevent unbounded memory growth.
- _research_single_topic() calls researcher.search() or researcher.research()
  with a minimal, compatible signature rather than hard-coded kwargs that only
  matched older SelfResearcher versions.
- Results are persisted to the KB if knowledge_db is provided.
- shutdown() is idempotent (safe to call multiple times).
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("ParallelLearning")

# Cap on the number of completed-task entries held in memory.
_MAX_COMPLETED_HISTORY: int = 100


class ParallelLearningEngine:
    """Process multiple research topics in parallel for faster learning."""

    def __init__(
        self,
        max_workers: int = 4,
        timeout_per_topic: int = 30,
        knowledge_db: Any = None,
    ):
        """
        Parameters
        ----------
        max_workers:       Maximum concurrent research threads.
        timeout_per_topic: Maximum seconds to wait for a single topic.
        knowledge_db:      Optional KnowledgeDB for persisting results.
        """
        self.max_workers = max_workers
        self.timeout_per_topic = timeout_per_topic
        self._db = knowledge_db
        self._executor: Optional[ThreadPoolExecutor] = None
        self._shutdown = False

        # Lightweight task tracking (no Future objects stored here).
        self.running_tasks: Dict[str, Dict[str, Any]] = {}
        self.completed_tasks: List[Dict[str, Any]] = []
        self.failed_tasks: List[Dict[str, Any]] = []
        self.stats: Dict[str, Any] = {
            "total_topics_processed": 0,
            "topics_completed": 0,
            "topics_failed": 0,
            "average_time_per_topic": 0.0,
            "parallel_speedup": 1.0,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

        log.info("✅ ParallelLearningEngine initialized (workers=%d)", max_workers)

    # ── Executor management ────────────────────────────────────────────────────

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazily create (or recreate) the thread-pool executor."""
        if self._executor is None or self._shutdown:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self._shutdown = False
        return self._executor

    # ── Public API ─────────────────────────────────────────────────────────────

    def research_topics_parallel(
        self,
        topics: List[str],
        researcher: Any,
    ) -> Dict[str, Any]:
        """Research multiple topics in parallel.

        Parameters
        ----------
        topics:     List of topic strings to research.
        researcher: Any object exposing ``search(topic)`` or ``research(topic)``.

        Returns
        -------
        Dict with ``status``, ``results``, timing, and stats.
        """
        if not topics:
            return {"status": "empty", "results": {}}

        log.info("🚀 [PARALLEL] Starting parallel research for %d topics", len(topics))

        executor = self._get_executor()
        start_time = time.time()
        results: Dict[str, Any] = {}
        futures: Dict[Any, str] = {}

        for topic in topics:
            future = executor.submit(self._research_single_topic, topic, researcher)
            futures[future] = topic
            self.running_tasks[topic] = {
                "status": "running",
                "start_time": time.time(),
            }

        completed = 0
        failed = 0

        for future in as_completed(futures):
            topic = futures[future]
            try:
                result = future.result(timeout=self.timeout_per_topic)
                results[topic] = result
                self.running_tasks[topic]["status"] = "completed"
                self._add_completed(topic, result)
                completed += 1
                log.info("✅ [PARALLEL] Completed: %s", topic)

                # Persist to KB
                if result.get("status") == "success":
                    self._persist(f"parallel_research:{topic}", {
                        "topic": topic,
                        "snippet": str(result.get("data", ""))[:300],
                    })

            except Exception as exc:
                log.error("❌ [PARALLEL] Failed: %s — %s", topic, exc)
                self.running_tasks[topic]["status"] = "failed"
                self.running_tasks[topic]["error"] = str(exc)
                self.failed_tasks.append({
                    "topic": topic,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                })
                failed += 1

        elapsed = time.time() - start_time

        # Prune running_tasks: remove completed/failed entries to free memory
        done_statuses = {"completed", "failed"}
        self.running_tasks = {
            k: v for k, v in self.running_tasks.items()
            if v.get("status") not in done_statuses
        }

        # Update stats
        self.stats["total_topics_processed"] += len(topics)
        self.stats["topics_completed"] += completed
        self.stats["topics_failed"] += failed
        if completed > 0 and elapsed > 0:
            self.stats["average_time_per_topic"] = elapsed / completed
            # Speedup vs. sequential: if each topic took avg_time, sequential
            # total = completed * avg_time; actual = elapsed
            self.stats["parallel_speedup"] = (completed * self.stats["average_time_per_topic"]) / elapsed

        return {
            "status": "completed",
            "total_topics": len(topics),
            "completed": completed,
            "failed": failed,
            "elapsed_seconds": elapsed,
            "parallel_speedup": self.stats["parallel_speedup"],
            "results": results,
        }

    def research_batches(
        self,
        topic_batches: List[List[str]],
        researcher: Any,
    ) -> Dict[str, Any]:
        """Research topics in batches for very large topic lists."""
        log.info("📦 [PARALLEL] Processing %d batches", len(topic_batches))

        all_results: Dict[str, Any] = {
            "status": "completed",
            "batches": [],
            "total_completed": 0,
            "total_failed": 0,
            "total_time": 0.0,
        }

        start_time = time.time()
        for i, batch in enumerate(topic_batches):
            batch_result = self.research_topics_parallel(batch, researcher)
            all_results["batches"].append({"batch_num": i + 1, "batch_size": len(batch), **batch_result})
            all_results["total_completed"] += batch_result.get("completed", 0)
            all_results["total_failed"] += batch_result.get("failed", 0)

        all_results["total_time"] = time.time() - start_time
        return all_results

    def get_stats(self) -> Dict[str, Any]:
        """Return performance statistics."""
        return {
            "stats": self.stats,
            "active_tasks": len(self.running_tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "max_workers": self.max_workers,
            "timeout_per_topic": self.timeout_per_topic,
        }

    def shutdown(self) -> None:
        """Gracefully shut down the executor.  Safe to call multiple times."""
        if self._executor is not None and not self._shutdown:
            self._executor.shutdown(wait=True)
            self._shutdown = True
            log.info("🛑 ParallelLearningEngine shutdown")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _research_single_topic(self, topic: str, researcher: Any) -> Dict[str, Any]:
        """Research a single topic using the provided researcher.

        Tries ``researcher.search(topic)`` first, then ``researcher.research(topic)``.
        Both are called with positional argument only for maximum compatibility.
        """
        try:
            if hasattr(researcher, "search"):
                data = researcher.search(topic)
            elif hasattr(researcher, "research"):
                data = researcher.research(topic)
            else:
                return {"status": "error", "topic": topic, "error": "no compatible research method"}

            return {
                "status": "success",
                "topic": topic,
                "results_count": len(data) if isinstance(data, (list, dict)) else 1,
                "data": data,
            }
        except Exception as exc:
            return {"status": "error", "topic": topic, "error": str(exc)}

    def _add_completed(self, topic: str, result: Dict[str, Any]) -> None:
        """Add to completed list, evicting oldest entries beyond the cap."""
        entry = {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": result.get("status", "unknown"),
        }
        if len(self.completed_tasks) >= _MAX_COMPLETED_HISTORY:
            self.completed_tasks.pop(0)
        self.completed_tasks.append(entry)

    def _persist(self, key: str, data: Any) -> None:
        """Persist a result fact to the KB."""
        if self._db is None:
            return
        try:
            if hasattr(self._db, "add_fact"):
                self._db.add_fact(key, data, tags=["parallel_learning"])
            elif hasattr(self._db, "store_learning"):
                self._db.store_learning({"key": key, "data": data, "tags": ["parallel_learning"]})
        except Exception as exc:
            log.debug("[ParallelLearning] KB persist failed: %s", exc)


if __name__ == "__main__":
    print("Running parallel_learning_engine.py")

