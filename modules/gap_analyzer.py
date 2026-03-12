#!/usr/bin/env python3
"""
GAP ANALYZER MODULE
Identifies knowledge gaps and suggests learning topics
"""

import logging
from typing import List, Dict, Set

log = logging.getLogger("GapAnalyzer")


class GapAnalyzer:
    """Identify and analyze knowledge gaps"""
    
    def __init__(self, knowledge_db, researcher):
        self.db = knowledge_db
        self.researcher = researcher
        self.known_topics = set()
        self.gap_suggestions = []
    
    def analyze_gaps(self, researched_topics: List[str]) -> Dict[str, List[str]]:
        """
        Analyze knowledge gaps from researched topics
        Identify related areas not yet covered
        """
        log.info(f"🔍 [GAP] Analyzing gaps from {len(researched_topics)} topics")
        
        gaps = {
            "missing_prerequisites": [],
            "related_areas": [],
            "deepening_opportunities": [],
            "cross_domain_connections": []
        }
        
        # Analyze each topic
        for topic in researched_topics:
            # Find prerequisites
            prereqs = self._find_missing_prerequisites(topic)
            gaps["missing_prerequisites"].extend(prereqs)
            
            # Find related areas
            related = self._find_related_areas(topic)
            gaps["related_areas"].extend(related)
            
            # Find deepening opportunities
            deep = self._find_deepening_opportunities(topic)
            gaps["deepening_opportunities"].extend(deep)
        
        # Remove duplicates
        for key in gaps:
            gaps[key] = list(set(gaps[key]))
        
        log.info(f"✅ [GAP] Found {sum(len(v) for v in gaps.values())} gaps")
        self.gap_suggestions = gaps
        return gaps
    
    def auto_fill_gaps(self, max_topics: int = 5) -> List[str]:
        """
        Automatically research and fill identified gaps
        """
        log.info(f"🚀 [GAP] Auto-filling gaps")
        
        # Get top gap suggestions
        all_gaps = []
        for gap_list in self.gap_suggestions.values():
            all_gaps.extend(gap_list)
        
        topics_to_research = all_gaps[:max_topics]
        
        if topics_to_research and hasattr(self.researcher, 'search'):
            for topic in topics_to_research:
                log.info(f"📚 [GAP] Researching gap: {topic}")
                try:
                    self.researcher.search(topic)
                except Exception as e:
                    log.debug(f"Gap research failed: {e}")
        
        log.info(f"✅ [GAP] Filled {len(topics_to_research)} gaps")
        return topics_to_research
    
    def _find_missing_prerequisites(self, topic: str) -> List[str]:
        """Find topics that should be learned first"""
        prerequisites = {
            "machine learning": ["linear algebra", "statistics", "calculus"],
            "deep learning": ["machine learning", "neural networks", "calculus"],
            "quantum computing": ["quantum mechanics", "linear algebra"],
            "data science": ["statistics", "programming", "data structures"],
        }
        
        return prerequisites.get(topic.lower(), [])
    
    def _find_related_areas(self, topic: str) -> List[str]:
        """Find related domains and topics"""
        related = {
            "ai": ["machine learning", "deep learning", "nlp", "computer vision"],
            "machine learning": ["ai", "statistics", "data science", "neural networks"],
            "programming": ["algorithms", "data structures", "software engineering"],
            "data science": ["statistics", "machine learning", "data visualization"],
        }
        
        for key in related:
            if key.lower() in topic.lower():
                return related[key]
        return []
    
    def _find_deepening_opportunities(self, topic: str) -> List[str]:
        """Find opportunities to deepen knowledge"""
        return [
            f"{topic} - advanced techniques",
            f"{topic} - real-world applications",
            f"{topic} - latest research",
            f"{topic} - best practices",
            f"{topic} - case studies"
        ]
