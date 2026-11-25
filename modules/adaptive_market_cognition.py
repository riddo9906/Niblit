#!/usr/bin/env python3
"""Adaptive market cognition integrated into the unified runtime."""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("Niblit.AdaptiveMarketCognition")

_MARKET_EVENT_TOKENS = (
    "market",
    "trade",
    "signal",
    "risk",
    "reflection",
    "evaluation",
    "decision",
    "forecast",
    "regime",
    "confidence",
)
_FINAL_EVENT_HINTS = (
    "market_episode.ingested",
    "trade_reflection.ingested",
    "market_regime.forecast",
    "reflection.complete",
    "response.complete",
    "decision.made",
    "task.completed",
    "task.failed",
)


def _clip(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, default: float = 0.0) -> float:
    # NaN comparisons are always False, so a bare min/max chain turns a non-finite
    # input into 1.0 ("maximally confident"). Treat it as unavailable instead.
    number = _to_float(value, default)
    if not math.isfinite(number):
        number = default
    return max(0.0, min(1.0, number))


def _optional_clamp(value: Any) -> float | None:
    """Clamp a real 0..1 measurement, or return None when there is no usable evidence.

    A missing field, a non-numeric string, a boolean, NaN and infinities all mean
    "not measured" rather than 0.0. Keeping that distinction is what stops an
    absent reading from being reported as a calm ("low") market.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def _bucket(value: Any) -> str:
    # An absent measurement is not a calm market: report "unknown" rather than
    # letting the 0.0 fallback claim a "low" volatility/risk state.
    v = _optional_clamp(value)
    if v is None:
        return "unknown"
    if v >= 0.75:
        return "high"
    if v >= 0.45:
        return "medium"
    return "low"


@dataclass
class MarketRetrievalBundle:
    query: str
    context: str
    similar_markets: list[dict[str, Any]] = field(default_factory=list)
    risk_profile: dict[str, Any] = field(default_factory=dict)
    confidence_evolution: dict[str, Any] = field(default_factory=dict)
    reflections: list[dict[str, Any]] = field(default_factory=list)
    causal_chain: list[dict[str, Any]] = field(default_factory=list)
    memory_hits: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    dqi_snapshot: dict[str, Any] = field(default_factory=dict)
    provider_routing_bias: dict[str, float] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "similar_markets": self.similar_markets,
            "risk_profile": self.risk_profile,
            "confidence_evolution": self.confidence_evolution,
            "reflections": self.reflections,
            "causal_chain": self.causal_chain,
            "memory_hits": self.memory_hits,
            "contradictions": self.contradictions,
            "dqi_snapshot": self.dqi_snapshot,
            "provider_routing_bias": self.provider_routing_bias,
            "telemetry": self.telemetry,
        }


class AdaptiveMarketCognitionLayer:
    """Canonical market experience, retrieval, risk, and quality layer."""

    def __init__(self, emit_runtime_event: Any | None = None) -> None:
        self._emit_runtime_event = emit_runtime_event
        self._lock = threading.RLock()
        self._open: dict[str, dict[str, Any]] = {}
        self._experiences: list[dict[str, Any]] = []
        self._retrieval_history: list[dict[str, Any]] = []
        self._risk_history: list[dict[str, Any]] = []
        self._confidence_history: list[dict[str, Any]] = []
        self._dqi_history: list[dict[str, Any]] = []
        self._reflections: list[dict[str, Any]] = []
        self._causal_chains: list[dict[str, Any]] = []
        self._contradictions: list[dict[str, Any]] = []
        self._memory_hits: list[dict[str, Any]] = []
        self._pending_kb_facts: list[dict[str, Any]] = []
        self._last_bundle: dict[str, Any] = {}
        self._last_query: str = ""
        self._last_regime: str = "unknown"

    def observe_event(
        self,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        significance: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = dict(payload or {})
        # Classify from event_type/source plus targeted payload fields first to
        # avoid JSON-serialising the full payload on every runtime event.
        type_source = f"{event_type} {source}".lower()
        if not any(token in type_source for token in _MARKET_EVENT_TOKENS):
            # Check a small set of relevant payload fields before giving up.
            quick = " ".join(
                str(payload.get(k) or "").lower()
                for k in ("topic", "symbol", "regime", "market_context", "reflection_summary", "decision")
            )
            if not any(token in quick for token in _MARKET_EVENT_TOKENS):
                return None
        trace_id = str(payload.get("trace_id") or f"market:{event_type}:{int(time.time() * 1000)}")
        with self._lock:
            experience = self._open.setdefault(
                trace_id,
                {
                    "trace_id": trace_id,
                    "source": source,
                    "topic": _clip(payload.get("topic") or event_type.replace(".", " "), 140),
                    "symbol": str(payload.get("symbol") or payload.get("ticker") or "unknown"),
                    "regime": str(payload.get("regime") or payload.get("market_regime") or self._last_regime or "unknown"),
                    "volatility_regime": str(payload.get("volatility_regime") or _bucket(payload.get("volatility"))),
                    "signal_state": dict(payload.get("signal_state") or {}),
                    "risk_state": dict(payload.get("risk_state") or {}),
                    "confidence_state": dict(payload.get("confidence_state") or {}),
                    "outcome_state": dict(payload.get("outcome_state") or {}),
                    "market_memory": [],
                    "retrievals": [],
                    "reflection": "",
                    "evaluation_score": 0.0,
                    "confidence_score": 0.0,
                    "risk_score": 0.0,
                    "dqi_score": 0.0,
                    "causal_chain": [],
                    "timestamp": time.time(),
                    "event_type": event_type,
                },
            )
            experience["event_type"] = event_type
            experience["topic"] = _clip(payload.get("topic") or experience["topic"], 140)
            experience["symbol"] = str(payload.get("symbol") or experience["symbol"])
            experience["regime"] = str(payload.get("regime") or payload.get("market_regime") or experience["regime"])
            experience["volatility_regime"] = str(
                payload.get("volatility_regime")
                or experience["volatility_regime"]
                or _bucket(payload.get("volatility"))
            )
            experience["signal_state"].update(self._signal_state(payload))
            # None means "no measurement": never let it overwrite real evidence,
            # including a value supplied through payload["risk_state"].
            for risk_key, risk_value in self._risk_state(payload).items():
                if risk_value is not None:
                    experience["risk_state"][risk_key] = risk_value
            experience["confidence_state"].update(self._confidence_state(payload))
            experience["outcome_state"].update(self._outcome_state(payload))
            if payload.get("retrievals"):
                experience["retrievals"].extend(list(payload.get("retrievals", []))[:6])
                experience["retrievals"] = experience["retrievals"][-8:]
            if payload.get("reflection_summary"):
                experience["reflection"] = _clip(payload.get("reflection_summary"), 280)
            elif "reflection" in event_type:
                experience["reflection"] = _clip(payload.get("summary") or payload.get("error"), 280)
            experience["evaluation_score"] = max(
                _clamp(payload.get("evaluation_score")),
                _clamp(payload.get("quality_score")),
                float(experience.get("evaluation_score", 0.0)),
            )
            experience["confidence_score"] = max(
                _clamp(payload.get("confidence")),
                _clamp(payload.get("confidence_score")),
                _clamp(payload.get("regime_confidence")),
                float(experience.get("confidence_score", 0.0)),
            )
            experience["causal_chain"].append(
                {
                    "event_type": event_type,
                    "source": source,
                    "summary": _clip(
                        payload.get("summary")
                        or payload.get("decision")
                        or payload.get("downstream_effect")
                        or payload.get("reflection_summary")
                        or event_type,
                        180,
                    ),
                }
            )
            experience["causal_chain"] = experience["causal_chain"][-8:]
            if experience["regime"] and experience["regime"] != "unknown":
                self._last_regime = experience["regime"]
        if any(token in event_type for token in _FINAL_EVENT_HINTS):
            return self._finalize_experience(trace_id, significance=significance)
        return None

    def build_market_retrieval_bundle(
        self,
        *,
        query: str,
        core: Any | None,
        runtime_mode: str = "api",
    ) -> MarketRetrievalBundle:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return MarketRetrievalBundle(query="", context="")
        query_tokens = set(re.findall(r"[a-zA-Z]{3,}", normalized_query.lower()))
        inferred_regime = self._infer_regime_from_query(normalized_query)
        with self._lock:
            experiences = list(self._experiences[-120:])
            recent_reflections = list(self._reflections[-20:])
            dqi_history = list(self._dqi_history[-20:])
            confidence_history = list(self._confidence_history[-20:])
        inferred_volatility = self._infer_volatility_from_query(normalized_query)
        similar = []
        for item in experiences:
            score = 0.0
            haystack = json.dumps(item, default=str).lower()
            overlap = len([token for token in query_tokens if token in haystack])
            score += min(0.4, overlap * 0.08)
            if inferred_regime and item.get("regime") == inferred_regime:
                score += 0.25
            # Only an explicit volatility cue in the query may bias ranking; a
            # default guess would hand every "medium" experience a free bonus.
            if inferred_volatility and item.get("volatility_regime") == inferred_volatility:
                score += 0.12
            score += _clamp(item.get("confidence_score")) * 0.08
            score += _clamp(item.get("evaluation_score")) * 0.07
            risk_evidence = dict(item.get("risk_state") or {}).get("risk_evidence")
            if isinstance(risk_evidence, dict):
                # Absent risk evidence is neither safe nor unsafe: give it the neutral
                # midpoint instead of the full "low risk" credit a 0.0 score earns.
                risk_weight = 0.08 if risk_evidence.get("state") in {"complete", "partial"} else 0.04
            else:
                # Record predates risk evidence tracking: keep the previous weighting.
                risk_weight = 0.08
            score += (1.0 - _clamp(item.get("risk_score"))) * risk_weight
            similar.append({**item, "similarity": round(min(1.0, score), 4)})
        similar.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)
        similar = similar[:5]
        memory_hits = self._recall_governed_memories(normalized_query)
        contradictions = self._build_contradictions(similar)
        risk_profile = self._aggregate_risk(similar)
        confidence = self._confidence_evolution(similar, confidence_history)
        dqi_snapshot = self._dqi_snapshot(dqi_history, similar)
        context_lines = [
            "Market intelligence context:",
            f"- inferred_regime: {inferred_regime or self._last_regime or 'unknown'}",
            f"- similar_market_hits: {len(similar)}",
            f"- risk_state: {risk_profile}",
            f"- confidence_evolution: {confidence}",
            f"- decision_quality_index: {dqi_snapshot}",
        ]
        if similar:
            context_lines.append("- similar_markets:")
            for item in similar[:3]:
                context_lines.append(
                    f"  • regime={item.get('regime')} vol={item.get('volatility_regime')} "
                    f"conf={_clamp(item.get('confidence_score')):.2f} risk={_clamp(item.get('risk_score')):.2f} "
                    f"dqi={_clamp(item.get('dqi_score')):.2f} outcome={item.get('outcome_state', {}).get('label', 'unknown')}"
                )
        if recent_reflections:
            context_lines.append("- recent_reflections:")
            for item in recent_reflections[-2:]:
                context_lines.append(f"  • {item.get('summary')}")
        if contradictions:
            context_lines.append("- unresolved_contradictions:")
            for item in contradictions[:3]:
                context_lines.append(f"  • {item.get('summary')}")
        if memory_hits:
            context_lines.append("- governed_memory_hits:")
            for item in memory_hits[:3]:
                context_lines.append(f"  • {item.get('summary')}")
        bundle = MarketRetrievalBundle(
            query=normalized_query,
            context="\n".join(context_lines),
            similar_markets=similar,
            risk_profile=risk_profile,
            confidence_evolution=confidence,
            reflections=recent_reflections[-5:],
            causal_chain=list(self._causal_chains[-6:]),
            memory_hits=memory_hits[:6],
            contradictions=contradictions,
            dqi_snapshot=dqi_snapshot,
            provider_routing_bias={
                "reasoning_boost": round(0.35 + (_clamp(risk_profile.get("regime_uncertainty")) * 0.45), 4),
                "local_boost": 0.15 if runtime_mode in {"cli", "offline"} else 0.05,
                "confidence_penalty": round(min(0.5, _clamp(risk_profile.get("risk_score")) * 0.5), 4),
            },
            telemetry={
                "similar_market_hits": len(similar),
                "memory_hits": len(memory_hits),
                "contradiction_count": len(contradictions),
                "risk_score": risk_profile.get("risk_score", 0.0),
                "confidence_delta": confidence.get("confidence_delta", 0.0),
                "dqi_score": dqi_snapshot.get("latest", 0.0),
            },
        )
        with self._lock:
            self._last_bundle = bundle.to_payload()
            self._last_query = normalized_query
            self._retrieval_history.append(
                {
                    "query": normalized_query,
                    "timestamp": time.time(),
                    "similar_market_hits": len(similar),
                    "memory_hits": len(memory_hits),
                    "risk_score": risk_profile.get("risk_score", 0.0),
                    "dqi_score": dqi_snapshot.get("latest", 0.0),
                }
            )
            self._retrieval_history = self._retrieval_history[-120:]
            self._memory_hits = memory_hits[-40:]
        self._emit("market.intelligence.retrieved", {"query": normalized_query, **bundle.telemetry})
        if core is not None:
            self._flush_knowledge_db(core)
        return bundle

    def update_runtime_outcome(self, *, query: str, response_text: str, error: str | None = None) -> None:
        quality = 0.2 if error else min(1.0, 0.35 + (len((response_text or "").split()) / 180.0))
        summary = {
            "query": _clip(query, 180),
            "quality": round(quality, 4),
            "error": bool(error),
            "response_excerpt": _clip(response_text, 180),
        }
        with self._lock:
            if self._dqi_history:
                self._dqi_history[-1]["outcome_quality"] = round(quality, 4)
            self._causal_chains.append(
                {
                    "query": summary["query"],
                    "quality": summary["quality"],
                    "error": summary["error"],
                    "trace": self._last_bundle.get("query", ""),
                }
            )
            self._causal_chains = self._causal_chains[-60:]
        self._emit("market.intelligence.outcome", summary)

    def status(self, *, core: Any | None = None) -> dict[str, Any]:
        if core is not None:
            self._flush_knowledge_db(core)
        with self._lock:
            # Which scoring contract produced each stored score. A record keeps the
            # policy it was scored under, so an old and a new DQI stay separable.
            policy_versions = Counter(
                str(item.get("dqi_policy") or "unrecorded") for item in self._dqi_history
            )
            return {
                "experience_count": len(self._experiences),
                "dqi_policy": self._DQI_POLICY,
                "dqi_policy_versions": dict(policy_versions),
                "market_cognition_timeline": list(self._experiences[-20:]),
                "similar_market_retrievals": list(self._retrieval_history[-20:]),
                "confidence_evolution": list(self._confidence_history[-20:]),
                "risk_intelligence": list(self._risk_history[-20:]),
                "reflection_summaries": list(self._reflections[-20:]),
                "causal_chains": list(self._causal_chains[-20:]),
                "dqi_scores": list(self._dqi_history[-20:]),
                "market_memory_retrievals": list(self._memory_hits[-20:]),
                "unresolved_market_contradictions": list(self._contradictions[-20:]),
                "last_bundle": dict(self._last_bundle),
            }

    def render_command(self, command: str, *, core: Any | None = None) -> str:
        text = (command or "").strip()
        lower = text.lower()
        if lower in {"market intelligence", "market intelligence status", "market cognition"}:
            return json.dumps(self.status(core=core), indent=2, sort_keys=True)
        mapping = {
            "market intelligence timeline": "market_cognition_timeline",
            "market intelligence retrievals": "similar_market_retrievals",
            "market intelligence risk": "risk_intelligence",
            "market intelligence confidence": "confidence_evolution",
            "market intelligence reflections": "reflection_summaries",
            "market intelligence causality": "causal_chains",
            "market intelligence dqi": "dqi_scores",
            "market intelligence memory": "market_memory_retrievals",
            "market intelligence contradictions": "unresolved_market_contradictions",
        }
        status = self.status(core=core)
        for key, field_name in mapping.items():
            if lower == key:
                return json.dumps(status.get(field_name, []), indent=2, sort_keys=True)
        return ""

    def _finalize_experience(
        self,
        trace_id: str,
        *,
        significance: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            experience = self._open.pop(trace_id, None)
            if experience is None:
                return None
        risk = self._calculate_risk(experience)
        experience["risk_score"] = risk["risk_score"]
        experience["risk_state"] = {**risk, **dict(experience.get("risk_state", {}))}
        experience["evaluation_score"] = max(
            float(experience.get("evaluation_score", 0.0)),
            _clamp((significance or {}).get("importance_score")),
        )
        # Derive confidence before reflecting: a reflection must report the value
        # the episode will actually carry, not the 0.0 placeholder it replaced.
        if float(experience.get("confidence_score", 0.0)) <= 0.0:
            experience["confidence_score"] = self._derived_confidence(experience, risk)
        experience["reflection"] = experience.get("reflection") or self._build_reflection(experience, risk)
        risk_credit, risk_awareness_state, risk_coverage = self._risk_awareness_credit(experience)
        # One breakdown drives the score and the auditable components, so the
        # telemetry cannot drift from the number it explains.
        dqi_breakdown = self._dqi_breakdown(experience, risk_credit=risk_credit)
        experience["dqi_score"] = dqi_breakdown["score"]
        experience["dqi_components"] = dqi_breakdown
        experience["outcome_state"].setdefault("label", self._outcome_label(experience))
        experience["outcome_state"]["confidence_justified"] = bool(
            float(experience.get("evaluation_score", 0.0)) + 0.1 >= float(experience.get("confidence_score", 0.0))
        )
        # An unmeasured uncertainty is not a perfect prediction: report null and
        # say why, instead of the 1.0 that 1 - 0.0 produced.
        missing_risk_inputs = set((risk.get("risk_evidence") or {}).get("missing") or [])
        uncertainty_measured = "regime_uncertainty" not in missing_risk_inputs
        record = {
            **experience,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(experience.get("timestamp", time.time()))),
            "dqi_policy": self._DQI_POLICY,
            "metaevaluation": {
                # Was min(1, words/50): it measured verbosity. Now it is the same
                # structural evidence check the DQI reflection term uses.
                "reflection_usefulness": round(_clamp(dqi_breakdown["terms"]["reasoning"]), 4),
                "reflection_usefulness_basis": "labelled_evidence",
                "reflection_usefulness_checks": dqi_breakdown["reasoning_evidence"]["checks"],
                "signal_usefulness": round(_clamp(experience.get("evaluation_score")), 4),
                "model_usefulness": round(_clamp(experience.get("confidence_score")), 4),
                "memory_usefulness": round(0.45 + min(0.4, len(experience.get("retrievals", [])) * 0.08), 4),
                "prediction_usefulness": (
                    round(max(0.0, 1.0 - risk["regime_uncertainty"]), 4) if uncertainty_measured else None
                ),
                "prediction_usefulness_evidence": "measured" if uncertainty_measured else "unmeasured",
            },
        }
        with self._lock:
            self._experiences.append(record)
            self._experiences = self._experiences[-180:]
            self._reflections.append(
                {
                    "trace_id": record["trace_id"],
                    "topic": record["topic"],
                    "summary": record["reflection"],
                    "risk_score": record["risk_score"],
                }
            )
            self._reflections = self._reflections[-120:]
            self._risk_history.append(
                {
                    "trace_id": record["trace_id"],
                    "topic": record["topic"],
                    **risk,
                }
            )
            self._risk_history = self._risk_history[-120:]
            self._confidence_history.append(
                {
                    "trace_id": record["trace_id"],
                    "topic": record["topic"],
                    "confidence": round(_clamp(record["confidence_score"]), 4),
                    "evaluation": round(_clamp(record["evaluation_score"]), 4),
                    "confidence_delta": round(_clamp(record["evaluation_score"]) - _clamp(record["confidence_score"]), 4),
                }
            )
            self._confidence_history = self._confidence_history[-120:]
            self._dqi_history.append(
                {
                    "trace_id": record["trace_id"],
                    "topic": record["topic"],
                    "latest": round(record["dqi_score"], 4),
                    "dqi_policy": self._DQI_POLICY,
                    "reasoning_quality": round(_clamp(dqi_breakdown["terms"]["reasoning"]), 4),
                    # The credit the DQI actually granted (0.0 when nothing was
                    # measured), not a bare 1 - risk_score that implied full marks.
                    "risk_awareness": round(risk_credit, 4),
                    "risk_awareness_state": risk_awareness_state,
                    "risk_awareness_measured": risk_awareness_state in {"complete", "partial"},
                    "risk_evidence_coverage": round(risk_coverage, 4),
                    "outcome_quality": round(_clamp(record["evaluation_score"]), 4),
                }
            )
            self._dqi_history = self._dqi_history[-120:]
            self._contradictions = self._build_contradictions(self._experiences[-20:])
        self._persist_experience(record)
        self._emit(
            "market.intelligence.finalized",
            {
                "trace_id": record["trace_id"],
                "topic": record["topic"],
                "risk_score": record["risk_score"],
                "dqi_score": record["dqi_score"],
            },
        )
        return record

    def _signal_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "signal": payload.get("signal"),
            "signal_strength": _clamp(payload.get("signal_strength")),
            "trend": payload.get("trend"),
            "scenario_probabilities": payload.get("scenario_probabilities") or {},
        }

    def _risk_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        # None marks a field with no usable evidence; observe_event skips those keys
        # so an unmeasured field is never stored as a measured 0.0 reading.
        return {
            "drawdown": _optional_clamp(payload.get("drawdown")),
            "exposure": _optional_clamp(payload.get("exposure")),
            "concentration_risk": _optional_clamp(payload.get("concentration_risk")),
            "volatility": _optional_clamp(payload.get("volatility")),
            "regime_uncertainty": _optional_clamp(payload.get("uncertainty")),
        }

    def _confidence_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "confidence": _clamp(payload.get("confidence") or payload.get("confidence_score")),
            "regime_confidence": _clamp(payload.get("regime_confidence")),
            "provider_confidence": _clamp(payload.get("provider_confidence")),
        }

    def _outcome_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = {
            "quality_score": _clamp(payload.get("quality_score")),
            "evaluation_score": _clamp(payload.get("evaluation_score")),
            "status": payload.get("status"),
            "decision": payload.get("decision") or payload.get("action"),
        }
        # An evaluation score is a judgement, not a verification. Only an outcome
        # the caller actually supplied may later be described as verified/realised.
        if payload.get("outcome_verified") is not None:
            state["verified"] = bool(payload.get("outcome_verified"))
        if payload.get("realized_outcome") is not None:
            state["realized"] = payload.get("realized_outcome")
        return state

    # Convex weights over the five risk inputs; they sum to 1.0.
    _RISK_WEIGHTS = {
        "volatility": 0.28,
        "drawdown": 0.22,
        "exposure": 0.18,
        "concentration_risk": 0.17,
        "regime_uncertainty": 0.15,
    }

    # Stamped on records and persisted payloads so a reader can tell which
    # decision-quality contract produced a score. v1 scored the reflection term as
    # min(1, words/40), so longer output raised DQI; v2 scores labelled evidence
    # instead. Legacy payloads keep their v1 stamp and are never rescored.
    _DQI_POLICY = "evidence-aware-v2"

    def _calculate_risk(self, experience: dict[str, Any]) -> dict[str, Any]:
        risk_state = dict(experience.get("risk_state", {}) or {})
        measured = {name: _optional_clamp(risk_state.get(name)) for name in self._RISK_WEIGHTS}
        missing = [name for name in self._RISK_WEIGHTS if measured[name] is None]
        available_weight = sum(weight for name, weight in self._RISK_WEIGHTS.items() if measured[name] is not None)
        if available_weight > 0.0:
            weighted = sum(
                measured[name] * weight
                for name, weight in self._RISK_WEIGHTS.items()
                if measured[name] is not None
            )
            # Renormalise over measured inputs only: a missing field must not count
            # as zero risk. With complete evidence this is the original formula.
            risk_score = round(min(1.0, weighted / available_weight), 4)
            evidence_state = "complete" if not missing else "partial"
        else:
            # Nothing measured: keep risk_score a float for existing numeric consumers,
            # but record that the score carries no evidence.
            risk_score = 0.0
            evidence_state = "missing"
        return {
            "risk_score": risk_score,
            "volatility_state": _bucket(risk_state.get("volatility")),
            "drawdown_state": _bucket(risk_state.get("drawdown")),
            "exposure_state": _bucket(risk_state.get("exposure")),
            "concentration_state": _bucket(risk_state.get("concentration_risk")),
            "regime_uncertainty": round(measured["regime_uncertainty"] or 0.0, 4),
            "risk_evidence": {"state": evidence_state, "missing": missing},
        }

    def _risk_evidence_position(self, risk: dict[str, Any]) -> tuple[str, int | None]:
        """Return the evidence state and how many risk inputs it actually covers."""
        total = len(self._RISK_WEIGHTS)
        evidence = risk.get("risk_evidence") if isinstance(risk.get("risk_evidence"), dict) else {}
        state = str(evidence.get("state") or "unrecorded")
        if state == "missing":
            return state, 0
        if state == "complete":
            return state, total
        if state == "partial":
            missing = [name for name in (evidence.get("missing") or []) if name in self._RISK_WEIGHTS]
            return state, max(0, total - len(missing))
        # A record from before risk-evidence tracking: coverage is unknown.
        return state, None

    def _risk_evidence_label(self, risk: dict[str, Any]) -> str:
        """Describe a risk score together with the evidence it rests on.

        A record with no risk evidence still stores ``risk_score = 0.0`` for the
        numeric contract. Printed alone that reads as a measured calm market, so
        the label keeps measured zero, partial and unmeasured cases distinct.
        """
        total = len(self._RISK_WEIGHTS)
        state, measured = self._risk_evidence_position(risk)
        score = _optional_clamp(risk.get("risk_score"))
        if state == "missing" or score is None:
            # Keep the same word count as the measured labels: the reflection text
            # feeds a length-based DQI term, so wording must not shift the score.
            return f"unmeasured (0/{total} risk inputs measured)"
        if state == "complete":
            return f"{score:.4f} (measured, {total}/{total} risk inputs)"
        if state == "partial":
            return f"{score:.4f} (partial, {measured}/{total} risk inputs)"
        return f"{score:.4f} (evidence state unrecorded)"

    @staticmethod
    def _verified_outcome_label(experience: dict[str, Any]) -> str:
        outcome = dict(experience.get("outcome_state") or {})
        realized = outcome.get("realized")
        if realized is not None:
            kind = "verified" if outcome.get("verified") else "recorded, verification unmarked"
            return f"{realized} ({kind})"
        if outcome.get("verified"):
            return "marked verified by caller (no realised result recorded)"
        return "none recorded (no realised result attached)"

    # Labels a reflection uses to separate observation, inference, prediction,
    # verified outcome and the risk-evidence statement it rests on.
    _REFLECTION_TAGS = ("observed", "inferred", "predicted", "verified_outcome", "risk")

    # One check per question the DQI reasoning term is meant to answer.
    _REASONING_CHECKS = (
        "observations_grounded",
        "predictions_separated",
        "outcomes_not_conflated",
        "assumptions_scoped",
        "risk_evidence_reported",
        "decision_evaluated",
    )

    _NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

    def _reflection_sections(self, text: Any) -> dict[str, str]:
        """Split a reflection into its labelled sections.

        Only the first occurrence of a label is kept and a section ends at the next
        label, so repeating a claim or padding it with prose cannot add evidence.
        """
        raw = str(text or "")
        markers = sorted(
            (index, tag)
            for tag in self._REFLECTION_TAGS
            for index in (raw.find(f"{tag}="),)
            if index >= 0
        )
        sections: dict[str, str] = {}
        for position, (index, tag) in enumerate(markers):
            start = index + len(tag) + 1
            end = markers[position + 1][0] if position + 1 < len(markers) else len(raw)
            sections.setdefault(tag, raw[start:end].strip(" [];\t\r\n"))
        return sections

    @classmethod
    def _mentions_value(cls, section: str, values: list[float]) -> bool:
        """True when the section reports one of the supplied recorded values."""
        numbers = [float(token) for token in cls._NUMBER_RE.findall(str(section or ""))]
        return any(abs(number - value) <= 1e-4 for number in numbers for value in values)

    def _reasoning_quality(
        self, experience: dict[str, Any], risk: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
        """Score what a reflection asserts, not how much text it contains.

        Every check asks a question the decision-quality index is supposed to
        answer: does the text report recorded observations, keep predictions apart
        from verified outcomes, scope its assumptions to the available evidence,
        state the risk evidence honestly and evaluate the recorded decision?
        Duplicate or padded text cannot pass a check it did not already pass, and
        text that asserts more than the episode supports fails its check.
        """
        text = str(experience.get("reflection") or "")
        sections = self._reflection_sections(text)
        evaluation = _clamp(experience.get("evaluation_score"))
        confidence = _clamp(experience.get("confidence_score"))
        evidence_state, measured_inputs = self._risk_evidence_position(risk)
        retrievals = len(experience.get("retrievals") or [])
        scenarios = experience.get("signal_state", {}).get("scenario_probabilities") or {}
        if not isinstance(scenarios, dict):
            scenarios = {}
        outcome = dict(experience.get("outcome_state") or {})
        regime = str(experience.get("regime") or "").strip().lower()
        topic = str(experience.get("topic") or "").strip()
        checks: dict[str, bool] = {}

        # 1. An observation must be a value the episode actually recorded.
        observed_section = sections.get("observed", "")
        observed_values = [evaluation, confidence, float(retrievals)]
        if measured_inputs is not None:
            observed_values.append(float(measured_inputs))
        checks["observations_grounded"] = bool(observed_section) and self._mentions_value(
            observed_section, observed_values
        )

        # 2. A forecast is only supported when the episode recorded one; inventing
        #    a probability is not evidence of predictive quality.
        predicted_section = sections.get("predicted", "")
        if scenarios:
            recorded_names = [str(name) for name in list(scenarios)[:3]]
            checks["predictions_separated"] = bool(predicted_section) and all(
                name in predicted_section for name in recorded_names
            )
        else:
            checks["predictions_separated"] = "none" in predicted_section.lower()

        # 3. "Verified" describes the record, not the prose: a reflection may only
        #    claim verification the episode actually carries.
        verified_section = sections.get("verified_outcome", "")
        verified_lower = verified_section.lower()
        realized = outcome.get("realized")
        if realized is not None:
            checks["outcomes_not_conflated"] = (
                str(realized) in verified_section
                and ("verified" in verified_lower) == bool(outcome.get("verified"))
            )
        elif outcome.get("verified"):
            checks["outcomes_not_conflated"] = "verified" in verified_lower
        else:
            checks["outcomes_not_conflated"] = (
                bool(verified_section) and "none" in verified_lower and "verified" not in verified_lower
            )

        # 4. Assumptions must be labelled and may not invent a regime.
        inferred_section = sections.get("inferred", "")
        inferred_lower = inferred_section.lower()
        scoped = any(
            marker in inferred_lower
            for marker in ("assumed", "unverified", "not directly measured", "inferred")
        )
        named_regimes = [name for name in ("bull", "bear", "volatile", "sideways") if name in inferred_lower]
        checks["assumptions_scoped"] = (
            bool(inferred_section) and scoped and all(name == regime for name in named_regimes)
        )

        # 5. The risk wording must match the evidence that exists. Missing evidence
        #    may never be reported as measured.
        risk_section = sections.get("risk", "").lower()
        if evidence_state == "missing":
            checks["risk_evidence_reported"] = risk_section.startswith("unmeasured")
        elif evidence_state == "partial":
            checks["risk_evidence_reported"] = "partial" in risk_section
        elif evidence_state == "complete":
            checks["risk_evidence_reported"] = (
                "measured" in risk_section
                and "unmeasured" not in risk_section
                and "partial" not in risk_section
            )
        else:
            checks["risk_evidence_reported"] = "unrecorded" in risk_section

        # 6. The reflection must say which decision it evaluated and how it scored.
        checks["decision_evaluated"] = (
            bool(topic)
            and topic.lower() in text.lower()
            and self._mentions_value(f"{observed_section} {verified_section}", [evaluation])
        )

        passed = sum(1 for name in self._REASONING_CHECKS if checks.get(name))
        score = round(passed / len(self._REASONING_CHECKS), 4)
        return score, {
            "score": score,
            "checks": {name: bool(checks.get(name)) for name in self._REASONING_CHECKS},
            "checks_passed": passed,
            "checks_total": len(self._REASONING_CHECKS),
            "risk_evidence_state": evidence_state,
            "basis": "labelled_evidence",
        }

    def _build_reflection(self, experience: dict[str, Any], risk: dict[str, Any]) -> str:
        """Compose a reflection that labels what kind of statement each part makes.

        Only values carried by the episode are reported as observed; calibration
        and regime context are inferences; an evaluation score is never upgraded
        to a verified outcome, and no prediction is invented for an episode that
        carries none.
        """
        evaluation = _clamp(experience.get("evaluation_score"))
        confidence = _clamp(experience.get("confidence_score"))
        gap = round(confidence - evaluation, 4)
        evidence_state, measured_inputs = self._risk_evidence_position(risk)
        measured_text = "unknown" if measured_inputs is None else str(measured_inputs)
        observed = (
            f"evaluation_score={round(evaluation, 4)}; confidence_score={round(confidence, 4)}; "
            f"risk_inputs_measured={measured_text}/{len(self._RISK_WEIGHTS)} ({evidence_state}); "
            f"retrievals={len(experience.get('retrievals', []))}"
        )
        inferred = (
            "signal_coherence=not directly measured; "
            f"confidence_calibration={gap:+.4f} "
            f"({'confidence ahead of recorded evaluation' if gap > 0.1 else 'confidence within recorded evaluation'}); "
            f"regime_context={experience.get('regime', 'unknown')} (assumed from event, unverified)"
        )
        scenarios = experience.get("signal_state", {}).get("scenario_probabilities") or {}
        if isinstance(scenarios, dict) and scenarios:
            listed = ", ".join(
                f"{name}={_clamp(value):.4f}" for name, value in list(scenarios.items())[:3]
            )
            predicted = f"p({listed}) (recorded forecast, unverified)"
        else:
            predicted = "none recorded for this episode"
        return (
            f"Market reflection for {experience.get('topic')}: "
            f"observed=[{observed}]; inferred=[{inferred}]; "
            f"predicted=[{predicted}]; "
            f"verified_outcome=[{self._verified_outcome_label(experience)}]; "
            f"risk={self._risk_evidence_label(risk)}."
        )

    def _derived_confidence(self, experience: dict[str, Any], risk: dict[str, Any]) -> float:
        """Derive confidence from recorded evidence, charging explicit gaps.

        A measured risk score still lowers confidence. When risk inputs are
        absent, the stored 0.0 is a compatibility placeholder rather than a calm
        market, so the unmeasured evidence coverage carries a fixed penalty. An
        episode with no risk evidence is therefore never more confident than one
        that measured the same risk and found it low.

        A record from before risk-evidence tracking has no coverage information
        and keeps the previous behaviour instead of being penalised retroactively.
        """
        base = 0.35 + (_clamp(experience.get("evaluation_score")) * 0.35) + (len(experience.get("retrievals", [])) * 0.04)
        evidence = risk.get("risk_evidence") if isinstance(risk.get("risk_evidence"), dict) else {}
        coverage = self._risk_evidence_coverage(evidence)
        risk_penalty = 0.0 if evidence.get("state") == "missing" else (0.3 * _clamp(risk.get("risk_score")))
        evidence_penalty = 0.12 * (1.0 - coverage)
        return round(max(0.0, min(1.0, base - risk_penalty - evidence_penalty)), 4)

    # Documented decision-quality weights (they sum to 1.0). This is a composite
    # process-quality index, not a calibrated probability. The "reasoning" term
    # used to be called "reflection" and scored text length; it now scores the
    # evidence the reflection labels (see _reasoning_quality).
    _DQI_WEIGHTS = {
        "signal": 0.14,
        "confidence": 0.17,
        "reasoning": 0.14,
        "evaluation": 0.18,
        "risk_awareness": 0.14,
        "retrieval": 0.10,
        "outcome": 0.13,
    }

    def _risk_evidence_coverage(self, evidence: Any) -> float:
        """Weighted share of the documented risk inputs that carry a measurement.

        A legacy record with no ``risk_evidence`` keeps full coverage so the
        historical confidence and DQI behaviour is unchanged.
        """
        if not isinstance(evidence, dict):
            return 1.0
        state = evidence.get("state")
        if state == "complete":
            return 1.0
        if state != "partial":
            return 0.0
        missing_names = evidence.get("missing")
        missing_set = (
            set(missing_names) if isinstance(missing_names, (list, tuple, set)) else set(self._RISK_WEIGHTS)
        )
        return max(
            0.0,
            min(1.0, sum(weight for name, weight in self._RISK_WEIGHTS.items() if name not in missing_set)),
        )

    def _risk_awareness_credit(self, experience: dict[str, Any]) -> tuple[float, str, float]:
        """Credit the DQI risk term actually earns, with its evidence state.

        The documented term is (1 - risk_score) * 0.14. Credit is granted only for
        risk inputs that were actually measured: no measurements earn 0.0 rather
        than a fabricated 1.0, and partial evidence earns a proportional share so
        it is not equated with complete evidence. A record that predates
        ``risk_evidence`` keeps the previous full-weight behaviour.
        """
        awareness = 1.0 - _clamp(experience.get("risk_score"))
        evidence = dict(experience.get("risk_state") or {}).get("risk_evidence")
        state = evidence.get("state") if isinstance(evidence, dict) else None
        if state not in {"complete", "partial", "missing"}:
            return awareness * self._DQI_WEIGHTS["risk_awareness"], "unrecorded", 1.0
        if state == "missing":
            return 0.0, "missing", 0.0
        if state == "complete":
            coverage = 1.0
        else:
            missing_names = evidence.get("missing")
            missing_set = (
                set(missing_names)
                if isinstance(missing_names, (list, tuple, set))
                else set(self._RISK_WEIGHTS)
            )
            coverage = max(
                0.0,
                min(1.0, sum(w for name, w in self._RISK_WEIGHTS.items() if name not in missing_set)),
            )
        return awareness * self._DQI_WEIGHTS["risk_awareness"] * coverage, state, coverage

    def _dqi_breakdown(
        self,
        experience: dict[str, Any],
        *,
        risk_credit: float | None = None,
        reasoning_quality: float | None = None,
        reasoning_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the DQI and the terms it is made of.

        The reasoning term was ``min(1, words / 40)``, which let a padded
        reflection buy quality credit. It is now a structural evidence check, so
        equivalent evidence scores the same however many words carry it.
        """
        if reasoning_quality is None or reasoning_evidence is None:
            computed_quality, computed_evidence = self._reasoning_quality(
                experience, dict(experience.get("risk_state") or {})
            )
            if reasoning_quality is None:
                reasoning_quality = computed_quality
            if reasoning_evidence is None:
                reasoning_evidence = computed_evidence
        reasoning_quality = _clamp(reasoning_quality)
        retrieval_quality = min(1.0, len(experience.get("retrievals", [])) / 6.0)
        if risk_credit is None:
            risk_credit, _state, _coverage = self._risk_awareness_credit(experience)
        risk_credit = _clamp(risk_credit)
        signal_quality = _clamp(experience.get("signal_state", {}).get("signal_strength"))
        confidence_quality = 1.0 - abs(
            _clamp(experience.get("confidence_score")) - _clamp(experience.get("evaluation_score"))
        )
        evaluation_quality = _clamp(experience.get("evaluation_score"))
        outcome_quality = _clamp(
            experience.get("outcome_state", {}).get("quality_score") or experience.get("evaluation_score")
        )
        score = round(
            min(
                1.0,
                (signal_quality * self._DQI_WEIGHTS["signal"])
                + (confidence_quality * self._DQI_WEIGHTS["confidence"])
                + (reasoning_quality * self._DQI_WEIGHTS["reasoning"])
                + (evaluation_quality * self._DQI_WEIGHTS["evaluation"])
                + risk_credit
                + (retrieval_quality * self._DQI_WEIGHTS["retrieval"])
                + (outcome_quality * self._DQI_WEIGHTS["outcome"]),
            ),
            4,
        )
        return {
            "score": score,
            "policy": self._DQI_POLICY,
            "terms": {
                "signal": round(signal_quality, 4),
                "confidence": round(confidence_quality, 4),
                "reasoning": round(reasoning_quality, 4),
                "evaluation": round(evaluation_quality, 4),
                "risk_awareness": round(risk_credit, 4),
                "retrieval": round(retrieval_quality, 4),
                "outcome": round(outcome_quality, 4),
            },
            "weights": dict(self._DQI_WEIGHTS),
            "reasoning_evidence": reasoning_evidence,
        }

    def _compute_dqi(
        self,
        experience: dict[str, Any],
        *,
        risk_credit: float | None = None,
        reasoning_quality: float | None = None,
    ) -> float:
        """Return the decision-quality score; see :meth:`_dqi_breakdown`."""
        return self._dqi_breakdown(
            experience, risk_credit=risk_credit, reasoning_quality=reasoning_quality
        )["score"]

    def _outcome_label(self, experience: dict[str, Any]) -> str:
        score = _clamp(experience.get("evaluation_score"))
        if score >= 0.7:
            return "successful"
        if score <= 0.35:
            return "failed"
        return "mixed"

    def _recall_governed_memories(self, query: str) -> list[dict[str, Any]]:
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            hits = get_governed_qdrant_memory_cluster().recall(
                query,
                top_k=6,
                memory_types=["episodic_memory", "reflection_memory", "execution_memory"],
            )
        except Exception:
            return []
        out = []
        for item in hits:
            payload = dict(item.get("payload") or {})
            out.append(
                {
                    "memory_id": item.get("memory_id"),
                    "score": item.get("score"),
                    "summary": _clip(payload.get("summary") or payload.get("content_text") or payload.get("reflection_summary"), 180),
                    "trace_id": (payload.get("replay_metadata") or {}).get("trace_id"),
                }
            )
        return out

    def _persist_experience(self, record: dict[str, Any]) -> None:
        # DQI measures decision-process quality, not temporal coherence. Keep
        # an explicitly measured coherence value authoritative; for older
        # unmeasured market episodes, apply the constitutional admissibility
        # floor rather than interpreting a low DQI as unstable memory.
        coherence_value = record.get("coherence_score")
        coherence_score = (
            _clamp(coherence_value)
            if coherence_value is not None
            else max(0.3, _clamp(record.get("dqi_score")))
        )
        risk_evidence = dict(record.get("risk_state") or {}).get("risk_evidence")
        risk_evidence_state = (
            str(risk_evidence.get("state"))
            if isinstance(risk_evidence, dict) and risk_evidence.get("state")
            else "unrecorded"
        )
        # A record keeps the policy it was scored under. A legacy record persisted by
        # this code must not be re-stamped as v2, which would present an old
        # word-count score as a current evidence-based one.
        record_policy = str(record.get("dqi_policy") or self._DQI_POLICY)
        reasoning_quality = ((record.get("dqi_components") or {}).get("terms") or {}).get("reasoning")
        # A missing-evidence record still stores risk_score=0.0 for the numeric
        # contract, so the summary prints what the number is based on instead of
        # letting a bare 0.0 read as a measured calm market.
        summary = (
            f"market experience topic={record.get('topic')} regime={record.get('regime')} "
            f"volatility={record.get('volatility_regime')} "
            f"risk={self._risk_evidence_label({'risk_score': record.get('risk_score'), 'risk_evidence': risk_evidence})} "
            f"dqi={record.get('dqi_score')} dqi_policy={record_policy} "
            f"risk_evidence={risk_evidence_state} outcome={record.get('outcome_state', {}).get('label')}"
        )
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            cluster = get_governed_qdrant_memory_cluster()
            cluster.write_memory(
                summary,
                memory_type="episodic_memory",
                payload={
                    "summary": summary,
                    "reflection_summary": record.get("reflection", ""),
                    "coherence_score": coherence_score,
                    "dqi_score": record.get("dqi_score", 0.0),
                    "dqi_policy": record_policy,
                    "dqi_reasoning_quality": reasoning_quality,
                    "risk_evidence_state": risk_evidence_state,
                    "risk_score_measured": risk_evidence_state in {"complete", "partial"},
                    "advisor_lineage": [step.get("event_type") for step in record.get("causal_chain", [])],
                    "replay_metadata": {
                        "trace_id": record.get("trace_id", ""),
                        "causal_references": [step.get("summary") for step in record.get("causal_chain", [])],
                    },
                    "market_context": {
                        "regime": record.get("regime"),
                        "volatility_regime": record.get("volatility_regime"),
                        "risk_state": record.get("risk_state"),
                    },
                },
            )
            cluster.write_memory(
                record.get("reflection", summary),
                memory_type="reflection_memory",
                payload={
                    "summary": record.get("reflection", summary),
                    "reflection_summary": record.get("reflection", summary),
                    "coherence_score": coherence_score,
                    "dqi_score": record.get("dqi_score", 0.0),
                    "dqi_policy": record_policy,
                    "dqi_reasoning_quality": reasoning_quality,
                    "risk_evidence_state": risk_evidence_state,
                    "risk_score_measured": risk_evidence_state in {"complete", "partial"},
                    "advisor_lineage": [record.get("regime"), record.get("volatility_regime")],
                    "replay_metadata": {
                        "trace_id": record.get("trace_id", ""),
                        "causal_references": [step.get("summary") for step in record.get("causal_chain", [])],
                    },
                },
            )
        except Exception as exc:
            log.debug("adaptive market cognition persistence degraded: %s", exc)
        with self._lock:
            self._pending_kb_facts.append(
                {
                    "key": f"market-experience:{record.get('trace_id')}",
                    "value": summary,
                    "tags": [
                        "market_cognition",
                        str(record.get("regime", "unknown")),
                        str(record.get("volatility_regime", "unknown")),
                        str(record.get("symbol", "unknown")),
                    ],
                }
            )
            self._pending_kb_facts = self._pending_kb_facts[-120:]

    def _flush_knowledge_db(self, core: Any) -> None:
        db = getattr(core, "db", None)
        if db is None or not hasattr(db, "add_fact"):
            log.debug("adaptive market cognition knowledge DB flush skipped: add_fact unavailable")
            return
        with self._lock:
            pending = list(self._pending_kb_facts)
            self._pending_kb_facts.clear()
        for item in pending:
            try:
                db.add_fact(item["key"], item["value"], tags=item["tags"])
            except Exception:
                continue

    def _build_contradictions(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contradictions = []
        for index, left in enumerate(items):
            left_outcome = str(left.get("outcome_state", {}).get("label", ""))
            for right in items[index + 1 :]:
                if left.get("regime") != right.get("regime"):
                    continue
                if left_outcome and right.get("outcome_state", {}).get("label") and left_outcome != right.get("outcome_state", {}).get("label"):
                    contradictions.append(
                        {
                            "regime": left.get("regime"),
                            "summary": f"{left.get('regime')} regime produced mixed outcomes across similar experiences",
                            "left_trace_id": left.get("trace_id"),
                            "right_trace_id": right.get("trace_id"),
                        }
                    )
        return contradictions[:20]

    @staticmethod
    def _aggregate_evidence_state(states: list[str]) -> str:
        if not states or all(state in {"unknown", "missing"} for state in states):
            return "unknown"
        if all(state == "complete" for state in states):
            return "complete"
        return "partial"

    def _aggregate_risk(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            latest = self._risk_history[-1] if self._risk_history else {}
            return {
                "risk_score": _clamp(latest.get("risk_score")),
                "regime_uncertainty": _clamp(latest.get("regime_uncertainty")),
                "volatility_state": latest.get("volatility_state", "unknown"),
                "risk_evidence_state": (latest.get("risk_evidence") or {}).get("state", "unknown"),
            }
        evidence_states = [
            str((item.get("risk_state") or {}).get("risk_evidence", {}).get("state", "unknown")) for item in items
        ]
        # Only records that actually measured risk may shape the average. A record
        # with missing evidence stores a placeholder 0.0, which would otherwise
        # drag the profile towards calm instead of leaving it undetermined.
        measured_items = [
            item
            for item in items
            if not (
                isinstance((item.get("risk_state") or {}).get("risk_evidence"), dict)
                and (item.get("risk_state") or {}).get("risk_evidence", {}).get("state") == "missing"
            )
        ]
        risk_score = (
            sum(_clamp(item.get("risk_score")) for item in measured_items) / len(measured_items)
            if measured_items
            else 0.0
        )
        uncertainties = [
            value
            for value in (
                _optional_clamp((item.get("risk_state") or {}).get("regime_uncertainty"))
                for item in measured_items
            )
            if value is not None
        ]
        regime_uncertainty = sum(uncertainties) / len(uncertainties) if uncertainties else 0.0
        volatility_counter = Counter(str(item.get("volatility_regime", "unknown")) for item in measured_items)
        return {
            "risk_score": round(risk_score, 4),
            "regime_uncertainty": round(regime_uncertainty, 4),
            "volatility_state": volatility_counter.most_common(1)[0][0] if volatility_counter else "unknown",
            "risk_evidence_state": self._aggregate_evidence_state(evidence_states),
            "risk_inputs_measured": len(measured_items),
            "experiences_considered": len(items),
        }

    def _confidence_evolution(self, similar: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
        latest = history[-1] if history else {}
        if similar:
            avg_conf = sum(_clamp(item.get("confidence_score")) for item in similar) / max(1, len(similar))
            avg_eval = sum(_clamp(item.get("evaluation_score")) for item in similar) / max(1, len(similar))
        else:
            avg_conf = _clamp(latest.get("confidence"))
            avg_eval = _clamp(latest.get("evaluation"))
        return {
            "confidence": round(avg_conf, 4),
            "evaluation": round(avg_eval, 4),
            "confidence_delta": round(avg_eval - avg_conf, 4),
            "calibration": round(max(0.0, 1.0 - abs(avg_eval - avg_conf)), 4),
        }

    def _dqi_snapshot(self, history: list[dict[str, Any]], similar: list[dict[str, Any]]) -> dict[str, Any]:
        latest = dict(history[-1]) if history else {}
        policy_counts = Counter(str(item.get("dqi_policy") or "unrecorded") for item in history)
        similar_policy_counts = Counter(str(item.get("dqi_policy") or "unrecorded") for item in similar)
        # Only scores from the current policy are averaged. v1 rewarded reflection
        # length, so pooling it with v2 would silently rescore history and make the
        # snapshot depend on how old a record is. A store with no current-policy
        # record falls back to the unfiltered values, and the counts below say so.
        current = [item for item in history if item.get("dqi_policy") == self._DQI_POLICY]
        trend = [_clamp(item.get("latest")) for item in (current or history)[-5:]]
        avg_recent = sum(trend) / len(trend) if trend else 0.0
        similar_current = [item for item in similar if item.get("dqi_policy") == self._DQI_POLICY]
        if similar_current:
            similar_source = similar_current
        elif current:
            # The store has current-policy scores, so a legacy similar record is not
            # comparable and cannot enter the average; fall back to the current
            # recent average instead of mixing contracts.
            similar_source = []
        else:
            similar_source = list(similar)
        avg_similar = (
            sum(_clamp(item.get("dqi_score")) for item in similar_source) / len(similar_source)
            if similar_source
            else avg_recent
        )
        # A recorded 0.0 is a real score, not a missing value: only fall back to the
        # average when no history entry exists at all.
        latest_value = latest.get("latest")
        if latest_value is None:
            latest_value = avg_similar
        return {
            "latest": round(_clamp(latest_value), 4),
            "recent_average": round(avg_recent, 4),
            "similar_average": round(avg_similar, 4),
            "policy": self._DQI_POLICY,
            "latest_policy": (str(latest.get("dqi_policy") or "unrecorded") if latest else None),
            "latest_is_current_policy": (
                (str(latest.get("dqi_policy") or "unrecorded") == self._DQI_POLICY) if latest else None
            ),
            "policies": dict(policy_counts) or {"unrecorded": 0},
            "similar_policies": dict(similar_policy_counts),
            "legacy_records_excluded": sum(
                count for policy, count in policy_counts.items() if policy != self._DQI_POLICY
            ),
            "legacy_similar_excluded": sum(
                count for policy, count in similar_policy_counts.items() if policy != self._DQI_POLICY
            ),
            "latest_risk_awareness_state": str(latest.get("risk_awareness_state") or "unrecorded"),
            "latest_risk_awareness_measured": bool(latest.get("risk_awareness_measured")),
        }

    def _infer_regime_from_query(self, query: str) -> str:
        lower = query.lower()
        if "bear" in lower:
            return "bear"
        if "bull" in lower:
            return "bull"
        if "volatile" in lower or "volatility" in lower:
            return "volatile"
        if "range" in lower or "sideways" in lower:
            return "sideways"
        return ""

    def _infer_volatility_from_query(self, query: str) -> str:
        lower = query.lower()
        if "high volatility" in lower or "volatility spike" in lower:
            return "high"
        if "low volatility" in lower:
            return "low"
        return ""

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._emit_runtime_event is None:
            return
        try:
            self._emit_runtime_event(event_type, "AdaptiveMarketCognitionLayer", payload)
        except Exception:
            return
