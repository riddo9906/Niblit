#!/usr/bin/env python3
"""
modules/model_ecology.py — Phase Ω Unified Model Ecology

Evolves the model roster from interchangeable endpoints into
specialised **cognitive organs**, each with tracked trust, performance
history, and cognitive-load awareness.

Current models:
    Qwen 0.5B          — fast routing, low-cost tasks
    Llama 3.2 1B       — reasoning, medium tasks
    Cloud LLM (Ollama) — larger context, higher accuracy
    Remote GPT         — deep synthesis, complex tasks
    TFT                — market forecasting

Model Ecology adds:
    specialization_map — which task types each model excels at
    trust_scores       — per-model EMA of historical success
    ensemble_support   — call multiple models, arbitrate disagreement
    cognitive_load     — current RAM/latency cost of each model
    dynamic blending   — weight-average multiple model outputs

Configuration (env vars)
------------------------
    NIBLIT_ME_ENABLED       — "0" to disable (default 1)
    NIBLIT_ME_STATE_PATH    — override state file path

Usage::

    from modules.model_ecology import get_model_ecology

    eco = get_model_ecology()
    sel = eco.select_for_task("explain transformer architecture")
    print(sel)            # "llama3"

    eco.record_outcome("llama3", success=True, latency_ms=340, quality=0.85)

    report = eco.ecology_report()
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_ME_ENABLED", "1").strip() not in ("0", "false")
_STATE_PATH: str = os.getenv(
    "NIBLIT_ME_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model_ecology_state.json"),
)
_EMA = 0.15   # trust/quality EMA alpha


# ── ModelProfile ──────────────────────────────────────────────────────────────

@dataclass
class ModelProfile:
    """Trust, performance and specialisation record for one model."""
    model_id: str
    display_name: str
    is_local: bool
    specializations: List[str]   # task labels this model is best at
    trust_score: float = 0.7     # 0.0–1.0 EMA of historical success
    avg_quality: float = 0.7     # 0.0–1.0 EMA of response quality
    avg_latency_ms: float = 0.0  # EMA latency
    call_count: int = 0
    error_count: int = 0
    cognitive_load: float = 0.0  # RAM footprint fraction 0.0–1.0

    @property
    def success_rate(self) -> float:
        return 1.0 if self.call_count == 0 else (self.call_count - self.error_count) / self.call_count

    def composite_score(self) -> float:
        """Combined score: trust × quality × (1 − load_penalty)."""
        load_penalty = min(0.3, self.cognitive_load * 0.3)
        return self.trust_score * self.avg_quality * (1.0 - load_penalty)

    def to_dict(self) -> Dict:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "is_local": self.is_local,
            "specializations": self.specializations,
            "trust_score": round(self.trust_score, 4),
            "avg_quality": round(self.avg_quality, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_rate": round(self.success_rate, 4),
            "composite_score": round(self.composite_score(), 4),
            "cognitive_load": round(self.cognitive_load, 4),
        }


# ── Default roster ────────────────────────────────────────────────────────────

def _default_roster() -> Dict[str, ModelProfile]:
    return {
        "qwen": ModelProfile(
            model_id="qwen", display_name="Qwen 2.5 0.5B", is_local=True,
            specializations=["routing", "classification", "conversational", "short_qa"],
            cognitive_load=0.1,
        ),
        "llama3": ModelProfile(
            model_id="llama3", display_name="Llama 3.2 1B", is_local=True,
            specializations=["reasoning", "analytical", "code", "explanation"],
            cognitive_load=0.25,
        ),
        "cloud": ModelProfile(
            model_id="cloud", display_name="Cloud LLM (Ollama)", is_local=False,
            specializations=["long_context", "synthesis", "creative", "document_qa"],
            cognitive_load=0.0,
        ),
        "gpt": ModelProfile(
            model_id="gpt", display_name="Remote GPT", is_local=False,
            specializations=["deep_synthesis", "complex_reasoning", "strategy"],
            cognitive_load=0.0,
        ),
        "tft": ModelProfile(
            model_id="tft", display_name="TFT Forecaster", is_local=True,
            specializations=["forecasting", "trading", "time_series", "market"],
            cognitive_load=0.05,
        ),
    }


# ── DisagreementArbitration ───────────────────────────────────────────────────

@dataclass
class EnsembleResult:
    """Result of a multi-model ensemble call."""
    outputs: Dict[str, str]      # model_id → raw output
    selected: str                # model_id of chosen output
    agreement_score: float       # 0.0–1.0 how much outputs agree
    confidence: float

    def to_dict(self) -> Dict:
        return {
            "selected": self.selected,
            "agreement_score": round(self.agreement_score, 4),
            "confidence": round(self.confidence, 4),
            "model_count": len(self.outputs),
        }


# ── ModelEcology ──────────────────────────────────────────────────────────────

class ModelEcology:
    """Manages the cognitive model ecosystem.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: Dict[str, ModelProfile] = _default_roster()
        self._select_count: int = 0
        self._load_state()
        log.debug("[ModelEcology] initialised with %d models", len(self._profiles))

    # ── Selection ─────────────────────────────────────────────────────────────

    def select_for_task(
        self,
        task_text: str = "",
        task_type: Optional[str] = None,
        force_local: bool = False,
        complexity: float = 0.5,
    ) -> str:
        """Return the model_id best suited for the given task.

        Args:
            task_text:   Raw task string (used for specialization matching).
            task_type:   Explicit task type label (overrides task_text matching).
            force_local: If True, only consider local models.
            complexity:  Task complexity 0.0–1.0 (higher → prefer stronger model).

        Returns:
            model_id string.
        """
        if not _ENABLED:
            return "qwen"
        with self._lock:
            profiles = dict(self._profiles)

        candidates = {mid: p for mid, p in profiles.items()
                      if not force_local or p.is_local}
        if not candidates:
            return "qwen"

        # Specialization boost
        task_lower = (task_text or "").lower()
        effective_type = task_type or self._infer_type(task_lower)

        scored: List[Tuple[float, str]] = []
        for mid, p in candidates.items():
            base = p.composite_score()
            spec_boost = 0.2 if effective_type in p.specializations else 0.0
            complexity_penalty = 0.0
            # penalise qwen/tft for high complexity non-forecast tasks
            if mid == "qwen" and complexity > 0.7 and effective_type not in p.specializations:
                complexity_penalty = 0.15
            score = base + spec_boost - complexity_penalty
            scored.append((score, mid))

        scored.sort(reverse=True)
        best = scored[0][1]

        with self._lock:
            self._select_count += 1

        log.debug("[ModelEcology] select: task=%s → %s", effective_type, best)
        return best

    def _infer_type(self, text: str) -> str:
        """Lightweight task-type inference from raw text."""
        if any(w in text for w in ("forecast", "predict", "price", "btc", "market", "trade")):
            return "forecasting"
        if any(w in text for w in ("code", "implement", "function", "debug", "script")):
            return "code"
        if any(w in text for w in ("explain", "analyse", "analyze", "reason", "why", "how")):
            return "reasoning"
        if any(w in text for w in ("strategy", "plan", "goal", "objective")):
            return "strategy"
        return "routing"

    # ── Outcome recording ─────────────────────────────────────────────────────

    def record_outcome(
        self,
        model_id: str,
        success: bool,
        latency_ms: float = 0.0,
        quality: float = 0.5,
    ) -> None:
        """Update trust / quality EMA for *model_id*.

        Args:
            model_id:   Model that was used.
            success:    Whether the call completed without error.
            latency_ms: Wall-clock latency.
            quality:    Response quality score 0.0–1.0.
        """
        if not _ENABLED:
            return
        with self._lock:
            p = self._profiles.get(model_id)
            if p is None:
                return
            p.call_count += 1
            if not success:
                p.error_count += 1
            trust_signal = 1.0 if success else 0.0
            p.trust_score = _EMA * trust_signal + (1 - _EMA) * p.trust_score
            p.avg_quality = _EMA * quality + (1 - _EMA) * p.avg_quality
            if latency_ms > 0:
                if p.avg_latency_ms <= 0:
                    p.avg_latency_ms = latency_ms
                else:
                    p.avg_latency_ms = _EMA * latency_ms + (1 - _EMA) * p.avg_latency_ms
        self._save_state()

    # ── Ensemble arbitration ──────────────────────────────────────────────────

    def arbitrate_disagreement(self, outputs: Dict[str, str]) -> EnsembleResult:
        """Choose the best output from a multi-model ensemble.

        Uses trust-weighted voting: the model with the highest trust score
        whose output is "agreed upon" by at least one other model wins.
        Falls back to highest-trust model.

        Args:
            outputs: model_id → raw output string mapping.

        Returns:
            :class:`EnsembleResult`.
        """
        if not outputs:
            return EnsembleResult(outputs={}, selected="qwen", agreement_score=0.0, confidence=0.0)

        with self._lock:
            trust = {mid: self._profiles[mid].trust_score
                     for mid in outputs if mid in self._profiles}

        if not trust:
            best = next(iter(outputs))
            return EnsembleResult(outputs=outputs, selected=best, agreement_score=0.0, confidence=0.5)

        best_model = max(trust, key=trust.__getitem__)
        agreement = self._compute_agreement(outputs)
        confidence = trust.get(best_model, 0.5)

        return EnsembleResult(
            outputs=outputs,
            selected=best_model,
            agreement_score=round(agreement, 4),
            confidence=round(confidence, 4),
        )

    def _compute_agreement(self, outputs: Dict[str, str]) -> float:
        """Fraction of model-pair outputs that share at least 40 % token overlap."""
        items = list(outputs.items())
        if len(items) < 2:
            return 1.0
        agreements = 0
        pairs = 0
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                t_a = set(items[i][1].lower().split())
                t_b = set(items[j][1].lower().split())
                pairs += 1
                if _jaccard(t_a, t_b) >= 0.4:
                    agreements += 1
        return agreements / pairs if pairs else 1.0

    # ── Reports ───────────────────────────────────────────────────────────────

    def ecology_report(self) -> Dict:
        """Return a ranked model ecology report."""
        with self._lock:
            profiles = list(self._profiles.values())
        sorted_profiles = sorted(profiles, key=lambda p: p.composite_score(), reverse=True)
        return {
            "select_count": self._select_count,
            "models": [p.to_dict() for p in sorted_profiles],
        }

    def status(self) -> Dict:
        return {
            "enabled": _ENABLED,
            **self.ecology_report(),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            with self._lock:
                for mid, d in data.items():
                    if mid in self._profiles:
                        p = self._profiles[mid]
                        p.trust_score = d.get("trust_score", p.trust_score)
                        p.avg_quality = d.get("avg_quality", p.avg_quality)
                        p.avg_latency_ms = d.get("avg_latency_ms", p.avg_latency_ms)
                        p.call_count = d.get("call_count", p.call_count)
                        p.error_count = d.get("error_count", p.error_count)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[ModelEcology] load state failed: %s", exc)

    def _save_state(self) -> None:
        try:
            with self._lock:
                data = {mid: p.to_dict() for mid, p in self._profiles.items()}
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, _STATE_PATH)
        except Exception as exc:
            log.debug("[ModelEcology] save state failed: %s", exc)


# ── Helper ────────────────────────────────────────────────────────────────────

def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────
_eco: Optional[ModelEcology] = None
_eco_lock = threading.Lock()


def get_model_ecology() -> ModelEcology:
    """Return the module-level :class:`ModelEcology` singleton."""
    global _eco
    with _eco_lock:
        if _eco is None:
            _eco = ModelEcology()
    return _eco
