#!/usr/bin/env python3
"""
Rate Limiting & Backpressure - Prevent system overload

Implements token bucket algorithm for request rate limiting with proper
backpressure handling. Prevents cascading failures and resource exhaustion.

Features:
- Token bucket algorithm
- Configurable refill rate
- Async-ready
- Per-endpoint limits
- Backpressure signaling
"""

import asyncio
import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field

log = logging.getLogger("RateLimiting")


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    capacity: float
    refill_rate: float
    tokens: float = field(default=0)
    last_refill: float = field(default_factory=time.time)
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_rate
        )
        self.last_refill = now
    
    async def acquire(self, tokens: float = 1.0, timeout: float = 60.0):
        """
        Acquire tokens, waiting if necessary.
        
        Args:
            tokens: Number of tokens to acquire
            timeout: Maximum wait time in seconds
            
        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        start_time = time.time()
        
        while True:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return
            
            # Calculate wait time
            wait_time = (tokens - self.tokens) / self.refill_rate
            remaining_timeout = timeout - (time.time() - start_time)
            
            if remaining_timeout <= 0:
                raise asyncio.TimeoutError(
                    f"Rate limit timeout: waited {timeout}s"
                )
            
            # Sleep for min of wait_time and remaining_timeout
            await asyncio.sleep(min(wait_time, remaining_timeout, 0.1))


class RateLimiter:
    """
    Rate limiter with backpressure support.
    
    Features:
    - Global and per-endpoint rate limits
    - Async-ready
    - Configurable timeouts
    - Metrics tracking
    """
    
    def __init__(self, max_requests_per_sec: int = 100):
        """
        Initialize rate limiter.
        
        Args:
            max_requests_per_sec: Global request limit
        """
        self.global_bucket = TokenBucket(
            capacity=max_requests_per_sec,
            refill_rate=max_requests_per_sec
        )
        self.endpoint_buckets: Dict[str, TokenBucket] = {}
        self.metrics = {
            "acquired": 0,
            "rejected": 0,
            "timeouts": 0,
        }
        log.debug(f"RateLimiter initialized: {max_requests_per_sec} req/sec")
    
    async def acquire(
        self,
        endpoint: Optional[str] = None,
        tokens: float = 1.0,
        timeout: float = 60.0
    ) -> bool:
        """
        Acquire rate limit tokens.
        
        Args:
            endpoint: Specific endpoint (for per-endpoint limits)
            tokens: Number of tokens to acquire
            timeout: Maximum wait time
            
        Returns:
            True if acquired, False if rejected
        """
        try:
            # Always use global bucket
            await self.global_bucket.acquire(tokens, timeout)
            
            # Per-endpoint bucket if specified
            if endpoint:
                if endpoint not in self.endpoint_buckets:
                    self.endpoint_buckets[endpoint] = TokenBucket(
                        capacity=100,
                        refill_rate=10
                    )
                await self.endpoint_buckets[endpoint].acquire(tokens, timeout)
            
            self.metrics["acquired"] += 1
            return True
            
        except asyncio.TimeoutError:
            self.metrics["timeouts"] += 1
            log.warning(f"Rate limit timeout for {endpoint}")
            return False
        except Exception as e:
            log.error(f"Rate limit error: {e}")
            self.metrics["rejected"] += 1
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Get rate limiter statistics."""
        return {
            **self.metrics,
            "total_requests": self.metrics["acquired"] + self.metrics["rejected"],
        }


# Example usage
if __name__ == "__main__":
    async def test():
        limiter = RateLimiter(max_requests_per_sec=10)
        
        # Acquire tokens
        for i in range(15):
            success = await limiter.acquire(tokens=1.0, timeout=5.0)
            print(f"Request {i+1}: {'Acquired' if success else 'Rejected'}")
        
        print(f"Stats: {limiter.get_stats()}")
    
    asyncio.run(test())
