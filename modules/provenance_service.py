#!/usr/bin/env python3
"""Canonical provenance + checkpoint service for cognitive runtime rollout."""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.cognitive_contract import CognitiveCheckpointRecord, CognitiveProvenanceRecord

log = logging.getLogger("Niblit.ProvenanceService")


class ProvenanceService:
    """Tracks causal lineage, knowledge mutations, and resumable checkpoints."""

    def __init__(self, persistence_manager: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._persistence_manager = persistence_manager
        self._records: dict[str, CognitiveProvenanceRecord] = {}

    def record(self, record: CognitiveProvenanceRecord) -> dict[str, Any]:
        with self._lock:
            self._records[record.trace_id] = record
        self._append_jsonl("provenance", record.to_dict())
        return record.to_dict()

    def update(
        self,
        trace_id: str,
        *,
        request_id: str = "",
        trigger_chain: list[str] | None = None,
        recalled_knowledge: list[str] | None = None,
        plan_branch: str | None = None,
        executed_function: str | None = None,
        output_summary: str | None = None,
        knowledge_mutations: list[str] | None = None,
        downstream_consumers: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._records.get(trace_id) or CognitiveProvenanceRecord(trace_id=trace_id, request_id=request_id or trace_id)
            if request_id:
                current.request_id = request_id
            if trigger_chain:
                current.trigger_chain = list(trigger_chain)
            if recalled_knowledge:
                current.recalled_knowledge = list(recalled_knowledge)
            if plan_branch:
                current.plan_branch = plan_branch
            if executed_function:
                current.executed_function = executed_function
            if output_summary:
                current.output_summary = output_summary[:240]
            if knowledge_mutations:
                current.knowledge_mutations = list(knowledge_mutations)
            if downstream_consumers:
                current.downstream_consumers = list(downstream_consumers)
            self._records[trace_id] = current
            payload = current.to_dict()
        self._append_jsonl("provenance", payload)
        return payload

    def get(self, trace_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(trace_id)
            return record.to_dict() if record is not None else {}

    def save_checkpoint(self, checkpoint: CognitiveCheckpointRecord) -> dict[str, Any]:
        payload = checkpoint.to_dict()
        if self._persistence_manager is not None and hasattr(self._persistence_manager, "write_cognitive_checkpoint"):
            self._persistence_manager.write_cognitive_checkpoint(checkpoint.checkpoint_id, payload)
        else:
            self._append_jsonl("checkpoints", payload)
        return payload

    def load_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        if self._persistence_manager is not None and hasattr(self._persistence_manager, "read_cognitive_checkpoint"):
            loaded = self._persistence_manager.read_cognitive_checkpoint(checkpoint_id)
            return dict(loaded or {})
        return {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"tracked_traces": len(self._records)}

    def _append_jsonl(self, channel: str, record: dict[str, Any]) -> None:
        if self._persistence_manager is None or not hasattr(self._persistence_manager, "append_jsonl_record"):
            return
        try:
            root = getattr(self._persistence_manager, "root_dir", "")
            path = f"{root}/cognitive/{channel}.jsonl" if root else f"cognitive/{channel}.jsonl"
            self._persistence_manager.append_jsonl_record(path, record)
        except Exception as exc:
            log.debug("Failed persisting %s record: %s", channel, exc)
