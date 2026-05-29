#!/usr/bin/env python3
"""Canonical cognitive episode runtime primitives for governed cognition flow."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("Niblit.CognitiveEpisode")


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _clip(text: Any, limit: int = 240) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class CognitiveEpisode:
    trace_id: str
    runtime_id: str
    cognition_id: str
    episode_id: str
    topic: str
    source_events: list[dict[str, Any]] = field(default_factory=list)
    retrievals: list[dict[str, Any]] = field(default_factory=list)
    provider_used: str = "unknown"
    runtime_mode: str = "api"
    reasoning_steps: list[str] = field(default_factory=list)
    reflection: str = ""
    evaluation_score: float = 0.0
    memory_written: bool = False
    downstream_effect: str = ""
    confidence_score: float = 0.0
    anomaly_score: float = 0.0
    novelty_score: float = 0.0
    market_context: dict[str, Any] = field(default_factory=dict)
    telemetry_summary: dict[str, Any] = field(default_factory=dict)
    timestamp_lineage: dict[str, Any] = field(default_factory=dict)
    significance: dict[str, Any] = field(default_factory=dict)
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    governance_flags: list[str] = field(default_factory=list)
    dataset_candidates: list[dict[str, Any]] = field(default_factory=list)
    causal_influences: dict[str, float] = field(default_factory=dict)
    metaevaluation: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeSignificanceEngine:
    """Convert noisy runtime events into ranked cognitive signal."""

    _HIGH_VALUE_TOKENS = (
        "cognition",
        "reflection",
        "evaluation",
        "memory",
        "provider.failed",
        "provider.completed",
        "routing",
        "learning",
        "market",
        "trade",
        "anomaly",
        "contradiction",
        "dataset",
        "confidence",
        "episode",
    )
    _ANOMALY_TOKENS = ("error", "failed", "warning", "anomaly", "contradiction", "drift", "timeout")

    def __init__(self, summarizer: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._event_counts: Counter[str] = Counter()
        self._fingerprints: Counter[str] = Counter()
        self._classifications: Counter[str] = Counter()
        self._high_signal_events = 0
        self._noise_events = 0
        self._summarizer = summarizer

    @staticmethod
    def _fingerprint(event_type: str, source: str, payload: dict[str, Any]) -> str:
        stable = {
            "event_type": event_type,
            "source": source,
            "topic": payload.get("topic") or payload.get("query") or payload.get("command"),
            "provider": payload.get("provider") or payload.get("active_provider"),
            "runtime_mode": payload.get("runtime_mode"),
            "event_category": payload.get("event_category"),
            "event_priority": payload.get("event_priority"),
            "memory_type": payload.get("memory_type"),
            "status": payload.get("status"),
        }
        blob = json.dumps(stable, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()[:16]

    def score_event(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        lowered = f"{event_type} {source} {json.dumps(payload, sort_keys=True, default=str)}".lower()
        fp = self._fingerprint(event_type, source, payload)
        with self._lock:
            seen_type = self._event_counts[event_type]
            seen_fp = self._fingerprints[fp]
            self._event_counts[event_type] += 1
            self._fingerprints[fp] += 1

        importance = 0.18
        importance += 0.16 if payload.get("event_priority") == "high" else 0.0
        importance += 0.09 if payload.get("event_priority") == "critical" else 0.0
        importance += sum(0.06 for token in self._HIGH_VALUE_TOKENS if token in lowered)
        importance = min(1.0, importance)

        novelty = max(0.02, min(1.0, 1.0 / (1.0 + (seen_type * 0.22) + (seen_fp * 0.75))))
        repetition_decay = max(0.08, 1.0 / (1.0 + seen_type + seen_fp))

        anomaly = 0.06 if payload.get("event_priority") == "high" else 0.0
        anomaly += sum(0.14 for token in self._ANOMALY_TOKENS if token in lowered)
        if payload.get("error"):
            anomaly += 0.22
        if payload.get("dropped_events") or payload.get("unconsumed_events"):
            anomaly += 0.08
        anomaly = min(1.0, anomaly)

        salience = min(
            1.0,
            (importance * 0.42)
            + (novelty * 0.16)
            + (anomaly * 0.2)
            + (0.12 if payload.get("trace_id") else 0.0)
            + (0.1 if payload.get("runtime_id") else 0.0),
        )

        cognition_relevance = 0.1 + sum(
            0.08
            for token in (
                "cognition",
                "reflection",
                "reason",
                "memory",
                "provider",
                "market",
                "learning",
                "dataset",
                "confidence",
            )
            if token in lowered
        )
        cognition_relevance = min(1.0, cognition_relevance)

        memory_worthiness = min(
            1.0,
            (importance * 0.26)
            + (novelty * 0.18)
            + (anomaly * 0.14)
            + (salience * 0.16)
            + (cognition_relevance * 0.26),
        )
        confidence_hint = min(
            1.0,
            max(
                0.0,
                0.35
                + (novelty * 0.15)
                + (importance * 0.15)
                + (0.1 if payload.get("provider") else 0.0)
                + (0.1 if payload.get("trace_id") else 0.0)
                - (anomaly * 0.25),
            ),
        )

        if memory_worthiness >= 0.85 or anomaly >= 0.8:
            classification = "critical"
        elif memory_worthiness >= 0.65:
            classification = "high"
        elif memory_worthiness >= 0.4:
            classification = "medium"
        else:
            classification = "low"

        summary = _clip(
            payload.get("summary")
            or payload.get("query")
            or payload.get("command")
            or payload.get("error")
            or event_type.replace(".", " "),
            180,
        )

        with self._lock:
            self._classifications[classification] += 1
            if classification in {"critical", "high"}:
                self._high_signal_events += 1
            else:
                self._noise_events += 1

        return {
            "importance_score": round(importance, 4),
            "novelty_score": round(novelty, 4),
            "anomaly_score": round(anomaly, 4),
            "repetition_decay": round(repetition_decay, 4),
            "salience_weight": round(salience, 4),
            "cognition_relevance_score": round(cognition_relevance, 4),
            "memory_worthiness_score": round(memory_worthiness, 4),
            "confidence_hint": round(confidence_hint, 4),
            "classification": classification,
            "summary": summary,
            "should_promote": classification in {"critical", "high"} or anomaly >= 0.72,
            "fingerprint": fp,
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self._classifications.values())
            return {
                "total_scored": total,
                "classifications": dict(self._classifications),
                "high_signal_events": self._high_signal_events,
                "noise_events": self._noise_events,
                "signal_density": round(self._high_signal_events / max(1, total), 4),
            }


class CognitiveDatasetBuilder:
    """Governed dataset candidate generation from cognitive episodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: list[dict[str, Any]] = []
        self._last_report: dict[str, Any] = {
            "autocommit_enabled": False,
            "pending_candidates": 0,
            "latest_batch_size": 0,
            "latest_episode_ids": [],
        }

    def observe_episode(self, episode: CognitiveEpisode) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if episode.significance.get("memory_worthiness_score", 0.0) < 0.6:
            return candidates
        if episode.reflection:
            candidates.append(
                {
                    "prompt": f"Reflect on runtime episode topic={episode.topic}",
                    "response": episode.reflection,
                    "source_subsystem": "cognitive_episode_reflection",
                    "memory_origin": "reflection",
                    "evaluation_score": max(episode.evaluation_score, episode.confidence_score),
                    "provider_used": episode.provider_used,
                    "runtime_mode": episode.runtime_mode,
                    "trace_id": episode.trace_id,
                }
            )
        if episode.reasoning_steps:
            candidates.append(
                {
                    "prompt": f"Summarize reasoning lineage for {episode.topic}",
                    "response": " | ".join(episode.reasoning_steps[:5]),
                    "source_subsystem": "cognitive_episode_reasoning",
                    "memory_origin": "cognition_trace",
                    "evaluation_score": max(episode.evaluation_score, episode.significance.get("importance_score", 0.0)),
                    "provider_used": episode.provider_used,
                    "runtime_mode": episode.runtime_mode,
                    "trace_id": episode.trace_id,
                }
            )
        with self._lock:
            self._pending.extend(candidates)
            self._pending = self._pending[-200:]
            self._last_report = {
                "autocommit_enabled": False,
                "pending_candidates": len(self._pending),
                "latest_batch_size": len(candidates),
                "latest_episode_ids": [episode.episode_id],
            }
        return candidates

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_report)

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._pending[-max(1, min(limit, 200)) :])


