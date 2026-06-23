#!/usr/bin/env python3
"""
modules/model_orchestrator.py — Phase 21 Multi-Model Orchestration

Automatically selects the best available model for a given task,
replacing the manual model-swapping approach with intelligent delegation.

Model roster
------------
Model           | Role                        | Env flag
----------------|-----------------------------|-----------------------
Llama 3.2 1B    | Reasoning / medium tasks    | NIBLIT_LLAMA_ENABLED=1
Qwen 0.5B       | Fast fallback / light tasks | always available (local)
Remote GPT      | Deep synthesis / complex    | OPENAI_API_KEY set
TFT adapter     | Market forecasting          | always available (EWMA)
Cloud LLM       | Remote LLM (Ollama etc.)    | NIBLIT_CLOUD_LLM_URL set

Selection logic (from ``select()``)
------------------------------------
1. Query :class:`~modules.runtime_resource_manager.RuntimeResourceManager`
   for resource constraints.
2. Consider the task's ``complexity``, ``requires_forecast``, and
   ``safety_level`` fields.
3. Return the model descriptor best matching all constraints.

Output
------
:class:`ModelSelection`::

    model_id      : str   — "qwen" | "llama3" | "gpt" | "tft" | "cloud"
    reason        : str   — human-readable rationale
    fallback      : str   — fallback model_id if primary fails
    is_local      : bool  — True when the model runs on-device
    max_tokens    : int   — recommended context window

Configuration (env vars)
------------------------
    NIBLIT_MO_ENABLED         — "0" to disable (default 1)
    NIBLIT_LLAMA_ENABLED      — "1" to include Llama 3.2 in roster (default 1)
    OPENAI_API_KEY            — set to enable remote GPT delegation
    NIBLIT_CLOUD_LLM_URL      — Ollama / LMStudio / custom URL

Usage::

    from modules.model_orchestrator import get_model_orchestrator

    orch = get_model_orchestrator()
    sel = orch.select(task={"complexity": 0.8, "requires_forecast": False})
    print(sel.model_id, sel.reason)
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_MO_ENABLED", "1").strip() not in ("0", "false")
_LLAMA_ENABLED: bool = os.getenv("NIBLIT_LLAMA_ENABLED", "1").strip() == "1"
_GPT_AVAILABLE: bool = bool(os.getenv("OPENAI_API_KEY", "").strip())
_CLOUD_URL: str = os.getenv("NIBLIT_CLOUD_LLM_URL", "").strip()


# ── Model descriptors ──────────────────────────────────────────────────────────

@dataclass
class ModelDescriptor:
    model_id: str
    display_name: str
    is_local: bool
    max_tokens: int
    complexity_threshold: float   # tasks with complexity > this are passed up
    ram_requirement_mb: float     # approximate RAM footprint


_MODELS: List[ModelDescriptor] = [
    ModelDescriptor("llama3","Llama 3.2 1B",      is_local=True,  max_tokens=16384, complexity_threshold=0.75, ram_requirement_mb=2000),
    ModelDescriptor("qwen",  "Qwen 2.5 0.5B",    is_local=True,  max_tokens=2048,  complexity_threshold=0.5, ram_requirement_mb=800),
    ModelDescriptor("cloud", "Cloud LLM (Ollama)",is_local=False, max_tokens=16384, complexity_threshold=0.9, ram_requirement_mb=0),
    ModelDescriptor("gpt",   "Remote GPT",        is_local=False, max_tokens=16384, complexity_threshold=1.0, ram_requirement_mb=0),
    ModelDescriptor("tft",   "TFT Forecast",      is_local=True,  max_tokens=0,     complexity_threshold=0.0, ram_requirement_mb=100),
]

_LLAMA_PRIORITY_INTENTS = {
    "reasoning",
    "reflection",
    "runtime_analysis",
    "telemetry_interpretation",
    "architecture_reasoning",
    "memory_synthesis",
    "ale_interpretation",
    "knowledge_gap_synthesis",
    "summarization",
}


# ── ModelSelection ────────────────────────────────────────────────────────────

@dataclass
class ModelSelection:
    """The orchestrator's model recommendation for a task."""
    model_id: str
    display_name: str
    reason: str
    fallback: str
    is_local: bool
    max_tokens: int

    def to_dict(self) -> Dict:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "reason": self.reason,
            "fallback": self.fallback,
            "is_local": self.is_local,
            "max_tokens": self.max_tokens,
        }


# ── ModelOrchestrator ─────────────────────────────────────────────────────────

