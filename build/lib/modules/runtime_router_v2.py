#!/usr/bin/env python3
"""NRR-v2 unified runtime router with deterministic single-backend execution."""

from __future__ import annotations

import logging
import os
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

    def _default_context_policy(self) -> Dict[str, Any]:
        target_ctx = int(
            (
                os.environ.get("NIBLIT_RUNTIME_CONTEXT_TARGET")
                or os.environ.get("NIBLIT_GGUF_N_CTX")
                or "16384"
            )
        )
        default_max_new = int(
            (
                os.environ.get("NIBLIT_RUNTIME_MAX_TOKENS")
                or os.environ.get("NIBLIT_LOCAL_MAX_NEW")
                or "512"
            )
        )
        return {
            "target_context_window": target_ctx,
            "default_max_new_tokens": default_max_new,
        }

    def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        max_tokens: Optional[int] = None,
        context_policy: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate via a single deterministic backend for this request cycle."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        brain = self._resolve_local_brain()
        policy = dict(self._default_context_policy())
        if context_policy:
            policy.update(context_policy)
        result = brain.route_inference(
            prompt=prompt,
            context=context,
            max_new_tokens=max_tokens,
            context_policy=policy,
        )

        backend = result.get("backend", "none")
        self._last_route = {
            "backend": backend,
            "error": result.get("error"),
            "tool_calls": result.get("tool_calls", []),
            "context_policy": result.get("context_policy", policy),
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


if __name__ == "__main__":
    print('Running runtime_router_v2.py')
