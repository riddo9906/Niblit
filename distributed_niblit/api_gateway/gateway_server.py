"""GatewayServer — HTTP-like request handler tying auth, rate limiting, routing.

Usage example::

    auth = AuthLayer()
    limiter = RateLimiter()
    router = RoutingLayer()
    server = GatewayServer(auth, limiter, router)
    resp = server.handle_request("/health", "GET", {"X-API-Key": key}, {})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

log = logging.getLogger("GatewayServer")


class GatewayServer:
    """Front-door request handler.

    Args:
        auth: AuthLayer instance.
        rate_limiter: RateLimiter instance.
        router: RoutingLayer instance.
    """

    def __init__(self, auth: Any, rate_limiter: Any, router: Any) -> None:
        self._auth = auth
        self._limiter = rate_limiter
        self._router = router
        self._stats: Dict[str, int] = {
            "total_requests": 0,
            "auth_failures": 0,
            "rate_limited": 0,
            "successes": 0,
        }

    # ── public API ──

    def handle_request(
        self,
        path: str,
        method: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process a request; return dict with status_code and body keys."""
        self._stats["total_requests"] += 1
        api_key = headers.get("X-API-Key", "")
        client_id = "anonymous"
        if api_key:
            if not self._auth.validate_api_key(api_key):
                self._stats["auth_failures"] += 1
                return {"status_code": 401, "body": {"error": "invalid_api_key"}}
            client_id = api_key[:8]
        if not self._limiter.allow(client_id):
            self._stats["rate_limited"] += 1
            return {"status_code": 429, "body": {"error": "rate_limit_exceeded"}}
        result = self._router.route(path, method, body)
        if "error" in result and result["error"] == "not_found":
            return {"status_code": 404, "body": result}
        self._stats["successes"] += 1
        log.debug("GatewayServer: %s %s → 200", method, path)
        return {"status_code": 200, "body": result}

    def get_stats(self) -> Dict[str, Any]:
        """Return cumulative request statistics."""
        return dict(self._stats)