class CausalCognitionTracker:
    """Runtime causal aggregation across finalized cognitive episodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._episodes_seen = 0
        self._influence_totals: dict[str, float] = defaultdict(float)
        self._outcome_totals: dict[str, float] = defaultdict(float)
        self._downstream_counter: Counter[str] = Counter()
        self._provider_counter: Counter[str] = Counter()
        self._runtime_mode_counter: Counter[str] = Counter()

    def observe_episode(self, episode: CognitiveEpisode) -> None:
        with self._lock:
            self._episodes_seen += 1
            for key, value in episode.causal_influences.items():
                self._influence_totals[key] += float(value)
            self._outcome_totals["evaluation_score"] += float(episode.evaluation_score)
            self._outcome_totals["confidence_score"] += float(episode.confidence_score)
            self._outcome_totals["anomaly_score"] += float(episode.anomaly_score)
            if episode.downstream_effect:
                self._downstream_counter[str(episode.downstream_effect)] += 1
            self._provider_counter[str(episode.provider_used or "unknown")] += 1
            self._runtime_mode_counter[str(episode.runtime_mode or "api")] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = max(1, self._episodes_seen)
            return {
                "episodes_seen": self._episodes_seen,
                "average_influence": {
                    key: round(val / total, 4) for key, val in self._influence_totals.items()
                },
                "average_outcomes": {
                    key: round(val / total, 4) for key, val in self._outcome_totals.items()
                },
                "top_downstream_effects": self._downstream_counter.most_common(8),
                "top_providers": self._provider_counter.most_common(6),
                "runtime_modes": dict(self._runtime_mode_counter),
            }


class CognitiveEpisodeManager:
    """Canonical episode aggregation over runtime events."""

    _FINAL_EVENT_HINTS = (
        "provider.completed",
        "provider.failed",
        "response.complete",
        "reflection.complete",
        "learning.cycle.complete",
        "memory.synthesis.created",
        "live.ingestion.completed",
        "execution.complete",
        "task.completed",
        "task.failed",
        "market_episode.ingested",
        "trade_reflection.ingested",
    )

    def __init__(self, runtime_id: str, max_episodes: int = 200) -> None:
        self.runtime_id = runtime_id
        self.max_episodes = max_episodes
        self._lock = threading.RLock()
        self._open: dict[str, CognitiveEpisode] = {}
        self._episodes: list[dict[str, Any]] = []
        self._reflections: list[dict[str, Any]] = []
        self._compression: dict[str, Any] = {}
        self._dataset_builder = CognitiveDatasetBuilder()
        self._confidence_summary: dict[str, Any] = {}
        self._causal_tracker = CausalCognitionTracker()

    @staticmethod
    def _topic(payload: dict[str, Any], event_type: str) -> str:
        return (
            str(
                payload.get("topic")
                or payload.get("query")
                or payload.get("command")
                or payload.get("provider")
                or payload.get("source_type")
                or event_type.replace(".", " ")
            )
            .strip()
            or "runtime cognition"
        )[:160]

    @staticmethod
    def _retrievals(payload: dict[str, Any]) -> list[dict[str, Any]]:
        retrievals = payload.get("retrievals") or payload.get("sources") or []
        out: list[dict[str, Any]] = []
        if isinstance(retrievals, list):
            for item in retrievals[:6]:
                if isinstance(item, dict):
                    out.append({"source": _clip(item.get("source") or item.get("url") or item.get("id"), 120)})
                else:
                    out.append({"source": _clip(item, 120)})
        return out

    @staticmethod
    def _market_context(payload: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for key in (
            "symbol",
            "regime",
            "trend",
            "volatility",
            "liquidity",
            "macro_sentiment",
            "execution_environment",
            "horizon_short",
            "horizon_medium",
            "horizon_long",
            "scenario_probabilities",
            "uncertainty",
            "action_recommendations",
        ):
            if key in payload:
                out[key] = payload.get(key)
        return out

    @staticmethod
    def _reasoning_lines(event_type: str, payload: dict[str, Any], significance: dict[str, Any]) -> list[str]:
        lines = []
        if payload.get("query"):
            lines.append(f"query:{_clip(payload.get('query'), 120)}")
        if payload.get("command"):
            lines.append(f"command:{_clip(payload.get('command'), 120)}")
        if payload.get("decision_lineage"):
            lines.extend(_clip(item, 120) for item in list(payload.get("decision_lineage", []))[:4])
        if payload.get("scores"):
            lines.append(f"scores:{_clip(payload.get('scores'), 120)}")
        lines.append(f"event:{event_type}")
        lines.append(f"significance:{significance.get('classification', 'low')}")
        return lines[:8]

    @staticmethod
    def _compute_confidence_breakdown(episode: CognitiveEpisode) -> dict[str, float]:
        retrieval = min(1.0, 0.35 + (len(episode.retrievals) * 0.12))
        reasoning = min(1.0, 0.35 + (len(episode.reasoning_steps) * 0.08) + (episode.evaluation_score * 0.3))
        provider = min(1.0, 0.35 + (0.3 if episode.provider_used != "unknown" else 0.0) - (episode.anomaly_score * 0.2))
        memory = min(1.0, 0.25 + (0.45 if episode.memory_written else 0.0) + (episode.significance.get("memory_worthiness_score", 0.0) * 0.2))
        source = min(1.0, 0.25 + (len(episode.source_events) * 0.09))
        market = min(1.0, 0.25 + (0.4 if episode.market_context else 0.0) + (episode.evaluation_score * 0.15))
        reflection = min(1.0, 0.2 + min(0.5, len(episode.reflection.split()) / 40.0))
        synthesis = round((retrieval + reasoning + provider + memory + source + market + reflection) / 7.0, 4)
        return {
            "retrieval_confidence": round(retrieval, 4),
            "reasoning_confidence": round(reasoning, 4),
            "provider_confidence": round(provider, 4),
            "memory_confidence": round(memory, 4),
            "source_confidence": round(source, 4),
            "market_interpretation_confidence": round(market, 4),
            "reflection_confidence": round(reflection, 4),
            "synthesis_confidence": synthesis,
        }

    @staticmethod
    def _compute_causal_influences(episode: CognitiveEpisode) -> dict[str, float]:
        retrieval = min(1.0, len(episode.retrievals) / 6.0)
        provider = 0.9 if episode.provider_used and episode.provider_used != "unknown" else 0.35
        memory = 0.85 if episode.memory_written else 0.3
        reflection = min(1.0, len(episode.reflection.split()) / 50.0) if episode.reflection else 0.15
        evaluation = max(0.0, min(1.0, float(episode.evaluation_score)))
        market = 0.8 if episode.market_context else 0.2
        runtime_mode = 0.75 if episode.runtime_mode in {"api", "agent"} else 0.55
        outcome = max(0.0, min(1.0, float(episode.confidence_score)))
        downstream = min(1.0, len(str(episode.downstream_effect or "").split()) / 8.0)
        return {
            "provider_influence": round(provider, 4),
            "memory_influence": round(memory, 4),
            "retrieval_influence": round(retrieval, 4),
            "reflection_influence": round(reflection, 4),
            "evaluation_influence": round(evaluation, 4),
            "market_influence": round(market, 4),
            "runtime_mode_influence": round(runtime_mode, 4),
            "cognition_outcome_influence": round(outcome, 4),
            "downstream_adaptive_effect": round(downstream, 4),
        }

    @staticmethod
    def _compute_metaevaluation(episode: CognitiveEpisode) -> dict[str, float]:
        cb = episode.confidence_breakdown
        evaluation = float(episode.evaluation_score)
        provider_quality = cb.get("provider_confidence", 0.0)
        memory_quality = cb.get("memory_confidence", 0.0)
        reasoning_quality = cb.get("reasoning_confidence", 0.0)
        reflection_quality = cb.get("reflection_confidence", 0.0)
        market_quality = cb.get("market_interpretation_confidence", 0.0)
        runtime_coherence = max(
            0.0,
            min(
                1.0,
                (cb.get("synthesis_confidence", 0.0) * 0.6)
                + ((1.0 - min(1.0, episode.anomaly_score)) * 0.4),
            ),
        )
        adaptive_quality = max(0.0, min(1.0, (evaluation * 0.65) + (reflection_quality * 0.35)))
        dataset_usefulness = min(
            1.0, (len(episode.dataset_candidates) / 3.0) + (evaluation * 0.2)
        )
        usefulness = max(0.0, min(1.0, (evaluation * 0.7) + (cb.get("synthesis_confidence", 0.0) * 0.3)))
        return {
            "reasoning_quality": round(reasoning_quality, 4),
            "memory_quality": round(memory_quality, 4),
            "provider_quality": round(provider_quality, 4),
            "reflection_quality": round(reflection_quality, 4),
            "cognition_usefulness": round(usefulness, 4),
            "market_interpretation_quality": round(market_quality, 4),
            "adaptive_learning_quality": round(adaptive_quality, 4),
            "hallucination_probability": round(max(0.0, min(1.0, episode.anomaly_score)), 4),
            "runtime_coherence": round(runtime_coherence, 4),
            "episode_usefulness": round(usefulness, 4),
            "dataset_usefulness": round(dataset_usefulness, 4),
        }

    def observe_event(self, event: dict[str, Any], runtime_mode: str = "api") -> dict[str, Any] | None:
        payload = dict(event.get("payload", {}) or {})
        significance = dict(event.get("significance", {}) or {})
        if not payload.get("trace_id") and not significance.get("should_promote"):
            if not any(token in str(event.get("type", "")) for token in self._FINAL_EVENT_HINTS):
                return None

        trace_id = str(payload.get("trace_id") or f"{self.runtime_id}:{event.get('id', int(time.time()*1000))}")
        episode = None
        with self._lock:
            episode = self._open.get(trace_id)
            if episode is None:
                episode = CognitiveEpisode(
                    trace_id=trace_id,
                    runtime_id=str(payload.get("runtime_id") or self.runtime_id),
                    cognition_id=str(payload.get("cognition_id") or f"cog-{uuid.uuid4().hex[:10]}"),
                    episode_id=f"ep-{uuid.uuid4().hex[:10]}",
                    topic=self._topic(payload, str(event.get("type", "runtime.event"))),
                    provider_used=str(payload.get("provider") or payload.get("active_provider") or "unknown"),
                    runtime_mode=str(payload.get("runtime_mode") or runtime_mode or "api"),
                    timestamp_lineage={
                        "opened_at": event.get("timestamp") or _iso_now(),
                        "last_event_at": event.get("timestamp") or _iso_now(),
                    },
                )
                self._open[trace_id] = episode

            episode.source_events.append(
                {
                    "id": event.get("id"),
                    "type": event.get("type"),
                    "source": event.get("source"),
                    "summary": significance.get("summary") or _clip(payload, 180),
                    "classification": significance.get("classification", "low"),
                }
            )
            episode.source_events = episode.source_events[-12:]
            episode.timestamp_lineage["last_event_at"] = event.get("timestamp") or _iso_now()
            episode.provider_used = str(payload.get("provider") or payload.get("active_provider") or episode.provider_used)
            episode.runtime_mode = str(payload.get("runtime_mode") or episode.runtime_mode)
            episode.retrievals.extend(self._retrievals(payload))
            episode.retrievals = episode.retrievals[-8:]
            episode.reasoning_steps.extend(self._reasoning_lines(str(event.get("type", "")), payload, significance))
            episode.reasoning_steps = episode.reasoning_steps[-10:]
            if payload.get("reflection_summary") or "reflection" in str(event.get("type", "")):
                episode.reflection = _clip(payload.get("reflection_summary") or payload.get("summary") or payload.get("error"), 280)
            episode.evaluation_score = max(
                float(payload.get("quality_score", 0.0) or 0.0),
                float(payload.get("evaluation_score", 0.0) or 0.0),
                float(episode.evaluation_score),
                float(significance.get("importance_score", 0.0) or 0.0),
            )
            episode.memory_written = bool(
                episode.memory_written
                or payload.get("memory_id")
                or "memory" in str(event.get("type", ""))
            )
            episode.downstream_effect = _clip(
                payload.get("downstream_effect")
                or payload.get("status")
                or payload.get("event_category")
                or str(event.get("type", "")),
                160,
            )
            episode.anomaly_score = max(float(episode.anomaly_score), float(significance.get("anomaly_score", 0.0) or 0.0))
            episode.novelty_score = max(float(episode.novelty_score), float(significance.get("novelty_score", 0.0) or 0.0))
            episode.market_context.update(self._market_context(payload))
            episode.telemetry_summary.update(payload.get("telemetry", {}) if isinstance(payload.get("telemetry"), dict) else {})
            episode.significance = significance
            if episode.memory_written and episode.significance.get("memory_worthiness_score", 0.0) < 0.5:
                episode.governance_flags.append("memory_written_low_significance_review")

        if self._should_finalize(str(event.get("type", "")), significance, episode):
            return self._finalize_episode(trace_id)
        return None

    def _should_finalize(self, event_type: str, significance: dict[str, Any], episode: CognitiveEpisode) -> bool:
        if any(token in event_type for token in self._FINAL_EVENT_HINTS):
            return True
        if significance.get("classification") == "critical":
            return True
        return len(episode.source_events) >= 6 and significance.get("should_promote", False)

    def _finalize_episode(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            episode = self._open.pop(trace_id, None)
            if episode is None:
                return None
            episode.confidence_breakdown = self._compute_confidence_breakdown(episode)
            episode.confidence_score = episode.confidence_breakdown.get("synthesis_confidence", 0.0)
            episode.timestamp_lineage["closed_at"] = _iso_now()
            episode.dataset_candidates = self._dataset_builder.observe_episode(episode)
            episode.causal_influences = self._compute_causal_influences(episode)
            episode.metaevaluation = self._compute_metaevaluation(episode)
            self._causal_tracker.observe_episode(episode)
            data = episode.to_dict()
            self._episodes.append(data)
            if len(self._episodes) > self.max_episodes:
                self._episodes = self._episodes[-self.max_episodes :]
            self._rebuild_reflections()
            self._rebuild_compression()
            self._rebuild_confidence_summary()
            return data

    def _rebuild_reflections(self) -> None:
        recent = self._episodes[-48:]
        if not recent:
            self._reflections = []
            return

        def _window_summary(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
            provider_counter = Counter(item.get("provider_used", "unknown") for item in items)
            avg_eval = sum(float(item.get("evaluation_score", 0.0) or 0.0) for item in items) / max(1, len(items))
            avg_conf = sum(float(item.get("confidence_score", 0.0) or 0.0) for item in items) / max(1, len(items))
            avg_anomaly = sum(float(item.get("anomaly_score", 0.0) or 0.0) for item in items) / max(1, len(items))
            memory_ratio = sum(1 for item in items if item.get("memory_written")) / max(1, len(items))
            summary = (
                f"{kind} reflection: provider_effectiveness={provider_counter.most_common(1)[0][0]}, "
                f"quality={avg_eval:.2f}, confidence={avg_conf:.2f}, anomaly={avg_anomaly:.2f}, "
                f"memory_usefulness={memory_ratio:.2f}"
            )
            return {
                "type": kind,
                "summary": summary,
                "generated_at": _iso_now(),
                "episode_count": len(items),
                "provider_effectiveness": dict(provider_counter),
                "hallucination_patterns": ["provider_confidence_gap"] if avg_conf < avg_eval else [],
                "runtime_instability": round(avg_anomaly, 4),
                "event_congestion": sum(len(item.get("source_events", [])) for item in items),
                "memory_usefulness": round(memory_ratio, 4),
                "cognition_drift": round(max(0.0, avg_anomaly - avg_eval), 4),
                "market_reasoning_quality": round(
                    sum(1 for item in items if item.get("market_context")) / max(1, len(items)),
                    4,
                ),
                "ale_effectiveness": round(sum(1 for item in items if "learning" in str(item.get("downstream_effect", ""))) / max(1, len(items)), 4),
                "training_quality": round(avg_eval, 4),
                "inference_latency_trends": {},
            }

        self._reflections = [
            _window_summary("hourly", recent[-12:]),
            _window_summary("session", recent[-24:]),
            _window_summary("daily", recent[-48:]),
            _window_summary("runtime_trend", recent),
            _window_summary("provider_performance", recent),
            _window_summary("cognition_quality", recent),
            _window_summary("market_cognition", [item for item in recent if item.get("market_context")] or recent[-6:]),
            _window_summary("memory_quality", [item for item in recent if item.get("memory_written")] or recent[-6:]),
        ]

    def _rebuild_compression(self) -> None:
        recent = self._episodes[-80:]
        clusters: dict[str, list[str]] = defaultdict(list)
        stale: list[str] = []
        preserved: list[str] = []
        now = time.time()
        for item in recent:
            topic = str(item.get("topic", "")).lower()
            tokens = sorted({token for token in topic.split() if len(token) > 2})[:3]
            key = " ".join(tokens) or "misc"
            clusters[key].append(str(item.get("episode_id")))
            last_ts = item.get("timestamp_lineage", {}).get("closed_at") or item.get("timestamp_lineage", {}).get("last_event_at")
            try:
                age = now - datetime.fromisoformat(str(last_ts)).timestamp()
            except Exception:
                age = 0.0
            if age > 86400 and float(item.get("evaluation_score", 0.0) or 0.0) < 0.45:
                stale.append(str(item.get("episode_id")))
            if float(item.get("evaluation_score", 0.0) or 0.0) >= 0.75 or item.get("market_context"):
                preserved.append(str(item.get("episode_id")))
        summaries = [
            {
                "cluster": name,
                "episode_ids": ids[:8],
                "summary": f"{name}: {len(ids)} related episodes",
            }
            for name, ids in clusters.items()
            if len(ids) > 1
        ]
        self._compression = {
            "semantic_clusters": summaries[:12],
            "duplicate_collapse_candidates": [item for item in summaries if len(item["episode_ids"]) > 2][:8],
            "episodic_summaries": summaries[:8],
            "stale_memory_candidates": stale[:12],
            "importance_weighted_retention": preserved[:12],
            "low_value_pruning_candidates": [ep for ep in stale if ep not in preserved][:12],
            "governance_required": True,
        }

    def _rebuild_confidence_summary(self) -> None:
        recent = self._episodes[-40:]
        if not recent:
            self._confidence_summary = {}
            return
        keys = [
            "retrieval_confidence",
            "reasoning_confidence",
            "provider_confidence",
            "memory_confidence",
            "source_confidence",
            "market_interpretation_confidence",
            "reflection_confidence",
            "synthesis_confidence",
        ]
        out = {}
        for key in keys:
            values = [
                float(item.get("confidence_breakdown", {}).get(key, 0.0) or 0.0)
                for item in recent
            ]
            out[key] = round(sum(values) / max(1, len(values)), 4)
        self._confidence_summary = out

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "episodes": list(self._episodes[-20:]),
                "episode_count": len(self._episodes),
                "open_episode_count": len(self._open),
                "reflections": list(self._reflections),
                "compression": dict(self._compression),
                "datasets": self._dataset_builder.status(),
                "pending_dataset_candidates": self._dataset_builder.pending(limit=12),
                "confidence_summary": dict(self._confidence_summary),
                "causality": self._causal_tracker.snapshot(),
            }

    def episodes(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._episodes[-max(1, min(limit, self.max_episodes)) :])
