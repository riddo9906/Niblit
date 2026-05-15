#!/usr/bin/env python3
"""Minimal safe LocalBrain wrapper for routing through NRR-v2."""

from __future__ import annotations

from typing import Any, Optional

from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2


class LocalBrainRouterV2Wrapper:
    """Wrapper exposing generate() while keeping LocalBrain internals intact."""

    def __init__(self, local_brain: Any) -> None:
        self._local_brain = local_brain
        self._router = NiblitUnifiedRuntimeRouterV2(local_brain=local_brain)

    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        return self._router.generate(prompt, context=context)

    @property
    def local_brain(self) -> Any:
        return self._local_brain


def apply_local_brain_router_v2_patch(local_brain: Optional[Any] = None) -> Any:
    """Patch LocalBrain.generate() to route through NRR-v2 without rewriting LocalBrain."""
    if local_brain is None:
        from modules.local_brain import get_local_brain

        local_brain = get_local_brain()

    if getattr(local_brain, "_nrr_v2_patched", False):
        return local_brain

    router = NiblitUnifiedRuntimeRouterV2(local_brain=local_brain)
    original_generate = local_brain.generate

    def _patched_generate(prompt: str, max_new_tokens: Optional[int] = None, system_prompt: Optional[str] = None) -> str:
        _ = max_new_tokens
        return router.generate(prompt, context=system_prompt)

    local_brain._nrr_v2_original_generate = original_generate
    local_brain.generate = _patched_generate
    local_brain._nrr_v2_patched = True
    return local_brain


def restore_local_brain_generate(local_brain: Optional[Any] = None) -> Any:
    """Restore LocalBrain.generate() after apply_local_brain_router_v2_patch()."""
    if local_brain is None:
        from modules.local_brain import get_local_brain

        local_brain = get_local_brain()

    original = getattr(local_brain, "_nrr_v2_original_generate", None)
    if original is not None:
        local_brain.generate = original
        local_brain._nrr_v2_patched = False
    return local_brain


if __name__ == "__main__":
    print('Running local_brain_patch.py')
