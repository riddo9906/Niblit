#!/usr/bin/env python3
"""
PARALLEL LEARNING ENGINE
Enables Niblit to research multiple topics simultaneously instead of sequentially.
Improvement #1: Faster Learning
"""

import threading
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

log = logging.getLogger("ParallelLearning")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)


class ParallelLearningEngine:
    """Process multiple research topics in parallel for faster learning"""
    
    def __init__(self, max_workers=4, timeout_per_topic=30):
        """
        Args:
            max_workers: Maximum concurrent research threads
            timeout_per_topic: Max seconds per topic research
        """
        self.max_workers = max_workers
        self.timeout_per_topic = timeout_per_topic
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        self.running_tasks = {}
        self.completed_tasks = []
        self.failed_tasks = []
        self.stats = {
            "total_topics_processed": 0,
            "topics_completed": 0,
            "topics_failed": 0,
            "average_time_per_topic": 0.0,
            "parallel_speedup": 1.0,
            "start_time": datetime.utcnow().isoformat()
        }
        
        log.info("✅ ParallelLearningEngine initialized")

    def research_topics_parallel(self, topics: List[str], researcher) -> Dict[str, any]:
        """
        Research multiple topics in parallel.
        
        Args:
            topics: List of topics to research
            researcher: SelfResearcher instance
            
        Returns:
            Dict with results, timing, and stats
        """
        if not topics:
            return {"status": "empty", "results": {}}
        
        log.info(f"🚀 [PARALLEL] Starting parallel research for {len(topics)} topics")
        
        start_time = time.time()
        results = {}
        futures = {}
        
        # Submit all topics
        for topic in topics:
            future = self.executor.submit(self._research_single_topic, topic, researcher)
            futures[future] = topic
            self.running_tasks[topic] = {
                "status": "running",
                "start_time": time.time(),
                "future": future
            }
        
        # Collect results as they complete
        completed = 0
        failed = 0
        
        for future in as_completed(futures):
            topic = futures[future]
            try:
                result = future.result(timeout=self.timeout_per_topic)
                results[topic] = result
                self.running_tasks[topic]["status"] = "completed"
                self.running_tasks[topic]["result"] = result
                self.completed_tasks.append({
                    "topic": topic,
                    "timestamp": datetime.utcnow().isoformat(),
                    "result": result
                })
                completed += 1
                log.info(f"✅ [PARALLEL] Completed: {topic}")
            except Exception as e:
                log.error(f"❌ [PARALLEL] Failed: {topic} - {e}")
                self.running_tasks[topic]["status"] = "failed"
                self.running_tasks[topic]["error"] = str(e)
                self.failed_tasks.append({
                    "topic": topic,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": str(e)
                })
                failed += 1
        
        elapsed = time.time() - start_time
        
        # Update stats
        self.stats["total_topics_processed"] += len(topics)
        self.stats["topics_completed"] += completed
        self.stats["topics_failed"] += failed
        
        if completed > 0:
            # Sequential would take: completed * average_topic_time
            sequential_time = completed * (elapsed / len(topics))
            self.stats["parallel_speedup"] = sequential_time / elapsed if elapsed > 0 else 1.0
            self.stats["average_time_per_topic"] = elapsed / completed
        
        return {
            "status": "completed",
            "total_topics": len(topics),
            "completed": completed,
            "failed": failed,
            "elapsed_seconds": elapsed,
            "parallel_speedup": self.stats["parallel_speedup"],
            "results": results
        }

    def _research_single_topic(self, topic: str, researcher) -> Dict:
        """Research a single topic"""
        try:
            if not hasattr(researcher, "search"):
                return {"status": "error", "message": "Researcher missing search method"}
            
            result = researcher.search(
                topic,
                max_results=5,
                use_llm=False,
                synthesize=False,
                enable_autonomous_learning=True
            )
            
            return {
                "status": "success",
                "topic": topic,
                "results_count": len(result) if isinstance(result, list) else 1,
                "data": result
            }
        except Exception as e:
            return {
                "status": "error",
                "topic": topic,
                "error": str(e)
            }

    def research_batches(self, topic_batches: List[List[str]], researcher) -> Dict:
        """
        Research topics in batches for very large topic lists.
        
        Args:
            topic_batches: List of topic lists (each list = batch)
            researcher: SelfResearcher instance
            
        Returns:
            Combined results from all batches
        """
        log.info(f"📦 [PARALLEL] Processing {len(topic_batches)} batches")
        
        all_results = {
            "status": "completed",
            "batches": [],
            "total_completed": 0,
            "total_failed": 0,
            "total_time": 0.0
        }
        
        start_time = time.time()
        
        for i, batch in enumerate(topic_batches):
            batch_result = self.research_topics_parallel(batch, researcher)
            all_results["batches"].append({
                "batch_num": i + 1,
                "batch_size": len(batch),
                **batch_result
            })
            all_results["total_completed"] += batch_result.get("completed", 0)
            all_results["total_failed"] += batch_result.get("failed", 0)
        
        all_results["total_time"] = time.time() - start_time
        
        return all_results

    def get_stats(self) -> Dict:
        """Get performance statistics"""
        return {
            "stats": self.stats,
            "running_tasks": len(self.running_tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "max_workers": self.max_workers,
            "timeout_per_topic": self.timeout_per_topic
        }

    def shutdown(self):
        """Gracefully shutdown executor"""
        self.executor.shutdown(wait=True)
        log.info("🛑 ParallelLearningEngine shutdown")


if __name__ == "__main__":
    print("Running parallel_learning_engine.py")
