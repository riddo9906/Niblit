"""RateLimiter — token-bucket per-client rate limiting for the API gateway.

Usage example::

    limiter = RateLimiter(default_rpm=60)
    allowed = limiter.allow("client-abc")
"""

from __future__ import annotations

import logging
import time
from typing import Dict

log = logging.getLogger("RateLimiter")

_DEFAULT_RPM = 60


class RateLimiter:
    """Token-bucket rate limiter.

    Args:
        default_rpm: Default requests-per-minute for new clients.
    """

    def __init__(self, default_rpm: int = _DEFAULT_RPM) -> None:
        self._default_rpm = default_rpm
        self._limits: Dict[str, int] = {}
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}

    # ── public API ──

    def allow(self, client_id: str) -> bool:
        """Return True if *client_id* may make a request right now."""
        rpm = self._limits.get(client_id, self._default_rpm)
        refill_rate = rpm / 60.0
        now = time.time()
        last = self._last_refill.get(client_id, now)
        elapsed = now - last
        tokens = self._tokens.get(client_id, float(rpm))
        tokens = min(float(rpm), tokens + elapsed * refill_rate)
        self._last_refill[client_id] = now
        if tokens >= 1.0:
            self._tokens[client_id] = tokens - 1.0
            return True
        self._tokens[client_id] = tokens
        log.warning("RateLimiter: client %s rate-limited", client_id)
        return False

    def set_limit(self, client_id: str, requests_per_minute: int) -> None:
        """Override rate limit for *client_id*."""
        self._limits[client_id] = requests_per_minute
        log.info("RateLimiter: %s limit set to %d rpm", client_id, requests_per_minute)

    def get_stats(self, client_id: str) -> Dict[str, object]:
        """Return current token and limit info for *client_id*."""
        return {
            "client_id": client_id,
            "rpm_limit": self._limits.get(client_id, self._default_rpm),
            "tokens_available": round(self._tokens.get(client_id, float(self._default_rpm)), 3),
        }


if __name__ == "__main__":
    print('Running rate_limiter.py')
