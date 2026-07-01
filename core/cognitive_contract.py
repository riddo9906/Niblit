#!/usr/bin/env python3
"""Canonical cognitive contract records for additive runtime rollout."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _utc_ts() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


@dataclass
class CognitiveRequestRecord:
    request_id: str
    trace_id: str
    cognition_id: str
    raw_text: str
    normalized_text: str
    source: str
    priority: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_utc_ts)

    @classmethod
    def create(
        cls,
        text: str,
        *,
        source: str,
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        cognition_id: str | None = None,
    ) -> "CognitiveRequestRecord":
        rid = request_id or _new_id("req")
        tid = trace_id or rid
        cid = cognition_id or _new_id("cog")
        normalized = " ".join(str(text or "").strip().split())
        return cls(
            request_id=rid,
            trace_id=tid,
            cognition_id=cid,
            raw_text=str(text or ""),
            normalized_text=normalized,
            source=str(source or "unknown"),
            priority=str(priority or "normal"),
            metadata=_coerce_dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveEventRecord:
    event_type: str
    source: str
    trace_id: str
    runtime_id: str
    cognition_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=_utc_ts)
    event_category: str = "runtime"
    event_priority: str = "normal"
    envelope_version: str = "cognitive.v1"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveReasoningRecord:
    request_id: str
    intent: str
    mode_name: str
    confidence: float
    semantic_profile: dict[str, Any] = field(default_factory=dict)
    recalled_knowledge: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitivePlanRecord:
    request_id: str
    trace_id: str
    mode_name: str
    intent: str
    steps: list[str] = field(default_factory=list)
    selected_module: str = ""
    selected_function: str = ""
    authorization: dict[str, Any] = field(default_factory=dict)
    branch: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveExecutionRecord:
    request_id: str
    trace_id: str
    cognition_id: str
    mode_name: str
    intent: str
    response: str
    steps_run: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    forecast_signal: str = "HOLD"
    reflection_notes: str = ""
    elapsed_ms: float = 0.0
    quality_score: float = 0.5
    errors: list[str] = field(default_factory=list)
    selected_module: str = ""
    selected_function: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveObservationRecord:
    request_id: str
    trace_id: str
    event_type: str
    summary: str
    quality_score: float = 0.5
    tool_success: bool | None = None
    outputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveReflectionRecord:
    request_id: str
    trace_id: str
    summary: str
    adaptation_proposals: list[str] = field(default_factory=list)
    governance_notes: list[str] = field(default_factory=list)
    overall_health: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveKnowledgeRecord:
    request_id: str
    trace_id: str
    category: str
    content: str
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveProvenanceRecord:
    trace_id: str
    request_id: str
    trigger_chain: list[str] = field(default_factory=list)
    recalled_knowledge: list[str] = field(default_factory=list)
    plan_branch: str = "default"
    executed_function: str = ""
    output_summary: str = ""
    knowledge_mutations: list[str] = field(default_factory=list)
    downstream_consumers: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=_utc_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveCheckpointRecord:
    checkpoint_id: str
    request_id: str
    trace_id: str
    status: str
    pending_plan: dict[str, Any] = field(default_factory=dict)
    partial_observation: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    rehydration_context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_utc_ts)
    updated_at: float = field(default_factory=_utc_ts)

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        trace_id: str,
        status: str,
        pending_plan: dict[str, Any] | None = None,
        partial_observation: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        rehydration_context: dict[str, Any] | None = None,
        checkpoint_id: str | None = None,
    ) -> "CognitiveCheckpointRecord":
        return cls(
            checkpoint_id=checkpoint_id or _new_id("chk"),
            request_id=request_id,
            trace_id=trace_id,
            status=status,
            pending_plan=_coerce_dict(pending_plan),
            partial_observation=_coerce_dict(partial_observation),
            provenance=_coerce_dict(provenance),
            rehydration_context=_coerce_dict(rehydration_context),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = _utc_ts()
        return payload


def classify_event_category(event_type: str) -> str:
    lowered = str(event_type or "").lower()
    if "memory" in lowered or "knowledge" in lowered:
        return "memory"
    if "reflect" in lowered or "cognition" in lowered:
        return "cognition"
    if "plan" in lowered or "task" in lowered or "execution" in lowered:
        return "orchestration"
    if "provider" in lowered or "model" in lowered:
        return "provider"
    if "metric" in lowered or "telemetry" in lowered:
        return "telemetry"
    return "runtime"


def normalize_event_envelope(
    *,
    event_type: str,
    source: str,
    payload: dict[str, Any] | None = None,
    runtime_id: str = "",
    cognition_id: str = "",
    trace_id: str = "",
    event_priority: str = "normal",
    provenance: dict[str, Any] | None = None,
) -> CognitiveEventRecord:
    body = _coerce_dict(payload)
    resolved_trace = str(body.get("trace_id") or trace_id or _new_id("trace"))
    resolved_cognition = str(body.get("cognition_id") or cognition_id or _new_id("cog"))
    resolved_runtime = str(body.get("runtime_id") or runtime_id or "")
    body.setdefault("trace_id", resolved_trace)
    if resolved_runtime:
        body.setdefault("runtime_id", resolved_runtime)
    body.setdefault("cognition_id", resolved_cognition)
    body.setdefault("event_category", body.get("event_category") or classify_event_category(event_type))
    body.setdefault("event_priority", body.get("event_priority") or event_priority)
    return CognitiveEventRecord(
        event_type=str(event_type or "runtime.event"),
        source=str(source or "unknown"),
        trace_id=resolved_trace,
        runtime_id=resolved_runtime,
        cognition_id=resolved_cognition,
        payload=body,
        event_category=str(body.get("event_category") or classify_event_category(event_type)),
        event_priority=str(body.get("event_priority") or event_priority),
        provenance=_coerce_dict(provenance),
    )


def build_provenance_record(
    *,
    request: CognitiveRequestRecord,
    plan: CognitivePlanRecord | None = None,
    recalled_knowledge: list[Any] | None = None,
    executed_function: str = "",
    output_summary: str = "",
    knowledge_mutations: list[str] | None = None,
    downstream_consumers: list[str] | None = None,
) -> CognitiveProvenanceRecord:
    return CognitiveProvenanceRecord(
        trace_id=request.trace_id,
        request_id=request.request_id,
        trigger_chain=[request.source, request.normalized_text[:120]],
        recalled_knowledge=[str(item)[:120] for item in _coerce_list(recalled_knowledge)],
        plan_branch=(plan.branch if plan is not None else "default"),
        executed_function=executed_function,
        output_summary=str(output_summary or "")[:240],
        knowledge_mutations=[str(item)[:120] for item in _coerce_list(knowledge_mutations)],
        downstream_consumers=[str(item)[:120] for item in _coerce_list(downstream_consumers)],
    )


def is_significant_cognitive_event(event_type: str, payload: dict[str, Any] | None = None) -> bool:
    lowered = str(event_type or "").lower()
    if any(
        token in lowered
        for token in (
            "execution.complete",
            "response.complete",
            "reflection.complete",
            "learning.cycle.complete",
            "task.completed",
            "task.failed",
            "provider.completed",
            "provider.failed",
            "trade_reflection.ingested",
            "market_episode.ingested",
        )
    ):
        return True
    body = _coerce_dict(payload)
    return bool(body.get("memory_id") or body.get("reflection_summary") or body.get("quality_score"))
