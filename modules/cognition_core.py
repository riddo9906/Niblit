#!/usr/bin/env python3
"""
modules/cognition_core.py — Unified Cognitive Core for Niblit
=============================================================
The CognitionCore is the architectural "glue layer" that unifies all of
Niblit's cognitive subsystems into a single coherent update cycle.

It bridges four previously independent engines:

  ┌─────────────────┐    ┌──────────────────┐
  │  GoalEngine     │───▶│  ReasoningEngine │
  │  (what to learn)│    │  (how to think)  │
  └────────┬────────┘    └────────┬─────────┘
           │                      │
           ▼                      ▼
  ┌─────────────────┐    ┌──────────────────┐
  │  KnowledgeDB    │◀───│  Belief Synthesis│
  │  (what we know) │    │  (CoT → KB facts)│
  └────────┬────────┘    └──────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────┐
  │  MemoryGraph + apply_decay / prune      │
  │  (feedback-weighted long-term memory)   │
  └─────────────────────────────────────────┘

The ``think(topic)`` method runs one full cognitive pass:

  1. **Retrieve** — pull relevant facts from MemoryGraph and KnowledgeDB.
  2. **Reason** — run ReasoningEngine chain-of-thought on the retrieved facts.
  3. **Synthesize beliefs** — distil the CoT conclusion into a KB fact update
     (Upgrade 1: reasoning as internal belief updates, not just retrieval).
  4. **Reinforce** — apply reward-model delta to retrieved MemoryGraph nodes.
  5. **Generate goals** — ask GoalEngine for the next learning objectives
     (Upgrade 2: goal-driven cognition).
  6. Returns a :class:`CognitionResult` with all artefacts.

The ``run_maintenance()`` method performs periodic memory health tasks:

  * Apply temporal decay to MemoryGraph nodes inactive for 7+ days.
  * Prune nodes whose score has fallen below the minimum threshold.
  * Store a maintenance summary in the KB.

The ``cycle(knowledge_db, ale_context)`` method is designed to be called
once per ALE cycle and injects the generated goals back into
``ale_context["goal_objectives"]`` for Phase A of the next cycle.

Usage::

    from modules.cognition_core import CognitionCore

    core = CognitionCore()
    result = core.think("transformer attention mechanism", knowledge_db=kb)
    print(result.conclusion)
    print(result.goals[:3])

Singleton via ``get_cognition_core()``.

Configuration (environment variables)::

    NIBLIT_DECAY_DAYS_INACTIVE  — Days without access before decay kicks in
                                   (default 7.0)
    NIBLIT_DECAY_FACTOR         — Multiplicative decay per maintenance run
                                   (default 0.95)
    NIBLIT_DECAY_PRUNE_THRESHOLD — Score below which unused nodes are pruned
                                   (default 0.10)
    NIBLIT_COGNITION_MAINTENANCE_EVERY — Run maintenance every N cycles
                                          (default 5)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_DECAY_DAYS_INACTIVE = float(os.environ.get("NIBLIT_DECAY_DAYS_INACTIVE", "7.0"))
_DECAY_FACTOR = float(os.environ.get("NIBLIT_DECAY_FACTOR", "0.95"))
_DECAY_PRUNE_THRESHOLD = float(os.environ.get("NIBLIT_DECAY_PRUNE_THRESHOLD", "0.10"))
_MAINTENANCE_EVERY = int(os.environ.get("NIBLIT_COGNITION_MAINTENANCE_EVERY", "5"))

# ── Optional dependency imports (graceful degradation) ────────────────────────
try:
    from modules.reasoning_engine import get_reasoning_engine as _get_reasoning_engine
    _REASONING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _get_reasoning_engine = None  # type: ignore[assignment]
    _REASONING_AVAILABLE = False

try:
    from modules.memory_graph import get_memory_graph as _get_memory_graph
    _MEMORY_GRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _get_memory_graph = None  # type: ignore[assignment]
    _MEMORY_GRAPH_AVAILABLE = False

try:
    from modules.goal_engine import get_goal_engine as _get_goal_engine, Goal
    _GOAL_ENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _get_goal_engine = None  # type: ignore[assignment]
    Goal = None  # type: ignore[assignment,misc]
    _GOAL_ENGINE_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CognitionResult:
    """Output of a single ``CognitionCore.think()`` pass.

    Attributes
    ----------
    topic:       The topic that was reasoned about.
    conclusion:  The chain-of-thought conclusion string.
    confidence:  Confidence score for the conclusion (0–1).
    beliefs_updated: Number of KB belief-update facts written.
    goals:       List of :class:`~modules.goal_engine.Goal` objects generated.
    cot_steps:   Number of reasoning steps taken.
    source:      ``"llm"`` or ``"graph"`` depending on CoT backend used.
    latency_ms:  Wall-clock time for the think() call in milliseconds.
    ts:          UNIX timestamp of completion.
    """
    topic: str
    conclusion: str = ""
    confidence: float = 0.0
    beliefs_updated: int = 0
    goals: List[Any] = field(default_factory=list)
    cot_steps: int = 0
    source: str = "none"
    latency_ms: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "conclusion": self.conclusion,
            "confidence": round(self.confidence, 3),
            "beliefs_updated": self.beliefs_updated,
            "goals": [g.to_dict() if hasattr(g, "to_dict") else str(g) for g in self.goals[:5]],
            "cot_steps": self.cot_steps,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# CognitionCore
# ─────────────────────────────────────────────────────────────────────────────

class CognitionCore:
    """Unified cognitive orchestrator.

    Ties together ReasoningEngine, GoalEngine, MemoryGraph, and KnowledgeDB
    into a single coherent update cycle.

    Args:
        reasoning_engine: Optional :class:`~modules.reasoning_engine.ReasoningEngine`.
                          Defaults to module-level singleton when None.
        memory_graph:     Optional :class:`~modules.memory_graph.MemoryGraph`.
                          Defaults to module-level singleton when None.
        goal_engine:      Optional :class:`~modules.goal_engine.GoalEngine`.
                          Defaults to module-level singleton when None.
        knowledge_db:     Optional KnowledgeDB for belief persistence.
        decay_days_inactive: Days before inactive nodes start decaying.
        decay_factor:     Multiplicative decay coefficient per maintenance run.
        prune_threshold:  MemoryGraph nodes scoring below this are pruned.
        maintenance_every: Run decay+prune every N ``cycle()`` calls.
    """

    def __init__(
        self,
        reasoning_engine: Optional[Any] = None,
        memory_graph: Optional[Any] = None,
        goal_engine: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        decay_days_inactive: float = _DECAY_DAYS_INACTIVE,
        decay_factor: float = _DECAY_FACTOR,
        prune_threshold: float = _DECAY_PRUNE_THRESHOLD,
        maintenance_every: int = _MAINTENANCE_EVERY,
    ) -> None:
        # ── Wire subsystems ──────────────────────────────────────────────────
        if reasoning_engine is not None:
            self.reasoning_engine: Optional[Any] = reasoning_engine
        elif _REASONING_AVAILABLE and _get_reasoning_engine is not None:
            try:
                self.reasoning_engine = _get_reasoning_engine()
            except Exception:  # pragma: no cover
                self.reasoning_engine = None
        else:
            self.reasoning_engine = None

        if memory_graph is not None:
            self.memory_graph: Optional[Any] = memory_graph
        elif _MEMORY_GRAPH_AVAILABLE and _get_memory_graph is not None:
            try:
                self.memory_graph = _get_memory_graph()
            except Exception:  # pragma: no cover
                self.memory_graph = None
        else:
            self.memory_graph = None

        if goal_engine is not None:
            self.goal_engine: Optional[Any] = goal_engine
        elif _GOAL_ENGINE_AVAILABLE and _get_goal_engine is not None:
            try:
                self.goal_engine = _get_goal_engine()
            except Exception:  # pragma: no cover
                self.goal_engine = None
        else:
            self.goal_engine = None

        self.knowledge_db = knowledge_db

        # ── Decay / maintenance config ────────────────────────────────────────
        self._decay_days_inactive = decay_days_inactive
        self._decay_factor = decay_factor
        self._prune_threshold = prune_threshold
        self._maintenance_every = maintenance_every

        # ── State ─────────────────────────────────────────────────────────────
        self._lock = threading.Lock()
        self._cycle_count: int = 0
        self._think_count: int = 0
        self._last_maintenance_ts: Optional[int] = None
        self._stats: Dict[str, Any] = {
            "think_calls": 0,
            "cycle_calls": 0,
            "beliefs_updated_total": 0,
            "goals_generated_total": 0,
            "maintenance_runs": 0,
            "nodes_decayed_total": 0,
            "nodes_pruned_total": 0,
        }

        log.info(
            "[CognitionCore] Initialised — reasoning=%s memory_graph=%s "
            "goal_engine=%s decay_days=%.1f prune_threshold=%.2f",
            self.reasoning_engine is not None,
            self.memory_graph is not None,
            self.goal_engine is not None,
            self._decay_days_inactive,
            self._prune_threshold,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Upgrade 1 — Reasoning as belief synthesis
    # ─────────────────────────────────────────────────────────────────────────

    def think(
        self,
        topic: str,
        facts: Optional[List[Dict[str, Any]]] = None,
        knowledge_db: Optional[Any] = None,
        ale_context: Optional[Dict[str, Any]] = None,
    ) -> CognitionResult:
        """Run a full cognitive pass for *topic*.

        Steps
        -----
        1. **Retrieve** recent KB facts for the topic (if knowledge_db provided).
        2. **Build knowledge graph** — feed retrieved facts into ReasoningEngine.
        3. **Chain-of-thought** — reason over the knowledge graph.
        4. **Synthesize belief** — write the CoT conclusion back to the KB as
           a structured belief-update fact (``ale_belief:<ts>``).
        5. **Reinforce graph nodes** — apply a small positive score delta to
           nodes that were used during reasoning.
        6. **Generate goals** — ask GoalEngine for learning objectives given
           the current context.

        Args:
            topic:        The concept or question to reason about.
            facts:        Pre-loaded facts (optional; auto-loaded from KB when
                          *knowledge_db* is set).
            knowledge_db: Override instance KnowledgeDB for this call only.
            ale_context:  ALE cross-cycle context dict for GoalEngine input.

        Returns:
            :class:`CognitionResult` with conclusion, confidence, goals, etc.
        """
        t0 = time.time()
        kb = knowledge_db or self.knowledge_db
        result = CognitionResult(topic=topic)

        # ── Step 1: Retrieve facts ────────────────────────────────────────────
        if facts is None:
            facts = self._retrieve_facts(topic, kb)

        # ── Step 2–3: Build graph + chain-of-thought ──────────────────────────
        cot = None
        if self.reasoning_engine is not None:
            try:
                if facts:
                    self.reasoning_engine.build_knowledge_graph(facts)
                cot = self.reasoning_engine.chain_of_thought(topic, facts=facts)
                result.conclusion = cot.conclusion or ""
                result.confidence = cot.confidence
                result.cot_steps = len(cot.steps)
                result.source = getattr(cot, "source", "graph")
                log.debug(
                    "[CognitionCore] CoT for '%s': %d steps, conf=%.2f, src=%s",
                    topic[:60], result.cot_steps, result.confidence, result.source,
                )
            except Exception as exc:
                log.debug("[CognitionCore] chain_of_thought failed: %s", exc)

        # ── Step 4: Synthesize belief → KB ────────────────────────────────────
        if result.conclusion and kb is not None:
            written = self._write_belief(topic, result.conclusion, result.confidence, kb)
            result.beliefs_updated = written

        # ── Step 5: Reinforce MemoryGraph nodes used during CoT ──────────────
        if cot is not None and self.memory_graph is not None:
            self._reinforce_from_cot(cot)

        # ── Step 6: Generate goals ────────────────────────────────────────────
        if self.goal_engine is not None:
            try:
                result.goals = self.goal_engine.generate_goals(
                    knowledge_db=kb,
                    ale_context=ale_context or {},
                    reasoning_engine=self.reasoning_engine,
                )
            except Exception as exc:
                log.debug("[CognitionCore] goal generation failed: %s", exc)

        result.latency_ms = (time.time() - t0) * 1000
        result.ts = int(time.time())

        with self._lock:
            self._stats["think_calls"] += 1
            self._stats["beliefs_updated_total"] += result.beliefs_updated
            self._stats["goals_generated_total"] += len(result.goals)
            self._think_count += 1

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Upgrade 3 — Feedback-weighted memory maintenance
    # ─────────────────────────────────────────────────────────────────────────

    def run_maintenance(self, knowledge_db: Optional[Any] = None) -> Dict[str, Any]:
        """Apply memory decay and prune low-scoring nodes.

        This implements Upgrade 3 (feedback-weighted learning): knowledge that
        is never retrieved gradually loses weight; knowledge that is repeatedly
        useful retains and grows its score.

        Args:
            knowledge_db: Optional KB for storing the maintenance summary.

        Returns:
            Dict with ``decayed``, ``pruned``, ``nodes_before``, ``nodes_after``.
        """
        kb = knowledge_db or self.knowledge_db
        summary: Dict[str, Any] = {
            "decayed": 0,
            "pruned": 0,
            "nodes_before": 0,
            "nodes_after": 0,
        }

        if self.memory_graph is None:
            return summary

        summary["nodes_before"] = self.memory_graph.count()

        # Apply temporal decay
        try:
            decayed = self.memory_graph.apply_decay(
                days_inactive=self._decay_days_inactive,
                decay_factor=self._decay_factor,
            )
            summary["decayed"] = decayed
        except Exception as exc:
            log.debug("[CognitionCore] apply_decay failed: %s", exc)

        # Prune nodes that have fallen below the score floor
        try:
            pruned = self.memory_graph.prune_low_score(min_score=self._prune_threshold)
            summary["pruned"] = pruned
        except Exception as exc:
            log.debug("[CognitionCore] prune_low_score failed: %s", exc)

        summary["nodes_after"] = self.memory_graph.count()

        # Persist summary to KB
        if kb is not None:
            try:
                kb.add_fact(
                    f"ale_memory_maintenance:{int(time.time())}",
                    summary,
                    tags=["memory", "decay", "maintenance", "cognition_core"],
                )
            except Exception:
                pass

        self._last_maintenance_ts = int(time.time())
        with self._lock:
            self._stats["maintenance_runs"] += 1
            self._stats["nodes_decayed_total"] += summary["decayed"]
            self._stats["nodes_pruned_total"] += summary["pruned"]

        log.info(
            "[CognitionCore] Maintenance: decayed=%d pruned=%d "
            "nodes %d→%d",
            summary["decayed"], summary["pruned"],
            summary["nodes_before"], summary["nodes_after"],
        )
        return summary

    # ─────────────────────────────────────────────────────────────────────────
    # Upgrade 4 — Unified cycle (ALE integration)
    # ─────────────────────────────────────────────────────────────────────────

    def cycle(
        self,
        knowledge_db: Optional[Any] = None,
        ale_context: Optional[Dict[str, Any]] = None,
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one full cognitive cycle — designed to be called by ALE.

        Performs a ``think()`` pass on *topic* (or a goal-derived topic when
        *topic* is None), injects the generated goals back into *ale_context*
        under the ``"goal_objectives"`` key, and conditionally runs memory
        maintenance every :attr:`_maintenance_every` cycles.

        Args:
            knowledge_db: KnowledgeDB instance.
            ale_context:  ALE ``_cross_cycle_context`` dict — updated in place
                          with ``goal_objectives`` and ``cognition_conclusion``.
            topic:        Optional topic override.  Falls back to the top
                          goal topic from the previous cycle's GoalEngine output.

        Returns:
            Summary dict with keys: ``topic``, ``conclusion``, ``confidence``,
            ``goals_count``, ``maintenance_ran``, ``cycle_count``.
        """
        kb = knowledge_db or self.knowledge_db
        ctx = ale_context if ale_context is not None else {}

        # Resolve topic: explicit > last goal > fallback
        if not topic:
            if self.goal_engine is not None:
                top = self.goal_engine.top_topics(1)
                topic = top[0] if top else "self-improvement cognition"
            else:
                topic = "self-improvement cognition"

        # Run cognitive pass
        result = self.think(topic, knowledge_db=kb, ale_context=ctx)

        # Inject goals into ALE cross-cycle context
        if result.goals:
            ctx["goal_objectives"] = [g.to_dict() if hasattr(g, "to_dict") else str(g) for g in result.goals]
            ctx["cognition_conclusion"] = result.conclusion
            log.info(
                "[CognitionCore] Injected %d goals into ALE context",
                len(result.goals),
            )

        # Periodic maintenance
        maintenance_ran = False
        with self._lock:
            self._cycle_count += 1
            self._stats["cycle_calls"] += 1
            cycle_no = self._cycle_count

        if cycle_no % self._maintenance_every == 0:
            self.run_maintenance(knowledge_db=kb)
            maintenance_ran = True

        return {
            "topic": topic,
            "conclusion": result.conclusion,
            "confidence": result.confidence,
            "goals_count": len(result.goals),
            "beliefs_updated": result.beliefs_updated,
            "maintenance_ran": maintenance_ran,
            "cycle_count": cycle_no,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _retrieve_facts(
        self, topic: str, knowledge_db: Optional[Any]
    ) -> List[Dict[str, Any]]:
        """Retrieve KB facts relevant to *topic*."""
        if knowledge_db is None:
            return []
        facts: List[Dict[str, Any]] = []
        try:
            for prefix in ("topic_knowledge:", "ale_research:", "ale_reflection:"):
                if hasattr(knowledge_db, "search"):
                    raw = knowledge_db.search(prefix + topic[:30]) or []
                    for item in raw[:5]:
                        if isinstance(item, dict):
                            facts.append({
                                "key": str(item.get("key", prefix)),
                                "value": str(item.get("value", item.get("text", "")))[:500],
                            })
                        elif isinstance(item, str):
                            facts.append({"key": prefix, "value": item[:500]})
        except Exception as exc:
            log.debug("[CognitionCore] _retrieve_facts failed: %s", exc)
        return facts[:20]

    def _write_belief(
        self,
        topic: str,
        conclusion: str,
        confidence: float,
        knowledge_db: Any,
    ) -> int:
        """Write a CoT conclusion as a belief-update fact to the KB.

        Returns 1 if written successfully, 0 otherwise.
        """
        if not conclusion or confidence < 0.1:
            return 0
        try:
            knowledge_db.add_fact(
                f"ale_belief:{int(time.time())}",
                {
                    "topic": topic,
                    "conclusion": conclusion,
                    "confidence": round(confidence, 3),
                    "source": "cognition_core_cot",
                },
                tags=["belief", "cognition", "reasoning", "cot"],
            )
            log.debug(
                "[CognitionCore] Wrote belief update for '%s' (conf=%.2f)",
                topic[:60], confidence,
            )
            return 1
        except Exception as exc:
            log.debug("[CognitionCore] _write_belief failed: %s", exc)
            return 0

    def _reinforce_from_cot(self, cot: Any) -> None:
        """Reinforce MemoryGraph nodes that contributed to the CoT reasoning."""
        if self.memory_graph is None:
            return
        try:
            # Extract concepts mentioned in CoT steps and reinforce them
            concepts: List[str] = []
            for step in getattr(cot, "steps", []):
                q = getattr(step, "question", "")
                a = getattr(step, "answer", "")
                # Pull quoted concept names from step text
                import re
                concepts.extend(re.findall(r"'([^']{2,40})'", f"{q} {a}"))

            for concept in set(concepts[:10]):
                # Reinforce any matching node in the graph
                with self.memory_graph._lock:
                    for nid, nd in self.memory_graph._nodes.items():
                        if concept.lower() in nd.text.lower():
                            nd.adjust_score(0.02)  # small positive delta
                            nd.touch()
                            break
        except Exception as exc:
            log.debug("[CognitionCore] _reinforce_from_cot failed: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a status dict for this core."""
        with self._lock:
            stats = dict(self._stats)
        result: Dict[str, Any] = {
            **stats,
            "reasoning_available": self.reasoning_engine is not None,
            "memory_graph_available": self.memory_graph is not None,
            "goal_engine_available": self.goal_engine is not None,
            "decay_days_inactive": self._decay_days_inactive,
            "decay_factor": self._decay_factor,
            "prune_threshold": self._prune_threshold,
            "last_maintenance_ts": self._last_maintenance_ts,
        }
        if self.memory_graph is not None:
            try:
                result["memory_graph_stats"] = self.memory_graph.stats()
            except Exception:  # pragma: no cover
                pass
        if self.goal_engine is not None:
            try:
                result["goal_engine_status"] = self.goal_engine.status()
            except Exception:  # pragma: no cover
                pass
        return result


# ── Singleton ─────────────────────────────────────────────────────────────────
_core: Optional[CognitionCore] = None
_core_lock = threading.Lock()


def get_cognition_core(**kwargs) -> CognitionCore:
    """Return the process-level :class:`CognitionCore` singleton."""
    global _core  # pylint: disable=global-statement
    with _core_lock:
        if _core is None:
            _core = CognitionCore(**kwargs)
        return _core


if __name__ == "__main__":
    print('Running cognition_core.py')
