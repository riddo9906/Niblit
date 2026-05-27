#!/usr/bin/env python3
"""
modules/llm_provider_manager.py — Runtime LLM provider selector for Niblit.

Priority:
    1. Llama3 Local Brain (QwenLocalBrain preset) ← PRIMARY (default)
    2. HuggingFace Router (HFBrain / HFAdapter)  ← FALLBACK
    3. Anthropic Claude (ClaudeEngine)           ← FALLBACK
    4. Ruflo HTTP Bridge (RufloAdapter)          ← OPTIONAL FALLBACK

The active provider can be switched at runtime via the ``llm-provider``
CLI command or by setting ``NIBLIT_LLM_PROVIDER=hf|anthropic|qwen|llama3|ruflo`` in
the environment before startup.

Usage::

    mgr = get_llm_provider_manager()
    response = mgr.ask("What is photosynthesis?")

    mgr.switch("anthropic")   # swap at runtime
    mgr.switch("hf")          # swap back
    mgr.switch("qwen")        # use local Qwen brain

    info = mgr.status()       # {"active": "hf", "hf": True, "anthropic": False, ...}
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("LLMProviderManager")

# ── module-level singleton ────────────────────────────────────────────────────
_manager: LLMProviderManager | None = None
_manager_lock = threading.Lock()

VALID_PROVIDERS = ("hf", "anthropic", "qwen", "llama3", "ruflo")
DEFAULT_PROVIDER = "llama3"
_DEFAULT_MAX_TOKENS = int(
    os.getenv("NIBLIT_PROVIDER_MAX_TOKENS", os.getenv("NIBLIT_LOCAL_MAX_NEW", "512"))
)


def get_llm_provider_manager() -> LLMProviderManager:
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
    ``"qwen"``       Local local-brain compatibility alias.
    ``"llama3"``     Local Llama3 preset via
                      :class:`~modules.local_brain.QwenLocalBrain`
                      (local model, no cloud API key required).
    ``"ruflo"``      Ruflo HTTP bridge via :class:`~modules.ruflo_adapter.RufloAdapter`
                     (requires ``RUFLO_API_URL`` and optional auth/model vars).

    The active provider is stored as a plain string attribute so it can be
    read or overwritten by any module that holds a reference.
    """

    def __init__(self) -> None:
        raw = os.getenv("NIBLIT_LLM_PROVIDER", DEFAULT_PROVIDER).lower().strip()
        self.active: str = raw if raw in VALID_PROVIDERS else DEFAULT_PROVIDER
        self._lock = threading.Lock()

        # Lazily resolved provider instances — set by wire() or on first ask()
        self._hf_brain: Any | None = None
        self._claude: Any | None = None
        self._local_brain: Any | None = None
        self._ruflo: Any | None = None
        self._provider_metrics: dict[str, dict[str, float]] = {
            p: {"calls": 0.0, "quality": 0.0, "latency_ms": 0.0} for p in VALID_PROVIDERS
        }
        self._provider_capabilities: dict[str, dict[str, float]] = {
            "qwen": {"long_context": 0.78, "cognition": 0.70, "latency": 0.90},
            "llama3": {"long_context": 0.96, "cognition": 0.95, "latency": 0.82},
            "hf": {"long_context": 0.80, "cognition": 0.75, "latency": 0.70},
            "anthropic": {"long_context": 0.92, "cognition": 0.95, "latency": 0.60},
            "ruflo": {"long_context": 0.78, "cognition": 0.72, "latency": 0.88},
        }

    # ── wiring (called by niblit_core / niblit_brain after init) ─────────────

    def wire(
        self,
        hf_brain: Any | None = None,
        claude: Any | None = None,
        local_brain: Any | None = None,
    ) -> None:
        """Attach live provider instances.  Safe to call multiple times."""
        with self._lock:
            if hf_brain is not None:
                self._hf_brain = hf_brain
            if claude is not None:
                self._claude = claude
            if local_brain is not None:
                self._local_brain = local_brain

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

    def status(self) -> dict[str, Any]:
        """Return a status dict with provider availability."""
        hf_ok = self._hf_available()
        ant_ok = self._anthropic_available()
        qwen_ok = self._qwen_available()
        ruflo_ok = self._ruflo_available()
        return {
            "active": self.active,
            "hf": hf_ok,
            "anthropic": ant_ok,
            "qwen": qwen_ok,
            "llama3": qwen_ok,
            "ruflo": ruflo_ok,
            "hf_model": getattr(self._hf_brain, "model", "n/a") if hf_ok else "n/a",
            "anthropic_model": (
                getattr(self._claude, "_model", "n/a")
                if self._claude is not None
                else "n/a"
            ),
            "qwen_model": (
                getattr(self._local_brain, "model_name", "n/a")
                if self._local_brain is not None
                else "n/a"
            ),
            "llama3_model": (
                getattr(self._local_brain, "model_name", "n/a")
                if self._local_brain is not None
                else "n/a"
            ),
            "ruflo_model": (
                getattr(self._ruflo, "model", "n/a")
                if self._ruflo is not None and ruflo_ok
                else "n/a"
            ),
            "provider_rankings": self.provider_rankings(prefer_long_context=True),
            "provider_metrics": {k: dict(v) for k, v in self._provider_metrics.items()},
        }

    # ── main ask() entry point ────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        """Generate a response using the active provider, falling back to the other.

        Returns ``None`` when both providers are unavailable.
        """
        providers = {
            "hf": self._ask_hf,
            "anthropic": self._ask_anthropic,
            "qwen": self._ask_qwen,
            "llama3": self._ask_llama3,
            "ruflo": self._ask_ruflo,
        }
        order = self._ranked_provider_order(prompt=prompt, prefer_long_context=max_tokens >= 1024)

        for idx, provider_name in enumerate(order):
            fn = providers[provider_name]
            try:
                ts = time.time()
                result = fn(prompt, system=system, max_tokens=max_tokens)
                latency_ms = max(0.0, (time.time() - ts) * 1000.0)
                self.record_provider_feedback(
                    provider_name,
                    quality_score=1.0 if result else 0.0,
                    latency_ms=latency_ms,
                )
                if result:
                    return result
            except Exception as exc:
                role = "Primary" if idx == 0 else "Fallback"
                log.debug("[LLMProviderManager] %s (%s) error: %s", role, provider_name, exc)
        return None

    def record_provider_feedback(
        self,
        provider: str,
        *,
        quality_score: float,
        latency_ms: float | None = None,
    ) -> None:
        """Record runtime evaluation feedback for provider ranking."""
        if provider not in VALID_PROVIDERS:
            return
        q = max(0.0, min(1.0, float(quality_score)))
        with self._lock:
            m = self._provider_metrics.setdefault(
                provider, {"calls": 0.0, "quality": 0.0, "latency_ms": 0.0}
            )
            calls = m["calls"] + 1.0
            m["quality"] = ((m["quality"] * m["calls"]) + q) / calls
            if latency_ms is not None:
                lat = max(0.0, float(latency_ms))
                m["latency_ms"] = (
                    ((m["latency_ms"] * m["calls"]) + lat) / calls if m["calls"] > 0 else lat
                )
            m["calls"] = calls

    def provider_rankings(self, *, prompt: str = "", prefer_long_context: bool = False) -> dict[str, float]:
        """Return governance-aware provider scores for current request shape."""
        return {p: s for p, s in self._ranked_provider_scores(prompt, prefer_long_context)}

    def _ranked_provider_order(self, prompt: str, prefer_long_context: bool) -> list[str]:
        ranked = [p for p, _ in self._ranked_provider_scores(prompt, prefer_long_context)]
        if self.active in ranked:
            ranked.remove(self.active)
            ranked.insert(0, self.active)
        return ranked

    def _ranked_provider_scores(
        self,
        prompt: str,
        prefer_long_context: bool,
    ) -> list[tuple[str, float]]:
        availability = {
            "hf": self._hf_available(),
            "anthropic": self._anthropic_available(),
            "qwen": self._qwen_available(),
            "llama3": self._qwen_available(),
            "ruflo": self._ruflo_available(),
        }
        scores: list[tuple[str, float]] = []
        prompt_len = len(prompt or "")
        for provider in VALID_PROVIDERS:
            if not availability.get(provider, False):
                continue
            caps = self._provider_capabilities.get(provider, {})
            metrics = self._provider_metrics.get(provider, {})
            quality = float(metrics.get("quality", 0.0) or 0.0)
            latency_ms = float(metrics.get("latency_ms", 0.0) or 0.0)
            latency_score = 1.0 / (1.0 + (latency_ms / 1200.0)) if latency_ms > 0 else caps.get("latency", 0.7)
            long_ctx_weight = 0.35 if (prefer_long_context or prompt_len > 900) else 0.15
            score = (
                caps.get("cognition", 0.7) * 0.45
                + max(caps.get("long_context", 0.7), long_ctx_weight) * 0.20
                + quality * 0.20
                + latency_score * 0.15
            )
            scores.append((provider, round(score, 4)))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores

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

    def _ask_hf(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        hf = self._hf_brain
        if hf is None:
            hf = self._lazy_hf()
            self._hf_brain = hf
        if hf is None or not getattr(hf, "enabled", False):
            return None
        # HFBrain.ask_single() takes a plain prompt string
        result = hf.ask_single(prompt)
        return result if result and result.strip() else None

    def _ask_anthropic(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        cl = self._claude
        if cl is None:
            cl = self._lazy_claude()
            self._claude = cl
        if cl is None or not cl.is_available():
            return None
        # ClaudeEngine.generate() accepts query + optional system override
        result = cl.generate(prompt, system=system or "", max_tokens=max_tokens)
        return result if result and result.strip() else None

    def _qwen_available(self) -> bool:
        lb = self._local_brain
        if lb is None:
            self._local_brain = self._lazy_local_brain()
            lb = self._local_brain
        return lb is not None

    def _ruflo_available(self) -> bool:
        rf = self._ruflo
        if rf is None:
            self._ruflo = self._lazy_ruflo()
            rf = self._ruflo
        return rf is not None and getattr(rf, "is_available", lambda: False)()

    def _ask_qwen(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        lb = self._resolve_local_brain()
        if lb is None:
            return None
        return self._call_local_brain(lb, prompt=prompt, system=system, max_tokens=max_tokens)

    def _ask_llama3(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        lb = self._resolve_local_brain(preset="llama3")
        if lb is None:
            return None
        return self._call_local_brain(lb, prompt=prompt, system=system, max_tokens=max_tokens)

    def _resolve_local_brain(self, preset: str | None = None) -> Any | None:
        if preset == "llama3":
            try:
                from modules.local_brain import swap_local_brain  # type: ignore[import]
                lb = swap_local_brain("llama3")
                self._local_brain = lb
                return lb
            except Exception:
                pass
        lb = self._local_brain
        if lb is None:
            self._local_brain = self._lazy_local_brain()
            lb = self._local_brain
        return lb

    @staticmethod
    def _call_local_brain(
        lb: Any,
        *,
        prompt: str,
        system: str,
        max_tokens: int,
    ) -> str | None:
        result = None
        if hasattr(lb, "generate"):
            result = lb.generate(prompt, max_new_tokens=max_tokens, system_prompt=system or None)
        elif hasattr(lb, "ask"):
            result = lb.ask(prompt, context=system or "")
        if not result or not str(result).strip():
            return None
        text = str(result).strip()
        lower = text.lower()
        if lower.startswith("[localbrain ") and ("unavailable" in lower or "error" in lower):
            return None
        return text

    def _ask_ruflo(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        rf = self._ruflo
        if rf is None:
            rf = self._lazy_ruflo()
            self._ruflo = rf
        if rf is None or not getattr(rf, "is_available", lambda: False)():
            return None
        result = rf.generate(prompt, system=system or "", max_tokens=max_tokens)
        return result if result and result.strip() else None

    def _lazy_hf(self) -> Any | None:
        """Try to import and instantiate HFBrain without requiring a DB."""
        try:
            from modules.hf_brain import HFBrain  # type: ignore[import]
            return HFBrain(db=None)
        except Exception as exc:
            log.debug("[LLMProviderManager] HFBrain lazy-init failed: %s", exc)
            return None

    def _lazy_claude(self) -> Any | None:
        """Try to import and instantiate ClaudeEngine."""
        try:
            from niblit_models.claude_engine import ClaudeEngine  # type: ignore[import]
            return ClaudeEngine()
        except Exception as exc:
            log.debug("[LLMProviderManager] ClaudeEngine lazy-init failed: %s", exc)
            return None

    def _lazy_local_brain(self) -> Any | None:
        """Try to import and instantiate local Qwen brain singleton."""
        try:
            from modules.local_brain import get_local_brain  # type: ignore[import]
            return get_local_brain()
        except Exception as exc:
            log.debug("[LLMProviderManager] LocalBrain lazy-init failed: %s", exc)
            return None

    def _lazy_ruflo(self) -> Any | None:
        """Try to import and instantiate Ruflo HTTP adapter."""
        try:
            from modules.ruflo_adapter import RufloAdapter  # type: ignore[import]
            return RufloAdapter()
        except Exception as exc:
            log.debug("[LLMProviderManager] RufloAdapter lazy-init failed: %s", exc)
            return None


if __name__ == "__main__":
    print('Running llm_provider_manager.py')
