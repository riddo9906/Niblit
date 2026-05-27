#!/usr/bin/env python3
"""modules/knowledge_gap_cognition.py — Governed Llama3 Knowledge-Gap Cognition Layer.

This module is a GOVERNED COGNITION AUGMENTATION LAYER.  It is NOT:
- a standalone orchestrator
- a new event system
- a replacement for ALE
- a direct autonomous coding engine

It IS:
- an additive escalation layer that extends existing ALE cognition when
  knowledge gaps, failed research, or low-confidence synthesis are detected.

All inference is routed through the canonical path:
    RuntimeRouterV2 → LocalBrain.route_inference()

No direct provider HTTP calls are made here.

Architecture
------------
CognitionEscalationLayer
  .escalate(gap)
    → build governed prompt
    → RuntimeRouterV2.generate()      ← canonical router (uses LocalBrain)
    → normalize via memory_contracts.normalize_memory_payload()
    → emit EventBus events
    → record TelemetryCollector counters
    → (optional) write to governed_qdrant_memory

Public API
----------
``KnowledgeGapSignal``
    Dataclass describing a detected knowledge gap.

``CognitionEscalationLayer``
    Governed synthesis layer with feature-flag and budget controls.

``get_cognition_escalation_layer()``
    Process-level singleton.

Configuration (env vars)
------------------------
    NIBLIT_COGNITION_ESCALATION_ENABLED  — "0" to disable entirely (default 1)
    NIBLIT_COGNITION_MAX_BUDGET          — max escalations per ALE cycle (default 3)
    NIBLIT_COGNITION_CONFIDENCE_FLOOR    — min gap confidence to trigger (default 0.4)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("Niblit.KnowledgeGapCognition")

# ── Feature flags & thresholds ─────────────────────────────────────────────────

_ENABLED: bool = os.getenv("NIBLIT_COGNITION_ESCALATION_ENABLED", "1").strip().lower() not in ("0", "false")
_MAX_BUDGET: int = max(1, int(os.getenv("NIBLIT_COGNITION_MAX_BUDGET", "3")))
_CONFIDENCE_FLOOR: float = float(os.getenv("NIBLIT_COGNITION_CONFIDENCE_FLOOR", "0.4"))
_MIN_SYNTHESIS_WORD_COUNT: float = 80.0

# ── Gap class constants ────────────────────────────────────────────────────────

GAP_CLASS_RESEARCH    = "research_gap"
GAP_CLASS_SYNTHESIS   = "synthesis_gap"
GAP_CLASS_REFLECTION  = "reflection_gap"
GAP_CLASS_ARCHITECTURE = "architecture_gap"
GAP_CLASS_MARKET      = "market_gap"
GAP_CLASS_TELEMETRY   = "telemetry_gap"
GAP_CLASS_METACOGNITION = "metacognition_gap"

# Memory type produced per gap class
_GAP_MEMORY_MAP: dict[str, str] = {
    GAP_CLASS_RESEARCH:     "semantic_memory",
    GAP_CLASS_SYNTHESIS:    "reflection_memory",
    GAP_CLASS_REFLECTION:   "reflection_memory",
    GAP_CLASS_ARCHITECTURE: "runtime_memory",
    GAP_CLASS_MARKET:       "semantic_memory",
    GAP_CLASS_TELEMETRY:    "runtime_memory",
    GAP_CLASS_METACOGNITION: "reflection_memory",
}


# ── KnowledgeGapSignal ─────────────────────────────────────────────────────────

@dataclass
class KnowledgeGapSignal:
    """Describes a detected cognition gap that requires escalation.

    Attributes
    ----------
    gap_class:   One of the GAP_CLASS_* constants above.
    topic:       Human-readable subject (e.g. "async python patterns").
    reason:      Machine-readable reason code (e.g. "empty_research_results").
    context:     Optional serialisable context dict (search query, prior facts, …).
    confidence:  Estimated existing confidence 0–1.  Gap triggers when < floor.
    trace_id:    Lineage identifier propagated to memory and telemetry.
    source_module: Name of the calling module for telemetry attribution.
    """

    gap_class: str = GAP_CLASS_RESEARCH
    topic: str = ""
    reason: str = "unknown"
    context: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    trace_id: str = ""
    source_module: str = "unknown"

    def __post_init__(self) -> None:
        if not self.trace_id:
            seed = f"{self.gap_class}:{self.topic}:{int(time.time())}"
            self.trace_id = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:16]


# ── Prompt builders (one per gap class) ───────────────────────────────────────

def _build_research_prompt(gap: KnowledgeGapSignal) -> str:
    ctx = gap.context.get("prior_knowledge", "")
    return (
        f"You are a knowledge synthesis assistant for a governed AI runtime.\n"
        f"Internet research for the topic '{gap.topic}' returned no usable results.\n"
        f"Prior knowledge: {ctx[:400] if ctx else 'none'}\n\n"
        f"Synthesize a concise, factual overview of '{gap.topic}' based on your training.\n"
        f"Focus on: key concepts, typical usage, common patterns, and potential pitfalls.\n"
        f"Keep your response under 400 words. Do not fabricate specific URLs or citations."
    )


def _build_reflection_prompt(gap: KnowledgeGapSignal) -> str:
    health = gap.context.get("health", 0.0)
    failures = gap.context.get("failures", [])
    return (
        f"You are a reflection synthesis assistant for a governed AI runtime.\n"
        f"The reflection engine reports low system health ({health:.2f}).\n"
        f"Detected failures: {failures[:5]}\n\n"
        f"Provide a structured self-improvement synthesis with:\n"
        f"1. Root cause hypothesis for the observed quality degradation.\n"
        f"2. Three concrete adaptation proposals.\n"
        f"3. Recommended knowledge areas to reinforce.\n"
        f"Keep your response under 300 words. Do not suggest autonomous code changes."
    )


def _build_metacognition_prompt(gap: KnowledgeGapSignal) -> str:
    quality = gap.context.get("knowledge_quality", "unknown")
    pct = gap.context.get("confidence_pct", "unknown")
    return (
        f"You are a metacognition synthesis assistant for a governed AI runtime.\n"
        f"Current knowledge quality: {quality} ({pct}% confidence).\n"
        f"Topic area: {gap.topic}\n\n"
        f"Synthesize:\n"
        f"1. Which conceptual areas in '{gap.topic}' are most likely under-represented.\n"
        f"2. Recommended learning topics to raise confidence.\n"
        f"3. How to detect when this knowledge gap is resolved.\n"
        f"Keep your response under 250 words."
    )


def _build_architecture_prompt(gap: KnowledgeGapSignal) -> str:
    return (
        f"You are an architecture interpretation assistant for a governed AI runtime.\n"
        f"Topic: '{gap.topic}'\n"
        f"Reason: {gap.reason}\n\n"
        f"Synthesize:\n"
        f"1. Key architectural concepts relevant to this topic.\n"
        f"2. Integration patterns and tradeoffs.\n"
        f"3. Governance and safety considerations.\n"
        f"Keep your response under 350 words. Do not suggest filesystem or code mutations."
    )


def _build_market_prompt(gap: KnowledgeGapSignal) -> str:
    ctx = gap.context.get("market_context", "")
    return (
        f"You are a market cognition synthesis assistant for a governed AI runtime.\n"
        f"Topic: '{gap.topic}'\n"
        f"Market context: {ctx[:400] if ctx else 'insufficient data'}\n\n"
        f"Synthesize:\n"
        f"1. Observable market regime characteristics.\n"
        f"2. Volatility and risk pattern interpretation.\n"
        f"3. Long-term structural observations relevant to strategy evaluation.\n"
        f"Keep your response under 350 words. Do NOT suggest specific trade actions."
    )


def _build_generic_prompt(gap: KnowledgeGapSignal) -> str:
    return (
        f"You are a governed cognitive synthesis assistant.\n"
        f"Gap class: {gap.gap_class} | Topic: '{gap.topic}' | Reason: {gap.reason}\n\n"
        f"Provide a concise, factual synthesis to fill this knowledge gap.\n"
        f"Keep your response under 300 words."
    )


_PROMPT_BUILDERS = {
    GAP_CLASS_RESEARCH:     _build_research_prompt,
    GAP_CLASS_SYNTHESIS:    _build_reflection_prompt,
    GAP_CLASS_REFLECTION:   _build_reflection_prompt,
    GAP_CLASS_ARCHITECTURE: _build_architecture_prompt,
    GAP_CLASS_MARKET:       _build_market_prompt,
    GAP_CLASS_TELEMETRY:    _build_generic_prompt,
    GAP_CLASS_METACOGNITION: _build_metacognition_prompt,
}


# ── CognitionEscalationLayer ───────────────────────────────────────────────────

class CognitionEscalationLayer:
    """Governed runtime cognition fallback layer.

    Routes unresolved cognition tasks through:
        RuntimeRouterV2 → LocalBrain.route_inference()

    Does NOT:
    - make direct provider HTTP calls
    - bypass LocalBrain or RuntimeRouterV2
    - mutate repositories, deploy code, or execute trades
    - bypass governance or approval systems

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._budget_used: int = 0
        self._budget_reset_cycle: int = 0
        # Telemetry metrics
        self._gap_count: int = 0
        self._success_count: int = 0
        self._failure_count: int = 0
        self._quality_sum: float = 0.0
        self._router: Any = None
        log.debug("[CognitionEscalation] initialised (enabled=%s, budget=%d)", _ENABLED, _MAX_BUDGET)

    # ── Router access (canonical path only) ───────────────────────────────────

    def _get_router(self) -> Any:
        """Lazily resolve RuntimeRouterV2 — canonical inference path."""
        if self._router is not None:
            return self._router
        try:
            from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2
            self._router = NiblitUnifiedRuntimeRouterV2()
        except Exception as exc:
            log.debug("[CognitionEscalation] RuntimeRouterV2 unavailable: %s", exc)
        return self._router

    # ── Budget management ──────────────────────────────────────────────────────

    def reset_cycle_budget(self, cycle_id: int = 0) -> None:
        """Reset per-cycle budget counter (call at ALE cycle start)."""
        with self._lock:
            self._reset_cycle_budget_unlocked(cycle_id)

    def _reset_cycle_budget_unlocked(self, cycle_id: int = 0) -> None:
        """Reset per-cycle budget counter (caller must hold self._lock).

        Kept separate from :meth:`reset_cycle_budget` to avoid lock re-entry
        deadlocks when budget checks happen inside other lock-protected paths.
        """
        if cycle_id != self._budget_reset_cycle:
            self._budget_used = 0
            self._budget_reset_cycle = cycle_id

    # ── Main escalation entry point ────────────────────────────────────────────

    def escalate(
        self,
        gap: KnowledgeGapSignal,
        *,
        write_memory: bool = True,
        cycle_id: int = 0,
    ) -> dict[str, Any]:
        """Escalate a knowledge gap through the canonical governed inference path.

        Parameters
        ----------
        gap:          The gap signal describing what needs to be synthesised.
        write_memory: If True (default), persist normalised output to governed
                      memory when synthesis succeeds.
        cycle_id:     ALE cycle identifier for budget tracking.

        Returns
        -------
        dict with keys:
            synthesis (str)   — the synthesised text, or "" on failure
            success   (bool)
            trace_id  (str)
            gap_class (str)
            memory_type (str)
            quality   (float) — estimated synthesis quality 0–1
        """
        result: dict[str, Any] = {
            "synthesis": "",
            "success": False,
            "trace_id": gap.trace_id,
            "gap_class": gap.gap_class,
            "memory_type": _GAP_MEMORY_MAP.get(gap.gap_class, "semantic_memory"),
            "quality": 0.0,
        }

        if not _ENABLED:
            return result

        # Budget guard — prevent runaway loops
        with self._lock:
            self._reset_cycle_budget_unlocked(cycle_id)
            if self._budget_used >= _MAX_BUDGET:
                log.debug(
                    "[CognitionEscalation] Budget exhausted (used=%d, max=%d) — skipping %r",
                    self._budget_used, _MAX_BUDGET, gap.topic,
                )
                return result
            self._budget_used += 1
            self._gap_count += 1

        # Emit gap-detected event
        self._emit_event("cognition.gap.detected", gap)

        # Record telemetry counter
        self._increment_counter("cognition.gap.detected", gap.gap_class)

        t0 = time.monotonic()
        try:
            router = self._get_router()
            if router is None:
                raise RuntimeError("RuntimeRouterV2 unavailable")

            prompt_builder = _PROMPT_BUILDERS.get(gap.gap_class, _build_generic_prompt)
            prompt = prompt_builder(gap)

            # Canonical routing: RuntimeRouterV2 → LocalBrain.route_inference()
            synthesis = router.generate(prompt=prompt, context=gap.context.get("prior_knowledge"))

            if not synthesis or synthesis.strip() == "[RuntimeRouterV2] empty response":
                raise RuntimeError("empty synthesis response")

            duration_ms = (time.monotonic() - t0) * 1000
            quality = self._estimate_quality(synthesis, gap)

            result.update({
                "synthesis": synthesis,
                "success": True,
                "quality": quality,
            })

            with self._lock:
                self._success_count += 1
                self._quality_sum += quality

            # Persist to governed memory
            if write_memory:
                self._write_governed_memory(gap, synthesis, quality)

            # Record telemetry
            self._record_histogram("cognition.synthesis_quality", quality)
            self._record_histogram("cognition.synthesis_duration_ms", duration_ms)
            self._increment_counter("cognition.synthesis.success", gap.gap_class)

            # Emit synthesis-complete event
            self._emit_event("cognition.synthesis.complete", gap, extra={
                "quality": quality,
                "duration_ms": duration_ms,
            })

            log.info(
                "[CognitionEscalation] ✅ %s/%r synthesised (quality=%.2f, %.0fms)",
                gap.gap_class, gap.topic[:60], quality, duration_ms,
            )

        except Exception as exc:
            with self._lock:
                self._failure_count += 1
            self._increment_counter("cognition.synthesis.failure", gap.gap_class)
            log.debug("[CognitionEscalation] ❌ %s/%r failed: %s", gap.gap_class, gap.topic[:60], exc)

        return result

    # ── Quality estimation (heuristic — no external call) ─────────────────────

    @staticmethod
    def _estimate_quality(synthesis: str, gap: KnowledgeGapSignal) -> float:
        """Estimate synthesis quality from basic heuristics."""
        if not synthesis:
            return 0.0
        word_count = len(synthesis.split())
        length_score = min(1.0, word_count / _MIN_SYNTHESIS_WORD_COUNT)
        # Penalise if synthesis just echoes the topic verbatim
        topic_words = set(gap.topic.lower().split())
        synth_words = set(synthesis.lower().split())
        overlap = len(topic_words & synth_words) / max(1, len(topic_words))
        novelty_score = max(0.0, 1.0 - overlap * 0.5)
        return round((length_score * 0.6 + novelty_score * 0.4), 3)

    # ── Governed memory write ──────────────────────────────────────────────────

    def _write_governed_memory(
        self,
        gap: KnowledgeGapSignal,
        synthesis: str,
        quality: float,
    ) -> None:
        """Normalise and persist to governed memory (non-blocking, never raises)."""
        try:
            from shared.governance_contract.memory_contracts import normalize_memory_payload
            memory_type = _GAP_MEMORY_MAP.get(gap.gap_class, "semantic_memory")

            payload = normalize_memory_payload(
                {
                    "summary": synthesis[:240],
                    "coherence_score": quality,
                    "importance_score": max(0.5, quality),
                    "advisor_lineage": [gap.source_module, "knowledge_gap_cognition"],
                    "causal_chain": [gap.reason],
                    "replay_metadata": {
                        "trace_id": gap.trace_id,
                        "causal_references": [gap.reason, gap.gap_class],
                        "decision_lineage": [f"gap_escalation:{gap.gap_class}"],
                    },
                    "telemetry": {
                        "source": "knowledge_gap_cognition",
                        "trace_id": gap.trace_id,
                    },
                },
                text=synthesis,
                memory_type=memory_type,
                node_identity="niblit_core",
                authority="knowledge_gap_cognition",
            )

            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster
            cluster = get_governed_qdrant_memory_cluster()
            cluster.write_memory(synthesis, memory_type=memory_type, payload=payload)
            log.debug("[CognitionEscalation] memory written (type=%s, trace=%s)", memory_type, gap.trace_id)
        except Exception as exc:
            log.debug("[CognitionEscalation] governed memory write skipped: %s", exc)

    # ── Event emission ─────────────────────────────────────────────────────────

    def _emit_event(
        self,
        event_type: str,
        gap: KnowledgeGapSignal,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            from modules.event_bus import NiblitEvent, get_event_bus
            payload: dict[str, Any] = {
                "gap_class": gap.gap_class,
                "topic": gap.topic,
                "trace_id": gap.trace_id,
                "source_module": gap.source_module,
            }
            if extra:
                payload.update(extra)
            get_event_bus().publish(NiblitEvent(
                type=event_type,
                source="knowledge_gap_cognition",
                payload=payload,
            ))
        except Exception:
            pass

    # ── Telemetry helpers ──────────────────────────────────────────────────────

    def _increment_counter(self, name: str, label: str = "") -> None:
        try:
            from modules.metrics_observability import get_telemetry_collector
            collector = get_telemetry_collector()
            if collector:
                full_name = f"{name}.{label}" if label else name
                collector.increment_counter(full_name)
        except Exception:
            pass

    def _record_histogram(self, name: str, value: float) -> None:
        try:
            from modules.metrics_observability import get_telemetry_collector
            collector = get_telemetry_collector()
            if collector:
                collector.record_histogram(name, value)
        except Exception:
            pass

    # ── Metrics snapshot ───────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        """Return a snapshot of cognition escalation metrics."""
        with self._lock:
            total = self._success_count + self._failure_count
            return {
                "enabled": _ENABLED,
                "gap_detected_total": self._gap_count,
                "synthesis_success": self._success_count,
                "synthesis_failure": self._failure_count,
                "synthesis_success_rate": round(self._success_count / total, 3) if total else 0.0,
                "avg_synthesis_quality": round(self._quality_sum / max(1, self._success_count), 3),
                "budget_used_this_cycle": self._budget_used,
                "budget_max": _MAX_BUDGET,
            }


# ── Singleton ──────────────────────────────────────────────────────────────────

_layer: CognitionEscalationLayer | None = None
_layer_lock = threading.Lock()


def get_cognition_escalation_layer() -> CognitionEscalationLayer:
    """Return the process-level :class:`CognitionEscalationLayer` singleton."""
    global _layer
    with _layer_lock:
        if _layer is None:
            _layer = CognitionEscalationLayer()
    return _layer


if __name__ == "__main__":
    print("Running knowledge_gap_cognition.py")
