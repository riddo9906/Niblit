#!/usr/bin/env python3
"""Full memory loop for NRR-v2 cognitive runtime."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any, Dict, List, Optional

from modules.embedding_engine import embed
from modules.hybrid_qdrant_manager import get_hybrid_manager
from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2
from modules.vector_memory.qdrant_adapter import QdrantAdapter


class NiblitMemoryLoop:
    """Implements INPUT → EMBED → RETRIEVE → REASON → GENERATE → STORE."""

    def __init__(
        self,
        router: Optional[NiblitUnifiedRuntimeRouterV2] = None,
        vector_memory: Optional[QdrantAdapter] = None,
    ) -> None:
        self.router = router or NiblitUnifiedRuntimeRouterV2()
        self.vector_memory = vector_memory or QdrantAdapter(get_hybrid_manager())

    @staticmethod
    def _recency_weight(payload: Dict[str, Any]) -> float:
        ts = int(payload.get("updated_at") or payload.get("created_at") or 0)
        if ts <= 0:
            return 0.0
        age_seconds = max(0, time.time() - ts)
        age_hours = age_seconds / 3600.0
        return float(math.exp(-age_hours / 72.0))

    @staticmethod
    def _frequency_weight(payload: Dict[str, Any]) -> float:
        freq = int(payload.get("frequency") or 1)
        return float(max(0.0, min(1.0, freq / 10.0)))

    def _rerank(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for hit in hits:
            payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else {}
            cosine_similarity = float(hit.get("score", 0.0))
            recency_weight = self._recency_weight(payload)
            frequency_weight = self._frequency_weight(payload)
            score = cosine_similarity * 0.6 + recency_weight * 0.2 + frequency_weight * 0.2
            enriched = dict(hit)
            enriched["rerank_score"] = float(score)
            ranked.append(enriched)
        ranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
        return ranked

    @staticmethod
    def _inject_memory_context(base_context: Optional[str], memories: List[Dict[str, Any]]) -> str:
        context_lines = [base_context.strip()] if base_context and base_context.strip() else []
        if memories:
            context_lines.append("Relevant memory context:")
            for item in memories:
                text = (item.get("text") or "").strip()
                if text:
                    context_lines.append(f"- {text}")
        return "\n".join(context_lines)

    def run(self, user_input: str, context: Optional[str] = None, top_k: int = 5) -> Dict[str, Any]:
        """Execute the full chat memory loop with strict embedding/Qdrant controls."""
        query_vector = embed(user_input)
        routed_models = ["e5"] if len(query_vector) == 384 else None
        hits = self.vector_memory.query(
            user_input,
            collection="episodic_memory",
            top_k=top_k,
            models=routed_models,
        )
        ranked_hits = self._rerank(hits)

        contextual_prompt = user_input
        contextual_system = self._inject_memory_context(context, ranked_hits[:top_k])
        response = self.router.generate(contextual_prompt, context=contextual_system)

        memory_id = str(uuid.uuid4())
        memory_text = f"USER: {user_input}\nASSISTANT: {response}"
        memory_vector = embed(memory_text)
        metadata = {
            "kind": "chat_turn",
            "updated_at": int(time.time()),
            "created_at": int(time.time()),
            "frequency": 1,
        }
        self.vector_memory.insert_vector(
            memory_text,
            {
                "collection": "episodic_memory",
                "doc_id": memory_id,
                "payload": metadata,
                "vector": memory_vector,
                "models": ["e5"] if len(memory_vector) == 384 else None,
            },
        )

        return {
            "response": response,
            "memory_hits": ranked_hits,
            "memory_id": memory_id,
            "router": self.router.last_route(),
        }


if __name__ == "__main__":
    print('Running memory_loop.py')
