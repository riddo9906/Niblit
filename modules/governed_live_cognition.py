#!/usr/bin/env python3
"""Governed live data collection + cognition ingestion for fresh runtime knowledge."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

log = logging.getLogger("GovernedLiveCognition")

_COLLECTOR: "GovernedLiveCognitionCollector | None" = None
_LOCK = threading.Lock()

_SOURCE_MEMORY_TYPE = {
    "news_feed": "semantic_memory",
    "research_feed": "semantic_memory",
    "financial_feed": "market_memory",
    "technical_documentation": "semantic_memory",
    "runtime_telemetry_stream": "runtime_memory",
    "governance_runtime_state": "runtime_memory",
}


class GovernedLiveCognitionCollector:
    """Normalize live results, route synthesis through RouterV2, and persist governed memory."""

    def __init__(self) -> None:
        self._ingestions = 0
        self._last_result: dict[str, Any] = {}

    def ingest(
        self,
        *,
        query: str,
        items: list[Any],
        source_type: str,
        source_module: str,
        router: Any | None = None,
        knowledge_db: Any | None = None,
        brain_trainer: Any | None = None,
        runtime_id: str = "",
    ) -> dict[str, Any]:
        normalized = self._normalize_items(items)
        trace_id = hashlib.sha1(
            f"{source_type}:{query}:{time.time()}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        cognition_id = f"cog-{trace_id[:10]}"
        result = {
            "success": False,
            "trace_id": trace_id,
            "runtime_id": runtime_id,
            "cognition_id": cognition_id,
            "source_type": source_type,
            "source_module": source_module,
            "memory_type": _SOURCE_MEMORY_TYPE.get(source_type, "semantic_memory"),
            "items_ingested": len(normalized),
            "synthesis": "",
            "quality": 0.0,
        }
        if not query or not normalized:
            return result

        self._emit(
            "live.ingestion.started",
            payload={
                **result,
                "event_category": "ingestion",
                "event_priority": "high",
                "query": query,
            },
        )
        synthesis = self._synthesize(
            query=query,
            normalized=normalized,
            router=router,
        )
        if not synthesis:
            self._emit(
                "live.ingestion.failed",
                payload={
                    **result,
                    "query": query,
                    "event_category": "ingestion",
                    "event_priority": "high",
                },
            )
            return result

        quality = self._estimate_quality(synthesis, normalized)
        result.update(
            {
                "success": True,
                "synthesis": synthesis,
                "quality": quality,
            }
        )
        self._persist(
            query=query,
            synthesis=synthesis,
            normalized=normalized,
            result=result,
            knowledge_db=knowledge_db,
            brain_trainer=brain_trainer,
        )
        self._emit(
            "live.ingestion.completed",
            payload={
                **result,
                "query": query,
                "event_category": "ingestion",
                "event_priority": "high",
            },
        )
        self._emit(
            "memory.synthesis.created",
            payload={
                **result,
                "query": query,
                "event_category": "memory",
                "event_priority": "normal",
            },
        )
        self._ingestions += 1
        self._last_result = dict(result)
        return result

    @staticmethod
    def _normalize_items(items: list[Any]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in items[:8]:
            if isinstance(item, dict):
                text = (
                    item.get("snippet")
                    or item.get("text")
                    or item.get("summary")
                    or item.get("description")
                    or item.get("content")
                    or ""
                )
                source = str(item.get("source") or item.get("url") or "live_source")
            else:
                text = str(item)
                source = "live_source"
            text = str(text or "").strip()
            if text:
                normalized.append({"text": text[:700], "source": source[:200]})
        return normalized

    def _synthesize(self, *, query: str, normalized: list[dict[str, str]], router: Any | None) -> str:
        if router is None:
            try:
                from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2

                router = NiblitUnifiedRuntimeRouterV2()
            except Exception as exc:
                log.debug("router unavailable for live ingestion: %s", exc)
                return ""
        evidence = "\n".join(
            f"- source={item['source']}: {item['text']}" for item in normalized
        )
        prompt = (
            "You are the governed live cognition layer for Niblit.\n"
            "Synthesize fresh external/runtime evidence into a concise factual runtime brief.\n"
            "Return: summary, knowledge gaps, confidence notes, and source freshness observations.\n"
            "Do not invent sources or autonomous actions.\n\n"
            f"Topic: {query}\n"
            f"Evidence:\n{evidence[:3200]}"
        )
        try:
            return str(router.generate(prompt=prompt, context="governed_live_cognition") or "").strip()
        except Exception as exc:
            log.debug("live cognition synthesis failed: %s", exc)
            return ""

    @staticmethod
    def _estimate_quality(synthesis: str, normalized: list[dict[str, str]]) -> float:
        if not synthesis:
            return 0.0
        word_score = min(1.0, len(synthesis.split()) / 80.0)
        coverage_score = min(1.0, len(normalized) / 4.0)
        return round((word_score * 0.7) + (coverage_score * 0.3), 3)

    def _persist(
        self,
        *,
        query: str,
        synthesis: str,
        normalized: list[dict[str, str]],
        result: dict[str, Any],
        knowledge_db: Any | None,
        brain_trainer: Any | None,
    ) -> None:
        payload = {
            "summary": synthesis[:240],
            "reflection_summary": synthesis[:240],
            "importance_score": max(0.5, float(result["quality"])),
            "coherence_score": float(result["quality"]),
            "advisor_lineage": [result["source_module"], "governed_live_cognition"],
            "causal_chain": [query, result["source_type"]],
            "replay_metadata": {
                "trace_id": result["trace_id"],
                "decision_lineage": [f"live_ingestion:{result['source_type']}"],
                "causal_references": [item["source"] for item in normalized[:4]],
            },
            "telemetry": {
                "trace_id": result["trace_id"],
                "runtime_id": result["runtime_id"],
                "cognition_id": result["cognition_id"],
                "source_module": result["source_module"],
            },
        }
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            cluster = get_governed_qdrant_memory_cluster()
            cluster.write_memory(
                synthesis,
                memory_type=str(result["memory_type"]),
                payload=payload,
            )
        except Exception as exc:
            log.debug("governed live memory write skipped: %s", exc)
        if knowledge_db is not None and hasattr(knowledge_db, "add_fact"):
            try:
                knowledge_db.add_fact(
                    f"live_ingestion:{result['source_type']}:{int(time.time())}",
                    {
                        "query": query,
                        "summary": synthesis[:400],
                        "trace_id": result["trace_id"],
                        "sources": [item["source"] for item in normalized[:4]],
                        "quality": result["quality"],
                    },
                    tags=["live_ingestion", result["source_type"], "governed_cognition"],
                )
            except Exception:
                pass
        if brain_trainer is not None and hasattr(brain_trainer, "ingest_research"):
            try:
                brain_trainer.ingest_research(
                    f"live:{result['source_type']}:{query[:80]}",
                    synthesis,
                )
            except Exception:
                pass

    @staticmethod
    def _emit(event_type: str, *, payload: dict[str, Any]) -> None:
        try:
            from modules.event_bus import NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=event_type,
                    source="governed_live_cognition",
                    payload=payload,
                )
            )
        except Exception:
            return

    def status(self) -> dict[str, Any]:
        return {
            "ingestions_total": self._ingestions,
            "last_result": dict(self._last_result),
        }


def get_governed_live_cognition_collector() -> GovernedLiveCognitionCollector:
    global _COLLECTOR
    with _LOCK:
        if _COLLECTOR is None:
            _COLLECTOR = GovernedLiveCognitionCollector()
    return _COLLECTOR
