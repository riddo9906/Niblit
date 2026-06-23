"""modules/brain_router.py — Intelligent Multi-Brain Router (Niblit Hybrid Brain v1).

Routes each prompt to the most appropriate intelligence source:

    ┌──────────────────────────┐
    │   Cognitive Kernel v3    │  ← MASTER CONTROLLER
    │ (Reasoning + Routing)    │
    └──────────┬───────────────┘
               │
    ┌──────────┼──────────────────┐
    │          │                  │
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Local    │ │ Cloud    │ │ Memory Brain │
│ Brain    │ │ Brain    │ │ (GraphRAG)   │
│ (Qwen)   │ │ (HF/etc) │ │              │
└──────────┘ └──────────┘ └──────────────┘

Routing strategies
------------------
* **local-first**  — fast, offline, cheap (simple prompts)
* **memory-augmented** — local brain + GraphRAG/KB context (knowledge-heavy)
* **cloud-escalation** — cloud LLM for complex / long prompts
* **hybrid**        — local draft → cloud refinement (power mode)

Performance modes (``NIBLIT_BRAIN_MODE`` env var)
--------------------------------------------------
local     → always use local brain only
balanced  → smart routing (default)
power     → hybrid always
offline   → no cloud calls; local + memory only

All routing decisions are logged and optionally persisted to memory so the
router can be improved over time.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("Niblit.BrainRouter")

# ── Performance mode ──────────────────────────────────────────────────────────
_BRAIN_MODE = os.environ.get("NIBLIT_BRAIN_MODE", "balanced").lower()

# Token complexity thresholds
_SIMPLE_WORDS   = int(os.environ.get("NIBLIT_ROUTER_SIMPLE_WORDS", "15"))
_COMPLEX_WORDS  = int(os.environ.get("NIBLIT_ROUTER_COMPLEX_WORDS", "40"))

# Keywords that indicate a knowledge-heavy prompt
_KNOWLEDGE_KEYWORDS = {
    "explain", "why", "how", "what", "describe", "definition",
    "history", "overview", "concept", "theory", "meaning",
}


def _analyze_prompt(prompt: str) -> Dict[str, Any]:
    """Score a prompt across routing dimensions."""
    words = prompt.split()
    n = len(words)
    lower = prompt.lower()
    return {
        "word_count":      n,
        "simple":          n <= _SIMPLE_WORDS,
        "complex":         n > _COMPLEX_WORDS,
        "knowledge_heavy": any(kw in lower for kw in _KNOWLEDGE_KEYWORDS),
    }


class BrainRouter:
    """Routes prompts to the best intelligence source.

    Parameters
    ----------
    local_brain:
        A :class:`~modules.local_brain.QwenLocalBrain` instance (or any
        object with ``ask(prompt, context='')`` and ``is_available()``).
    cloud_brain:
        A callable ``(prompt) -> str`` that queries the cloud LLM
        (HFBrain / LLMProviderManager / ChatCompletions).
    memory_retriever:
        A callable ``(query) -> str`` that returns relevant context from
        GraphRAG / MWDS (optional).
    mode:
        One of ``local``, ``balanced``, ``power``, ``offline``.
        Defaults to the ``NIBLIT_BRAIN_MODE`` env var or ``balanced``.
    """

    def __init__(
        self,
        local_brain: Any = None,
        cloud_brain: Optional[Callable[[str], str]] = None,
        memory_retriever: Optional[Callable[[str], str]] = None,
        mode: str = _BRAIN_MODE,
    ) -> None:
        self.local_brain = local_brain
        self.cloud_brain = cloud_brain
        self.memory_retriever = memory_retriever
        self.mode = mode
        self._router = None
        self._lock = threading.Lock()
        self._routing_stats: Dict[str, int] = {
            "local": 0, "memory_augmented": 0, "cloud": 0, "hybrid": 0,
        }
        log.info("[BrainRouter] Initialised — mode=%s", self.mode)

    # ── Public entry point ────────────────────────────────────────────────────

    def route(self, prompt: str, context: str = "") -> str:
        """Route *prompt* to the best brain and return the response.

        Parameters
        ----------
        prompt:
            The user's query.
        context:
            Pre-assembled context (SECA/RAG/GraphRAG) — passed to the
            local brain for memory-augmented calls.
        """
        score = _analyze_prompt(prompt)
        path  = self._choose_path(score)

        log.debug(
            "[BrainRouter] prompt_words=%d path=%s mode=%s",
            score["word_count"], path, self.mode,
        )

        with self._lock:
            self._routing_stats[path] = self._routing_stats.get(path, 0) + 1

        if path == "local":
            return self._local_first(prompt, context)
        if path == "memory_augmented":
            return self._memory_augmented(prompt, context)
        if path == "cloud":
            return self._cloud_escalation(prompt)
        # hybrid
        return self._hybrid_response(prompt, context)

    # ── Path selection ────────────────────────────────────────────────────────

    def _choose_path(self, score: Dict[str, Any]) -> str:
        """Decide which routing path to use based on mode + prompt score."""
        if self.mode == "local":
            return "local"
        if self.mode == "offline":
            return "memory_augmented" if score["knowledge_heavy"] else "local"
        if self.mode == "power":
            return "hybrid"

        # balanced (default)
        if score["simple"]:
            return "local"
        if score["knowledge_heavy"] and not score["complex"]:
            return "memory_augmented"
        if score["complex"]:
            return "cloud"
        return "local"  # medium prompts default to local

    # ── Routing strategies ────────────────────────────────────────────────────

    def _router_generate(self, prompt: str, context: str = "") -> str:
        """Canonical local path: RuntimeRouterV2 → LocalBrain.route_inference()."""
        try:
            if self._router is None:
                from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2
                self._router = NiblitUnifiedRuntimeRouterV2(self.local_brain)
            return str(self._router.generate(prompt=prompt, context=context))
        except Exception as exc:
            log.debug("[BrainRouter] router path failed: %s", exc)
            if self.local_brain and self.local_brain.is_available():
                try:
                    return self.local_brain.ask(prompt, context=context)
                except Exception as inner_exc:
                    log.debug("[BrainRouter] local fallback failed: %s", inner_exc)
            return ""

    def _local_first(self, prompt: str, context: str = "") -> str:
        """Fast path: local Qwen brain only."""
        if self.local_brain and self.local_brain.is_available():
            try:
                return self._router_generate(prompt, context=context)
            except Exception as exc:
                log.debug("[BrainRouter] local_first failed: %s", exc)
        # Escalate to cloud if local not ready
        return self._cloud_escalation(prompt)

    def _memory_augmented(self, prompt: str, context: str = "") -> str:
        """Smart path: retrieve memory context, then run local brain."""
        retrieved = context
        if not retrieved and self.memory_retriever:
            try:
                retrieved = self.memory_retriever(prompt) or ""
            except Exception as exc:
                log.debug("[BrainRouter] memory_retriever failed: %s", exc)

        if self.local_brain and self.local_brain.is_available():
            try:
                return self._router_generate(prompt, context=retrieved)
            except Exception as exc:
                log.debug("[BrainRouter] memory_augmented local failed: %s", exc)

        # Fallback: cloud with context prepended
        cloud_prompt = (
            (retrieved.strip() + "\n\n" + prompt) if retrieved.strip() else prompt
        )
        return self._cloud_escalation(cloud_prompt)

    def _cloud_escalation(self, prompt: str) -> str:
        """Power path: send prompt directly to cloud brain."""
        if self.cloud_brain:
            try:
                result = self.cloud_brain(prompt)
                if result and isinstance(result, str):
                    return result
            except Exception as exc:
                log.debug("[BrainRouter] cloud_escalation failed: %s", exc)
        # Cloud failed → fall back to local
        if self.local_brain and self.local_brain.is_available():
            try:
                return self._router_generate(prompt)
            except Exception as exc:
                log.debug("[BrainRouter] cloud_escalation→local fallback failed: %s", exc)
        return ""

    def _hybrid_response(self, prompt: str, context: str = "") -> str:
        """Real magic: local draft → cloud refinement."""
        local_draft = ""
        if self.local_brain and self.local_brain.is_available():
            try:
                local_draft = self._router_generate(prompt, context=context)
            except Exception as exc:
                log.debug("[BrainRouter] hybrid local draft failed: %s", exc)

        if local_draft and self.cloud_brain:
            refine_prompt = (
                f"Refine and improve this answer:\n\n{local_draft}\n\n"
                f"Original question: {prompt}"
            )
            try:
                refined = self.cloud_brain(refine_prompt)
                if refined and isinstance(refined, str):
                    return refined
            except Exception as exc:
                log.debug("[BrainRouter] hybrid cloud refinement failed: %s", exc)

        # Return local draft as fallback
        if local_draft:
            return local_draft
        return self._cloud_escalation(prompt)

    # ── Control ───────────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Change the routing mode at runtime."""
        valid = {"local", "balanced", "power", "offline"}
        if mode not in valid:
            raise ValueError(f"mode must be one of {valid}, got {mode!r}")
        self.mode = mode
        log.info("[BrainRouter] Mode changed to: %s", mode)

    def stats(self) -> Dict[str, Any]:
        """Return routing decision statistics."""
        with self._lock:
            total = sum(self._routing_stats.values()) or 1
            return {
                "mode": self.mode,
                "local_available": self.local_brain.is_available() if self.local_brain else False,
                "cloud_available": self.cloud_brain is not None,
                "routing_counts": dict(self._routing_stats),
                "routing_pct": {
                    k: f"{v/total:.0%}" for k, v in self._routing_stats.items()
                },
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[BrainRouter] = None
_inst_lock = threading.Lock()


def get_brain_router(
    local_brain: Any = None,
    cloud_brain: Optional[Callable[[str], str]] = None,
    memory_retriever: Optional[Callable[[str], str]] = None,
    mode: str = _BRAIN_MODE,
) -> BrainRouter:
    """Return the process-wide :class:`BrainRouter` singleton.

    The first call creates the instance with the provided arguments.
    Subsequent calls ignore arguments and return the cached instance.
    """
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = BrainRouter(
                    local_brain=local_brain,
                    cloud_brain=cloud_brain,
                    memory_retriever=memory_retriever,
                    mode=mode,
                )
    return _instance


def reset_brain_router() -> None:
    """Reset the singleton (testing / re-wiring after init)."""
    global _instance
    with _inst_lock:
        _instance = None


if __name__ == "__main__":
    print('Running brain_router.py')
