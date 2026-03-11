#!/usr/bin/env python3
"""
Multi-Level Caching - L1 (Memory), L2 (Redis), L3 (Database)

Hierarchical caching strategy for optimal performance:
- L1: In-memory cache (fastest, smallest)
- L2: Redis cache (warm data)
- L3: Database cache (persistent)

Features:
- Automatic promotion to faster levels
- TTL management
- Demotion on miss
- Metrics tracking
"""

import time
import logging
from typing import Optional, Any, Dict
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("MultiLevelCaching")


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    value: Any
    created_at: float
    ttl: int
    hits: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return (time.time() - self.created_at) > self.ttl


class CacheLevel(ABC):
    """Base class for cache level."""
    
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        pass
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int):
        """Set value in cache."""
        pass
    
    @abstractmethod
    async def delete(self, key: str):
        """Delete value from cache."""
        pass


class InMemoryCache(CacheLevel):
    """L1: In-memory cache (fastest, smallest)."""
    
    def __init__(self, max_entries: int = 1000):
        self.cache: Dict[str, CacheEntry] = {}
        self.max_entries = max_entries
        self.metrics = {"hits": 0, "misses": 0, "evictions": 0}
    
    async def get(self, key: str) -> Optional[Any]:
        """Get from memory cache."""
        if key not in self.cache:
            self.metrics["misses"] += 1
            return None
        
        entry = self.cache[key]
        
        if entry.is_expired():
            del self.cache[key]
            self.metrics["misses"] += 1
            return None
        
        entry.hits += 1
        self.metrics["hits"] += 1
        return entry.value
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set in memory cache."""
        if len(self.cache) >= self.max_entries:
            # LRU eviction
            oldest_key = min(
                self.cache.keys(),
                key=lambda k: self.cache[k].created_at
            )
            del self.cache[oldest_key]
            self.metrics["evictions"] += 1
        
        self.cache[key] = CacheEntry(value, time.time(), ttl)
    
    async def delete(self, key: str):
        """Delete from memory cache."""
        if key in self.cache:
            del self.cache[key]


class RedisCache(CacheLevel):
    """L2: Redis cache (warm data)."""
    
    def __init__(self):
        self.metrics = {"hits": 0, "misses": 0}
        log.debug("RedisCache: stub (implement with redis-py)")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get from Redis."""
        # TODO: Implement with redis-py
        self.metrics["misses"] += 1
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set in Redis."""
        # TODO: Implement with redis-py
        pass
    
    async def delete(self, key: str):
        """Delete from Redis."""
        # TODO: Implement with redis-py
        pass


class DatabaseCache(CacheLevel):
    """L3: Database cache (persistent)."""
    
    def __init__(self):
        self.metrics = {"hits": 0, "misses": 0}
        log.debug("DatabaseCache: stub (implement with sqlalchemy)")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get from database."""
        # TODO: Implement with database
        self.metrics["misses"] += 1
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set in database."""
        # TODO: Implement with database
        pass
    
    async def delete(self, key: str):
        """Delete from database."""
        # TODO: Implement with database
        pass


class CacheStrategy:
    """
    Multi-level cache with automatic promotion/demotion.
    
    Features:
    - Automatic level selection
    - Promotion on hit
    - Demotion on miss
    - Unified interface
    """
    
    def __init__(self):
        self.l1 = InMemoryCache(max_entries=1000)
        self.l2 = RedisCache()
        self.l3 = DatabaseCache()
        self.metrics = {"promotions": 0, "demotions": 0}
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache, promoting to faster level on hit.
        
        Args:
            key: Cache key
            
        Returns:
            Value or None
        """
        # Try L1
        value = await self.l1.get(key)
        if value is not None:
            return value
        
        # Try L2
        value = await self.l2.get(key)
        if value is not None:
            # Promote to L1
            await self.l1.set(key, value, ttl=300)
            self.metrics["promotions"] += 1
            return value
        
        # Try L3
        value = await self.l3.get(key)
        if value is not None:
            # Promote to L1 and L2
            await self.l1.set(key, value, ttl=300)
            await self.l2.set(key, value, ttl=3600)
            self.metrics["promotions"] += 1
            return value
        
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """
        Set value in all cache levels.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        """
        await self.l1.set(key, value, min(ttl, 300))  # L1: shorter TTL
        await self.l2.set(key, value, min(ttl, 3600))  # L2: medium TTL
        await self.l3.set(key, value, ttl)  # L3: full TTL
    
    async def delete(self, key: str):
        """Delete from all levels."""
        await self.l1.delete(key)
        await self.l2.delete(key)
        await self.l3.delete(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "l1": self.l1.metrics,
            "l2": self.l2.metrics,
            "l3": self.l3.metrics,
            "strategy": self.metrics,
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def test():
        cache = CacheStrategy()
        
        # Set value
        await cache.set("key1", "value1", ttl=3600)
        print("Set key1")
        
        # Get value
        value = await cache.get("key1")
        print(f"Got: {value}")
        
        # Get again (should hit L1)
        value = await cache.get("key1")
        print(f"Got again: {value}")
        
        print(f"Stats: {cache.get_stats()}")
    
    asyncio.run(test())
