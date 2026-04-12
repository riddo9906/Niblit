"""modules/meta_cognition/self_model.py — SelfConceptEngine (MSG Layer v1).

Maintains a persistent internal "self-image" for Niblit:

    SelfModel = {
        capabilities:       known strengths (domain → confidence),
        limitations:        known weaknesses (domain → weakness_score),
        active_domains:     currently active research/skill domains,
        confidence_map:     per-domain knowledge confidence ∈ [0, 1],
        evolution_history:  list of past self-modifications with outcomes,
    }

The model is updated incrementally each ALE cycle so it reflects Niblit's
evolving knowledge state.  All data is stored in ``niblit_state.json`` under
the ``msg_self_model`` key so it survives process restarts.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.SelfModel")

_STATE_PATH = Path(os.environ.get("NIBLIT_STATE_PATH", "niblit_state.json"))
_SELF_MODEL_KEY = "msg_self_model"


@dataclass
class EvolutionRecord:
    """One past self-modification event."""
    ts: float = field(default_factory=time.time)
    description: str = ""
    module: str = ""
    outcome: str = "unknown"   # "improved" | "neutral" | "degraded"
    delta: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "EvolutionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


class SelfModel:
    """Persistent internal self-image for Niblit.

    All mutable state is thread-safe; reads and writes acquire ``_lock``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.capabilities: Dict[str, float] = {}         # domain → strength ∈[0,1]
        self.limitations: Dict[str, float] = {}          # domain → weakness ∈[0,1]
        self.active_domains: List[str] = []
        self.confidence_map: Dict[str, float] = {}       # domain → kb confidence
        self.evolution_history: List[EvolutionRecord] = []
        self._cycle_count: int = 0
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if _STATE_PATH.exists():
                data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                saved = data.get(_SELF_MODEL_KEY, {})
                self.capabilities   = saved.get("capabilities", {})
                self.limitations    = saved.get("limitations", {})
                self.active_domains = saved.get("active_domains", [])
                self.confidence_map = saved.get("confidence_map", {})
                self._cycle_count   = saved.get("cycle_count", 0)
                self.evolution_history = [
                    EvolutionRecord.from_dict(e)
                    for e in saved.get("evolution_history", [])
                ]
        except Exception as exc:
            log.debug("[SelfModel] load failed: %s", exc)

    def _save(self) -> None:
        try:
            data: Dict[str, Any] = {}
            if _STATE_PATH.exists():
                try:
                    data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data[_SELF_MODEL_KEY] = {
                "capabilities":    self.capabilities,
                "limitations":     self.limitations,
                "active_domains":  self.active_domains,
                "confidence_map":  self.confidence_map,
                "cycle_count":     self._cycle_count,
                "evolution_history": [e.to_dict() for e in self.evolution_history[-50:]],
            }
            _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            log.debug("[SelfModel] save failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def record_cycle(self, cycle: int, topic: str) -> None:
        """Update active_domains and cycle_count; called each ALE cycle."""
        with self._lock:
            self._cycle_count = cycle
            if topic and topic not in self.active_domains:
                self.active_domains.append(topic)
                if len(self.active_domains) > 30:
                    self.active_domains = self.active_domains[-30:]
            self._save()

    def update_confidence(self, domain: str, confidence: float) -> None:
        """Set or update per-domain knowledge confidence."""
        with self._lock:
            confidence = max(0.0, min(1.0, confidence))
            prev = self.confidence_map.get(domain, 0.5)
            # Exponential moving average (α=0.3)
            self.confidence_map[domain] = round(prev * 0.7 + confidence * 0.3, 4)
            if confidence >= 0.7:
                self.capabilities[domain] = self.confidence_map[domain]
                self.limitations.pop(domain, None)
            elif confidence < 0.4:
                self.limitations[domain] = round(1.0 - confidence, 4)
                self.capabilities.pop(domain, None)
            self._save()

    def record_evolution(
        self,
        description: str,
        module: str = "",
        outcome: str = "unknown",
        delta: float = 0.0,
    ) -> None:
        """Append an evolution event to the history."""
        with self._lock:
            self.evolution_history.append(
                EvolutionRecord(
                    description=description,
                    module=module,
                    outcome=outcome,
                    delta=delta,
                )
            )
            self._save()

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable state snapshot."""
        with self._lock:
            return {
                "cycle_count":      self._cycle_count,
                "capabilities":     dict(self.capabilities),
                "limitations":      dict(self.limitations),
                "active_domains":   list(self.active_domains[-10:]),
                "confidence_map":   dict(self.confidence_map),
                "evolution_events": len(self.evolution_history),
            }

    def strengths(self, top_n: int = 5) -> List[str]:
        """Return the top-N capability domains sorted by score."""
        with self._lock:
            return sorted(self.capabilities, key=lambda k: self.capabilities[k],
                          reverse=True)[:top_n]

    def weaknesses(self, top_n: int = 5) -> List[str]:
        """Return the top-N weakness domains sorted by score (highest = weakest)."""
        with self._lock:
            return sorted(self.limitations, key=lambda k: self.limitations[k],
                          reverse=True)[:top_n]


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[SelfModel] = None
_inst_lock = threading.Lock()


def get_self_model() -> SelfModel:
    """Return the process-wide :class:`SelfModel` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = SelfModel()
    return _instance
