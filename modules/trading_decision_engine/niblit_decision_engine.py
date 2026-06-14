#!/usr/bin/env python3
"""modules/trading_decision_engine/niblit_decision_engine.py

Niblit Decision Engine — deterministic memory-to-action reasoning layer.

Converts stored memory (Qdrant vector store + MemoryGraph + metadata) into
structured trading decisions compatible with Freqtrade execution logic.

Pipeline
--------
1. Query market context string
2. Retrieve Qdrant semantic memory via :class:`HybridQdrantManager`
3. Expand candidate set via :class:`MemoryGraph` multi-hop walk
4. Score aggregated memory signals (profit/loss/pattern keywords)
5. Apply risk-control constraints (confidence floor, memory floor, loss penalty)
6. Emit a :class:`TradingDecision`

Memory types used
-----------------
- ``semantic_memory``  — pattern, breakout, reversal, trend signals
- ``episodic_memory``  — event / system-behavior logs
- ``execution_memory`` — code / strategy-logic evolution
- ``reflection_memory``— profit, loss, win, error outcomes

Design notes
------------
* All third-party dependencies (qdrant, MemoryGraph, MemoryRouterCore) are
  injected at construction time so the engine is fully testable offline with
  mocks.
* ``HybridQdrantManager.query()`` returns dicts with keys ``id``, ``score``,
  ``payload``, ``model``.  Text is extracted from ``payload["text"]``.
* ``MemoryGraph.search()`` takes a float-list embedding and returns dicts with
  keys ``id``, ``text``, ``score``, ``hops``.  When no embedding is available
  (Qdrant returns no vectors) the graph expansion step is skipped gracefully.
* Risk controls:
    - NEVER trade if ``confidence < _MIN_CONFIDENCE`` (default 0.25)
    - ALWAYS hold if ``memory_count < _MIN_MEMORY_THRESHOLD`` (default 5)
    - Penalise repeated loss patterns by an additive ``_LOSS_PENALTY``
    - Reduce confidence by ``_CONFLICT_PENALTY`` fraction when both
      buy-positive and sell-positive signals co-exist in the same memory set
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("NiblitDecisionEngine")

# ── Risk-control constants (env-tuneable in a future iteration) ───────────────

# Minimum confidence required before any non-hold action is emitted.
_MIN_CONFIDENCE: float = 0.25

# Minimum number of retrieved memories required to trade; hold if below.
_MIN_MEMORY_THRESHOLD: int = 5

# Additive penalty applied to the running score for each loss/error token found.
_LOSS_PENALTY: float = 0.50

# Relative confidence reduction (fraction of abs-score) when opposing signals
# are simultaneously present (buy-positive AND sell-positive memories exist).
_CONFLICT_REDUCTION: float = 0.30

# ── Buy-positive and sell-positive keyword sets ───────────────────────────────

_BUY_KEYWORDS: dict[str, float] = {
    "profit": 0.40,
    "win": 0.40,
    "breakout": 0.30,
    "trend": 0.30,
    "reversal": 0.20,
    "bullish": 0.35,
    "momentum": 0.25,
    "support": 0.20,
    "recovery": 0.20,
    "accumulation": 0.25,
}

_SELL_KEYWORDS: dict[str, float] = {
    "loss": 0.50,
    "error": 0.50,
    "stop": 0.30,
    "bearish": 0.35,
    "breakdown": 0.30,
    "decline": 0.25,
    "resistance": 0.20,
    "drawdown": 0.35,
    "fail": 0.30,
}

# Qdrant collections to query, ordered by relevance for trading signals.
_TRADING_COLLECTIONS: list[str] = [
    "semantic_memory",
    "reflection_memory",
    "episodic_memory",
    "execution_memory",
]


# ─────────────────────────────────────────────────────────────────────────────
# TradingDecision dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradingDecision:
    """Structured output of :meth:`NiblitDecisionEngine.decide`.

    Attributes
    ----------
    action:     ``"buy"`` | ``"sell"`` | ``"hold"``
    confidence: Normalised confidence in [0, 1].
    symbol:     Trading pair / instrument (e.g. ``"BTC/USDT"``).
    reasoning:  Ordered list of memory snippets that drove this decision.
    metadata:   Supplementary diagnostics (memory_count, raw score, etc.).
    timestamp:  UNIX timestamp of decision creation.
    """

    action: str
    confidence: float
    symbol: str
    reasoning: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "symbol": self.symbol,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────────────
# NiblitDecisionEngine
# ─────────────────────────────────────────────────────────────────────────────

class NiblitDecisionEngine:
    """Converts Qdrant + MemoryGraph state into trading decisions.

    Parameters
    ----------
    qdrant_manager:
        A :class:`~modules.hybrid_qdrant_manager.HybridQdrantManager` instance
        (or any object with a compatible ``query(text, collection, top_k)``
        method returning a list of ``{"id", "score", "payload", "model"}``
        dicts).
    memory_graph:
        A :class:`~modules.memory_graph.MemoryGraph` instance (or any object
        with a compatible ``search(query_embedding, top_k)`` method returning
        a list of ``{"id", "text", "score", "hops"}`` dicts).
    router:
        A :class:`~modules.memory.router.memory_router.MemoryRouterCore`
        instance used to route new memory payloads into the correct collection.
        Currently reserved for future backprop / feedback loops; not required
        for inference.
    collections:
        Ordered list of Qdrant collection names to query.  Defaults to
        :data:`_TRADING_COLLECTIONS`.
    """

    def __init__(
        self,
        qdrant_manager: Any,
        memory_graph: Any,
        router: Any,
        *,
        collections: list[str] | None = None,
    ) -> None:
        self.qdrant = qdrant_manager
        self.graph = memory_graph
        self.router = router
        self._collections: list[str] = collections or list(_TRADING_COLLECTIONS)

    # ------------------------------------------------------------------
    # MEMORY RETRIEVAL LAYER
    # ------------------------------------------------------------------

    def retrieve_context(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Pull semantic memory from all configured Qdrant collections.

        Returns a flat list of result dicts, each containing at minimum
        ``text`` (extracted from ``payload``) and ``score``.
        """
        results: list[dict[str, Any]] = []
        for collection in self._collections:
            try:
                hits = self.qdrant.query(query, collection, top_k=limit)
                for hit in hits:
                    payload = hit.get("payload") or {}
                    text = (
                        payload.get("text")
                        or payload.get("content")
                        or payload.get("description")
                        or ""
                    )
                    results.append(
                        {
                            "id": hit.get("id"),
                            "text": str(text),
                            "score": float(hit.get("score", 0.0)),
                            "collection": collection,
                            "model": hit.get("model", ""),
                        }
                    )
            except Exception as exc:
                log.debug("[NiblitDecisionEngine] Qdrant query failed for '%s': %s", collection, exc)
        return results

    # ------------------------------------------------------------------
    # GRAPH EXPANSION LAYER
    # ------------------------------------------------------------------

    def expand_with_graph(self, memories: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        """Expand memory candidates via MemoryGraph multi-hop walk.

        For each Qdrant result that carries a vector embedding in its
        ``payload["embedding"]`` field, a graph search is performed and the
        neighbouring nodes are added to the candidate pool.

        When no embeddings are available the original list is returned
        unchanged (graceful degradation).
        """
        expanded: list[dict[str, Any]] = []
        for mem in memories:
            embedding = (mem.get("payload") or {}).get("embedding")
            if not embedding:
                continue
            try:
                neighbours = self.graph.search(embedding, top_k=top_k)
                for nb in neighbours:
                    expanded.append(
                        {
                            "id": nb.get("id"),
                            "text": str(nb.get("text", "")),
                            "score": float(nb.get("score", 0.0)),
                            "collection": "memory_graph",
                            "model": "graph",
                        }
                    )
            except Exception as exc:
                log.debug("[NiblitDecisionEngine] Graph expansion failed: %s", exc)
        return expanded

    # ------------------------------------------------------------------
    # DECISION SCORING ENGINE
    # ------------------------------------------------------------------

    def score_signal(self, memories: list[dict[str, Any]]) -> float:
        """Compute a scalar trading signal score from memory text content.

        Positive values favour a buy action; negative values favour a sell
        action.  The result is clamped to ``[-1.0, 1.0]``.

        Buy-positive keywords contribute positive weight.
        Sell-positive keywords contribute negative weight.
        Loss/error tokens also trigger an additional :data:`_LOSS_PENALTY`.
        """
        score = 0.0
        has_buy_signal = False
        has_sell_signal = False

        for mem in memories:
            text = mem.get("text", "").lower()
            if not text:
                continue

            for keyword, weight in _BUY_KEYWORDS.items():
                if keyword in text:
                    score += weight
                    has_buy_signal = True

            for keyword, weight in _SELL_KEYWORDS.items():
                if keyword in text:
                    score -= weight
                    has_sell_signal = True

            # Extra penalty for repeated loss/error patterns.
            if "loss" in text or "error" in text:
                score -= _LOSS_PENALTY

        # Conflict detection: both buy and sell signals present → reduce confidence.
        if has_buy_signal and has_sell_signal:
            score *= 1.0 - _CONFLICT_REDUCTION

        return max(-1.0, min(1.0, score))

    # ------------------------------------------------------------------
    # RISK CONTROL LAYER
    # ------------------------------------------------------------------

    def _apply_risk_controls(
        self,
        action: str,
        confidence: float,
        memory_count: int,
        score: float,
    ) -> tuple[str, float]:
        """Enforce safety constraints before emitting a trade signal.

        Rules
        -----
        1. Hold if ``memory_count < _MIN_MEMORY_THRESHOLD``.
        2. Hold if ``confidence < _MIN_CONFIDENCE``.

        Returns the (possibly overridden) ``(action, confidence)`` pair.
        """
        if memory_count < _MIN_MEMORY_THRESHOLD:
            log.debug(
                "[NiblitDecisionEngine] Insufficient memory (%d < %d) — forcing hold",
                memory_count,
                _MIN_MEMORY_THRESHOLD,
            )
            return "hold", 0.0

        if confidence < _MIN_CONFIDENCE:
            log.debug(
                "[NiblitDecisionEngine] Confidence too low (%.3f < %.3f) — forcing hold",
                confidence,
                _MIN_CONFIDENCE,
            )
            return "hold", confidence

        return action, confidence

    # ------------------------------------------------------------------
    # DECISION GENERATION
    # ------------------------------------------------------------------

    def decide(self, query: str, symbol: str, limit: int = 10) -> TradingDecision:
        """Generate a trading decision for *symbol* given a market-context *query*.

        Steps
        -----
        1. Retrieve semantic memories from Qdrant.
        2. Expand candidate pool via MemoryGraph.
        3. Score aggregated memories.
        4. Determine raw action from score thresholds.
        5. Apply risk-control constraints.
        6. Build and return :class:`TradingDecision`.

        Parameters
        ----------
        query:
            Natural-language description of the current market context
            (e.g. ``"BTC/USDT daily chart breakout above resistance"``).
        symbol:
            The trading pair / instrument identifier.
        limit:
            Maximum memories retrieved per Qdrant collection.
        """
        # Step 1 — Qdrant memory retrieval
        base_memories = self.retrieve_context(query, limit=limit)

        # Step 2 — Graph expansion
        graph_memories = self.expand_with_graph(base_memories, top_k=limit // 2 or 5)

        all_memories = base_memories + graph_memories
        memory_count = len(all_memories)

        # Step 3 — Signal scoring
        score = self.score_signal(all_memories)

        # Step 4 — Raw action from score thresholds
        if score > _MIN_CONFIDENCE:
            raw_action = "buy"
        elif score < -_MIN_CONFIDENCE:
            raw_action = "sell"
        else:
            raw_action = "hold"

        raw_confidence = abs(score)

        # Step 5 — Risk controls
        action, confidence = self._apply_risk_controls(
            raw_action, raw_confidence, memory_count, score
        )

        # Step 6 — Reasoning trace (top-10 non-empty snippets)
        reasoning: list[str] = []
        for mem in all_memories:
            text = mem.get("text", "").strip()
            if text:
                reasoning.append(text[:120])
            if len(reasoning) >= 10:
                break

        log.debug(
            "[NiblitDecisionEngine] symbol=%s action=%s confidence=%.3f "
            "score=%.3f memories=%d",
            symbol, action, confidence, score, memory_count,
        )

        return TradingDecision(
            action=action,
            confidence=confidence,
            symbol=symbol,
            reasoning=reasoning,
            metadata={
                "memory_count": memory_count,
                "qdrant_count": len(base_memories),
                "graph_count": len(graph_memories),
                "raw_score": round(score, 4),
                "raw_action": raw_action,
                "collections_queried": self._collections,
            },
            timestamp=time.time(),
        )
