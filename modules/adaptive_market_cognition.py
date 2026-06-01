#!/usr/bin/env python3
"""Adaptive market cognition integrated into the unified runtime."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
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
    return max(0.0, min(1.0, _to_float(value, default)))


def _bucket(value: Any) -> str:
    v = _clamp(value, 0.0)
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
        lowered = f"{event_type} {source} {json.dumps(payload, sort_keys=True, default=str)}".lower()
        if not any(token in lowered for token in _MARKET_EVENT_TOKENS):
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
            experience["risk_state"].update(self._risk_state(payload))
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
        similar = []
        for item in experiences:
            score = 0.0
            haystack = json.dumps(item, default=str).lower()
            overlap = len([token for token in query_tokens if token in haystack])
            score += min(0.4, overlap * 0.08)
            if inferred_regime and item.get("regime") == inferred_regime:
                score += 0.25
            if item.get("volatility_regime") == self._infer_volatility_from_query(normalized_query):
                score += 0.12
            score += _clamp(item.get("confidence_score")) * 0.08
            score += _clamp(item.get("evaluation_score")) * 0.07
            score += (1.0 - _clamp(item.get("risk_score"))) * 0.08
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
            return {
                "experience_count": len(self._experiences),
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
        experience["reflection"] = experience.get("reflection") or self._build_reflection(experience, risk)
        experience["evaluation_score"] = max(
            float(experience.get("evaluation_score", 0.0)),
            _clamp((significance or {}).get("importance_score")),
        )
        if float(experience.get("confidence_score", 0.0)) <= 0.0:
            experience["confidence_score"] = self._derived_confidence(experience, risk)
        experience["dqi_score"] = self._compute_dqi(experience)
        experience["outcome_state"].setdefault("label", self._outcome_label(experience))
        experience["outcome_state"]["confidence_justified"] = bool(
            float(experience.get("evaluation_score", 0.0)) + 0.1 >= float(experience.get("confidence_score", 0.0))
        )
        record = {
            **experience,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(experience.get("timestamp", time.time()))),
            "metaevaluation": {
                "reflection_usefulness": round(min(1.0, len(experience.get("reflection", "").split()) / 50.0), 4),
                "signal_usefulness": round(_clamp(experience.get("evaluation_score")), 4),
                "model_usefulness": round(_clamp(experience.get("confidence_score")), 4),
                "memory_usefulness": round(0.45 + min(0.4, len(experience.get("retrievals", [])) * 0.08), 4),
                "prediction_usefulness": round(max(0.0, 1.0 - risk["regime_uncertainty"]), 4),
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
                    "risk_awareness": round(1.0 - risk["risk_score"], 4),
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
        return {
            "drawdown": _clamp(payload.get("drawdown")),
            "exposure": _clamp(payload.get("exposure")),
            "concentration_risk": _clamp(payload.get("concentration_risk")),
            "volatility": _clamp(payload.get("volatility")),
            "regime_uncertainty": _clamp(payload.get("uncertainty")),
        }

    def _confidence_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "confidence": _clamp(payload.get("confidence") or payload.get("confidence_score")),
            "regime_confidence": _clamp(payload.get("regime_confidence")),
            "provider_confidence": _clamp(payload.get("provider_confidence")),
        }

    def _outcome_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "quality_score": _clamp(payload.get("quality_score")),
            "evaluation_score": _clamp(payload.get("evaluation_score")),
            "status": payload.get("status"),
            "decision": payload.get("decision") or payload.get("action"),
        }

    def _calculate_risk(self, experience: dict[str, Any]) -> dict[str, Any]:
        risk_state = dict(experience.get("risk_state", {}) or {})
        volatility = _clamp(risk_state.get("volatility"))
        drawdown = _clamp(risk_state.get("drawdown"))
        exposure = _clamp(risk_state.get("exposure"))
        concentration = _clamp(risk_state.get("concentration_risk"))
        regime_uncertainty = _clamp(risk_state.get("regime_uncertainty"))
        risk_score = round(
            min(1.0, (volatility * 0.28) + (drawdown * 0.22) + (exposure * 0.18) + (concentration * 0.17) + (regime_uncertainty * 0.15)),
            4,
        )
        return {
            "risk_score": risk_score,
            "volatility_state": _bucket(volatility),
            "drawdown_state": _bucket(drawdown),
            "exposure_state": _bucket(exposure),
            "concentration_state": _bucket(concentration),
            "regime_uncertainty": round(regime_uncertainty, 4),
        }

    def _build_reflection(self, experience: dict[str, Any], risk: dict[str, Any]) -> str:
        worked = "signal coherence held" if _clamp(experience.get("evaluation_score")) >= 0.6 else "evidence base was thin"
        failed = "confidence ran ahead of evidence" if _clamp(experience.get("confidence_score")) > _clamp(experience.get("evaluation_score")) else "risk controls contained uncertainty"
        return (
            f"Market reflection for {experience.get('topic')}: worked={worked}; failed={failed}; "
            f"assumption_correct={experience.get('regime', 'unknown')} regime context mattered; "
            f"assumption_wrong=ignore risk spikes; confidence_calibration={round(_clamp(experience.get('evaluation_score')) - _clamp(experience.get('confidence_score')), 4)}; "
            f"risk_awareness={risk.get('risk_score', 0.0)}."
        )

    def _derived_confidence(self, experience: dict[str, Any], risk: dict[str, Any]) -> float:
        base = 0.35 + (_clamp(experience.get("evaluation_score")) * 0.35) + (len(experience.get("retrievals", [])) * 0.04)
        return round(max(0.0, min(1.0, base - (risk["risk_score"] * 0.3))), 4)

    def _compute_dqi(self, experience: dict[str, Any]) -> float:
        reflection_quality = min(1.0, len(str(experience.get("reflection", "")).split()) / 40.0)
        retrieval_quality = min(1.0, len(experience.get("retrievals", [])) / 6.0)
        risk_awareness = 1.0 - _clamp(experience.get("risk_score"))
        signal_quality = _clamp(experience.get("signal_state", {}).get("signal_strength"))
        confidence_quality = 1.0 - abs(_clamp(experience.get("confidence_score")) - _clamp(experience.get("evaluation_score")))
        evaluation_quality = _clamp(experience.get("evaluation_score"))
        outcome_quality = _clamp(experience.get("outcome_state", {}).get("quality_score") or experience.get("evaluation_score"))
        return round(
            min(
                1.0,
                (signal_quality * 0.14)
                + (confidence_quality * 0.17)
                + (reflection_quality * 0.14)
                + (evaluation_quality * 0.18)
                + (risk_awareness * 0.14)
                + (retrieval_quality * 0.1)
                + (outcome_quality * 0.13),
            ),
            4,
        )

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
        summary = (
            f"market experience topic={record.get('topic')} regime={record.get('regime')} "
            f"volatility={record.get('volatility_regime')} risk={record.get('risk_score')} "
            f"dqi={record.get('dqi_score')} outcome={record.get('outcome_state', {}).get('label')}"
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
                    "coherence_score": record.get("dqi_score", 0.0),
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
                    "coherence_score": record.get("dqi_score", 0.0),
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

    def _aggregate_risk(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            latest = self._risk_history[-1] if self._risk_history else {}
            return {
                "risk_score": _clamp(latest.get("risk_score")),
                "regime_uncertainty": _clamp(latest.get("regime_uncertainty")),
                "volatility_state": latest.get("volatility_state", "unknown"),
            }
        risk_score = sum(_clamp(item.get("risk_score")) for item in items) / max(1, len(items))
        regime_uncertainty = sum(_clamp(item.get("risk_state", {}).get("regime_uncertainty")) for item in items) / max(1, len(items))
        return {
            "risk_score": round(risk_score, 4),
            "regime_uncertainty": round(regime_uncertainty, 4),
            "volatility_state": max((str(item.get("volatility_regime", "unknown")) for item in items), key=len, default="unknown"),
        }

    def _confidence_evolution(self, similar: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
        latest = history[-1] if history else {}
        avg_conf = sum(_clamp(item.get("confidence_score")) for item in similar) / max(1, len(similar)) if similar else _clamp(latest.get("confidence"))
        avg_eval = sum(_clamp(item.get("evaluation_score")) for item in similar) / max(1, len(similar)) if similar else _clamp(latest.get("evaluation"))
        return {
            "confidence": round(avg_conf, 4),
            "evaluation": round(avg_eval, 4),
            "confidence_delta": round(avg_eval - avg_conf, 4),
            "calibration": round(max(0.0, 1.0 - abs(avg_eval - avg_conf)), 4),
        }

    def _dqi_snapshot(self, history: list[dict[str, Any]], similar: list[dict[str, Any]]) -> dict[str, Any]:
        latest = history[-1] if history else {}
        trend = [float(item.get("latest", 0.0) or 0.0) for item in history[-5:]]
        avg_recent = sum(trend) / max(1, len(trend)) if trend else 0.0
        avg_similar = sum(_clamp(item.get("dqi_score")) for item in similar) / max(1, len(similar)) if similar else avg_recent
        return {
            "latest": round(float(latest.get("latest", avg_similar) or avg_similar), 4),
            "recent_average": round(avg_recent, 4),
            "similar_average": round(avg_similar, 4),
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
        return "medium"

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._emit_runtime_event is None:
            return
        try:
            self._emit_runtime_event(event_type, "AdaptiveMarketCognitionLayer", payload)
        except Exception:
            return
