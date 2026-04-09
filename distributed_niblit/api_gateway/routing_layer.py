"""RoutingLayer — path-based request routing for the API gateway.

Usage example::

    router = RoutingLayer()
    router.add_route("/health", lambda p, m, b: {"ok": True})
    result = router.route("/health", "GET", {})
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("RoutingLayer")


class RoutingLayer:
    """Maps URL paths to handler callables."""

    def __init__(self) -> None:
        self._routes: Dict[str, Callable] = {}

    # ── public API ──

    def add_route(self, path: str, handler: Callable) -> None:
        """Register *handler* for *path*."""
        self._routes[path] = handler
        log.debug("RoutingLayer: registered route %s", path)

    def route(self, path: str, method: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch request to matching handler; return 404 dict if none."""
        handler = self._routes.get(path)
        if handler is None:
            log.warning("RoutingLayer: no handler for %s %s", method, path)
            return {"error": "not_found", "path": path}
        try:
            result = handler(path, method, body)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:
            log.warning("RoutingLayer: handler error for %s — %s", path, exc)
            return {"error": str(exc)}

    def list_routes(self) -> List[str]:
        """Return registered paths."""
        return list(self._routes.keys())


if __name__ == "__main__":
    print('Running routing_layer.py')