class ModelOrchestrator:
    """Selects the optimal model for a task based on constraints.

    Thread-safe singleton.  Falls back to ``"qwen"`` on any error.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._selection_count: int = 0
        self._model_usage: Dict[str, int] = {}
        log.debug("[ModelOrchestrator] initialised (llama=%s gpt=%s cloud=%s)",
                  _LLAMA_ENABLED, _GPT_AVAILABLE, bool(_CLOUD_URL))

    # ── Public API ────────────────────────────────────────────────────────────

    def select(self, task: Optional[Dict[str, Any]] = None) -> ModelSelection:
        """Select the best model for *task*.

        Args:
            task: Dict with optional keys:
                  ``complexity``        (float 0.0–1.0, default 0.5)
                  ``requires_forecast`` (bool, default False)
                  ``safety_level``      (str "low"|"medium"|"high", default "low")
                  ``intent``            (str, default "conversational")

        Returns:
            :class:`ModelSelection` — always valid.
        """
        if not _ENABLED:
            return self._qwen_selection("orchestrator disabled")
        try:
            return self._select_inner(dict(task or {}))
        except Exception as exc:
            log.warning("[ModelOrchestrator] select error: %s", exc)
            return self._qwen_selection(f"error: {exc}")

    def _select_inner(self, task: Dict) -> ModelSelection:
        complexity    = float(task.get("complexity", 0.5))
        req_forecast  = bool(task.get("requires_forecast", False))
        safety_level  = str(task.get("safety_level", "low"))
        intent        = str(task.get("intent", "conversational"))

        # Forecasting intent always uses TFT
        if req_forecast or intent in ("forecasting", "trading"):
            return self._make_selection("tft", reason="forecasting task", fallback="qwen")

        if _LLAMA_ENABLED and intent in _LLAMA_PRIORITY_INTENTS:
            return self._make_selection(
                "llama3",
                reason=f"llama-priority intent ({intent})",
                fallback="qwen",
            )

        # Get resource constraints
        rec = self._get_resource_rec()

        # High safety → stay local
        force_local = safety_level == "high"

        # Cascade through models by complexity
        if complexity <= 0.5 or rec.prefer_qwen:
            return self._qwen_selection(
                "low complexity" if not rec.prefer_qwen else rec.reason
            )

        if complexity <= 0.75 and _LLAMA_ENABLED and not rec.prefer_qwen:
            return self._make_selection("llama3", reason=f"medium complexity ({complexity:.2f})", fallback="qwen")

        if not force_local and _CLOUD_URL and not rec.prefer_qwen:
            return self._make_selection("cloud", reason=f"high complexity ({complexity:.2f}), cloud available", fallback="llama3" if _LLAMA_ENABLED else "qwen")

        if not force_local and _GPT_AVAILABLE and not rec.prefer_qwen:
            return self._make_selection("gpt", reason=f"high complexity ({complexity:.2f}), GPT available", fallback="qwen")

        return self._qwen_selection(f"fallback to local (complexity={complexity:.2f})")

    def _make_selection(self, model_id: str, reason: str, fallback: str = "qwen") -> ModelSelection:
        desc = next((m for m in _MODELS if m.model_id == model_id), _MODELS[0])
        with self._lock:
            self._selection_count += 1
            self._model_usage[model_id] = self._model_usage.get(model_id, 0) + 1
        log.debug("[ModelOrchestrator] selected %s: %s", model_id, reason)
        return ModelSelection(
            model_id=model_id,
            display_name=desc.display_name,
            reason=reason,
            fallback=fallback,
            is_local=desc.is_local,
            max_tokens=desc.max_tokens,
        )

    def _qwen_selection(self, reason: str) -> ModelSelection:
        return self._make_selection("qwen", reason=reason, fallback="qwen")

    def _get_resource_rec(self):
        """Fetch resource recommendation (best-effort)."""
        try:
            from modules.runtime_resource_manager import get_resource_manager
            return get_resource_manager().recommend()
        except Exception:
            # Safe default: no constraints
            from dataclasses import dataclass as _dc
            @_dc
            class _FakeRec:
                prefer_qwen = False
                reason = "resource manager unavailable"
            return _FakeRec()

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "selection_count": self._selection_count,
                "model_usage": dict(self._model_usage),
                "available_models": {
                    "qwen": True,
                    "llama3": _LLAMA_ENABLED,
                    "gpt": _GPT_AVAILABLE,
                    "cloud": bool(_CLOUD_URL),
                    "tft": True,
                },
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_orch: Optional[ModelOrchestrator] = None
_orch_lock = threading.Lock()


def get_model_orchestrator() -> ModelOrchestrator:
    """Return the module-level :class:`ModelOrchestrator` singleton."""
    global _orch
    with _orch_lock:
        if _orch is None:
            _orch = ModelOrchestrator()
    return _orch


if __name__ == "__main__":
    print('Running model_orchestrator.py')
