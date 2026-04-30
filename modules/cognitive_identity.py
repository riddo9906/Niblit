#!/usr/bin/env python3
"""modules/cognitive_identity.py — Cognitive Identity Layer for Niblit.

Maintains a **persistent, evolving behavioral identity** for Niblit that
reflects *how* it makes decisions over time, not just *what* it knows.

Identity fields
---------------
``decision_style``
    Inferred style based on which advisor wins most often:
    ``"analytical"`` (reasoning-dominant), ``"memory-driven"``,
    ``"goal-focused"``, ``"language-centric"`` (LLM-dominant), or
    ``"balanced"``.

``risk_tolerance``
    Float in [0.0, 1.0].  High → prefers bolder, more novel responses
    (LLM/Reasoning).  Low → prefers safe, memory-backed responses.
    Updated from rolling quality scores.

``response_bias``
    Per-advisor multiplicative bias dict used by the DecisionEngine to
    apply a personality-driven boost/penalty on top of base weights.
    e.g. ``{"reasoning": 1.15, "llm": 0.90}``.

``total_decisions``
    Running count of all decisions evaluated.

``advisor_win_counts``
    Per-advisor win count — tracks which advisor is trusted most.

``quality_history``
    Rolling list of quality scores (last ``_HISTORY_LEN``).

Persistence
-----------
Serialised as JSON to ``niblit_cognitive_identity.json`` in the process
working directory (or ``NIBLIT_IDENTITY_PATH`` env var).

Public API
----------
``CognitiveIdentity``
    The identity manager.  Call ``update(advisor, quality)`` after each
    decision.

``CognitiveIdentity.get_advisor_weights() → Dict[str, float]``
    Seeded weights for the EvaluationEngine, combining base defaults with
    the learned response_bias.

``CognitiveIdentity.get_profile() → IdentityProfile``
    Current identity snapshot.

``get_cognitive_identity() → CognitiveIdentity``
    Process-level singleton.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("CognitiveIdentity")

# ── Persistence path ───────────────────────────────────────────────────────────

_IDENTITY_PATH = os.environ.get(
    "NIBLIT_IDENTITY_PATH",
    "niblit_cognitive_identity.json",
)

_HISTORY_LEN = 100  # rolling quality score buffer size

# ── Base starting weights (before identity bias is applied) ───────────────────
_BASE_WEIGHTS: Dict[str, float] = {
    "memory":    0.20,
    "reasoning": 0.20,
    "goal":      0.10,
    "llm":       0.40,
    "quality":   0.10,
}

# ── Style thresholds ──────────────────────────────────────────────────────────
_STYLE_MAP = {
    "reasoning": "analytical",
    "memory":    "memory-driven",
    "goal":      "goal-focused",
    "llm":       "language-centric",
}


# ─────────────────────────────────────────────────────────────────────────────
# IdentityProfile
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IdentityProfile:
    """A point-in-time snapshot of Niblit's cognitive identity.

    Attributes
    ----------
    decision_style:    Dominant decision style inferred from advisor wins.
    risk_tolerance:    Aggressiveness preference [0.0 = cautious, 1.0 = bold].
    response_bias:     Per-advisor multiplicative bias applied to weights.
    decision_policy:   Active behavioural directives enforced by DecisionEngine:
                       ``exploration_rate`` — probability of boosting a non-winner
                         to inject diversity (epsilon-greedy exploration);
                       ``risk_preference``  — "conservative"|"balanced"|"bold";
                       ``priority_mode``    — "goal_first"|"quality_first"|"balanced".
    total_decisions:   Total evaluation cycles since creation.
    advisor_win_counts: How many times each advisor was chosen.
    quality_history:   Rolling buffer of quality scores.
    last_updated:      UNIX timestamp of most recent update.
    """

    decision_style: str = "balanced"
    risk_tolerance: float = 0.50
    response_bias: Dict[str, float] = field(default_factory=lambda: {
        "memory":    1.0,
        "reasoning": 1.0,
        "goal":      1.0,
        "llm":       1.0,
        "quality":   1.0,
    })
    decision_policy: Dict[str, Any] = field(default_factory=lambda: {
        "exploration_rate": 0.10,
        "risk_preference":  "balanced",
        "priority_mode":    "balanced",
    })
    total_decisions: int = 0
    advisor_win_counts: Dict[str, int] = field(default_factory=dict)
    quality_history: List[float] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["quality_history"] = d["quality_history"][-20:]  # keep last 20 for readability
        return d


# ─────────────────────────────────────────────────────────────────────────────
# CognitiveIdentity
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveIdentity:
    """Persistent cognitive identity manager.

    Tracks which advisors win most, infers a decision style, and maintains
    a response_bias dict that the EvaluationEngine + DecisionEngine use as
    a personality-driven multiplier on top of base weights.

    Args:
        path: JSON file path for persistence.  Defaults to
              ``NIBLIT_IDENTITY_PATH`` env var or
              ``niblit_cognitive_identity.json``.
    """

    def __init__(self, path: str = _IDENTITY_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._profile = self._load()
        log.info(
            "[CognitiveIdentity] Loaded — style=%s risk=%.2f decisions=%d",
            self._profile.decision_style,
            self._profile.risk_tolerance,
            self._profile.total_decisions,
        )

    # ── Primary update API ────────────────────────────────────────────────────

    def update(self, chosen_advisor: str, quality_score: float) -> None:
        """Record a decision outcome and update the identity profile.

        Args:
            chosen_advisor: Name of the advisor whose output was selected.
            quality_score:  RewardModel quality score for the response.
        """
        with self._lock:
            p = self._profile

            # Win count.
            p.advisor_win_counts[chosen_advisor] = (
                p.advisor_win_counts.get(chosen_advisor, 0) + 1
            )
            p.total_decisions += 1

            # Rolling quality history.
            p.quality_history.append(float(quality_score))
            if len(p.quality_history) > _HISTORY_LEN:
                p.quality_history.pop(0)

            # Infer decision_style from dominant advisor.
            if p.advisor_win_counts:
                dominant = max(p.advisor_win_counts, key=p.advisor_win_counts.get)  # type: ignore[arg-type]
                p.decision_style = _STYLE_MAP.get(dominant, "balanced")

            # Update risk_tolerance from rolling quality.
            if len(p.quality_history) >= 5:
                avg_quality = sum(p.quality_history[-20:]) / len(p.quality_history[-20:])
                # High average quality → system is performing well → can be a bit
                # bolder (raise risk_tolerance slightly).  Poor average → be
                # more conservative.
                if avg_quality >= 0.65:
                    p.risk_tolerance = min(1.0, p.risk_tolerance + 0.005)
                elif avg_quality <= 0.35:
                    p.risk_tolerance = max(0.0, p.risk_tolerance - 0.005)

            # Update response_bias.
            self._update_bias(p)

            p.last_updated = time.time()

        self._save()

    def _update_bias(self, p: IdentityProfile) -> None:
        """Recompute per-advisor bias from win-rate statistics.

        Advisors winning more than their fair share get a small boost
        (max ×1.50); losers get a gentle penalty (min ×0.60).
        Changes are gentle (step 0.01 per call) to avoid instability.
        """
        if p.total_decisions < 5:
            return  # not enough data yet

        fair_share = 1.0 / max(len(p.advisor_win_counts), 1)
        for advisor in _BASE_WEIGHTS:
            wins = p.advisor_win_counts.get(advisor, 0)
            win_rate = wins / p.total_decisions
            current_bias = p.response_bias.get(advisor, 1.0)

            if win_rate > fair_share:
                # Winning more than expected → small positive nudge.
                new_bias = min(1.50, current_bias + 0.01)
            else:
                # Underperforming → gentle decay toward 0.60 floor.
                new_bias = max(0.60, current_bias - 0.01)

            p.response_bias[advisor] = round(new_bias, 4)

    # ── Read API ──────────────────────────────────────────────────────────────

    def get_profile(self) -> IdentityProfile:
        """Return a snapshot copy of the current identity profile."""
        with self._lock:
            return IdentityProfile(
                decision_style=self._profile.decision_style,
                risk_tolerance=self._profile.risk_tolerance,
                response_bias=dict(self._profile.response_bias),
                total_decisions=self._profile.total_decisions,
                advisor_win_counts=dict(self._profile.advisor_win_counts),
                quality_history=list(self._profile.quality_history[-20:]),
                last_updated=self._profile.last_updated,
            )

    def get_advisor_weights(self) -> Dict[str, float]:
        """Return base weights multiplied by the current response_bias.

        These seed weights are used by EvaluationEngine so the DecisionEngine
        gets personality-adjusted starting weights on each call.
        """
        with self._lock:
            result = {}
            for advisor, base in _BASE_WEIGHTS.items():
                bias = self._profile.response_bias.get(advisor, 1.0)
                result[advisor] = round(base * bias, 4)
            return result

    def get_advisor_bias(self, advisor: str) -> float:
        """Return the multiplicative bias for a single *advisor* name."""
        with self._lock:
            return self._profile.response_bias.get(advisor, 1.0)

    def get_decision_style(self) -> str:
        """Return the current inferred decision style."""
        with self._lock:
            return self._profile.decision_style

    def get_risk_tolerance(self) -> float:
        """Return the current risk-tolerance in [0.0, 1.0]."""
        with self._lock:
            return self._profile.risk_tolerance

    def get_decision_policy(self) -> Dict[str, Any]:
        """Return a copy of the active decision policy.

        The decision policy is enforced by DecisionEngine inside
        ``decide()`` to apply personality-driven selection behaviour.
        """
        with self._lock:
            return dict(self._profile.decision_policy)

    def update_decision_policy(
        self,
        exploration_nudge: float = 0.0,
        risk_preference: Optional[str] = None,
        priority_mode: Optional[str] = None,
    ) -> None:
        """Update the decision policy directives.

        Args:
            exploration_nudge: Delta applied to ``exploration_rate``
                               (clamped to [0.0, 0.40]).
            risk_preference:   New value for ``risk_preference``; ignored when
                               ``None``.
            priority_mode:     New value for ``priority_mode``; ignored when
                               ``None``.
        """
        with self._lock:
            pol = self._profile.decision_policy
            if exploration_nudge != 0.0:
                pol["exploration_rate"] = round(
                    max(0.0, min(0.40, pol.get("exploration_rate", 0.10) + exploration_nudge)),
                    4,
                )
            if risk_preference is not None:
                pol["risk_preference"] = risk_preference
            if priority_mode is not None:
                pol["priority_mode"] = priority_mode
        self._save()

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status dict for the /status or health endpoints."""
        with self._lock:
            return self._profile.to_dict()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> IdentityProfile:
        """Load the identity profile from disk, or return a fresh default."""
        try:
            if os.path.isfile(self._path):
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Merge persisted decision_policy with defaults so new keys
                # introduced in later versions are always present.
                default_policy: Dict[str, Any] = {
                    "exploration_rate": 0.10,
                    "risk_preference":  "balanced",
                    "priority_mode":    "balanced",
                }
                persisted_policy = data.get("decision_policy", {})
                default_policy.update(persisted_policy)

                p = IdentityProfile(
                    decision_style=data.get("decision_style", "balanced"),
                    risk_tolerance=float(data.get("risk_tolerance", 0.50)),
                    response_bias=data.get("response_bias", {}),
                    decision_policy=default_policy,
                    total_decisions=int(data.get("total_decisions", 0)),
                    advisor_win_counts=data.get("advisor_win_counts", {}),
                    quality_history=list(data.get("quality_history", [])),
                    last_updated=float(data.get("last_updated", time.time())),
                )
                # Ensure bias dict covers all known advisors.
                for advisor in _BASE_WEIGHTS:
                    p.response_bias.setdefault(advisor, 1.0)
                return p
        except Exception as exc:
            log.debug("[CognitiveIdentity] load failed (%s) — starting fresh", exc)
        return IdentityProfile()

    def _save(self) -> None:
        """Persist the current profile to JSON (silent on failure)."""
        try:
            with self._lock:
                data = self._profile.to_dict()
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            log.debug("[CognitiveIdentity] save failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_identity: Optional[CognitiveIdentity] = None
_identity_lock = threading.Lock()


def get_cognitive_identity(path: str = _IDENTITY_PATH) -> CognitiveIdentity:
    """Return the process-level :class:`CognitiveIdentity` singleton."""
    global _identity  # pylint: disable=global-statement
    with _identity_lock:
        if _identity is None:
            _identity = CognitiveIdentity(path=path)
        return _identity


if __name__ == "__main__":
    ident = get_cognitive_identity()
    for i in range(10):
        ident.update("reasoning", 0.7)
    for i in range(5):
        ident.update("llm", 0.55)
    p = ident.get_profile()
    print("Style:", p.decision_style)
    print("Risk tolerance:", p.risk_tolerance)
    print("Biases:", p.response_bias)
    print("Weights:", ident.get_advisor_weights())
