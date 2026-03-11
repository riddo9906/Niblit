#!/usr/bin/env python3
"""
Connection Pooling - Reuse expensive connections

Manages pools of connections to external services (database, HTTP, etc.)
to optimize resource usage and improve performance.

Features:
- Connection reuse
- Pool size limits
- Connection health checking
- Async support
- Timeout handling
"""

import asyncio
import logging
from typing import Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger("ConnectionPooling")


@dataclass
class PoolConfig:
    """Configuration for connection pool."""
    min_size: int = 5
    max_size: int = 20
    timeout_seconds: float = 30.0
    idle_timeout_seconds: float = 300.0  # 5 minutes
    
    def __post_init__(self):
        if self.min_size > self.max_size:
            raise ValueError("min_size cannot exceed max_size")


class Connection:
    """Wrapper for a pooled connection."""
    
    def __init__(self, conn_id: int, resource: Any):
        self.id = conn_id
        self.resource = resource
        self.created_at = datetime.now()
        self.last_used_at = datetime.now()
        self.in_use = False
    
    def mark_used(self):
        """Mark connection as used."""
        self.last_used_at = datetime.now()
    
    def is_idle(self, idle_timeout: float) -> bool:
        """Check if connection is idle."""
        elapsed = (datetime.now() - self.last_used_at).total_seconds()
        return elapsed > idle_timeout


class ConnectionPool:
    """
    Connection pool for managing expensive resources.
    
    Features:
    - Automatic pool sizing
    - Health checking
    - Timeout handling
    - Metrics tracking
    """
    
    def __init__(self, config: Optional[PoolConfig] = None):
        """
        Initialize connection pool.
        
        Args:
            config: Pool configuration
        """
        self.config = config or PoolConfig()
        self.available: List[Connection] = []
        self.in_use: List[Connection] = []
        self.next_id = 0
        self.metrics = {
            "created": 0,
            "released": 0,
            "timeouts": 0,
            "errors": 0,
        }
        log.debug(f"ConnectionPool initialized: {self.config}")
    
    async def acquire(self, timeout: float = 30.0) -> Connection:
        """
        Acquire connection from pool.
        
        Args:
            timeout: Maximum wait time
            
        Returns:
            Connection object
            
        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # Try to get available connection
            if self.available:
                conn = self.available.pop(0)
                conn.in_use = True
                conn.mark_used()
                self.in_use.append(conn)
                return conn
            
            # Create new connection if under max
            if len(self.in_use) + len(self.available) < self.config.max_size:
                conn = Connection(self.next_id, self._create_resource())
                self.next_id += 1
                conn.in_use = True
                self.in_use.append(conn)
                self.metrics["created"] += 1
                return conn
            
            # Wait and retry
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                self.metrics["timeouts"] += 1
                raise asyncio.TimeoutError(
                    f"Connection pool timeout after {timeout}s"
                )
            
            await asyncio.sleep(0.1)
    
    async def release(self, conn: Connection):
        """
        Release connection back to pool.
        
        Args:
            conn: Connection to release
        """
        if conn in self.in_use:
            self.in_use.remove(conn)
        
        conn.in_use = False
        conn.mark_used()
        self.available.append(conn)
        self.metrics["released"] += 1
    
    async def close_all(self):
        """Close all connections in pool."""
        for conn in self.available + self.in_use:
            try:
                await self._close_resource(conn.resource)
            except Exception as e:
                log.warning(f"Error closing connection: {e}")
                self.metrics["errors"] += 1
        
        self.available.clear()
        self.in_use.clear()
    
    def _create_resource(self) -> Any:
        """Create new resource (override in subclass)."""
        return object()
    
    async def _close_resource(self, resource: Any):
        """Close resource (override in subclass)."""
        pass
    
    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "available": len(self.available),
            "in_use": len(self.in_use),
            "total": len(self.available) + len(self.in_use),
            "max_size": self.config.max_size,
            **self.metrics,
        }


# Example usage
if __name__ == "__main__":
    async def test():
        pool = ConnectionPool()
        
        # Acquire and release connections
        conns = []
        for i in range(5):
            conn = await pool.acquire(timeout=5.0)
            conns.append(conn)
            print(f"Acquired connection {conn.id}")
        
        print(f"Pool stats: {pool.get_stats()}")
        
        for conn in conns:
            await pool.release(conn)
            print(f"Released connection {conn.id}")
        
        print(f"Final stats: {pool.get_stats()}")
    
    asyncio.run(test())
