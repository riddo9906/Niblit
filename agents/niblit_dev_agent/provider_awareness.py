#!/usr/bin/env python3
"""Provider awareness for NiblitDevAgent via LocalBrain/RouterV2/provider manager."""

from __future__ import annotations

from typing import Any


class ProviderAwareness:
    """Read-only provider inspection through existing provider abstractions."""

    def __init__(
        self,
        local_brain: Any | None = None,
        router_v2: Any | None = None,
        llm_provider_manager: Any | None = None,
    ) -> None:
        self._local_brain = local_brain
        self._router_v2 = router_v2
        self._provider_manager = llm_provider_manager

    def _resolve_local_brain(self) -> Any | None:
        if self._local_brain is not None:
            return self._local_brain
        try:
            from modules.local_brain import get_local_brain

            self._local_brain = get_local_brain()
        except Exception:
            self._local_brain = None
        return self._local_brain

    def _resolve_provider_manager(self) -> Any | None:
        if self._provider_manager is not None:
            return self._provider_manager
        try:
            from modules.llm_provider_manager import get_llm_provider_manager

            self._provider_manager = get_llm_provider_manager()
        except Exception:
            self._provider_manager = None
        return self._provider_manager

    def _resolve_router(self, local_brain: Any | None) -> Any | None:
        if self._router_v2 is not None:
            return self._router_v2
        try:
            from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2

            self._router_v2 = NiblitUnifiedRuntimeRouterV2(local_brain=local_brain)
        except Exception:
            self._router_v2 = None
        return self._router_v2

    def get_provider_snapshot(self) -> dict[str, Any]:
        provider_manager = self._resolve_provider_manager()
        local_brain = self._resolve_local_brain()
        router = self._resolve_router(local_brain)

        status = {}
        if provider_manager is not None and hasattr(provider_manager, "status"):
            try:
                status = dict(provider_manager.status())
            except Exception:
                status = {}

        active_provider = str(status.get("active", "unknown"))

        provider_health = {
            key: bool(status.get(key))
            for key in ("hf", "anthropic", "qwen", "ruflo")
            if key in status
        }

        fallback_available = any(
            ok for provider, ok in provider_health.items() if provider != active_provider
        )

        local_status = {}
        if local_brain is not None and hasattr(local_brain, "status"):
            try:
                local_status = dict(local_brain.status())
            except Exception:
                local_status = {}

        last_route = {}
        if router is not None and hasattr(router, "last_route"):
            try:
                last_route = dict(router.last_route())
            except Exception:
                last_route = {}

        return {
            "active_provider": active_provider,
            "provider_status": status,
            "provider_health": provider_health,
            "fallback_available": bool(fallback_available),
            "router_last_route": last_route,
            "backend_metadata": {
                "local_backend": local_status.get("backend_in_use", "unknown"),
                "local_model": local_status.get("model_name", "unknown"),
                "llama_server_url": local_status.get("llama_server_url", ""),
            },
        }
