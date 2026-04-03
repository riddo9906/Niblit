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

import os
import tempfile
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
    """L2: Redis cache (warm data). Falls back to no-op if redis-py is not installed."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.metrics = {"hits": 0, "misses": 0}
        self._client = None
        try:
            import redis as _redis
            self._client = _redis.Redis(host=host, port=port, db=db,
                                        socket_connect_timeout=1, socket_timeout=1)
            self._client.ping()
            log.info("RedisCache: connected to Redis at %s:%d", host, port)
        except Exception as e:
            log.debug("RedisCache: Redis not available (%s) — L2 cache disabled", e)
            self._client = None

    async def get(self, key: str) -> Optional[Any]:
        if self._client is None:
            self.metrics["misses"] += 1
            return None
        try:
            import json as _json
            raw = self._client.get(key)
            if raw is None:
                self.metrics["misses"] += 1
                return None
            self.metrics["hits"] += 1
            return _json.loads(raw)
        except Exception:
            self.metrics["misses"] += 1
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        if self._client is None:
            return
        try:
            import json as _json
            self._client.setex(key, ttl, _json.dumps(value, default=str))
        except Exception as e:
            log.debug("RedisCache.set error: %s", e)

    async def delete(self, key: str):
        if self._client is None:
            return
        try:
            self._client.delete(key)
        except Exception:
            pass


class DatabaseCache(CacheLevel):
    """L3: Database cache using SQLite (stdlib, no extra deps)."""

    _DB_PATH = os.environ.get("NIBLIT_CACHE_DB_PATH") or os.path.join(
        os.getcwd() if os.access(os.getcwd(), os.W_OK) else tempfile.gettempdir(),
        "niblit_cache.db",
    )

    def __init__(self, db_path: Optional[str] = None):
        self.metrics = {"hits": 0, "misses": 0}
        self._db_path = db_path or self._DB_PATH
        self._init_db()

    def _init_db(self):
        try:
            import sqlite3 as _sq
            con = _sq.connect(self._db_path, check_same_thread=False)
            con.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(key TEXT PRIMARY KEY, value TEXT, expires_at REAL)"
            )
            con.commit()
            con.close()
        except Exception as e:
            log.debug("DatabaseCache._init_db error: %s", e)

    def _con(self):
        import sqlite3 as _sq
        return _sq.connect(self._db_path, check_same_thread=False)

    async def get(self, key: str) -> Optional[Any]:
        try:
            import json as _json
            con = self._con()
            row = con.execute(
                "SELECT value, expires_at FROM cache WHERE key=?", (key,)
            ).fetchone()
            con.close()
            if row is None:
                self.metrics["misses"] += 1
                return None
            value_raw, expires_at = row
            if expires_at < time.time():
                self.metrics["misses"] += 1
                return None
            self.metrics["hits"] += 1
            return _json.loads(value_raw)
        except Exception:
            self.metrics["misses"] += 1
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        try:
            import json as _json
            con = self._con()
            expires_at = time.time() + ttl
            con.execute(
                "INSERT OR REPLACE INTO cache(key,value,expires_at) VALUES(?,?,?)",
                (key, _json.dumps(value, default=str), expires_at),
            )
            con.commit()
            con.close()
        except Exception as e:
            log.debug("DatabaseCache.set error: %s", e)

    async def delete(self, key: str):
        try:
            con = self._con()
            con.execute("DELETE FROM cache WHERE key=?", (key,))
            con.commit()
            con.close()
        except Exception:
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
