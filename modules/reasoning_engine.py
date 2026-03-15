#!/usr/bin/env python3
"""
REASONING ENGINE MODULE
Connects disparate knowledge to create logical chains
"""

import logging
from typing import List, Dict, Set, Tuple, Optional
import json

log = logging.getLogger("ReasoningEngine")


class ReasoningEngine:
    """Build knowledge graphs and reasoning chains"""
    
    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.graph = {}  # {concept: [related_concepts]}
        self.reasoning_chains = []
    
    def build_knowledge_graph(self, facts: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """
        Build knowledge graph from facts
        Identifies connections between concepts
        """
        log.info(f"🧠 [REASONING] Building knowledge graph from {len(facts)} facts")
        
        graph = {}
        concepts = set()
        
        # Extract concepts from facts
        for fact in facts:
            key = str(fact.get("key", ""))
            value = str(fact.get("value", ""))
            
            # Extract key concepts
            key_concepts = self._extract_concepts(key)
            value_concepts = self._extract_concepts(value)
            
            concepts.update(key_concepts)
            concepts.update(value_concepts)
        
        # Build connections
        for concept in concepts:
            related = self._find_related(concept, facts)
            if related:
                graph[concept] = list(related)
        
        self.graph = graph
        log.info(f"✅ [REASONING] Built graph with {len(graph)} concepts")
        return graph
    
    def create_reasoning_chain(self, start_concept: str, depth: int = 3) -> List[str]:
        """
        Create logical chain from starting concept
        Follows connections through knowledge graph
        """
        log.info(f"🔗 [REASONING] Creating chain from '{start_concept}'")
        
        chain = [start_concept]
        current = start_concept
        
        for _ in range(depth):
            if current in self.graph:
                related = self.graph[current]
                if related:
                    next_concept = related[0]  # Take first related
                    if next_concept not in chain:
                        chain.append(next_concept)
                        current = next_concept
        
        log.info(f"✅ [REASONING] Chain: {' → '.join(chain)}")
        return chain
    
    def infer_new_knowledge(self) -> List[str]:
        """
        Infer new knowledge from existing connections
        Find patterns and derive conclusions
        """
        log.info(f"🔮 [REASONING] Inferring new knowledge")
        inferences = []
        
        # Find common patterns
        for concept, related in self.graph.items():
            if len(related) >= 2:
                inference = f"{concept} connects to: {', '.join(related[:3])}"
                inferences.append(inference)
        
        log.info(f"✅ [REASONING] Generated {len(inferences)} inferences")
        return inferences
    
    def _extract_concepts(self, text) -> Set[str]:
        """Extract key concepts from text"""
        words = str(text).lower().split()
        # Filter meaningful words
        stopwords = {'the', 'a', 'an', 'is', 'are', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        return {w.strip('.,!?;:') for w in words if w not in stopwords and len(w) > 3}
    
    def _find_related(self, concept: str, facts: List[Dict]) -> Set[str]:
        """Find concepts related to given concept"""
        related = set()
        concept_lower = concept.lower()
        
        for fact in facts:
            value = str(fact.get("value", "")).lower()
            if concept_lower in value:
                # Extract other concepts from same fact
                key_concepts = self._extract_concepts(str(fact.get("key", "")))
                related.update(key_concepts)
        
        return related
