#!/usr/bin/env python3
"""
modules/llm_provider_manager.py — Runtime LLM provider selector for Niblit.

Priority:
    1. HuggingFace Router (HFBrain / HFAdapter)  ← PRIMARY
    2. Anthropic Claude (ClaudeEngine)            ← FALLBACK

The active provider can be switched at runtime via the ``llm-provider``
CLI command or by setting ``NIBLIT_LLM_PROVIDER=hf|anthropic`` in the
environment before startup.

Usage::

    mgr = get_llm_provider_manager()
    response = mgr.ask("What is photosynthesis?")

    mgr.switch("anthropic")   # swap at runtime
    mgr.switch("hf")          # swap back

    info = mgr.status()       # {"active": "hf", "hf": True, "anthropic": False, ...}
"""

import logging
import os
import threading
from typing import Any, Dict, Optional

log = logging.getLogger("LLMProviderManager")

# ── module-level singleton ────────────────────────────────────────────────────
_manager: Optional["LLMProviderManager"] = None
_manager_lock = threading.Lock()

VALID_PROVIDERS = ("hf", "anthropic")


def get_llm_provider_manager() -> "LLMProviderManager":
    """Return the process-level :class:`LLMProviderManager` singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LLMProviderManager()
    return _manager


class LLMProviderManager:
    """Routes LLM calls to the active provider with automatic fallback.

    Providers
    ---------
    ``"hf"``         HuggingFace Router via :class:`~modules.hf_brain.HFBrain`
                     (requires ``HF_TOKEN`` / ``HF_API_KEY``).
    ``"anthropic"``  Anthropic Messages API via
                     :class:`~niblit_models.claude_engine.ClaudeEngine`
                     (requires ``ANTHROPIC_API_KEY``).

    The active provider is stored as a plain string attribute so it can be
    read or overwritten by any module that holds a reference.
    """

    def __init__(self) -> None:
        raw = os.getenv("NIBLIT_LLM_PROVIDER", "hf").lower().strip()
        self.active: str = raw if raw in VALID_PROVIDERS else "hf"
        self._lock = threading.Lock()

        # Lazily resolved provider instances — set by wire() or on first ask()
        self._hf_brain: Optional[Any] = None
        self._claude: Optional[Any] = None

    # ── wiring (called by niblit_core / niblit_brain after init) ─────────────

    def wire(
        self,
        hf_brain: Optional[Any] = None,
        claude: Optional[Any] = None,
    ) -> None:
        """Attach live provider instances.  Safe to call multiple times."""
        with self._lock:
            if hf_brain is not None:
                self._hf_brain = hf_brain
            if claude is not None:
                self._claude = claude

    # ── runtime switch ────────────────────────────────────────────────────────

    def switch(self, provider: str) -> str:
        """Change the active provider.  Returns a human-readable confirmation."""
        provider = provider.lower().strip()
        if provider not in VALID_PROVIDERS:
            return f"❌ Unknown provider '{provider}'. Choose: {', '.join(VALID_PROVIDERS)}"
        with self._lock:
            self.active = provider
        log.info("[LLMProviderManager] Active provider → %s", provider)
        return f"✅ LLM provider switched to **{provider}**."

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a status dict with provider availability."""
        hf_ok = self._hf_available()
        ant_ok = self._anthropic_available()
        return {
            "active": self.active,
            "hf": hf_ok,
            "anthropic": ant_ok,
            "hf_model": getattr(self._hf_brain, "model", "n/a") if hf_ok else "n/a",
            "anthropic_model": (
                getattr(self._claude, "_model", "n/a")
                if self._claude is not None else "n/a"
            ),
        }

    # ── main ask() entry point ────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 500,
    ) -> Optional[str]:
        """Generate a response using the active provider, falling back to the other.

        Returns ``None`` when both providers are unavailable.
        """
        primary, fallback = (
            (self._ask_hf, self._ask_anthropic)
            if self.active == "hf"
            else (self._ask_anthropic, self._ask_hf)
        )

        try:
            result = primary(prompt, system=system, max_tokens=max_tokens)
            if result:
                return result
        except Exception as exc:
            log.debug("[LLMProviderManager] Primary (%s) error: %s", self.active, exc)

        # Fallback
        fallback_name = "anthropic" if self.active == "hf" else "hf"
        log.debug("[LLMProviderManager] Falling back to %s", fallback_name)
        try:
            return fallback(prompt, system=system, max_tokens=max_tokens)
        except Exception as exc:
            log.debug("[LLMProviderManager] Fallback (%s) error: %s", fallback_name, exc)
            return None

    # ── private helpers ───────────────────────────────────────────────────────

    def _hf_available(self) -> bool:
        hf = self._hf_brain
        if hf is None:
            self._hf_brain = self._lazy_hf()
            hf = self._hf_brain
        return hf is not None and getattr(hf, "enabled", False) and bool(getattr(hf, "token", None))

    def _anthropic_available(self) -> bool:
        cl = self._claude
        if cl is None:
            self._claude = self._lazy_claude()
            cl = self._claude
        return cl is not None and getattr(cl, "is_available", lambda: False)()

    def _ask_hf(self, prompt: str, system: str = "", max_tokens: int = 500) -> Optional[str]:
        hf = self._hf_brain
        if hf is None:
            hf = self._lazy_hf()
            self._hf_brain = hf
        if hf is None or not getattr(hf, "enabled", False):
            return None
        # HFBrain.ask_single() takes a plain prompt string
        result = hf.ask_single(prompt)
        return result if result and result.strip() else None

    def _ask_anthropic(self, prompt: str, system: str = "", max_tokens: int = 500) -> Optional[str]:
        cl = self._claude
        if cl is None:
            cl = self._lazy_claude()
            self._claude = cl
        if cl is None or not cl.is_available():
            return None
        # ClaudeEngine.generate() accepts query + optional system override
        result = cl.generate(prompt, system=system or "", max_tokens=max_tokens)
        return result if result and result.strip() else None

    def _lazy_hf(self) -> Optional[Any]:
        """Try to import and instantiate HFBrain without requiring a DB."""
        try:
            from modules.hf_brain import HFBrain  # type: ignore[import]
            return HFBrain(db=None)
        except Exception as exc:
            log.debug("[LLMProviderManager] HFBrain lazy-init failed: %s", exc)
            return None

    def _lazy_claude(self) -> Optional[Any]:
        """Try to import and instantiate ClaudeEngine."""
        try:
            from niblit_models.claude_engine import ClaudeEngine  # type: ignore[import]
            return ClaudeEngine()
        except Exception as exc:
            log.debug("[LLMProviderManager] ClaudeEngine lazy-init failed: %s", exc)
            return None
