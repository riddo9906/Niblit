#!/usr/bin/env python3
"""
ADAPTIVE LEARNING MODULE
Learn user preferences and adapt learning strategy dynamically
"""

import logging
from typing import Dict, List, Any
from collections import defaultdict

log = logging.getLogger("AdaptiveLearning")


class AdaptiveLearning:
    """Adapt learning based on user feedback and preferences"""
    
    def __init__(self):
        self.user_preferences = defaultdict(int)
        self.feedback_history = []
        self.learning_strategy = "balanced"  # balanced, aggressive, conservative
    
    def track_user_interest(self, topic: str, interest_level: int = 1) -> None:
        """
        Track topics the user is interested in
        Higher numbers = more interest
        """
        log.info(f"📌 [ADAPTIVE] Tracking interest in '{topic}' (level: {interest_level})")
        self.user_preferences[topic] += interest_level
    
    def record_feedback(self, query: str, response: str, satisfaction: int) -> None:
        """
        Record user feedback on responses
        Satisfaction: 1-5 (1=bad, 5=excellent)
        """
        log.info(f"💬 [ADAPTIVE] Recording feedback: {satisfaction}/5")
        
        self.feedback_history.append({
            "query": query,
            "response": response,
            "satisfaction": satisfaction
        })
        
        # Adjust strategy based on feedback
        if satisfaction >= 4:
            self.learning_strategy = "aggressive"  # Continue this path
        elif satisfaction <= 2:
            self.learning_strategy = "conservative"  # Slow down
    
    def get_recommended_topics(self, count: int = 5) -> List[str]:
        """
        Get recommended research topics based on user preferences
        """
        log.info(f"🎯 [ADAPTIVE] Getting recommendations")
        
        # Sort by preference
        sorted_topics = sorted(self.user_preferences.items(), key=lambda x: x[1], reverse=True)
        recommendations = [topic for topic, _ in sorted_topics[:count]]
        
        log.info(f"✅ [ADAPTIVE] Recommended: {recommendations}")
        return recommendations
    
    def adjust_learning_pace(self) -> Dict[str, Any]:
        """
        Adjust learning pace based on performance
        """
        log.info(f"⚙️ [ADAPTIVE] Adjusting learning pace")
        
        # Calculate average satisfaction
        if self.feedback_history:
            avg_satisfaction = sum(f["satisfaction"] for f in self.feedback_history) / len(self.feedback_history)
        else:
            avg_satisfaction = 3
        
        pace = {
            "strategy": self.learning_strategy,
            "average_satisfaction": avg_satisfaction,
            "cycles_per_hour": 6 if self.learning_strategy == "aggressive" else 3,
            "topics_per_cycle": 3 if self.learning_strategy == "aggressive" else 1,
            "explanation": f"Learning pace set to '{self.learning_strategy}' based on feedback"
        }
        
        log.info(f"✅ [ADAPTIVE] Pace adjusted: {pace}")
        return pace
