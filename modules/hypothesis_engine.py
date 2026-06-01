#!/usr/bin/env python3
"""Canonical runtime hypothesis cognition engine."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("Niblit.HypothesisEngine")

_STATUS_EMERGING = "emerging"
_STATUS_ACTIVE = "active"
_STATUS_MONITORING = "monitoring"
_STATUS_UNRESOLVED_CONTRADICTION = "unresolved_contradiction"
_STATUS_SUPERSEDED = "superseded"
_STATUS_DEPRECATED = "deprecated"

_ALLOWED_STATUS = {
    _STATUS_EMERGING,
    _STATUS_ACTIVE,
    _STATUS_MONITORING,
    _STATUS_UNRESOLVED_CONTRADICTION,
    _STATUS_SUPERSEDED,
    _STATUS_DEPRECATED,
}

_STREAM_MARKET = "market_cognition"
_STREAM_DOCUMENT = "document_cognition"
_STREAM_REFLECTION = "reflection_cognition"
_STREAM_RUNTIME = "runtime_cognition"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clip(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    return max(0.0, min(1.0, out))


@dataclass
class HypothesisEvidence:
    evidence_id: str
    hypothesis_id: str
    source: str
    source_type: str
    source_id: str
    summary: str
    impact: str
    confidence_signal: float
    timestamp: str = field(default_factory=_iso_now)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HypothesisContradiction:
    contradiction_id: str
    hypothesis_id: str
    summary: str
    source: str
    evidence_ids: list[str] = field(default_factory=list)
    state: str = "unresolved"
    timestamp: str = field(default_factory=_iso_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HypothesisRecord:
    hypothesis_id: str
    topic: str
    statement: str
    status: str
    origin_stream: str
    confidence: float
    created_at: str = field(default_factory=_iso_now)
    updated_at: str = field(default_factory=_iso_now)
    supersedes: str | None = None
    superseded_by: str | None = None
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    source_lineage: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    contradiction_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HypothesisEngine:
    """Canonical hypothesis model + evidence/contradiction lifecycle."""

    def __init__(self, emit_runtime_event: Any | None = None) -> None:
        self._emit_runtime_event = emit_runtime_event
        self._lock = threading.RLock()
        self._hypotheses: dict[str, HypothesisRecord] = {}
        self._topic_index: dict[str, list[str]] = {}
        self._evidence: dict[str, HypothesisEvidence] = {}
        self._contradictions: dict[str, HypothesisContradiction] = {}
        self._source_index: dict[str, list[str]] = {}
        self._market_graph_chains: list[dict[str, Any]] = []
        self._source_map = self._build_source_map()

    @staticmethod
    def _build_source_map() -> dict[str, dict[str, Any]]:
        return {
            "cognitive_episode": {
                "module": "modules/cognitive_episode.py",
                "hypothesis_fields": ["topic", "reasoning_steps", "reflection", "market_context"],
                "evidence_fields": ["evaluation_score", "confidence_score", "metaevaluation", "causal_influences"],
                "contradiction_fields": ["governance_flags", "anomaly_score", "confidence_breakdown"],
            },
            "reflection_engine": {
                "module": "modules/reflection_engine.py",
                "hypothesis_fields": ["summary", "adaptation_proposals", "stale_assumptions"],
                "evidence_fields": ["overall_health", "failures_detected", "strategy_drifts"],
                "contradiction_fields": ["overconfident_areas", "governance_notes"],
            },
            "evaluation_engine": {
                "module": "modules/evaluation_engine.py",
                "hypothesis_fields": ["user_input", "chosen_advisor", "outcome"],
                "evidence_fields": ["quality_score", "outcome", "weight_updates"],
                "contradiction_fields": ["outcome", "quality_score"],
            },
            "adaptive_market_cognition": {
                "module": "modules/adaptive_market_cognition.py",
                "hypothesis_fields": ["market_cognition_timeline", "last_bundle", "causal_chains"],
                "evidence_fields": ["confidence_evolution", "risk_intelligence", "dqi_scores"],
                "contradiction_fields": ["unresolved_market_contradictions"],
            },
            "adaptive_retrieval_cognition": {
                "module": "modules/adaptive_retrieval_cognition.py",
                "hypothesis_fields": ["last_bundle", "topic_mastery", "lineage"],
                "evidence_fields": ["source_quality", "topic_mastery", "curriculum"],
                "contradiction_fields": ["contradictions", "knowledge_gaps"],
            },
            "lean_algo_manager": {
                "module": "modules/lean_algo_manager.py",
                "hypothesis_fields": ["trade_reflection.ingested", "market_episode.ingested", "trading.results"],
                "evidence_fields": ["confidence", "regime", "summary", "results"],
                "contradiction_fields": ["drawdown", "risk", "mixed outcomes"],
            },
        }

    def source_map(self) -> dict[str, dict[str, Any]]:
        return dict(self._source_map)

    def create_hypothesis(
        self,
        *,
        topic: str,
        statement: str,
        origin_stream: str,
        confidence: float = 0.45,
        source_lineage: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        status: str = _STATUS_EMERGING,
    ) -> dict[str, Any]:
        topic_key = self._topic_key(topic)
        if status not in _ALLOWED_STATUS:
            status = _STATUS_EMERGING
        existing = self._find_existing(topic=topic, statement=statement, origin_stream=origin_stream)
        if existing is not None:
            return existing.to_dict()
        hid = f"hyp-{uuid.uuid4().hex[:10]}"
        record = HypothesisRecord(
            hypothesis_id=hid,
            topic=(topic or "general").strip() or "general",
            statement=_clip(statement, 300),
            status=status,
            origin_stream=origin_stream or _STREAM_RUNTIME,
            confidence=_clamp(confidence, 0.45),
            confidence_breakdown={"base": _clamp(confidence, 0.45)},
            source_lineage=list(source_lineage or []),
            tags=list(tags or []),
        )
        record.audit.append({"ts": _iso_now(), "op": "create", "status": record.status, "confidence": record.confidence})
        with self._lock:
            self._hypotheses[hid] = record
            self._topic_index.setdefault(topic_key, [])
            self._topic_index[topic_key].append(hid)
        self._emit("hypothesis.created", {"hypothesis_id": hid, "topic": record.topic, "origin_stream": record.origin_stream})
        return record.to_dict()

    def update_hypothesis(self, hypothesis_id: str, **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            record = self._hypotheses.get(hypothesis_id)
            if record is None:
                return None
            if "statement" in updates:
                record.statement = _clip(updates["statement"], 300)
            if "status" in updates and updates["status"] in _ALLOWED_STATUS:
                record.status = updates["status"]
            if "tags" in updates and isinstance(updates["tags"], list):
                record.tags = [str(tag) for tag in updates["tags"]]
            if "source_lineage" in updates and isinstance(updates["source_lineage"], list):
                record.source_lineage = list(updates["source_lineage"])
            record.updated_at = _iso_now()
            record.audit.append({"ts": record.updated_at, "op": "update", "updates": sorted(updates.keys())})
            out = record.to_dict()
        self._emit("hypothesis.updated", {"hypothesis_id": hypothesis_id})
        return out

    def supersede_hypothesis(self, old_id: str, *, topic: str, statement: str, confidence: float = 0.5) -> dict[str, Any] | None:
        with self._lock:
            old = self._hypotheses.get(old_id)
            if old is None:
                return None
        new_record = self.create_hypothesis(
            topic=topic,
            statement=statement,
            origin_stream=old.origin_stream,
            confidence=confidence,
            source_lineage=list(old.source_lineage),
            tags=list(set(old.tags + ["superseding"])),
            status=_STATUS_EMERGING,
        )
        new_id = new_record.get("hypothesis_id", "")
        with self._lock:
            if old_id in self._hypotheses and new_id in self._hypotheses:
                self._hypotheses[old_id].status = _STATUS_SUPERSEDED
                self._hypotheses[old_id].superseded_by = new_id
                self._hypotheses[old_id].updated_at = _iso_now()
                self._hypotheses[new_id].supersedes = old_id
        self._emit("hypothesis.superseded", {"old_id": old_id, "new_id": new_id})
        return self.get_hypothesis(new_id)

    def deprecate_hypothesis(self, hypothesis_id: str, reason: str = "") -> dict[str, Any] | None:
        with self._lock:
            record = self._hypotheses.get(hypothesis_id)
            if record is None:
                return None
            record.status = _STATUS_DEPRECATED
            record.updated_at = _iso_now()
            record.audit.append({"ts": record.updated_at, "op": "deprecate", "reason": _clip(reason, 180)})
            out = record.to_dict()
        self._emit("hypothesis.deprecated", {"hypothesis_id": hypothesis_id, "reason": reason})
        return out

    def recalibrate_confidence(
        self,
        hypothesis_id: str,
        *,
        delta: float,
        source: str,
        reason: str,
        breakdown_key: str = "evidence_adjustment",
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._hypotheses.get(hypothesis_id)
            if record is None:
                return None
            before = record.confidence
            record.confidence = _clamp(before + delta, before)
            record.confidence_breakdown[breakdown_key] = round(record.confidence_breakdown.get(breakdown_key, 0.0) + delta, 4)
            record.updated_at = _iso_now()
            record.audit.append(
                {
                    "ts": record.updated_at,
                    "op": "recalibrate_confidence",
                    "source": source,
                    "reason": _clip(reason, 180),
                    "before": round(before, 4),
                    "after": round(record.confidence, 4),
                }
            )
            out = record.to_dict()
        self._emit("hypothesis.confidence.recalibrated", {"hypothesis_id": hypothesis_id, "delta": round(delta, 4), "source": source})
        return out

    def link_source(self, hypothesis_id: str, lineage: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            record = self._hypotheses.get(hypothesis_id)
            if record is None:
                return None
            record.source_lineage.append(dict(lineage or {}))
            record.source_lineage = record.source_lineage[-40:]
            record.updated_at = _iso_now()
            out = record.to_dict()
        self._emit("hypothesis.source.linked", {"hypothesis_id": hypothesis_id, "lineage_source": lineage.get("source") if isinstance(lineage, dict) else ""})
        return out

    def observe_runtime_event(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> list[str]:
        payload = dict(payload or {})
        stream = self._classify_stream(event_type=event_type, source=source, payload=payload)
        topic = self._topic_from_payload(payload, fallback=event_type.replace(".", " "))
        statement = self._statement_from_payload(payload, fallback=f"{stream} signal on {topic}")
        source_ref = {
            "source": source,
            "event_type": event_type,
            "trace_id": payload.get("trace_id"),
            "timestamp": _iso_now(),
        }
        created = self.create_hypothesis(
            topic=topic,
            statement=statement,
            origin_stream=stream,
            confidence=self._confidence_signal(payload),
            source_lineage=[source_ref],
            tags=[stream, "runtime_generated"],
            status=_STATUS_EMERGING,
        )
        hid = str(created.get("hypothesis_id"))
        evidence_id = self.ingest_evidence(
            source=source,
            source_type=stream,
            source_id=str(payload.get("trace_id") or f"{event_type}:{int(time.time() * 1000)}"),
            summary=_clip(payload.get("summary") or payload.get("reflection_summary") or statement, 260),
            payload=payload,
            hypothesis_id=hid,
        )
        if self._looks_like_contradiction(event_type, payload):
            self.register_contradiction(
                hypothesis_id=hid,
                summary=_clip(payload.get("summary") or payload.get("error") or f"Contradiction signal: {event_type}", 240),
                source=f"{source}:{event_type}",
                evidence_ids=[evidence_id] if evidence_id else [],
            )
        if stream == _STREAM_MARKET:
            self._append_market_graph_chain(payload)
        return [hid] if hid else []

    def ingest_snapshot_sources(
        self,
        *,
        cognitive_status: dict[str, Any] | None = None,
        market_status: dict[str, Any] | None = None,
        retrieval_status: dict[str, Any] | None = None,
        reflection_report: dict[str, Any] | None = None,
        evaluation_history: list[dict[str, Any]] | None = None,
        lean_events: list[dict[str, Any]] | None = None,
    ) -> None:
        cognitive_status = cognitive_status or {}
        market_status = market_status or {}
        retrieval_status = retrieval_status or {}
        episodes = cognitive_status.get("episodes", []) if isinstance(cognitive_status, dict) else []
        for episode in episodes[-6:]:
            self.observe_runtime_event("cognitive_episode.snapshot", "cognitive_episode", dict(episode or {}))
        market_timeline = market_status.get("market_cognition_timeline", []) if isinstance(market_status, dict) else []
        for item in market_timeline[-6:]:
            self.observe_runtime_event("market.snapshot", "adaptive_market_cognition", dict(item or {}))
        contradictions = retrieval_status.get("contradictions", []) if isinstance(retrieval_status, dict) else []
        for item in contradictions[-6:]:
            payload = dict(item or {})
            payload.setdefault("summary", payload.get("reason") or payload.get("topic") or "retrieval contradiction")
            self.observe_runtime_event("retrieval.contradiction.detected", "adaptive_retrieval_cognition", payload)
        if isinstance(reflection_report, dict) and reflection_report:
            self.observe_runtime_event("reflection.snapshot", "reflection_engine", dict(reflection_report))
        for rec in (evaluation_history or [])[-6:]:
            self.observe_runtime_event("evaluation.snapshot", "evaluation_engine", dict(rec or {}))
        for evt in (lean_events or [])[-8:]:
            self.observe_runtime_event(str(evt.get("type") or "lean.event"), "lean_algo_manager", dict(evt.get("payload") or {}))

    def ingest_evidence(
        self,
        *,
        source: str,
        source_type: str,
        source_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        hypothesis_id: str | None = None,
    ) -> str:
        payload = dict(payload or {})
        hid = hypothesis_id or self._infer_hypothesis_for_payload(payload)
        if not hid:
            created = self.create_hypothesis(
                topic=self._topic_from_payload(payload, fallback=source_type),
                statement=summary or f"Evidence-driven hypothesis from {source_type}",
                origin_stream=source_type,
                confidence=self._confidence_signal(payload),
                source_lineage=[{"source": source, "source_id": source_id}],
                tags=[source_type, "evidence_seeded"],
            )
            hid = str(created.get("hypothesis_id", ""))
        if not hid:
            return ""
        impact, delta = self._impact_from_payload(payload)
        evidence_id = f"hev-{uuid.uuid4().hex[:12]}"
        evidence = HypothesisEvidence(
            evidence_id=evidence_id,
            hypothesis_id=hid,
            source=source,
            source_type=source_type,
            source_id=source_id,
            summary=_clip(summary, 260),
            impact=impact,
            confidence_signal=self._confidence_signal(payload),
            payload=payload,
        )
        with self._lock:
            self._evidence[evidence_id] = evidence
            self._source_index.setdefault(source_type, [])
            self._source_index[source_type].append(evidence_id)
            record = self._hypotheses.get(hid)
            if record is not None:
                record.evidence_ids.append(evidence_id)
                record.evidence_ids = record.evidence_ids[-300:]
                record.updated_at = _iso_now()
                record.audit.append(
                    {
                        "ts": record.updated_at,
                        "op": "evidence_ingested",
                        "evidence_id": evidence_id,
                        "impact": impact,
                        "source": source,
                    }
                )
        if delta != 0.0:
            self.recalibrate_confidence(hid, delta=delta, source=source_type, reason=f"evidence impact={impact}")
        self._emit(
            "hypothesis.evidence.ingested",
            {"hypothesis_id": hid, "evidence_id": evidence_id, "impact": impact, "source_type": source_type},
        )
        return evidence_id

    def register_contradiction(
        self,
        *,
        hypothesis_id: str,
        summary: str,
        source: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._hypotheses.get(hypothesis_id)
            if record is None:
                return None
            contradiction = HypothesisContradiction(
                contradiction_id=f"hcon-{uuid.uuid4().hex[:10]}",
                hypothesis_id=hypothesis_id,
                summary=_clip(summary, 280),
                source=source,
                evidence_ids=list(evidence_ids or []),
            )
            self._contradictions[contradiction.contradiction_id] = contradiction
            record.contradiction_ids.append(contradiction.contradiction_id)
            record.status = _STATUS_UNRESOLVED_CONTRADICTION
            record.updated_at = _iso_now()
            record.audit.append(
                {
                    "ts": record.updated_at,
                    "op": "contradiction_registered",
                    "contradiction_id": contradiction.contradiction_id,
                    "source": source,
                }
            )
            out = contradiction.to_dict()
        self._emit(
            "hypothesis.contradiction.unresolved",
            {
                "hypothesis_id": hypothesis_id,
                "contradiction_id": out.get("contradiction_id"),
                "source": source,
            },
        )
        return out

    def build_market_knowledge_graph(self) -> dict[str, Any]:
        with self._lock:
            chains = list(self._market_graph_chains[-120:])
            hypotheses = list(self._hypotheses.values())
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        def _node(label: str, stage: str) -> str:
            token = f"{stage}:{label}"
            nid = hashlib.sha1(token.encode("utf-8")).hexdigest()[:12]
            nodes.setdefault(nid, {"id": nid, "label": label, "stage": stage})
            return nid

        for item in chains:
            regime = str(item.get("regime", "unknown"))
            signal = str(item.get("signal", "unknown"))
            confidence = f"{_clamp(item.get('confidence', 0.0)):.2f}"
            risk = f"{_clamp(item.get('risk', 0.0)):.2f}"
            outcome = str(item.get("outcome", "unknown"))
            reflection = _clip(item.get("reflection", "n/a"), 80)
            evaluation = f"{_clamp(item.get('evaluation', 0.0)):.2f}"
            order = [
                (_node(regime, "Regime"), "Regime"),
                (_node(signal, "Signal"), "Signal"),
                (_node(confidence, "Confidence"), "Confidence"),
                (_node(risk, "Risk"), "Risk"),
                (_node(outcome, "Outcome"), "Outcome"),
                (_node(reflection, "Reflection"), "Reflection"),
                (_node(evaluation, "Evaluation"), "Evaluation"),
            ]
            for left, right in zip(order, order[1:]):
                edges.append({"from": left[0], "to": right[0], "label": f"{left[1]}→{right[1]}"})
        return {
            "chain_model": "Regime→Signal→Confidence→Risk→Outcome→Reflection→Evaluation",
            "nodes": list(nodes.values()),
            "edges": edges[-400:],
            "chain_count": len(chains),
            "hypothesis_count": len(hypotheses),
        }

    def analyze_knowledge_gaps(self) -> dict[str, Any]:
        with self._lock:
            hypotheses = list(self._hypotheses.values())
            evidence = list(self._evidence.values())
        topic_stats: dict[str, dict[str, Any]] = {}
        for hyp in hypotheses:
            key = self._topic_key(hyp.topic)
            bucket = topic_stats.setdefault(
                key,
                {"topic": hyp.topic, "hypotheses": 0, "evidence": 0, "confidence_total": 0.0, "quality_total": 0.0},
            )
            bucket["hypotheses"] += 1
            bucket["confidence_total"] += hyp.confidence
        for ev in evidence:
            hyp = self._hypotheses.get(ev.hypothesis_id)
            if hyp is None:
                continue
            key = self._topic_key(hyp.topic)
            bucket = topic_stats.setdefault(
                key,
                {"topic": hyp.topic, "hypotheses": 0, "evidence": 0, "confidence_total": 0.0, "quality_total": 0.0},
            )
            bucket["evidence"] += 1
            bucket["quality_total"] += ev.confidence_signal
        ranked: list[dict[str, Any]] = []
        for stat in topic_stats.values():
            hypotheses_count = max(1, int(stat["hypotheses"]))
            evidence_count = int(stat["evidence"])
            coverage = min(1.0, evidence_count / (hypotheses_count * 3.0))
            mastery = _clamp((stat["confidence_total"] / hypotheses_count) * 0.6 + (coverage * 0.4))
            deficit = round(max(0.0, 1.0 - mastery), 4)
            ranked.append(
                {
                    "topic": stat["topic"],
                    "coverage": round(coverage, 4),
                    "mastery": round(mastery, 4),
                    "priority_score": deficit,
                    "missing_objective": f"Increase evidence quality and coverage for {stat['topic']}",
                }
            )
        ranked.sort(key=lambda row: row.get("priority_score", 0.0), reverse=True)
        return {
            "topic_coverage": ranked,
            "learning_priorities": ranked[:12],
            "missing_knowledge_objectives": [row["missing_objective"] for row in ranked[:12]],
        }

    def directed_hypothesis_questions(self) -> list[dict[str, Any]]:
        gap = self.analyze_knowledge_gaps()
        unresolved = self.unresolved_contradictions()
        with self._lock:
            hypotheses = list(self._hypotheses.values())
        questions: list[dict[str, Any]] = []
        for item in unresolved[:15]:
            questions.append(
                {
                    "type": "contradiction_resolution",
                    "topic": self._hypotheses.get(item["hypothesis_id"]).topic if item.get("hypothesis_id") in self._hypotheses else "unknown",
                    "question": f"What explains unresolved contradiction: {item.get('summary', '')}?",
                }
            )
        for row in gap.get("learning_priorities", [])[:15]:
            questions.append(
                {
                    "type": "missing_data",
                    "topic": row.get("topic"),
                    "question": f"Which data would most reduce uncertainty in {row.get('topic')}?",
                }
            )
        low_conf = sorted(hypotheses, key=lambda h: h.confidence)[:12]
        for hyp in low_conf:
            questions.append(
                {
                    "type": "failure_cause",
                    "topic": hyp.topic,
                    "question": f"Why is confidence low for hypothesis {hyp.hypothesis_id}?",
                }
            )
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for q in questions:
            key = f"{q.get('type')}::{q.get('topic')}::{q.get('question')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(q)
        return deduped[:40]

    def feed_ale_questions(self, core: Any | None = None) -> dict[str, Any]:
        questions = self.directed_hypothesis_questions()
        queued: list[str] = []
        if core is None:
            return {"queued": queued, "generated": len(questions)}
        db = getattr(core, "db", None)
        ale = getattr(core, "autonomous_engine", None)
        for item in questions[:20]:
            topic = _clip(f"hypothesis: {item.get('topic')} — {item.get('type')}", 180)
            if db is not None and hasattr(db, "queue_learning"):
                try:
                    db.queue_learning(topic)
                    queued.append(topic)
                except Exception:
                    continue
            if ale is not None and hasattr(ale, "add_research_topic"):
                try:
                    ale.add_research_topic(topic)
                except Exception:
                    pass
        return {"queued": queued, "generated": len(questions)}

    def persist(self, core: Any | None = None) -> None:
        if core is None:
            return
        db = getattr(core, "db", None)
        if db is None or not hasattr(db, "add_fact"):
            return
        snapshot = self.status(core=core)
        try:
            db.add_fact("hypothesis:status", json.dumps(snapshot.get("summary", {}), sort_keys=True), tags=["hypothesis", "runtime"])
            db.add_fact("hypothesis:gaps", json.dumps(snapshot.get("knowledge_gaps", {}), sort_keys=True), tags=["hypothesis", "knowledge_gap"])
        except Exception:
            pass
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            get_governed_qdrant_memory_cluster().write_memory(
                json.dumps(snapshot.get("summary", {}), sort_keys=True),
                memory_type="episodic_memory",
                payload={
                    "summary": "hypothesis runtime summary",
                    "content_text": json.dumps(snapshot.get("summary", {}), sort_keys=True),
                    "hypothesis_status": snapshot.get("summary", {}),
                },
            )
        except Exception as exc:
            log.debug("hypothesis qdrant persistence degraded: %s", exc)

    def list_hypotheses(self, *, topic: str | None = None, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._hypotheses.values())
        if topic:
            needle = topic.strip().lower()
            records = [item for item in records if needle in item.topic.lower() or needle in item.statement.lower() or needle in item.hypothesis_id.lower()]
        records.sort(key=lambda row: row.updated_at, reverse=True)
        return [item.to_dict() for item in records[:limit]]

    def get_hypothesis(self, hypothesis_id_or_topic: str) -> dict[str, Any] | None:
        query = (hypothesis_id_or_topic or "").strip()
        if not query:
            return None
        with self._lock:
            if query in self._hypotheses:
                rec = self._hypotheses[query]
            else:
                candidates = self._topic_index.get(self._topic_key(query), [])
                rec = self._hypotheses.get(candidates[-1]) if candidates else None
                if rec is None:
                    for item in self._hypotheses.values():
                        if query.lower() in item.topic.lower() or query.lower() in item.statement.lower():
                            rec = item
                            break
            if rec is None:
                return None
            evidence = [self._evidence[eid].to_dict() for eid in rec.evidence_ids if eid in self._evidence][-20:]
            contradictions = [self._contradictions[cid].to_dict() for cid in rec.contradiction_ids if cid in self._contradictions][-20:]
            uncertainty = round(max(0.0, 1.0 - rec.confidence), 4)
            next_steps = self._next_investigations(rec, evidence, contradictions)
            payload = rec.to_dict()
            payload.update(
                {
                    "support": evidence,
                    "contradictions": contradictions,
                    "uncertainty": uncertainty,
                    "next_investigations": next_steps,
                }
            )
            return payload

    def unresolved_contradictions(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [c.to_dict() for c in self._contradictions.values() if c.state == "unresolved"]
        items.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
        return items

    def status(self, *, core: Any | None = None) -> dict[str, Any]:
        with self._lock:
            hypotheses = list(self._hypotheses.values())
            evidence_count = len(self._evidence)
            contradiction_count = len([c for c in self._contradictions.values() if c.state == "unresolved"])
            summary = {
                "hypothesis_count": len(hypotheses),
                "status_counts": self._status_counts(hypotheses),
                "origin_counts": self._origin_counts(hypotheses),
                "evidence_count": evidence_count,
                "unresolved_contradiction_count": contradiction_count,
                "source_map": dict(self._source_map),
                "latest_hypotheses": [h.to_dict() for h in sorted(hypotheses, key=lambda x: x.updated_at, reverse=True)[:12]],
            }
        return {
            "summary": summary,
            "beliefs": [self._belief_view(row) for row in summary["latest_hypotheses"]],
            "unresolved_contradictions": self.unresolved_contradictions(),
            "market_knowledge_graph": self.build_market_knowledge_graph(),
            "knowledge_gaps": self.analyze_knowledge_gaps(),
            "directed_questions": self.directed_hypothesis_questions(),
        }

    def render_command(self, command: str, *, core: Any | None = None) -> str:
        text = (command or "").strip()
        lower = text.lower()
        if lower == "hypothesis status":
            out = self.status(core=core)
            if core is not None:
                self.persist(core)
                self.feed_ale_questions(core)
            return json.dumps(out, indent=2, sort_keys=True)
        if lower == "hypothesis list":
            return json.dumps(self.list_hypotheses(), indent=2, sort_keys=True)
        if lower.startswith("hypothesis show"):
            arg = text[len("hypothesis show") :].strip()
            if not arg:
                return json.dumps({"error": "usage: hypothesis show <id|topic>"}, indent=2, sort_keys=True)
            data = self.get_hypothesis(arg)
            if data is None:
                return json.dumps({"error": "hypothesis not found", "query": arg}, indent=2, sort_keys=True)
            return json.dumps(data, indent=2, sort_keys=True)
        return ""

    def _append_market_graph_chain(self, payload: dict[str, Any]) -> None:
        chain = {
            "regime": str(payload.get("regime") or payload.get("market_regime") or "unknown"),
            "signal": str(payload.get("signal") or payload.get("event_type") or payload.get("topic") or "unknown"),
            "confidence": _clamp(payload.get("confidence") or payload.get("confidence_score") or payload.get("regime_confidence"), 0.0),
            "risk": _clamp(payload.get("risk") or payload.get("risk_score") or payload.get("drawdown"), 0.0),
            "outcome": str(payload.get("outcome") or payload.get("outcome_label") or payload.get("label") or payload.get("status") or "unknown"),
            "reflection": _clip(payload.get("reflection_summary") or payload.get("reflection") or payload.get("summary") or "", 120),
            "evaluation": _clamp(payload.get("evaluation") or payload.get("evaluation_score") or payload.get("quality_score"), 0.0),
        }
        with self._lock:
            self._market_graph_chains.append(chain)
            self._market_graph_chains = self._market_graph_chains[-240:]

    @staticmethod
    def _belief_view(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "hypothesis_id": item.get("hypothesis_id"),
            "topic": item.get("topic"),
            "belief": item.get("statement"),
            "status": item.get("status"),
            "confidence": item.get("confidence"),
            "evidence_count": len(item.get("evidence_ids", [])),
            "contradiction_count": len(item.get("contradiction_ids", [])),
        }

    @staticmethod
    def _topic_key(topic: str) -> str:
        return (topic or "").strip().lower() or "general"

    def _find_existing(self, *, topic: str, statement: str, origin_stream: str) -> HypothesisRecord | None:
        fingerprint = f"{self._topic_key(topic)}::{_clip(statement, 160).lower()}::{origin_stream}"
        with self._lock:
            for item in self._hypotheses.values():
                probe = f"{self._topic_key(item.topic)}::{_clip(item.statement, 160).lower()}::{item.origin_stream}"
                if probe == fingerprint and item.status not in {_STATUS_SUPERSEDED, _STATUS_DEPRECATED}:
                    return item
        return None

    def _classify_stream(self, *, event_type: str, source: str, payload: dict[str, Any]) -> str:
        lowered = f"{event_type} {source} {json.dumps(payload, sort_keys=True, default=str)}".lower()
        if any(token in lowered for token in ("market", "trade", "regime", "dqi", "risk")):
            return _STREAM_MARKET
        if any(token in lowered for token in ("document", "pdf", "citation", "curriculum", "lineage")):
            return _STREAM_DOCUMENT
        if any(token in lowered for token in ("reflection", "evaluation", "outcome", "metaevaluation")):
            return _STREAM_REFLECTION
        return _STREAM_RUNTIME

    @staticmethod
    def _topic_from_payload(payload: dict[str, Any], fallback: str) -> str:
        topic = (
            payload.get("topic")
            or payload.get("query")
            or payload.get("symbol")
            or payload.get("regime")
            or payload.get("event_type")
            or fallback
        )
        return _clip(topic, 140) or "general"

    @staticmethod
    def _statement_from_payload(payload: dict[str, Any], fallback: str) -> str:
        for key in ("summary", "reflection_summary", "decision", "downstream_effect", "reason", "error"):
            if payload.get(key):
                return _clip(payload.get(key), 300)
        topic = payload.get("topic") or payload.get("query") or payload.get("symbol")
        if topic:
            return _clip(f"Hypothesis: {topic} has meaningful runtime signal and requires validation.", 300)
        return _clip(fallback, 300)

    @staticmethod
    def _confidence_signal(payload: dict[str, Any]) -> float:
        return max(
            _clamp(payload.get("confidence"), 0.0),
            _clamp(payload.get("confidence_score"), 0.0),
            _clamp(payload.get("evaluation_score"), 0.0),
            _clamp(payload.get("quality_score"), 0.0),
            _clamp(payload.get("dqi_score"), 0.0),
            0.45,
        )

    @staticmethod
    def _impact_from_payload(payload: dict[str, Any]) -> tuple[str, float]:
        signal = HypothesisEngine._confidence_signal(payload)
        contradiction_signal = bool(payload.get("contradiction") or payload.get("contradictions"))
        if contradiction_signal:
            return "decrease", -0.08
        if signal >= 0.68:
            return "increase", 0.06
        if signal <= 0.4:
            return "decrease", -0.06
        return "unchanged", 0.0

    @staticmethod
    def _looks_like_contradiction(event_type: str, payload: dict[str, Any]) -> bool:
        lowered = f"{event_type} {json.dumps(payload, sort_keys=True, default=str)}".lower()
        return bool(payload.get("contradictions")) or "contradiction" in lowered or "mixed outcomes" in lowered

    def _infer_hypothesis_for_payload(self, payload: dict[str, Any]) -> str:
        topic = self._topic_from_payload(payload, fallback="")
        if not topic:
            return ""
        with self._lock:
            candidates = self._topic_index.get(self._topic_key(topic), [])
            if candidates:
                return candidates[-1]
        return ""

    @staticmethod
    def _status_counts(records: list[HypothesisRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in records:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @staticmethod
    def _origin_counts(records: list[HypothesisRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in records:
            counts[item.origin_stream] = counts.get(item.origin_stream, 0) + 1
        return counts

    def _next_investigations(
        self,
        hypothesis: HypothesisRecord,
        evidence: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> list[str]:
        investigations: list[str] = []
        if hypothesis.confidence < 0.5:
            investigations.append(f"Collect higher-quality evidence for topic '{hypothesis.topic}'")
        if contradictions:
            investigations.append("Resolve unresolved contradictions before status promotion")
        if not evidence:
            investigations.append("Attach first evidence item from market/retrieval/reflection/runtime streams")
        if len(evidence) < 3:
            investigations.append("Increase evidence density across diverse sources")
        if not investigations:
            investigations.append("Promote to active monitoring and validate over next runtime cycles")
        return investigations

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._emit_runtime_event is None:
            return
        try:
            self._emit_runtime_event(event_type, "HypothesisEngine", payload)
        except Exception:
            pass

