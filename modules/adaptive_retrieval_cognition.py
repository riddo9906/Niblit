#!/usr/bin/env python3
"""Governed adaptive retrieval cognition layer for unified runtime."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("Niblit.AdaptiveRetrievalCognition")

_ALIAS_PREFIXES = ("retrieval", "memory-retrieval", "adaptive-retrieval", "cognition-retrieval")
_STATUS_SUBCOMMANDS = {
    "status",
    "inspect",
    "contradictions",
    "mastery",
    "sources",
    "gaps",
    "reflections",
    "curriculum",
    "lineage",
    "confidence",
    "causality",
}


@dataclass
class RetrievalBundle:
    query: str
    context: str
    retrievals: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    source_quality: dict[str, float] = field(default_factory=dict)
    topic_mastery: dict[str, dict[str, float | list[str]]] = field(default_factory=dict)
    unresolved_gaps: list[str] = field(default_factory=list)
    curriculum: list[str] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    provider_routing_bias: dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "retrievals": self.retrievals,
            "contradictions": self.contradictions,
            "source_quality": self.source_quality,
            "topic_mastery": self.topic_mastery,
            "unresolved_gaps": self.unresolved_gaps,
            "curriculum": self.curriculum,
            "lineage": self.lineage,
            "telemetry": self.telemetry,
            "provider_routing_bias": self.provider_routing_bias,
        }


class AdaptiveRetrievalCognition:
    """Canonical governed retrieval cognition layer integrated with runtime."""

    def __init__(self, emit_runtime_event: Any | None = None) -> None:
        self._emit_runtime_event = emit_runtime_event
        self._state: dict[str, Any] = {
            "queries": 0,
            "hits": 0,
            "contradictions": [],
            "source_stats": {},
            "topic_mastery": {},
            "gaps": {},
            "curriculum": [],
            "lineage": [],
            "latency_ms": [],
            "last_bundle": {},
            "historical_signals": {
                "adaptive_cycle_weight": 0.55,
                "civilization_agent_weight": 0.5,
                "metacognition_weight": 0.6,
                "metaevaluation_weight": 0.62,
                "predictive_weight": 0.58,
                "reinforcement_weight": 0.57,
            },
        }

    @staticmethod
    def parse_command(command: str) -> tuple[str, str]:
        text = (command or "").strip()
        lower = text.lower()
        for prefix in _ALIAS_PREFIXES:
            if lower == prefix:
                return "status", ""
            if lower.startswith(prefix + " "):
                rest = text[len(prefix) :].strip()
                sub = rest.split(None, 1)[0].lower() if rest else "status"
                arg = rest.split(None, 1)[1].strip() if len(rest.split(None, 1)) > 1 else ""
                if sub in _STATUS_SUBCOMMANDS:
                    return sub, arg
                return "status", rest
        return "", ""

    def build_retrieval_bundle(self, *, query: str, core: Any | None, runtime_mode: str = "api") -> RetrievalBundle:
        started = time.perf_counter()
        normalized_query = (query or "").strip()
        if not normalized_query:
            return RetrievalBundle(query="", context="")

        self._state["queries"] = int(self._state.get("queries", 0)) + 1
        records = self._retrieve_records(normalized_query, core)
        ranked = self._rank_records(normalized_query, records)
        contradictions = self._detect_contradictions(ranked)
        source_quality = self._score_sources(ranked, contradictions)
        topic_mastery, gaps, curriculum = self._update_topic_mastery(normalized_query, ranked, contradictions)
        lineage = self._build_lineage(normalized_query, ranked, contradictions)

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        self._state.setdefault("latency_ms", []).append(latency_ms)
        self._state["latency_ms"] = self._state["latency_ms"][-250:]

        synthesis_context = self._build_context(ranked, contradictions, source_quality, topic_mastery, gaps, curriculum)
        bundle = RetrievalBundle(
            query=normalized_query,
            context=synthesis_context,
            retrievals=ranked,
            contradictions=contradictions,
            source_quality=source_quality,
            topic_mastery=topic_mastery,
            unresolved_gaps=gaps,
            curriculum=curriculum,
            lineage=lineage,
            provider_routing_bias={
                "reasoning_boost": 0.6 if contradictions else 0.25,
                "local_boost": 0.3 if runtime_mode in {"cli", "offline"} else 0.1,
                "confidence_penalty": min(0.4, len(gaps) * 0.08),
            },
            telemetry={
                "hits": len(ranked),
                "retrieval_confidence": round(self._avg([item.get("score", 0.0) for item in ranked]), 4),
                "contradiction_count": len(contradictions),
                "active_sources": sorted({str(item.get("source", "unknown")) for item in ranked}),
                "source_quality": source_quality,
                "topic_mastery": topic_mastery,
                "unresolved_gaps": gaps,
                "curriculum": curriculum,
                "synthesis_complexity": min(1.0, round((len(ranked) / 10.0) + (len(contradictions) * 0.15), 4)),
                "retrieval_latency_ms": latency_ms,
                "lineage": lineage,
                "cognition_drift_indicator": round(len(gaps) / max(1, len(topic_mastery)), 4),
                "unresolved_contradiction_clusters": len({c.get("topic", "") for c in contradictions if c.get("topic")}),
            },
        )
        self._state["hits"] = int(self._state.get("hits", 0)) + len(ranked)
        self._state["last_bundle"] = bundle.to_payload()
        self._emit("retrieval.cognition.hit", {"query": normalized_query, **bundle.telemetry, "retrievals": ranked[:6]})
        if contradictions:
            self._emit("retrieval.contradiction.detected", {"query": normalized_query, "count": len(contradictions), "contradictions": contradictions})
        if curriculum:
            self._emit("retrieval.curriculum.recommended", {"query": normalized_query, "recommendations": curriculum})
        self._emit("retrieval.mastery.updated", {"topic_mastery": topic_mastery, "unresolved_gaps": gaps})
        return bundle

    def update_runtime_outcome(self, *, query: str, response_text: str, error: str | None = None) -> None:
        topic = self._infer_topic(query)
        quality = 0.2 if error else min(1.0, 0.35 + (len((response_text or "").split()) / 160.0))
        mastery = self._state.setdefault("topic_mastery", {}).setdefault(topic, self._new_topic_state())
        mastery["confidence"] = round((float(mastery.get("confidence", 0.0)) * 0.75) + (quality * 0.25), 4)
        mastery["progression"] = round(min(1.0, float(mastery.get("progression", 0.0)) + (0.02 if not error else 0.0)), 4)
        self._state.setdefault("lineage", []).append(
            {
                "ts": time.time(),
                "topic": topic,
                "query": query[:180],
                "response_quality": round(quality, 4),
                "error": bool(error),
            }
        )
        self._state["lineage"] = self._state["lineage"][-300:]

    def status(self, topic: str | None = None) -> dict[str, Any]:
        mastery = dict(self._state.get("topic_mastery", {}))
        if topic:
            key = topic.strip().lower()
            mastery = {k: v for k, v in mastery.items() if key in k}
        avg_latency = self._avg(self._state.get("latency_ms", []))
        return {
            "queries": self._state.get("queries", 0),
            "hits": self._state.get("hits", 0),
            "retrieval_hit_rate": round(float(self._state.get("hits", 0)) / max(1, int(self._state.get("queries", 0))), 4),
            "retrieval_latency_ms_avg": round(avg_latency, 3),
            "contradictions": list(self._state.get("contradictions", []))[-30:],
            "source_quality": dict(self._state.get("source_stats", {})),
            "topic_mastery": mastery,
            "knowledge_gaps": dict(self._state.get("gaps", {})),
            "curriculum": list(self._state.get("curriculum", []))[-40:],
            "lineage": list(self._state.get("lineage", []))[-50:],
            "last_bundle": dict(self._state.get("last_bundle", {})),
            "historical_signals": dict(self._state.get("historical_signals", {})),
        }

    def render_command(self, command: str) -> str:
        sub, arg = self.parse_command(command)
        if not sub:
            return ""
        status = self.status(topic=arg if sub == "inspect" else None)
        if sub == "status":
            return json.dumps(
                {
                    "queries": status["queries"],
                    "hits": status["hits"],
                    "retrieval_hit_rate": status["retrieval_hit_rate"],
                    "retrieval_latency_ms_avg": status["retrieval_latency_ms_avg"],
                    "contradiction_count": len(status["contradictions"]),
                    "topics": len(status["topic_mastery"]),
                },
                indent=2,
                sort_keys=True,
            )
        mapping = {
            "inspect": {"topic": arg, "mastery": status.get("topic_mastery", {}), "gaps": status.get("knowledge_gaps", {})},
            "contradictions": status.get("contradictions", []),
            "mastery": status.get("topic_mastery", {}),
            "sources": status.get("source_quality", {}),
            "gaps": status.get("knowledge_gaps", {}),
            "reflections": [
                {
                    "topic": item.get("topic"),
                    "reflection": item.get("reflection"),
                    "evaluation": item.get("evaluation"),
                    "confidence": item.get("confidence"),
                }
                for item in status.get("last_bundle", {}).get("retrievals", [])
                if item.get("reflection")
            ],
            "curriculum": status.get("curriculum", []),
            "lineage": status.get("lineage", []),
            "confidence": status.get("last_bundle", {}).get("telemetry", {}),
            "causality": status.get("historical_signals", {}),
        }
        return json.dumps(mapping.get(sub, status), indent=2, sort_keys=True)

    def _retrieve_records(self, query: str, core: Any | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if core is None:
            return rows
        db = getattr(core, "db", None)
        if db is None:
            return rows
        try:
            if hasattr(db, "search"):
                for item in (db.search(query, limit=14) or []):
                    rows.append(self._normalize_record(item, origin="search"))
            if hasattr(db, "recall"):
                for item in (db.recall(query, limit=12) or []):
                    rows.append(self._normalize_record(item, origin="recall"))
            if hasattr(db, "list_facts"):
                for item in (db.list_facts(limit=260) or [])[-140:]:
                    if query.lower() in json.dumps(item, default=str).lower():
                        rows.append(self._normalize_record(item, origin="facts"))
        except Exception as exc:
            log.debug("adaptive retrieval lookup failed: %s", exc)
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row.get('source')}::{row.get('text')[:180]}"
            unique[key] = row
        return list(unique.values())

    def _normalize_record(self, item: Any, *, origin: str) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {
                "origin": origin,
                "text": str(item),
                "topic": "general",
                "source": origin,
                "tags": [],
                "evaluation": 0.45,
                "confidence": 0.45,
                "reflection": "",
            }
        text = str(item.get("value") or item.get("summary") or item.get("response") or item)
        source = str(item.get("source") or item.get("source_module") or item.get("key") or origin)
        tags = item.get("tags") or []
        topic = str(item.get("topic") or self._infer_topic(text))
        return {
            "origin": origin,
            "text": text,
            "topic": topic,
            "source": source,
            "tags": tags if isinstance(tags, list) else [str(tags)],
            "evaluation": float(item.get("evaluation_score", item.get("coherence_score", 0.45)) or 0.45),
            "confidence": float(item.get("confidence", item.get("quality_score", 0.45)) or 0.45),
            "reflection": str(item.get("reflection") or item.get("reflection_summary") or ""),
            "lineage": item.get("lineage") or item.get("trace") or {},
        }

    def _rank_records(self, query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        q_words = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))
        ranked: list[dict[str, Any]] = []
        for item in rows:
            text = str(item.get("text", "")).lower()
            overlap = len([w for w in q_words if w in text])
            citation_density = min(1.0, (text.count("http") + text.count("cite") + text.count("source")) / 6.0)
            reflection_quality = min(1.0, len(str(item.get("reflection", "")).split()) / 50.0)
            evaluation_quality = max(0.0, min(1.0, float(item.get("evaluation", 0.45))))
            retrieval_frequency = min(1.0, self._source_frequency(item.get("source", "")) / 12.0)
            runtime_usefulness = max(0.0, min(1.0, (evaluation_quality * 0.6) + (float(item.get("confidence", 0.45)) * 0.4)))
            score = (
                (overlap * 0.18)
                + (citation_density * 0.14)
                + (reflection_quality * 0.12)
                + (evaluation_quality * 0.18)
                + (retrieval_frequency * 0.1)
                + (runtime_usefulness * 0.16)
                + (float(item.get("confidence", 0.45)) * 0.12)
            )
            item["score"] = round(min(1.0, score), 4)
            ranked.append(item)
            self._bump_source(item.get("source", "unknown"), item["score"])
        ranked.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return ranked[:12]

    def _detect_contradictions(self, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pos = ("improve", "increase", "gain", "faster", "better", "optimize")
        neg = ("degrade", "decrease", "worse", "slower", "risk", "fail")
        out: list[dict[str, Any]] = []
        for i, left in enumerate(ranked):
            lt = str(left.get("text", "")).lower()
            left_tokens = set(re.findall(r"[a-zA-Z]{4,}", lt))
            for right in ranked[i + 1 :]:
                rt = str(right.get("text", "")).lower()
                overlap = left_tokens.intersection(set(re.findall(r"[a-zA-Z]{4,}", rt)))
                if len(overlap) < 4:
                    continue
                l_pos = any(t in lt for t in pos)
                l_neg = any(t in lt for t in neg)
                r_pos = any(t in rt for t in pos)
                r_neg = any(t in rt for t in neg)
                if (l_pos and r_neg) or (l_neg and r_pos):
                    contradiction = {
                        "topic": str(left.get("topic") or right.get("topic") or "general"),
                        "left_source": left.get("source"),
                        "right_source": right.get("source"),
                        "left_score": left.get("score", 0.0),
                        "right_score": right.get("score", 0.0),
                        "shared_concepts": sorted(list(overlap))[:8],
                    }
                    out.append(contradiction)
        if out:
            store = self._state.setdefault("contradictions", [])
            store.extend(out)
            self._state["contradictions"] = store[-120:]
        return out[:20]

    def _update_topic_mastery(
        self,
        query: str,
        ranked: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, float | list[str]]], list[str], list[str]]:
        topic = self._infer_topic(query)
        mastery_store: dict[str, dict[str, Any]] = self._state.setdefault("topic_mastery", {})
        entry = mastery_store.setdefault(topic, self._new_topic_state())
        familiarity = min(1.0, float(entry.get("familiarity", 0.0)) + min(0.25, len(ranked) / 25.0))
        depth = min(1.0, float(entry.get("depth", 0.0)) + min(0.2, len({r.get('source') for r in ranked}) / 10.0))
        contradiction_density = min(1.0, len(contradictions) / max(1, len(ranked)))
        confidence = max(0.0, min(1.0, (self._avg([float(r.get("score", 0.0)) for r in ranked]) * 0.7) - (contradiction_density * 0.2)))
        progression = min(1.0, float(entry.get("progression", 0.0)) + (0.03 if ranked else 0.0))
        gaps: list[str] = []
        if depth < 0.45:
            gaps.append(f"{topic}: depth below governed threshold")
        if confidence < 0.5:
            gaps.append(f"{topic}: confidence requires stronger evaluation")
        if contradiction_density > 0.15:
            gaps.append(f"{topic}: contradiction cluster unresolved")
        entry.update(
            {
                "familiarity": round(familiarity, 4),
                "confidence": round(confidence, 4),
                "depth": round(depth, 4),
                "unresolved_gaps": gaps,
                "contradiction_density": round(contradiction_density, 4),
                "progression": round(progression, 4),
            }
        )
        mastery_store[topic] = entry
        gap_store = self._state.setdefault("gaps", {})
        gap_store[topic] = gaps

        recommendations: list[str] = []
        if depth < 0.5:
            recommendations.append(f"Ingest additional documents on '{topic}' to deepen conceptual coverage.")
        if contradiction_density > 0.1:
            recommendations.append(f"Run targeted reflection/evaluation cycle for '{topic}' contradiction resolution.")
        if confidence < 0.55:
            recommendations.append(f"Run self-research for '{topic}' with stronger citation density and causal evidence.")
        curriculum_store = self._state.setdefault("curriculum", [])
        curriculum_store.extend(recommendations)
        self._state["curriculum"] = curriculum_store[-200:]
        return {topic: dict(entry)}, gaps, recommendations

    def _build_lineage(
        self,
        query: str,
        ranked: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lineage = {
            "query": query,
            "source_lineage": [str(r.get("source")) for r in ranked[:10]],
            "document_lineage": [str(r.get("origin")) for r in ranked[:10]],
            "cognition_lineage": [str(r.get("topic")) for r in ranked[:10]],
            "reflection_lineage": [str(r.get("reflection"))[:80] for r in ranked if r.get("reflection")][:6],
            "episode_lineage": [str(r.get("lineage"))[:120] for r in ranked if r.get("lineage")][:6],
            "retrieval_lineage": [
                {
                    "source": r.get("source"),
                    "score": r.get("score"),
                    "evaluation": r.get("evaluation"),
                }
                for r in ranked[:10]
            ],
            "contradiction_lineage": contradictions[:10],
        }
        store = self._state.setdefault("lineage", [])
        store.append({"ts": time.time(), **lineage})
        self._state["lineage"] = store[-300:]
        return lineage

    def _score_sources(self, ranked: list[dict[str, Any]], contradictions: list[dict[str, Any]]) -> dict[str, float]:
        contradiction_by_source = Counter()
        for c in contradictions:
            contradiction_by_source[str(c.get("left_source", ""))] += 1
            contradiction_by_source[str(c.get("right_source", ""))] += 1
        quality: dict[str, float] = {}
        for item in ranked:
            src = str(item.get("source", "unknown"))
            stat = self._state.setdefault("source_stats", {}).setdefault(src, {"score": 0.5, "hits": 0})
            citation_density = min(1.0, str(item.get("text", "")).count("http") / 3.0)
            eval_quality = max(0.0, min(1.0, float(item.get("evaluation", 0.45))))
            reflect_quality = min(1.0, len(str(item.get("reflection", "")).split()) / 40.0)
            retrieval_frequency = min(1.0, float(stat.get("hits", 0)) / 30.0)
            contradiction_penalty = min(0.35, contradiction_by_source.get(src, 0) * 0.07)
            runtime_usefulness = max(0.0, min(1.0, (float(item.get("score", 0.0)) * 0.7) + (float(item.get("confidence", 0.0)) * 0.3)))
            score = max(
                0.0,
                min(
                    1.0,
                    (citation_density * 0.16)
                    + (reflect_quality * 0.14)
                    + (eval_quality * 0.2)
                    + (retrieval_frequency * 0.12)
                    + (runtime_usefulness * 0.23)
                    + (float(stat.get("score", 0.5)) * 0.2)
                    - contradiction_penalty,
                ),
            )
            stat["score"] = round((float(stat.get("score", 0.5)) * 0.7) + (score * 0.3), 4)
            quality[src] = round(float(stat["score"]), 4)
        return quality

    def _build_context(
        self,
        ranked: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
        source_quality: dict[str, float],
        topic_mastery: dict[str, dict[str, float | list[str]]],
        gaps: list[str],
        curriculum: list[str],
    ) -> str:
        if not ranked:
            return ""
        lines = ["[Adaptive Retrieval Cognition]"]
        lines.append("Top retrieved cognition:")
        for item in ranked[:8]:
            lines.append(
                f"- ({item.get('score', 0.0):.2f}) [{item.get('source', 'unknown')}] "
                f"topic={item.get('topic', 'general')} :: {str(item.get('text', ''))[:220]}"
            )
        if contradictions:
            lines.append("Contradictions detected:")
            for c in contradictions[:5]:
                lines.append(
                    f"- topic={c.get('topic')} :: {c.get('left_source')} vs {c.get('right_source')} "
                    f"shared={','.join(c.get('shared_concepts', [])[:5])}"
                )
        lines.append(f"Source reliability: {json.dumps(source_quality, sort_keys=True)}")
        lines.append(f"Topic mastery: {json.dumps(topic_mastery, sort_keys=True)}")
        if gaps:
            lines.append(f"Knowledge gaps: {json.dumps(gaps, ensure_ascii=False)}")
        if curriculum:
            lines.append(f"Curriculum recommendations: {json.dumps(curriculum, ensure_ascii=False)}")
        lines.append("Use retrieval evidence to refine reflection/evaluation confidence and causal reasoning.")
        return "\n".join(lines)

    @staticmethod
    def _new_topic_state() -> dict[str, Any]:
        return {
            "familiarity": 0.0,
            "confidence": 0.0,
            "depth": 0.0,
            "unresolved_gaps": [],
            "contradiction_density": 0.0,
            "progression": 0.0,
        }

    @staticmethod
    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(sum(float(v) for v in values) / max(1, len(values)))

    @staticmethod
    def _infer_topic(text: str) -> str:
        tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", (text or "").lower()) if t not in {"this", "that", "with", "from", "have", "about", "what", "when", "where", "which", "runtime", "retrieval"}]
        if not tokens:
            return "general"
        return " ".join(tokens[:2])

    def _source_frequency(self, source: Any) -> int:
        stats = self._state.setdefault("source_stats", {}).get(str(source), {})
        return int(stats.get("hits", 0))

    def _bump_source(self, source: Any, score: float) -> None:
        src = str(source or "unknown")
        stats = self._state.setdefault("source_stats", {}).setdefault(src, {"score": 0.5, "hits": 0})
        stats["hits"] = int(stats.get("hits", 0)) + 1
        stats["score"] = round((float(stats.get("score", 0.5)) * 0.8) + (float(score) * 0.2), 4)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if callable(self._emit_runtime_event):
            try:
                self._emit_runtime_event(event_type, "AdaptiveRetrievalCognition", payload)
            except Exception as exc:
                log.debug("runtime event emit failed: %s", exc)
        try:
            from modules.event_bus import NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(type=event_type, source="AdaptiveRetrievalCognition", payload=dict(payload))
            )
        except Exception:
            pass


if __name__ == "__main__":
    print("Running adaptive_retrieval_cognition.py")
