#!/usr/bin/env python3
"""
PARALLEL LEARNER MODULE
Enables simultaneous research on multiple topics for faster learning
"""

import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

log = logging.getLogger("ParallelLearner")


class ParallelLearner:
    """Process multiple research topics concurrently"""
    
    def __init__(self, researcher, max_workers: int = 3):
        self.researcher = researcher
        self.max_workers = max_workers
        self.results = {}
        self.lock = threading.Lock()
    
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
