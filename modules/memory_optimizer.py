#!/usr/bin/env python3
"""
MEMORY OPTIMIZER MODULE
Compress, organize, and optimize memory storage
"""

import logging
from typing import List, Dict, Any, Tuple
import hashlib

log = logging.getLogger("MemoryOptimizer")


class MemoryOptimizer:
    """Optimize memory storage and retrieval"""
    
    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.compression_stats = {}
    
    def compress_memories(self, facts: List[Dict]) -> Tuple[List[Dict], Dict]:
        """
        Compress memory entries
        Remove redundancy while keeping information
        """
        log.info(f"🗜️ [OPTIMIZE] Compressing {len(facts)} memory entries")
        
        compressed = []
        seen_hashes = set()
        duplicates = 0
        
        for fact in facts:
            # Create hash of fact content
            fact_str = f"{fact.get('key')}{fact.get('value')}"
            fact_hash = hashlib.md5(fact_str.encode()).hexdigest()
            
            if fact_hash not in seen_hashes:
                # Compress value by extracting key sentences
                value = fact.get("value", "")
                compressed_value = self._compress_text(value)
                
                compressed.append({
                    "key": fact.get("key"),
                    "value": compressed_value,
                    "tags": fact.get("tags", [])
                })
                seen_hashes.add(fact_hash)
            else:
                duplicates += 1
        
        stats = {
            "original_count": len(facts),
            "compressed_count": len(compressed),
            "duplicates_removed": duplicates,
            "compression_ratio": f"{(1 - len(compressed)/len(facts))*100:.1f}%"
        }
        
        self.compression_stats = stats
        log.info(f"✅ [OPTIMIZE] Compressed: {stats}")
        return compressed, stats
    
    def organize_hierarchically(self, facts: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Organize facts hierarchically by category
        """
        log.info(f"📊 [OPTIMIZE] Organizing {len(facts)} facts hierarchically")
        
        hierarchy = {}
        
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "uncategorized"
            
            if category not in hierarchy:
                hierarchy[category] = []
            hierarchy[category].append(fact)
        
        log.info(f"✅ [OPTIMIZE] Organized into {len(hierarchy)} categories")
        return hierarchy
    
    def optimize_retrieval(self, facts: List[Dict]) -> Dict[str, List[str]]:
        """
        Create index for faster retrieval
        """
        log.info(f"⚡ [OPTIMIZE] Creating retrieval index")
        
        index = {}
        
        for fact in facts:
            # Index by key
            key = fact.get("key", "")
            if key not in index:
                index[key] = []
            index[key].append(fact.get("value", ""))
            
            # Index by tags
            for tag in fact.get("tags", []):
                if tag not in index:
                    index[tag] = []
                index[tag].append(fact.get("value", ""))
        
        log.info(f"✅ [OPTIMIZE] Index created with {len(index)} entries")
        return index
    
    def _compress_text(self, text, sentences: int = 2) -> str:
        """Compress text by keeping key sentences"""
        if not isinstance(text, str):
            text = str(text)
        if len(text) < 100:
            return text
        
        sents = text.split(".")
        return ". ".join(sents[:sentences]) + "."
