#!/usr/bin/env python3
"""
Circuit Breaker - Prevent cascading failures

Implements the circuit breaker pattern for fault tolerance. Prevents
cascading failures by stopping requests to failing services.

States:
- CLOSED: Normal operation
- OPEN: Failing, reject requests
- HALF_OPEN: Testing if service recovered

Features:
- Automatic state transitions
- Configurable thresholds
- Timeout-based recovery
- Metrics tracking
"""

import time
import logging
from typing import Callable, Any, Optional
from enum import Enum
from dataclasses import dataclass

log = logging.getLogger("CircuitBreaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60
    
    def __post_init__(self):
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")


class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.

    Prevents cascading failures by monitoring service health and
    stopping requests when service becomes unavailable.
    """

    def __init__(
        self,
        name: str = "default",
        config: Optional[CircuitBreakerConfig] = None,
        failure_threshold: int = None,
        success_threshold: int = None,
        timeout_seconds: float = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Circuit breaker name
            config: Configuration (uses defaults if None)
            failure_threshold: Failures before opening (legacy support)
            success_threshold: Successes before closing (legacy support)
            timeout_seconds: Timeout seconds (legacy support)
        """
        self.name = name
        
        if config is None:
            if failure_threshold is not None or success_threshold is not None or timeout_seconds is not None:
                config = CircuitBreakerConfig(
                    failure_threshold=failure_threshold or 5,
                    success_threshold=success_threshold or 2,
                    timeout_seconds=timeout_seconds or 60,
                )
            else:
                config = CircuitBreakerConfig()
        
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.metrics = {
            "calls": 0,
            "failures": 0,
            "successes": 0,
            "rejections": 0,
        }

        log.debug(f"CircuitBreaker '{name}' initialized: {self.config}")

    async def call(
        self,
        fn: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            fn: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Exception: Original exception or CircuitBreakerOpen
        """
        self.metrics["calls"] += 1

        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                log.info(f"[{self.name}] HALF_OPEN: Testing recovery")
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
            else:
                self.metrics["rejections"] += 1
                raise Exception(
                    f"CircuitBreaker '{self.name}' is OPEN"
                )

        try:
            if hasattr(fn, '__await__'):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)

            self._on_success()
            return result

        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call."""
        self.metrics["successes"] += 1
        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                log.info(f"[{self.name}] CLOSED: Service recovered")
                self.state = CircuitState.CLOSED
                self.success_count = 0
        elif self.state == CircuitState.CLOSED:
            self.success_count = 0

    def _on_failure(self):
        """Handle failed call."""
        self.metrics["failures"] += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0

        if self.failure_count >= self.config.failure_threshold:
            log.warning(
                f"[{self.name}] OPEN: Failure threshold reached "
                f"({self.failure_count}/{self.config.failure_threshold})"
            )
            self.state = CircuitState.OPEN
        elif self.state == CircuitState.HALF_OPEN:
            log.warning(f"[{self.name}] Still failing, back to OPEN")
            self.state = CircuitState.OPEN
            self.failure_count = 1

    def _should_attempt_reset(self) -> bool:
        """Check if should attempt recovery."""
        if not self.last_failure_time:
            return False

        elapsed = time.time() - self.last_failure_time
        return elapsed >= self.config.timeout_seconds

    def get_state(self) -> str:
        """Get current state."""
        return self.state.value

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failure_count,
            "successes": self.success_count,
            **self.metrics,
        }


if __name__ == "__main__":
    import asyncio

    async def flaky_service(fail_until: int = 3):
        """Service that fails N times then succeeds."""
        if flaky_service.call_count < fail_until:
            flaky_service.call_count += 1
            raise Exception("Service error")
        return "Success"

    flaky_service.call_count = 0

    async def test():
        cb = CircuitBreaker("test_service")

        for i in range(10):
            try:
                result = await cb.call(flaky_service, fail_until=3)
                print(f"Call {i+1}: {result}")
            except Exception as e:
                print(f"Call {i+1}: {e}")

            await asyncio.sleep(0.5)

        print(f"\nStats: {cb.get_stats()}")

    asyncio.run(test())
