#!/usr/bin/env python3
"""
METACOGNITION MODULE
Know what you know - understand own knowledge and limitations
"""

import logging
from typing import Dict, List, Any

log = logging.getLogger("Metacognition")


class Metacognition:
    """Self-aware knowledge evaluation"""
    
    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.knowledge_map = {}
        self.confidence_levels = {}
        self.knowledge_boundaries = set()
    
    def build_knowledge_map(self, facts: List[Dict]) -> Dict[str, Any]:
        """
        Map what Niblit knows
        Track confidence levels and boundaries
        """
        log.info(f"🧠 [META] Building knowledge map from {len(facts)} facts")
        
        knowledge_map = {
            "total_facts": len(facts),
            "categories": {},
            "high_confidence": [],
            "medium_confidence": [],
            "low_confidence": [],
            "uncertain": []
        }
        
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "general"
            
            if category not in knowledge_map["categories"]:
                knowledge_map["categories"][category] = 0
            knowledge_map["categories"][category] += 1
            
            # Estimate confidence based on source
            confidence = self._estimate_confidence(fact)
            if confidence >= 0.8:
                knowledge_map["high_confidence"].append(key)
            elif confidence >= 0.5:
                knowledge_map["medium_confidence"].append(key)
            elif confidence >= 0.2:
                knowledge_map["low_confidence"].append(key)
            else:
                knowledge_map["uncertain"].append(key)
        
        self.knowledge_map = knowledge_map
        log.info(f"✅ [META] Knowledge map built")
        return knowledge_map
    
    def identify_knowledge_boundaries(self, attempted_topics: List[str]) -> Dict[str, List[str]]:
        """
        Identify where knowledge ends
        Recognize what Niblit doesn't know well
        """
        log.info(f"🚧 [META] Identifying knowledge boundaries")
        
        boundaries = {
            "well_understood": [],
            "partially_understood": [],
            "poorly_understood": [],
            "unknown": []
        }
        
        for topic in attempted_topics:
            # Check if in knowledge map
            topic_facts = [f for f in self.knowledge_map.get("high_confidence", []) if topic in f]
            
            if len(topic_facts) > 5:
                boundaries["well_understood"].append(topic)
            elif len(topic_facts) > 2:
                boundaries["partially_understood"].append(topic)
            elif len(topic_facts) > 0:
                boundaries["poorly_understood"].append(topic)
            else:
                boundaries["unknown"].append(topic)
        
        self.knowledge_boundaries = set(attempted_topics)
        log.info(f"✅ [META] Boundaries identified")
        return boundaries
    
    def evaluate_understanding(self) -> Dict[str, Any]:
        """
        Self-evaluate overall understanding
        """
        log.info(f"📊 [META] Evaluating understanding")
        
        total = len(self.knowledge_map.get("high_confidence", [])) + \
                len(self.knowledge_map.get("medium_confidence", [])) + \
                len(self.knowledge_map.get("low_confidence", []))
        
        evaluation = {
            "total_knowledge_items": self.knowledge_map.get("total_facts", 0),
            "high_confidence_facts": len(self.knowledge_map.get("high_confidence", [])),
            "medium_confidence_facts": len(self.knowledge_map.get("medium_confidence", [])),
            "low_confidence_facts": len(self.knowledge_map.get("low_confidence", [])),
            "uncertain_facts": len(self.knowledge_map.get("uncertain", [])),
            "overall_confidence": f"{(len(self.knowledge_map.get('high_confidence', [])) / max(1, total)) * 100:.1f}%",
            "knowledge_quality": "Good" if total > 50 else "Developing",
            "recommendation": "Continue learning to increase confidence across more domains"
        }
        
        log.info(f"✅ [META] Evaluation: {evaluation['overall_confidence']} confidence")
        return evaluation
    
    def _estimate_confidence(self, fact: Dict) -> float:
        """
        Estimate confidence in a fact
        Based on source and tags
        """
        source = fact.get("source", "unknown").lower()
        tags = fact.get("tags", [])
        
        confidence = 0.5  # Base confidence
        
        # Higher confidence for academic sources
        if "wikipedia" in source or "academic" in source:
            confidence += 0.2
        elif "research" in tags:
            confidence += 0.15
        elif "web" in tags:
            confidence += 0.1
        
        # Reduce for uncertain tags
        if "uncertain" in tags:
            confidence -= 0.2
        if "preliminary" in tags:
            confidence -= 0.15
        
        return min(1.0, max(0.0, confidence))
