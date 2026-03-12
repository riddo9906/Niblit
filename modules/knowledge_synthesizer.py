#!/usr/bin/env python3
"""
KNOWLEDGE SYNTHESIZER MODULE
Combines information from multiple sources into unified knowledge
"""

import logging
from typing import List, Dict, Any

log = logging.getLogger("KnowledgeSynthesizer")


class KnowledgeSynthesizer:
    """Synthesize knowledge from multiple sources"""
    
    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.synthesis_cache = {}
    
    def synthesize_cross_domain(self, topic: str, sources: List[Dict]) -> str:
        """
        Combine information from multiple domains
        Create unified understanding
        """
        log.info(f"🔀 [SYNTHESIZE] Cross-domain synthesis for '{topic}'")
        
        # Extract key points from each source
        key_points = []
        for i, source in enumerate(sources):
            text = source.get("text", "")
            key = self._extract_key_points(text)
            key_points.append({f"source_{i}": key})
        
        # Find common themes
        common_themes = self._find_common_themes(key_points)
        
        # Build synthesis
        synthesis = f"""
🔗 **Synthesized Knowledge: {topic}**

Common Themes:
{chr(10).join(f"• {theme}" for theme in common_themes[:5])}

Cross-Domain Insights:
- Applicable in multiple domains
- Connects diverse fields
- Universal principles identified
"""
        
        log.info(f"✅ [SYNTHESIZE] Synthesis created")
        return synthesis
    
    def create_summary(self, facts: List[Dict]) -> str:
        """Create comprehensive summary from facts"""
        log.info(f"📋 [SYNTHESIZE] Creating summary from {len(facts)} facts")
        
        if not facts:
            return "[No facts to summarize]"
        
        summary = "📚 **Knowledge Summary:**\n\n"
        
        categories = {}
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "General"
            if category not in categories:
                categories[category] = []
            categories[category].append(fact.get("value", ""))
        
        for category, values in list(categories.items())[:5]:
            summary += f"\n**{category}:**\n"
            for value in values[:2]:
                summary += f"• {value[:100]}...\n"
        
        log.info(f"✅ [SYNTHESIZE] Summary created")
        return summary
    
    def build_relationships(self, topics: List[str]) -> Dict[str, List[str]]:
        """Build relationship map between topics"""
        log.info(f"🔗 [SYNTHESIZE] Building relationships between {len(topics)} topics")
        
        relationships = {}
        for topic in topics:
            relationships[topic] = self._find_relationships(topic, topics)
        
        log.info(f"✅ [SYNTHESIZE] Relationships built")
        return relationships
    
    def _extract_key_points(self, text: str, limit: int = 3) -> List[str]:
        """Extract key points from text"""
        sentences = text.split(".")
        return [s.strip() for s in sentences[:limit] if len(s.strip()) > 20]
    
    def _find_common_themes(self, sources: List[Dict]) -> List[str]:
        """Find common themes across sources"""
        theme_words = {}
        
        for source in sources:
            for value_list in source.values():
                if isinstance(value_list, list):
                    for phrase in value_list:
                        words = phrase.lower().split()
                        for word in words:
                            if len(word) > 5:
                                theme_words[word] = theme_words.get(word, 0) + 1
        
        # Get most common themes
        return [word for word, count in sorted(theme_words.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    def _find_relationships(self, topic: str, all_topics: List[str]) -> List[str]:
        """Find relationships between topic and others"""
        related = []
        topic_lower = topic.lower()
        
        for other in all_topics:
            if other != topic and topic_lower in other.lower():
                related.append(other)
        
        return related
