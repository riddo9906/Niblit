#!/usr/bin/env python3
"""RuntimeManager agent wrapper for governed PDF document cognition."""

from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from core.event_bus import EventBus, EventType
from core.task_queue import Task
from modules.governed_document_cognition import get_governed_document_cognition


class DocumentCognitionAgent(BaseAgent):
    """Execute governed document cognition tasks through RuntimeManager authority."""

    HANDLED_TASK_TYPES = ["document_cognition", "pdf_cognition"]

    def __init__(self, *, core: Any | None = None, router_v2: Any | None = None) -> None:
        super().__init__("document_cognition")
        self._core = core
        self._router = router_v2

    def _execute(self, task: Task, event_bus: EventBus) -> dict[str, Any]:
        payload = dict(task.payload or {})
        directory = str(payload.get("directory") or "/home")
        recursive = bool(payload.get("recursive", True))
        max_documents = int(payload.get("max_documents", 25))
        router = payload.get("router") or self._router
        if router is None:
            try:
                from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2

                router = NiblitUnifiedRuntimeRouterV2(
                    local_brain=getattr(self._core, "local_brain", None)
                )
            except Exception:
                router = None

        collector = get_governed_document_cognition()
        result = collector.ingest_directory(
            directory=directory,
            recursive=recursive,
            max_documents=max_documents,
            router=router,
            knowledge_db=getattr(self._core, "db", None),
            evaluation_engine=getattr(self._core, "evaluation_engine", None),
            runtime_id=str(getattr(getattr(self._core, "runtime_manager", None), "runtime_id", "")),
            source_module="document_cognition_agent",
        )
        self._publish(
            event_bus,
            EventType.LEARNING_CYCLE_COMPLETED,
            {
                "task_type": task.task_type,
                "directory": directory,
                "ingested": result.get("ingested", 0),
                "failed": result.get("failed", 0),
            },
        )
        return result

