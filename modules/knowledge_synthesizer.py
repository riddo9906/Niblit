#!/usr/bin/env python3
"""
KNOWLEDGE SYNTHESIZER MODULE
Combines information from multiple sources into unified knowledge.

Improvements over the original:
- Stop-word filtering so _find_common_themes returns meaningful domain terms
  rather than high-frequency function words.
- synthesize_cross_domain() now produces actual content-based output built
  from extracted sentences and terms, instead of hardcoded placeholder strings.
- _find_relationships() uses term overlap (Jaccard similarity) to find
  semantically related topics instead of pure substring matching.
"""

import logging
import re
from typing import List, Dict

log = logging.getLogger("KnowledgeSynthesizer")

# Stop words to exclude when extracting key terms from knowledge text.
# These are common English function words that don't carry domain meaning.
_SYNTH_STOP_WORDS: frozenset = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "this", "that", "it", "its", "and", "or",
    "but", "not", "so", "as", "if", "which", "who", "what", "how", "when",
    "where", "why", "can", "also", "very", "such", "more", "than", "all",
    "any", "most", "some", "each", "use", "used", "using", "about", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "then", "there", "here", "just", "only", "same", "both", "few", "other",
    "because", "while", "although", "however", "therefore", "thus",
    "their", "they", "them", "these", "those", "you", "we", "our", "your",
    "his", "her", "my", "me", "he", "she", "i", "us",
})


class KnowledgeSynthesizer:
    """Synthesize knowledge from multiple sources."""

    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.synthesis_cache = {}

    def synthesize_cross_domain(self, topic: str, sources: List[Dict]) -> str:
        """Combine information from multiple sources into a unified synthesis.

        Extracts key sentences and the most frequent meaningful terms from
        all source texts to produce a content-based summary instead of
        generic placeholder text.
        """
        log.info("🔀 [SYNTHESIZE] Cross-domain synthesis for '%s'", topic)

        all_key_points: List[str] = []
        for source in sources:
            text = source.get("text", "")
            if text:
                all_key_points.extend(self._extract_key_points(text, limit=3))

        if not all_key_points:
            return f"No source content available for '{topic}'."

        # Build common themes from the extracted key points
        term_freq: Dict[str, int] = {}
        for sentence in all_key_points:
            for word in re.sub(r"[^\w\s]", " ", sentence.lower()).split():
                if len(word) >= 4 and word not in _SYNTH_STOP_WORDS:
                    term_freq[word] = term_freq.get(word, 0) + 1
        common_terms = [
            w for w, _ in sorted(term_freq.items(), key=lambda x: x[1], reverse=True)
            if term_freq[w] >= 2
        ][:5]

        # Deduplicate key points (keep longest unique sentences)
        seen: set = set()
        unique_points: List[str] = []
        for pt in all_key_points:
            norm = pt.lower().strip()
            if norm and norm not in seen:
                seen.add(norm)
                unique_points.append(pt)

        synthesis_lines = [f"🔗 **Synthesized Knowledge: {topic}**", ""]

        if common_terms:
            synthesis_lines.append("Key concepts:")
            for term in common_terms:
                synthesis_lines.append(f"• {term}")
            synthesis_lines.append("")

        synthesis_lines.append("Key findings:")
        for point in unique_points[:5]:
            synthesis_lines.append(f"• {point}")

        synthesis = "\n".join(synthesis_lines)
        log.info("✅ [SYNTHESIZE] Synthesis created (%d key points)", len(unique_points))
        return synthesis

    def create_summary(self, facts: List[Dict]) -> str:
        """Create comprehensive summary from facts."""
        log.info("📋 [SYNTHESIZE] Creating summary from %d facts", len(facts))

        if not facts:
            return "[No facts to summarize]"

        summary = "📚 **Knowledge Summary:**\n\n"

        categories: Dict[str, List[str]] = {}
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "General"
            if category not in categories:
                categories[category] = []
            categories[category].append(fact.get("value", ""))

        for category, values in list(categories.items())[:5]:
            summary += f"\n**{category}:**\n"
            for value in values[:2]:
                summary += f"• {str(value)[:100]}...\n"

        log.info("✅ [SYNTHESIZE] Summary created")
        return summary

    def build_relationships(self, topics: List[str]) -> Dict[str, List[str]]:
        """Build relationship map between topics using term overlap."""
        log.info("🔗 [SYNTHESIZE] Building relationships between %d topics", len(topics))
        relationships: Dict[str, List[str]] = {}
        for topic in topics:
            relationships[topic] = self._find_relationships(topic, topics)
        log.info("✅ [SYNTHESIZE] Relationships built")
        return relationships

    def _extract_key_points(self, text: str, limit: int = 3) -> List[str]:
        """Extract the most informative sentences from *text*.

        Filters out very short sentences (< 30 chars) which are likely
        headings or navigation elements rather than informative content.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        meaningful = [s.strip() for s in sentences if len(s.strip()) >= 30]
        # Sort by length descending — longer sentences usually carry more info
        meaningful.sort(key=len, reverse=True)
        return meaningful[:limit]

    def _find_common_themes(self, sources: List[Dict]) -> List[str]:
        """Find common meaningful themes across sources using term frequency.

        Filters stop words so the returned terms are domain-relevant keywords,
        not function words like "the" or "is".  Only terms that appear across
        at least 2 source entries are considered common themes.
        """
        term_freq: Dict[str, int] = {}

        for source in sources:
            # Sources arrive as {source_N: [sentence, ...]} dicts
            for value in source.values():
                if isinstance(value, list):
                    combined = " ".join(str(v) for v in value)
                elif isinstance(value, str):
                    combined = value
                else:
                    continue
                for word in re.sub(r"[^\w\s]", " ", combined.lower()).split():
                    if len(word) >= 4 and word not in _SYNTH_STOP_WORDS:
                        term_freq[word] = term_freq.get(word, 0) + 1

        # Return only terms seen ≥ 2 times, sorted by frequency
        frequent = [w for w, c in term_freq.items() if c >= 2]
        return sorted(frequent, key=lambda w: term_freq[w], reverse=True)[:8]

    def _find_relationships(self, topic: str, all_topics: List[str]) -> List[str]:
        """Find topics related to *topic* using Jaccard token overlap.

        Considers a pair related when their token sets share ≥ 25 % of their
        combined vocabulary — more robust than pure substring matching.
        """
        topic_tokens = set(
            re.sub(r"[^\w\s]", " ", topic.lower()).split()
        ) - _SYNTH_STOP_WORDS

        related: List[str] = []
        for other in all_topics:
            if other == topic:
                continue
            other_tokens = set(
                re.sub(r"[^\w\s]", " ", other.lower()).split()
            ) - _SYNTH_STOP_WORDS
            union = topic_tokens | other_tokens
            if not union:
                continue
            jaccard = len(topic_tokens & other_tokens) / len(union)
            if jaccard >= 0.25:
                related.append(other)

        return related


if __name__ == "__main__":
    print('Running knowledge_synthesizer.py')

