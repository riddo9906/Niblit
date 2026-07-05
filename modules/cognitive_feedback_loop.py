#!/usr/bin/env python3
"""Phase 2 — Closed Cognitive Feedback Loop.

Every runtime event travels through one standardized lifecycle pipeline.
No subsystem may bypass this pipeline; every module participates through
the Event Bus.  The loop is coordination-only — it never executes domain
logic directly.  Stage handlers are registered by subsystems and invoked
in strict sequence.

Pipeline stages (in order):
    event → intent_detection → planning → local_llm_consultation
    → reasoning → decision → execution → observation → reflection
    → knowledge_extraction → knowledge_validation → understanding_update
    → architecture_update → behaviour_update → memory_persistence
    → return_response
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

log = logging.getLogger("Niblit.CognitiveFeedbackLoop")

PIPELINE_STAGES = [
    "event",
    "intent_detection",
    "planning",
    "local_llm_consultation",
    "reasoning",
    "decision",
    "execution",
    "observation",
    "reflection",
    "knowledge_extraction",
    "knowledge_validation",
    "understanding_update",
    "architecture_update",
    "behaviour_update",
    "memory_persistence",
    "return_response",
]


@dataclass
class StageResult:
    stage: str
    status: str  # "ok" | "skipped" | "error"
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CognitivePipelineTrace:
    """Full audit trail for one event's journey through the cognitive pipeline."""

    trace_id: str
    source: str
    event_type: str
    started_at: float
    completed_at: float = 0.0
    stages: list[StageResult] = field(default_factory=list)
    final_response: dict[str, Any] = field(default_factory=dict)
    knowledge_created: list[str] = field(default_factory=list)
    understanding_updated: list[str] = field(default_factory=list)
    behaviour_updated: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at) * 1000.0
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "source": self.source,
            "event_type": self.event_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "stages": [s.to_dict() for s in self.stages],
            "final_response": self.final_response,
            "knowledge_created": self.knowledge_created,
            "understanding_updated": self.understanding_updated,
            "behaviour_updated": self.behaviour_updated,
        }


class CognitiveFeedbackLoop:
    """Runs every event through the standard 16-stage cognitive pipeline.

    Each stage can have zero or more handlers registered against it by
    subsystems.  If no handler is registered for a stage the stage is
    silently skipped (graceful degradation), so the loop functions even
    in a partially-wired runtime.

    Handlers receive a *context* dict that accumulates the outputs of all
    prior stages.  They should return a dict (or None) with their results.
    Raising an exception marks the stage as errored but does **not** abort
    the rest of the pipeline.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, list[Callable]] = {s: [] for s in PIPELINE_STAGES}
        self._traces: list[CognitivePipelineTrace] = []
        self._processed_count = 0
        self._error_count = 0

    # ── handler registration ────────────────────────────────────────────────

    def register_stage_handler(self, stage: str, handler: Callable) -> None:
        """Register a callable for a pipeline stage.

        The callable will receive one argument: the running *context* dict.
        It should return a dict (merged into context) or None.
        """
        if stage not in self._handlers:
            log.warning("[CognitiveFeedbackLoop] Unknown pipeline stage: %s", stage)
            return
        with self._lock:
            self._handlers[stage].append(handler)

    # ── pipeline execution ──────────────────────────────────────────────────

    def process(self, event: dict[str, Any]) -> CognitivePipelineTrace:
        """Run *event* through all 16 pipeline stages and return the trace."""
        payload = dict(event.get("payload", {}) or {})
        trace_id = str(payload.get("trace_id") or uuid.uuid4().hex[:16])
        source = str(event.get("source", "unknown"))
        event_type = str(event.get("type", "runtime.event"))

        trace = CognitivePipelineTrace(
            trace_id=trace_id,
            source=source,
            event_type=event_type,
            started_at=time.time(),
        )
        context: dict[str, Any] = {"event": event, "trace_id": trace_id, "payload": payload}

        for stage in PIPELINE_STAGES:
            result = self._run_stage(stage, context, trace)
            trace.stages.append(result)
            if result.status == "ok":
                context[stage] = result.output
            if result.status == "error":
                with self._lock:
                    self._error_count += 1

        trace.completed_at = time.time()
        with self._lock:
            self._processed_count += 1
            self._traces.append(trace)
            if len(self._traces) > 500:
                self._traces[:] = self._traces[-500:]

        return trace

    def _run_stage(
        self,
        stage: str,
        context: dict[str, Any],
        trace: CognitivePipelineTrace,
    ) -> StageResult:
        with self._lock:
            handlers = list(self._handlers.get(stage, []))

        if not handlers:
            return StageResult(stage=stage, status="skipped")

        t0 = time.time()
        merged: dict[str, Any] = {}
        for handler in handlers:
            try:
                result = handler(context)
                if isinstance(result, dict):
                    merged.update(result)
                    # Harvest cross-cutting outputs from certain stages
                    if stage == "knowledge_extraction":
                        trace.knowledge_created.extend(
                            result.get("knowledge_items", []) or []
                        )
                    elif stage == "understanding_update":
                        trace.understanding_updated.extend(
                            result.get("concepts_updated", []) or []
                        )
                    elif stage == "behaviour_update":
                        trace.behaviour_updated.extend(
                            result.get("rules_updated", []) or []
                        )
                    elif stage == "return_response":
                        trace.final_response.update(result)
            except Exception as exc:
                log.debug("[CognitiveFeedbackLoop] Stage handler error [%s]: %s", stage, exc)
                return StageResult(
                    stage=stage,
                    status="error",
                    error=str(exc),
                    duration_ms=(time.time() - t0) * 1000.0,
                )

        return StageResult(
            stage=stage,
            status="ok",
            output=merged,
            duration_ms=(time.time() - t0) * 1000.0,
        )

    # ── read access ─────────────────────────────────────────────────────────

    def recent_traces(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self._traces[-max(1, limit) :]]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pipeline_stages": list(PIPELINE_STAGES),
                "processed_count": self._processed_count,
                "error_count": self._error_count,
                "registered_handlers": {
                    s: len(h) for s, h in self._handlers.items()
                },
            }
