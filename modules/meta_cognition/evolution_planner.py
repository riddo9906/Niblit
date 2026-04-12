"""modules/meta_cognition/evolution_planner.py — EvolutionPlanner (MSG Layer v1).

Implements "plan → simulate → pick → evolve" instead of "iterate and pray".

Workflow
--------
1. :meth:`propose` — generate one or more candidate :class:`EvolutionCandidate`
   objects.
2. :meth:`simulate` — score candidates using a lightweight heuristic model
   (real simulator hooks can be plugged in later).
3. :meth:`pick_best` — return the highest-expected-gain candidate.
4. :meth:`commit` — mark a candidate as "committed" and record the outcome
   later via :meth:`record_outcome`.

All candidates are stored in memory and the last 100 committed candidates are
persisted to ``niblit_state.json`` so Niblit can learn from past decisions.
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

log = logging.getLogger("Niblit.EvolutionPlanner")

_STATE_PATH = Path(os.environ.get("NIBLIT_STATE_PATH", "niblit_state.json"))
_EP_KEY = "msg_evolution_planner"


@dataclass
class EvolutionCandidate:
    """A single proposed self-modification."""
    id: str = field(default_factory=lambda: f"ep_{int(time.time()*1000)}")
    description: str = ""
    target_module: str = ""
    expected_gain: float = 0.0      # predicted improvement ∈ [0, 1]
    simulated_score: float = 0.0    # score after simulate()
    risk: float = 0.1               # estimated risk ∈ [0, 1]
    status: str = "proposed"        # proposed | simulated | committed | done
    outcome_gain: Optional[float] = None  # actual gain after execution
    created_at: float = field(default_factory=time.time)
    committed_at: Optional[float] = None

    def net_value(self) -> float:
        """Expected gain adjusted for risk (risk-adjusted value)."""
        return self.expected_gain * (1.0 - self.risk)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvolutionCandidate":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


class EvolutionPlanner:
    """Plans Niblit's self-modification roadmap.

    Thread-safe.  Uses a lightweight internal simulation model;
    real sandbox execution can be added later as a plugin.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._candidates: List[EvolutionCandidate] = []
        self._committed: List[EvolutionCandidate] = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if _STATE_PATH.exists():
                data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                saved = data.get(_EP_KEY, {})
                self._committed = [
                    EvolutionCandidate.from_dict(c)
                    for c in saved.get("committed", [])
                ]
        except Exception as exc:
            log.debug("[EvolutionPlanner] load failed: %s", exc)

    def _save(self) -> None:
        try:
            data: Dict[str, Any] = {}
            if _STATE_PATH.exists():
                try:
                    data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data[_EP_KEY] = {
                "committed": [c.to_dict() for c in self._committed[-100:]],
            }
            _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            log.debug("[EvolutionPlanner] save failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def propose(
        self,
        description: str,
        target_module: str = "",
        expected_gain: float = 0.1,
        risk: float = 0.1,
    ) -> EvolutionCandidate:
        """Create and register a new evolution candidate."""
        with self._lock:
            c = EvolutionCandidate(
                description=description,
                target_module=target_module,
                expected_gain=expected_gain,
                risk=risk,
            )
            self._candidates.append(c)
            log.debug("[EvolutionPlanner] Proposed: %s (gain=%.2f, risk=%.2f)",
                      description[:60], expected_gain, risk)
            return c

    def simulate(self, candidate_id: Optional[str] = None) -> None:
        """Run the internal simulation model on pending candidates.

        Assigns a ``simulated_score`` that factors in the candidate's own
        expected gain, risk, and historical outcomes of similar changes.
        """
        with self._lock:
            targets = (
                [c for c in self._candidates if c.id == candidate_id]
                if candidate_id
                else [c for c in self._candidates if c.status == "proposed"]
            )
            if not targets:
                return

            # Simple heuristic simulation:
            # simulated_score = expected_gain * (1 - risk) * history_factor
            avg_historical = self._avg_historical_gain()
            for c in targets:
                history_factor = 0.8 if avg_historical is None else min(
                    1.2, max(0.5, avg_historical / max(c.expected_gain, 0.01))
                )
                c.simulated_score = round(c.expected_gain * (1 - c.risk) * history_factor, 4)
                c.status = "simulated"
                log.debug("[EvolutionPlanner] Simulated %s: score=%.3f",
                          c.description[:50], c.simulated_score)

    def pick_best(self) -> Optional[EvolutionCandidate]:
        """Return the highest simulated_score candidate (runs simulate first)."""
        with self._lock:
            pending = [c for c in self._candidates if c.status in ("proposed", "simulated")]
        # simulate outside lock to avoid nested locking
        self.simulate()
        with self._lock:
            simulated = [c for c in self._candidates if c.status == "simulated"]
            if not simulated:
                return None
            best = max(simulated, key=lambda c: c.simulated_score)
            log.info("[EvolutionPlanner] Best candidate: %s (score=%.3f)",
                     best.description[:60], best.simulated_score)
            return best

    def commit(self, candidate_id: str) -> bool:
        """Mark a candidate as committed (ready for execution)."""
        with self._lock:
            for c in self._candidates:
                if c.id == candidate_id:
                    c.status = "committed"
                    c.committed_at = time.time()
                    self._committed.append(c)
                    self._candidates.remove(c)
                    self._save()
                    log.info("[EvolutionPlanner] Committed: %s", c.description[:60])
                    return True
            return False

    def record_outcome(self, candidate_id: str, actual_gain: float) -> None:
        """Record the actual outcome gain for a committed candidate."""
        with self._lock:
            for c in self._committed:
                if c.id == candidate_id:
                    c.outcome_gain = actual_gain
                    c.status = "done"
                    self._save()
                    log.info("[EvolutionPlanner] Outcome recorded for %s: %.3f",
                             c.description[:50], actual_gain)
                    return

    def _avg_historical_gain(self) -> Optional[float]:
        """Mean outcome_gain across completed candidates."""
        done = [c.outcome_gain for c in self._committed
                if c.outcome_gain is not None]
        return sum(done) / len(done) if done else None

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot."""
        with self._lock:
            return {
                "pending_candidates": len(self._candidates),
                "committed_total": len(self._committed),
                "avg_historical_gain": self._avg_historical_gain(),
                "recent_committed": [
                    c.to_dict() for c in self._committed[-5:]
                ],
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[EvolutionPlanner] = None
_inst_lock = threading.Lock()


def get_evolution_planner() -> EvolutionPlanner:
    """Return the process-wide :class:`EvolutionPlanner` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = EvolutionPlanner()
    return _instance
