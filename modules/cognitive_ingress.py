#!/usr/bin/env python3
"""Mandatory canonical cognitive ingress path for additive rollout."""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.cognitive_contract import (
    CognitiveCheckpointRecord,
    CognitiveExecutionRecord,
    CognitiveKnowledgeRecord,
    CognitivePlanRecord,
    CognitiveReasoningRecord,
    CognitiveRequestRecord,
    build_provenance_record,
)

log = logging.getLogger("Niblit.CognitiveIngress")


class CognitiveIngress:
    """Thin canonical path above existing specialist modules."""

    def __init__(
        self,
        *,
        runtime_manager: Any | None = None,
        persistence_manager: Any | None = None,
        knowledge_db: Any | None = None,
        unified_memory: Any | None = None,
        provenance_service: Any | None = None,
        architecture_model: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._runtime_manager = runtime_manager
        self._persistence_manager = persistence_manager
        self._knowledge_db = knowledge_db
        self._unified_memory = unified_memory
        self._provenance_service = provenance_service
        self._architecture_model = architecture_model
        self._metrics: dict[str, int] = {}

    def ingest(
        self,
        text: str,
        *,
        source: str = "api",
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> CognitiveExecutionRecord:
        request = CognitiveRequestRecord.create(text, source=source, priority=priority, metadata=metadata)
        intent_engine = self._intent_engine()
        router = self._router()
        graph = self._graph()

        intent_profile = intent_engine.classify(request.normalized_text)
        mode = router.route(intent_profile)
        recalled = self._recall(request)
        authorization = self._authorize(request=request, mode=mode)
        plan = CognitivePlanRecord(
            request_id=request.request_id,
            trace_id=request.trace_id,
            mode_name=mode.mode_name,
            intent=mode.intent,
            steps=["normalize", "intent", "recall", "plan", "execute", "observe", "reflect"],
            selected_module="modules.execution_graph",
            selected_function="ExecutionGraph.run",
            authorization=authorization,
            branch=mode.mode_name,
        )
        checkpoint = CognitiveCheckpointRecord.create(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status="pending",
            pending_plan=plan.to_dict(),
            provenance={},
            rehydration_context={"source": source, "metadata": dict(metadata or {})},
        )
        self._save_checkpoint(checkpoint)

        exec_context = {
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "cognition_id": request.cognition_id,
            "ingress_source": source,
            "authorization": authorization,
            "memory_results": [item for item in recalled if isinstance(item, dict)],
            "selected_module": plan.selected_module,
            "selected_function": plan.selected_function,
        }
        exec_result = graph.run(request.normalized_text, context=exec_context, mode=mode)
        quality_score = float(getattr(exec_result, "quality_score", 0.5) or 0.5)
        execution = CognitiveExecutionRecord(
            request_id=request.request_id,
            trace_id=request.trace_id,
            cognition_id=request.cognition_id,
            mode_name=mode.mode_name,
            intent=mode.intent,
            response=str(getattr(exec_result, "response", "") or ""),
            steps_run=list(getattr(exec_result, "steps_run", []) or []),
            tools_called=list(getattr(exec_result, "tools_called", []) or []),
            forecast_signal=str(getattr(exec_result, "forecast_signal", "HOLD") or "HOLD"),
            reflection_notes=str(getattr(exec_result, "reflection_notes", "") or ""),
            elapsed_ms=float(getattr(exec_result, "elapsed_ms", 0.0) or 0.0),
            quality_score=max(0.0, min(1.0, quality_score)),
            errors=self._execution_errors(exec_result),
            selected_module=plan.selected_module,
            selected_function=plan.selected_function,
            metadata={
                "authorization": authorization,
                "semantic_profile": intent_profile.to_dict(),
                "recalled_knowledge": recalled,
            },
        )
        provenance = build_provenance_record(
            request=request,
            plan=plan,
            recalled_knowledge=[item.get("uid") or item.get("fact") or item.get("text") or "" for item in recalled],
            executed_function=plan.selected_function,
            output_summary=execution.response,
            downstream_consumers=["unified_runtime", "reflection_engine", "knowledge_memory"],
        )
        self._record_provenance(provenance.to_dict())
        self._record_knowledge(execution)

        self._save_checkpoint(
            CognitiveCheckpointRecord.create(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="completed",
                pending_plan=plan.to_dict(),
                partial_observation=execution.to_dict(),
                provenance=provenance.to_dict(),
                rehydration_context={"source": source},
                checkpoint_id=checkpoint.checkpoint_id,
            )
        )
        self._architecture_observe(
            {
                "type": "cognitive.ingress.completed",
                "source": "cognitive_ingress",
                "payload": {
                    "trace_id": request.trace_id,
                    "request_id": request.request_id,
                    "cognition_id": request.cognition_id,
                    "selected_module": plan.selected_module,
                    "selected_function": plan.selected_function,
                    "event_category": "orchestration",
                },
            }
        )
        self._record_metric(mode.mode_name)
        return execution

    def resume_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        if self._provenance_service is not None and hasattr(self._provenance_service, "load_checkpoint"):
            return dict(self._provenance_service.load_checkpoint(checkpoint_id) or {})
        if self._persistence_manager is not None and hasattr(self._persistence_manager, "read_cognitive_checkpoint"):
            return dict(self._persistence_manager.read_cognitive_checkpoint(checkpoint_id) or {})
        return {}

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._metrics)

    def _intent_engine(self) -> Any:
        from modules.intent_engine import get_intent_engine

        return get_intent_engine()

    def _router(self) -> Any:
        from modules.cognitive_router import get_cognitive_router

        return get_cognitive_router()

    def _graph(self) -> Any:
        from modules.execution_graph import get_execution_graph

        return get_execution_graph()

    def _recall(self, request: CognitiveRequestRecord) -> list[dict[str, Any]]:
        memory = self._unified_memory or self._resolve_runtime_dependency("get_unified_memory")
        if memory is not None and hasattr(memory, "recall_contract"):
            try:
                return list(memory.recall_contract(request))
            except Exception as exc:
                log.debug("recall_contract failed: %s", exc)
        if memory is not None and hasattr(memory, "recall"):
            try:
                return [item.to_dict() if hasattr(item, "to_dict") else dict(item or {}) for item in memory.recall(request.normalized_text, top_k=3)]
            except Exception as exc:
                log.debug("recall failed: %s", exc)
        return []

    def _authorize(self, *, request: CognitiveRequestRecord, mode: Any) -> dict[str, Any]:
        allowed = True
        reason = "allowed"
        if getattr(mode, "run_governance", False) and request.metadata.get("authorization_denied"):
            allowed = False
            reason = "metadata_denied"
        return {"allowed": allowed, "reason": reason, "mode": getattr(mode, "mode_name", "")}

    @staticmethod
    def _execution_errors(exec_result: Any) -> list[str]:
        step_results = list(getattr(exec_result, "step_results", []) or [])
        return [str(getattr(item, "error", "") or "") for item in step_results if not getattr(item, "success", True) and getattr(item, "error", "")]

    def _record_knowledge(self, execution: CognitiveExecutionRecord) -> None:
        if not execution.response.strip():
            return
        record = CognitiveKnowledgeRecord(
            request_id=execution.request_id,
            trace_id=execution.trace_id,
            category="execution",
            content=execution.response[:1000],
            importance=max(0.3, min(1.0, execution.quality_score)),
            tags=[execution.intent, execution.mode_name],
            provenance={"selected_function": execution.selected_function},
        )
        memory = self._unified_memory or self._resolve_runtime_dependency("get_unified_memory")
        if memory is not None and hasattr(memory, "remember_contract"):
            try:
                memory.remember_contract(record)
            except Exception as exc:
                log.debug("remember_contract failed: %s", exc)
        if self._knowledge_db is not None and hasattr(self._knowledge_db, "add_fact"):
            try:
                self._knowledge_db.add_fact(
                    f"cognitive:{execution.request_id}",
                    record.content,
                    tags=record.tags,
                )
            except Exception as exc:
                log.debug("knowledge_db add_fact failed: %s", exc)

    def _save_checkpoint(self, checkpoint: CognitiveCheckpointRecord) -> None:
        if self._provenance_service is not None and hasattr(self._provenance_service, "save_checkpoint"):
            self._provenance_service.save_checkpoint(checkpoint)
        elif self._persistence_manager is not None and hasattr(self._persistence_manager, "write_cognitive_checkpoint"):
            self._persistence_manager.write_cognitive_checkpoint(checkpoint.checkpoint_id, checkpoint.to_dict())

    def _record_provenance(self, payload: dict[str, Any]) -> None:
        if self._provenance_service is not None and hasattr(self._provenance_service, "update"):
            self._provenance_service.update(
                payload.get("trace_id", ""),
                request_id=payload.get("request_id", ""),
                trigger_chain=list(payload.get("trigger_chain", [])),
                recalled_knowledge=list(payload.get("recalled_knowledge", [])),
                plan_branch=payload.get("plan_branch", "default"),
                executed_function=payload.get("executed_function", ""),
                output_summary=payload.get("output_summary", ""),
                knowledge_mutations=list(payload.get("knowledge_mutations", [])),
                downstream_consumers=list(payload.get("downstream_consumers", [])),
            )

    def _architecture_observe(self, event: dict[str, Any]) -> None:
        if self._architecture_model is not None and hasattr(self._architecture_model, "observe_event"):
            self._architecture_model.observe_event(event, lineage_channel="cognitive_ingress")

    def _record_metric(self, mode_name: str) -> None:
        with self._lock:
            self._metrics[mode_name] = self._metrics.get(mode_name, 0) + 1

    def _resolve_runtime_dependency(self, getter_name: str) -> Any | None:
        if self._runtime_manager is not None and hasattr(self._runtime_manager, getter_name):
            try:
                return getattr(self._runtime_manager, getter_name)()
            except Exception:
                return None
        if getter_name == "get_unified_memory":
            try:
                from niblit_memory.unified_memory_engine import get_unified_memory

                return get_unified_memory()
            except Exception:
                return None
        return None


_INGRESS: CognitiveIngress | None = None
_INGRESS_LOCK = threading.Lock()


def get_cognitive_ingress(**kwargs: Any) -> CognitiveIngress:
    global _INGRESS  # pylint: disable=global-statement
    with _INGRESS_LOCK:
        if _INGRESS is None:
            _INGRESS = CognitiveIngress(**kwargs)
    return _INGRESS
