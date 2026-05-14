#!/usr/bin/env python3
"""NRR-v2 unified runtime router with deterministic single-backend execution."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.RuntimeRouterV2")


class NiblitUnifiedRuntimeRouterV2:
    """Single-entry router that wraps LocalBrain's proven routing pipeline."""

    def __init__(self, local_brain: Optional[Any] = None) -> None:
        self._local_brain = local_brain
        self._last_route: Dict[str, Any] = {}

    def _resolve_local_brain(self) -> Any:
        if self._local_brain is not None:
            return self._local_brain
        from modules.local_brain import get_local_brain

        self._local_brain = get_local_brain()
        return self._local_brain

    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate via a single deterministic backend for this request cycle."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        brain = self._resolve_local_brain()
        result = brain.route_inference(prompt=prompt, context=context)

        backend = result.get("backend", "none")
        self._last_route = {
            "backend": backend,
            "error": result.get("error"),
            "tool_calls": result.get("tool_calls", []),
        }

        if backend not in {"http", "subprocess", "python", "none"}:
            log.warning("[RuntimeRouterV2] unexpected backend '%s'", backend)

        text = result.get("text", "")
        if isinstance(text, str) and text.strip():
            return text
        return "[RuntimeRouterV2] empty response"

    def last_route(self) -> Dict[str, Any]:
        """Return the last routing decision metadata."""
        return dict(self._last_route)
