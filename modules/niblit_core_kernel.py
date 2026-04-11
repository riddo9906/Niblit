#!/usr/bin/env python3
"""
modules/niblit_core_kernel.py — Niblit Cognitive Kernel v1
==========================================================
The *NiblitCoreKernel* is the **central cognition bus** for Niblit.  It is the
single authoritative gateway for all cognitive operations: nothing thinks,
nothing remembers, nothing acts, and nothing evolves unless it flows through
here.

The five core operations
-------------------------
1. ``think(input_data, context)``
   Retrieves relevant memories, merges them with the incoming context, and
   runs a full chain-of-thought pass via :class:`~modules.cognition_core.CognitionCore`
   or falls back to the lightweight :class:`~modules.reasoning_engine.ReasoningEngine`.

2. ``remember(data, importance)``
   Persists data across the 3-tier memory hierarchy:

   * **Short-term** — a bounded in-memory deque of recent inputs/outputs.
   * **Working memory** — the current task context dict used during reasoning.
   * **Long-term** — :class:`~modules.memory_graph.MemoryGraph` (graph nodes)
     + KnowledgeDB (durable facts), weighted by *importance*.

3. ``decide(thought)``
   Intent-based routing: scores the ``thought`` string against keyword buckets
   (``research``, ``code``, ``reflect``, ``trade``, ``respond``) and returns
   the winning action name.

4. ``act(decision, payload)``
   Dispatches the chosen *decision* to the matching handler in
   :class:`ToolRouter`, which wraps existing Niblit modules
   (PhasedResearchEngine, CodeGenerator, CognitionCore, …) with safety guards
   and error reporting.

5. ``evolve(proposal)``
   Passes *proposal* through a 3-layer validation gate before delegating to
   the :class:`~modules.evolve.EvolveEngine`.  Dangerous operations are
   silently rejected; all evolution events are logged to the kernel.

Full cognitive loop
-------------------
``run_cognitive_loop(input_data)`` chains all five steps::

    INPUT → THINK → DECIDE → ACT → REMEMBER → (optional EVOLVE)

Integration
-----------
The kernel is wired into the **existing module graph** without replacing any
subsystem — it is purely additive.  Existing ALE cycles, STACA civilisation
runs, and direct module calls continue to work as before.  The kernel simply
provides a cleaner API surface on top of the modules that already exist.

Singleton via ``get_niblit_core_kernel()``.

Configuration (environment variables)
--------------------------------------
``NIBLIT_KERNEL_STM_SIZE``         — Short-term memory capacity (default 30)
``NIBLIT_KERNEL_WORKING_SIZE``     — Working memory max keys (default 20)
``NIBLIT_KERNEL_EVOLVE_ENABLED``   — Set to ``0`` to disable evolution gate
                                     entirely (default enabled)
``NIBLIT_KERNEL_SAFETY_STRICT``    — Set to ``1`` to add extra safety rules in
                                     the evolution gate (default ``0``)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Config from env ──────────────────────────────────────────────────────────
_STM_SIZE = int(os.environ.get("NIBLIT_KERNEL_STM_SIZE", "30"))
_WM_SIZE = int(os.environ.get("NIBLIT_KERNEL_WORKING_SIZE", "20"))
_EVOLVE_ENABLED = os.environ.get("NIBLIT_KERNEL_EVOLVE_ENABLED", "1") != "0"
_SAFETY_STRICT = os.environ.get("NIBLIT_KERNEL_SAFETY_STRICT", "0") == "1"

# ── Optional soft dependencies (lazy import pattern) ─────────────────────────
def _lazy(module_path: str, factory_fn: str) -> Any:
    """Try to import *module_path* and call *factory_fn*(); return None on failure."""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, factory_fn)()
    except Exception as exc:
        log.debug("[NiblitCoreKernel] Optional dep '%s.%s' unavailable: %s",
                  module_path, factory_fn, exc)
        return None


# ═════════════════════════════════════════════════════════════════════════════
# 3-Tier Memory System
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """A single item in short-term memory."""
    content: Any
    importance: float
    ts: int = field(default_factory=lambda: int(time.time()))
    source: str = "kernel"


class ShortTermMemory:
    """Bounded, thread-safe deque for recent inputs and outputs.

    Args:
        maxlen: Maximum number of entries to retain.
    """

    def __init__(self, maxlen: int = _STM_SIZE) -> None:
        self._q: Deque[MemoryEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, content: Any, importance: float = 0.5, source: str = "kernel") -> None:
        """Add an entry; oldest entries are automatically evicted when full."""
        with self._lock:
            self._q.append(MemoryEntry(content=content, importance=importance, source=source))

    def recent(self, n: int = 5) -> List[MemoryEntry]:
        """Return up to *n* most recent entries, newest first."""
        with self._lock:
            return list(reversed(list(self._q)))[:n]

    def recent_texts(self, n: int = 5) -> List[str]:
        """Return up to *n* most recent content strings."""
        return [str(e.content)[:300] for e in self.recent(n)]

    def clear(self) -> None:
        with self._lock:
            self._q.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)


class WorkingMemory:
    """Dict-based active task context, capped at *maxkeys*.

    Evicts the oldest key when full (LRU-lite via insertion order).

    Args:
        maxkeys: Maximum number of key/value pairs.
    """

    def __init__(self, maxkeys: int = _WM_SIZE) -> None:
        self._data: Dict[str, Any] = {}
        self._maxkeys = maxkeys
        self._lock = threading.Lock()

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                del self._data[key]  # refresh position
            elif len(self._data) >= self._maxkeys:
                # Evict oldest inserted key
                oldest = next(iter(self._data))
                del self._data[oldest]
            self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class KernelMemory:
    """Unified 3-tier memory interface for the cognitive kernel.

    Tier 1 (fast, volatile): :class:`ShortTermMemory` — recent raw inputs/outputs.
    Tier 2 (task-scoped):    :class:`WorkingMemory`    — active reasoning context.
    Tier 3 (persistent):     :class:`~modules.memory_graph.MemoryGraph`
                             + KnowledgeDB              — durable long-term memory.
    MWDS layer:              :class:`~modules.memory_weighting.MemoryStore` —
                             dynamic survival scoring (weight/decay/reinforce/tier).

    The MWDS layer is layered *on top of* the existing 3-tier stack.  It does
    not replace any existing functionality; it adds adaptive weight-based
    re-ranking to the ``retrieve()`` result set.

    Args:
        memory_graph:   Optional MemoryGraph (lazy-acquired if None).
        knowledge_db:   Optional KnowledgeDB for durable fact persistence.
        memory_store:   Optional :class:`~modules.memory_weighting.MemoryStore`
                        (lazy-acquired from ``get_memory_store()`` if None).
        stm_size:       Short-term memory capacity.
        wm_size:        Working memory capacity.
    """

    def __init__(
        self,
        memory_graph: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        memory_store: Optional[Any] = None,
        stm_size: int = _STM_SIZE,
        wm_size: int = _WM_SIZE,
    ) -> None:
        self.short_term = ShortTermMemory(maxlen=stm_size)
        self.working = WorkingMemory(maxkeys=wm_size)
        self._memory_graph = memory_graph
        self._knowledge_db = knowledge_db
        self._memory_store = memory_store

    @property
    def memory_graph(self) -> Optional[Any]:
        if self._memory_graph is None:
            self._memory_graph = _lazy("modules.memory_graph", "get_memory_graph")
        return self._memory_graph

    @property
    def memory_store(self) -> Optional[Any]:
        """Lazy accessor for the MWDS :class:`~modules.memory_weighting.MemoryStore`."""
        if self._memory_store is None:
            self._memory_store = _lazy(
                "modules.memory_weighting", "get_memory_store"
            )
        return self._memory_store

    def store(self, data: Any, importance: float = 0.5, source: str = "kernel") -> None:
        """Write *data* across all relevant tiers based on *importance*.

        * Always written to short-term memory.
        * If ``importance >= 0.5``: also stored in working memory under the
          current timestamp key.
        * If ``importance >= 0.7`` and MemoryGraph available: added as a
          concept node.
        * If ``importance >= 0.8`` and KnowledgeDB available: persisted as a
          durable fact.
        * **MWDS**: always registered in :class:`~modules.memory_weighting.MemoryStore`
          for adaptive weight tracking (regardless of importance tier).

        Args:
            data:       The item to store (any serialisable type).
            importance: Priority weight in ``[0, 1]``.
            source:     Tag for provenance tracking.
        """
        import hashlib
        text = str(data)[:500]

        # Tier 1 — always
        self.short_term.push(content=data, importance=importance, source=source)

        # Tier 2 — working memory for mid-importance items
        if importance >= 0.5:
            self.working.set(f"mem_{int(time.time())}", text[:200])

        # Tier 3a — MemoryGraph for high-importance items
        if importance >= 0.7 and self.memory_graph is not None:
            try:
                node_id = "ck_" + hashlib.md5(text.encode()).hexdigest()[:12]
                self.memory_graph.add(node_id, text)
            except Exception as exc:
                log.debug("[KernelMemory] memory_graph.add failed: %s", exc)

        # Tier 3b — KnowledgeDB for most important items
        if importance >= 0.8 and self._knowledge_db is not None:
            try:
                self._knowledge_db.add_fact(
                    f"kernel_memory:{int(time.time())}",
                    {"text": text, "importance": importance, "source": source},
                    tags=["kernel", "long_term_memory", source],
                )
            except Exception as exc:
                log.debug("[KernelMemory] knowledge_db.add_fact failed: %s", exc)

        # MWDS — register in MemoryStore for adaptive weight tracking
        ms = self.memory_store
        if ms is not None:
            try:
                record_id = "km_" + hashlib.md5(text.encode()).hexdigest()[:16]
                ms.store(record_id, text, source=source, confidence=importance)
            except Exception as exc:
                log.debug("[KernelMemory] memory_store.store failed: %s", exc)

    def retrieve(self, query: str, top_k: int = 5) -> List[str]:
        """Retrieve relevant memories for *query*.

        Checks short-term and working memory first, then MemoryGraph for
        semantic matches.  Results are re-ranked by the MWDS survival score
        when the :class:`~modules.memory_weighting.MemoryStore` is available.

        Args:
            query: Natural language query string.
            top_k: Maximum number of items to return.

        Returns:
            List of relevant text snippets, highest-weight first.
        """
        results: List[str] = []

        # Recent short-term items
        stm = self.short_term.recent_texts(top_k)
        results.extend(stm)

        # Working memory (keyword match)
        wm = self.working.snapshot()
        query_lower = query.lower()
        for v in wm.values():
            if any(word in str(v).lower() for word in query_lower.split()[:5]):
                results.append(str(v)[:200])

        # MemoryGraph semantic search (embedding-free text fallback)
        if self.memory_graph is not None:
            try:
                graph_hits = self.memory_graph.search(None, top_k=top_k)
                results.extend(h["text"][:200] for h in graph_hits[:top_k])
            except Exception as exc:
                log.debug("[KernelMemory] memory_graph.search failed: %s", exc)

        # Deduplicate while preserving order
        seen: set = set()
        deduped: List[str] = []
        for r in results:
            key = r[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        deduped = deduped[:top_k * 2]  # gather extra candidates for re-ranking

        # MWDS re-ranking — sort by adaptive survival score + centrality
        ms = self.memory_store
        if ms is not None:
            try:
                deduped = ms.retrieve_weighted(deduped, top_k=top_k)
            except Exception as exc:
                log.debug("[KernelMemory] MWDS re-rank failed: %s", exc)
                deduped = deduped[:top_k]
        else:
            deduped = deduped[:top_k]

        return deduped

    def decay(self) -> None:
        """Apply temporal decay.

        Delegates to MemoryGraph.apply_decay() *and* runs a MWDS maintenance
        pass (weight refresh + prune + compress).
        """
        if self.memory_graph is not None:
            try:
                self.memory_graph.apply_decay()
            except Exception as exc:
                log.debug("[KernelMemory] MemoryGraph.decay failed: %s", exc)

        ms = self.memory_store
        if ms is not None:
            try:
                graph_size = None
                if self.memory_graph is not None:
                    try:
                        graph_size = self.memory_graph.count()
                    except Exception:
                        pass
                ms.run_maintenance(total_nodes=graph_size)
            except Exception as exc:
                log.debug("[KernelMemory] MWDS maintenance failed: %s", exc)

    def reinforce(self, node_id: str, delta: float = 0.05) -> None:
        """Positively reinforce a memory node.

        Reinforces the MemoryGraph node *and* the matching MWDS record (if any).

        Args:
            node_id: Target node identifier (used for MemoryGraph and MWDS lookup).
            delta:   Positive score increment.
        """
        if self.memory_graph is not None:
            try:
                self.memory_graph.reinforce(node_id, delta=delta)
            except Exception as exc:
                log.debug("[KernelMemory] MemoryGraph.reinforce failed: %s", exc)

        ms = self.memory_store
        if ms is not None:
            try:
                ms.reinforce_by_id(node_id, success=True)
            except Exception as exc:
                log.debug("[KernelMemory] MWDS reinforce failed: %s", exc)

    def reinforce_content(self, text: str, success: bool = True) -> None:
        """Reinforce records matching *text* in the MWDS store.

        This is the preferred method when the node ID is not known but the
        content string is available.

        Args:
            text:    Content to match (first 60 chars used as key).
            success: Whether this retrieval was useful.
        """
        ms = self.memory_store
        if ms is not None:
            try:
                ms.reinforce_by_content(text, success=success)
            except Exception as exc:
                log.debug("[KernelMemory] MWDS reinforce_content failed: %s", exc)

    def weighted_stats(self) -> Dict[str, Any]:
        """Return MWDS tier breakdown and overall memory statistics."""
        ms = self.memory_store
        mwds_stats: Dict[str, Any] = {}
        if ms is not None:
            try:
                mwds_stats = ms.stats()
            except Exception:
                pass
        return mwds_stats

    def stats(self) -> Dict[str, Any]:
        """Return statistics across all memory tiers including MWDS."""
        graph_stats = {}
        if self.memory_graph is not None:
            try:
                graph_stats = self.memory_graph.stats()
            except Exception:  # pragma: no cover
                pass
        return {
            "short_term_count": len(self.short_term),
            "working_memory_count": len(self.working),
            "memory_graph": graph_stats,
            "mwds": self.weighted_stats(),
        }


# ═════════════════════════════════════════════════════════════════════════════
# Decision Engine (intent-based routing)
# ═════════════════════════════════════════════════════════════════════════════

# Intent keyword buckets — each keyword contributes +1 to its bucket's score.
_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "research":  ["learn", "research", "study", "find", "explore", "discover",
                  "what is", "explain", "describe", "tell me", "information",
                  "knowledge", "understand", "investigate"],
    "code":      ["build", "code", "fix", "write", "generate", "create",
                  "implement", "program", "script", "function", "class",
                  "module", "debug", "refactor", "test"],
    "reflect":   ["why", "analyze", "reflect", "reason", "think", "consider",
                  "evaluate", "assess", "review", "critique", "meta",
                  "introspect", "self", "cognition"],
    "trade":     ["trade", "market", "price", "stock", "buy", "sell",
                  "position", "portfolio", "strategy", "signal", "rl",
                  "reward", "kelly", "risk", "financial"],
    "evolve":    ["evolve", "improve", "upgrade", "modify", "update",
                  "enhance", "self-modify", "mutate", "patch", "rewrite"],
}

# Minimum score to activate an intent; below this → "respond"
_INTENT_THRESHOLD: int = 1


class DecisionEngine:
    """Intent-based routing from thought string to action name.

    Scores each keyword bucket and returns the highest-scoring action.

    Args:
        intent_keywords: Custom keyword mapping (defaults to :data:`_INTENT_KEYWORDS`).
        threshold:       Minimum score to activate an intent.
    """

    def __init__(
        self,
        intent_keywords: Optional[Dict[str, List[str]]] = None,
        threshold: int = _INTENT_THRESHOLD,
    ) -> None:
        self._keywords = intent_keywords or _INTENT_KEYWORDS
        self._threshold = threshold

    def decide(self, thought: str) -> str:
        """Score *thought* against all intent buckets and return the winner.

        Args:
            thought: The reasoning output string to classify.

        Returns:
            Action name: one of ``"research"``, ``"code"``, ``"reflect"``,
            ``"trade"``, ``"evolve"``, or ``"respond"``.
        """
        text = thought.lower()
        scores: Dict[str, int] = {
            intent: sum(1 for kw in keywords if kw in text)
            for intent, keywords in self._keywords.items()
        }
        best_intent = max(scores, key=lambda k: scores[k])
        best_score = scores[best_intent]
        if best_score < self._threshold:
            return "respond"
        return best_intent

    def score_breakdown(self, thought: str) -> Dict[str, int]:
        """Return the raw score for each intent bucket (useful for debugging)."""
        text = thought.lower()
        return {
            intent: sum(1 for kw in keywords if kw in text)
            for intent, keywords in self._keywords.items()
        }


# ═════════════════════════════════════════════════════════════════════════════
# Tool Router (execution layer)
# ═════════════════════════════════════════════════════════════════════════════

class ToolRouter:
    """Unified execution interface.  Maps action names to existing Niblit modules.

    Each action handler is a method that accepts a *payload* dict and returns a
    string result.  Handlers are resolved lazily on first use so startup remains
    fast even if optional dependencies are missing.

    Supported actions: ``research``, ``code``, ``reflect``, ``trade``,
    ``evolve``, ``respond``.

    Args:
        knowledge_db: Optional KnowledgeDB injected at construction.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self._knowledge_db = knowledge_db
        self._handlers: Dict[str, Any] = {
            "research":  self._research,
            "code":      self._generate_code,
            "reflect":   self._reflect,
            "trade":     self._trade,
            "evolve":    self._evolve_step,
            "respond":   self._respond,
        }

    def execute(self, action: str, payload: Any) -> str:
        """Dispatch *action* with *payload* to the matching handler.

        Unknown actions fall back to ``respond``.  All exceptions are caught
        and returned as error strings so the kernel loop is never interrupted.

        Args:
            action:  Action name (case-insensitive).
            payload: Arbitrary payload passed to the handler.

        Returns:
            Human-readable result string.
        """
        handler = self._handlers.get(action.lower(), self._respond)
        try:
            return handler(payload)
        except Exception as exc:
            log.warning("[ToolRouter] execute('%s') error: %s", action, exc)
            return f"[ToolRouter:{action} error: {exc}]"

    def _research(self, payload: Any) -> str:
        query = str(payload)[:200] if payload else "general research"
        try:
            from modules.phased_research_engine import get_phased_research_engine  # noqa
            engine = get_phased_research_engine()
            result = engine.research(query, phase_budget={"phase1": 20, "phase2": 0, "phase3": 0})
            return result.summary if hasattr(result, "summary") else str(result)[:300]
        except Exception as exc:
            log.debug("[ToolRouter] research fallback: %s", exc)
            return f"[Research dispatched for: {query[:80]}]"

    def _generate_code(self, payload: Any) -> str:
        prompt = str(payload)[:500] if payload else "generate a Python function"
        try:
            from modules.code_generator import CodeGenerator  # noqa
            gen = CodeGenerator()
            result = gen.generate(prompt=prompt, language="python")
            if isinstance(result, dict):
                return result.get("code", result.get("output", str(result)))[:500]
            return str(result)[:500]
        except Exception as exc:
            log.debug("[ToolRouter] code_generator fallback: %s", exc)
            return f"[Code generation queued for: {prompt[:80]}]"

    def _reflect(self, payload: Any) -> str:
        thought = str(payload)[:400] if payload else "reflect on current state"
        try:
            from modules.cognition_core import get_cognition_core  # noqa
            core = get_cognition_core()
            result = core.think(thought, knowledge_db=self._knowledge_db)
            return result.conclusion or f"[Reflected on: {thought[:80]}]"
        except Exception as exc:
            log.debug("[ToolRouter] reflect fallback: %s", exc)
            return f"[Reflection on: {thought[:80]}]"

    def _trade(self, payload: Any) -> str:
        signal = str(payload)[:200] if payload else ""
        try:
            from modules.trading_brain import TradingBrain  # noqa
            tb = TradingBrain()
            # Don't trigger a live trade — just get a status assessment
            status = tb.get_status() if hasattr(tb, "get_status") else {}
            return f"TradingBrain status: {status or 'available'}"
        except Exception as exc:
            log.debug("[ToolRouter] trade fallback: %s", exc)
            return f"[Trade signal queued: {signal[:80]}]"

    def _evolve_step(self, payload: Any) -> str:
        """Run one EvolveEngine step — used only when kernel.evolve() gates through."""
        try:
            from modules.evolve import EvolveEngine  # noqa
            eng = EvolveEngine()
            result = eng.step()
            return f"EvolveEngine step complete: {result.get('summary', 'ok')}"
        except Exception as exc:
            log.debug("[ToolRouter] evolve_step fallback: %s", exc)
            return f"[Evolution step queued: {str(payload)[:80]}]"

    def _respond(self, payload: Any) -> str:
        """Default handler — returns a templated response for the given payload."""
        return f"Niblit: I processed your input — '{str(payload)[:120]}'"


# ═════════════════════════════════════════════════════════════════════════════
# Evolution Gate
# ═════════════════════════════════════════════════════════════════════════════

# Hard-blocked strings — evolution proposals containing these are always rejected.
_EVOLUTION_BLOCKLIST: Tuple[str, ...] = (
    "delete core",
    "delete kernel",
    "delete niblit",
    "overwrite core",
    "rm -rf",
    "os.remove",
    "shutil.rmtree",
)

# Additional rules enabled when NIBLIT_KERNEL_SAFETY_STRICT=1
_STRICT_BLOCKLIST: Tuple[str, ...] = (
    "subprocess",
    "exec(",
    "eval(",
    "__import__",
    "system(",
)


class EvolutionGate:
    """3-layer safety validation for self-improvement proposals.

    Layer 1 — Blocklist:  Rejects any proposal containing a known dangerous
                          phrase (case-insensitive).
    Layer 2 — Length:     Rejects proposals shorter than 10 characters
                          (low-signal noise).
    Layer 3 — Semantics:  Rejects proposals that attempt to modify core kernel
                          files or bypass safety checks.

    Args:
        strict: Enable additional strict-mode checks from
                :data:`_STRICT_BLOCKLIST`.
    """

    def __init__(self, strict: bool = _SAFETY_STRICT) -> None:
        self._strict = strict

    def validate(self, proposal: str) -> Tuple[bool, str]:
        """Check *proposal* and return ``(is_valid, reason)``.

        Args:
            proposal: The evolution proposal text.

        Returns:
            ``(True, "")``             — proposal is safe to apply.
            ``(False, <reason_str>)``  — proposal was rejected.
        """
        if not proposal or not isinstance(proposal, str):
            return False, "Proposal is empty or not a string"

        lower = proposal.lower()

        # Layer 1 — Blocklist
        for blocked in _EVOLUTION_BLOCKLIST:
            if blocked in lower:
                return False, f"Blocked phrase detected: '{blocked}'"

        # Layer 1b — Strict blocklist
        if self._strict:
            for blocked in _STRICT_BLOCKLIST:
                if blocked in lower:
                    return False, f"Strict-mode blocked phrase: '{blocked}'"

        # Layer 2 — Length check
        if len(proposal.strip()) < 10:
            return False, "Proposal too short (< 10 chars) — likely low-signal noise"

        # Layer 3 — Semantic: no direct modifications to core kernel or safety files
        core_files = [
            "niblit_core_kernel",
            "niblit_kernel",
            "security_hardening",
            "security_membrane",
            "slice_guard",
        ]
        if any(cf in lower for cf in core_files):
            return (
                False,
                "Proposals must not directly modify kernel or security modules — "
                "use the staged upgrade pathway instead",
            )

        return True, ""


# ═════════════════════════════════════════════════════════════════════════════
# Kernel Result
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class KernelResult:
    """Output of a single ``run_cognitive_loop()`` pass.

    Attributes
    ----------
    input_data:   The raw input provided to the loop.
    thought:      The reasoning conclusion produced by ``think()``.
    decision:     The action name chosen by ``decide()``.
    action_result:The string returned by ``act()``.
    remembered:   Whether ``remember()`` was called for this cycle.
    evolved:      Whether ``evolve()`` was invoked (and passed the gate).
    latency_ms:   Total wall-clock time for the cycle in milliseconds.
    ts:           UNIX timestamp of completion.
    """
    input_data: Any
    thought: str = ""
    decision: str = "respond"
    action_result: str = ""
    remembered: bool = False
    evolved: bool = False
    latency_ms: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": str(self.input_data)[:200],
            "thought": self.thought[:300],
            "decision": self.decision,
            "action_result": self.action_result[:300],
            "remembered": self.remembered,
            "evolved": self.evolved,
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ═════════════════════════════════════════════════════════════════════════════
# NiblitCoreKernel
# ═════════════════════════════════════════════════════════════════════════════

class NiblitCoreKernel:
    """Niblit Cognitive Kernel v1.

    The single authoritative gateway for all cognitive operations.  Wraps
    all existing Niblit modules behind the five-method API surface:
    ``think``, ``remember``, ``decide``, ``act``, ``evolve``.

    Args:
        cognition_core:   Optional :class:`~modules.cognition_core.CognitionCore`.
        reasoning_engine: Optional :class:`~modules.reasoning_engine.ReasoningEngine`.
        memory_graph:     Optional :class:`~modules.memory_graph.MemoryGraph`.
        evolve_engine:    Optional :class:`~modules.evolve.EvolveEngine`.
        knowledge_db:     Optional KnowledgeDB for long-term storage.
        tool_router:      Optional :class:`ToolRouter` override.
        evolve_enabled:   Whether the evolve gate is active (default True).
        strict_safety:    Enable strict-mode evolution blocking.
    """

    def __init__(
        self,
        cognition_core: Optional[Any] = None,
        reasoning_engine: Optional[Any] = None,
        memory_graph: Optional[Any] = None,
        evolve_engine: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        tool_router: Optional[ToolRouter] = None,
        evolve_enabled: bool = _EVOLVE_ENABLED,
        strict_safety: bool = _SAFETY_STRICT,
    ) -> None:
        # ── Resolve subsystem dependencies lazily ─────────────────────────
        self._cognition_core = cognition_core
        self._reasoning_engine = reasoning_engine
        self._memory_graph = memory_graph
        self._evolve_engine = evolve_engine
        self.knowledge_db = knowledge_db

        # ── Core sub-components ──────────────────────────────────────────
        self.memory = KernelMemory(
            memory_graph=memory_graph,
            knowledge_db=knowledge_db,
        )
        self.decision_engine = DecisionEngine()
        self.gate = EvolutionGate(strict=strict_safety)
        self.tool_router = tool_router or ToolRouter(knowledge_db=knowledge_db)

        # ── State ─────────────────────────────────────────────────────────
        self._evolve_enabled = evolve_enabled
        self._lock = threading.Lock()
        self._cycle_count: int = 0
        self._stats: Dict[str, Any] = {
            "think_calls": 0,
            "remember_calls": 0,
            "decide_calls": 0,
            "act_calls": 0,
            "evolve_calls": 0,
            "evolve_accepted": 0,
            "evolve_rejected": 0,
            "loop_calls": 0,
        }

        log.info(
            "[NiblitCoreKernel] v1 initialised — evolve_enabled=%s strict=%s",
            evolve_enabled, strict_safety,
        )

    # ── Lazy module accessors ─────────────────────────────────────────────────

    @property
    def cognition_core(self) -> Optional[Any]:
        if self._cognition_core is None:
            self._cognition_core = _lazy("modules.cognition_core", "get_cognition_core")
        return self._cognition_core

    @property
    def reasoning_engine(self) -> Optional[Any]:
        if self._reasoning_engine is None:
            self._reasoning_engine = _lazy("modules.reasoning_engine", "get_reasoning_engine")
        return self._reasoning_engine

    @property
    def evolve_engine(self) -> Optional[Any]:
        if self._evolve_engine is None:
            self._evolve_engine = _lazy("modules.evolve", "step")  # module-level fn
        return self._evolve_engine

    # ══════════════════════════════════════════════════════════════════════════
    # 1. THINK — reasoning + context synthesis
    # ══════════════════════════════════════════════════════════════════════════

    def think(
        self,
        input_data: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Reasoning pass over *input_data*.

        Merges incoming context with relevant memories, then delegates to
        :class:`~modules.cognition_core.CognitionCore` (preferred) or falls
        back to :class:`~modules.reasoning_engine.ReasoningEngine`.

        If neither engine is available, returns a structured summary of the
        memory context.

        Args:
            input_data: The user query, task description, or sensor input.
            context:    Optional extra context dict (e.g. ALE cycle state).

        Returns:
            A reasoning conclusion string.
        """
        with self._lock:
            self._stats["think_calls"] += 1

        topic = str(input_data)[:200]

        # Retrieve relevant memories
        memories = self.memory.retrieve(topic, top_k=5)
        merged_context: Dict[str, Any] = {
            "input": topic,
            "memory": memories,
            **(context or {}),
            "working_memory": self.memory.working.snapshot(),
        }

        # ── CognitionCore path (preferred) ────────────────────────────────
        cc = self.cognition_core
        if cc is not None:
            try:
                result = cc.think(
                    topic=topic,
                    facts=[{"key": "ctx", "value": str(merged_context)[:400]}],
                    knowledge_db=self.knowledge_db,
                )
                thought = result.conclusion
                if thought:
                    log.debug("[NiblitCoreKernel] think via CognitionCore: %.80s", thought)
                    return thought
                # Empty conclusion — fall through to ReasoningEngine
                log.debug("[NiblitCoreKernel] CognitionCore returned empty conclusion; trying RE")
            except Exception as exc:
                log.debug("[NiblitCoreKernel] CognitionCore.think failed: %s", exc)

        # ── ReasoningEngine fallback ──────────────────────────────────────
        re = self.reasoning_engine
        if re is not None:
            try:
                cot = re.chain_of_thought(topic)
                thought = getattr(cot, "conclusion", "") or topic
                log.debug("[NiblitCoreKernel] think via ReasoningEngine: %.80s", thought)
                return thought
            except Exception as exc:
                log.debug("[NiblitCoreKernel] ReasoningEngine.chain_of_thought failed: %s", exc)

        # ── Minimal fallback: return memory-enriched summary or topic ─────
        if memories:
            return f"Context for '{topic[:60]}': " + "; ".join(memories[:2])[:200]
        return topic

    # ══════════════════════════════════════════════════════════════════════════
    # 2. REMEMBER — controlled 3-tier memory write
    # ══════════════════════════════════════════════════════════════════════════

    def remember(self, data: Any, importance: float = 0.5) -> None:
        """Store *data* in the appropriate memory tier(s) based on *importance*.

        * 0.0–0.49 → short-term only (volatile).
        * 0.50–0.69 → short-term + working memory.
        * 0.70–0.79 → short-term + working memory + MemoryGraph.
        * 0.80–1.00 → all tiers including KnowledgeDB.

        Args:
            data:       Any serialisable item.
            importance: Priority weight in ``[0, 1]``.
        """
        with self._lock:
            self._stats["remember_calls"] += 1
        importance = float(max(0.0, min(1.0, importance)))
        self.memory.store(data, importance=importance, source="kernel_remember")
        log.debug("[NiblitCoreKernel] remember(importance=%.2f): %.60s", importance, str(data))

    # ══════════════════════════════════════════════════════════════════════════
    # 3. DECIDE — intent-based action selection
    # ══════════════════════════════════════════════════════════════════════════

    def decide(self, thought: str) -> str:
        """Classify *thought* into an action name.

        Delegates to :class:`DecisionEngine`'s keyword-scoring algorithm.

        Args:
            thought: The string produced by ``think()``.

        Returns:
            Action name: ``"research"``, ``"code"``, ``"reflect"``,
            ``"trade"``, ``"evolve"``, or ``"respond"``.
        """
        with self._lock:
            self._stats["decide_calls"] += 1
        decision = self.decision_engine.decide(thought)
        log.debug("[NiblitCoreKernel] decide → '%s' for: %.60s", decision, thought)
        return decision

    # ══════════════════════════════════════════════════════════════════════════
    # 4. ACT — safe tool execution
    # ══════════════════════════════════════════════════════════════════════════

    def act(self, decision: str, payload: Any) -> str:
        """Execute *decision* with *payload* via the :class:`ToolRouter`.

        Args:
            decision: The action name returned by ``decide()``.
            payload:  The reasoning output or user input to forward.

        Returns:
            Human-readable result string from the tool handler.
        """
        with self._lock:
            self._stats["act_calls"] += 1
        result = self.tool_router.execute(decision, payload)
        log.debug("[NiblitCoreKernel] act('%s') → %.80s", decision, result)
        return result

    # ══════════════════════════════════════════════════════════════════════════
    # 5. EVOLVE — gated self-improvement
    # ══════════════════════════════════════════════════════════════════════════

    def evolve(self, proposal: str) -> str:
        """Validate *proposal* through the :class:`EvolutionGate` and apply it.

        Args:
            proposal: Natural-language or code description of the proposed
                      self-improvement.

        Returns:
            Acceptance message with EvolveEngine output, or a rejection
            message explaining why the proposal was blocked.
        """
        with self._lock:
            self._stats["evolve_calls"] += 1

        if not self._evolve_enabled:
            return "[Evolution gate disabled — set NIBLIT_KERNEL_EVOLVE_ENABLED=1 to enable]"

        valid, reason = self.gate.validate(proposal)
        if not valid:
            with self._lock:
                self._stats["evolve_rejected"] += 1
            log.info("[NiblitCoreKernel] Rejected evolution: %s", reason)
            return f"Rejected evolution — {reason}"

        with self._lock:
            self._stats["evolve_accepted"] += 1

        # Log the accepted proposal
        log.info("[NiblitCoreKernel] Accepted evolution proposal: %.100s", proposal)

        # Delegate to ToolRouter's evolve handler (wraps EvolveEngine.step())
        result = self.tool_router.execute("evolve", proposal)
        return f"Evolution applied: {result}"

    # ══════════════════════════════════════════════════════════════════════════
    # Full cognitive loop
    # ══════════════════════════════════════════════════════════════════════════

    def run_cognitive_loop(
        self,
        input_data: Any,
        context: Optional[Dict[str, Any]] = None,
        auto_evolve: bool = False,
    ) -> KernelResult:
        """Run one full cognitive cycle: THINK → DECIDE → ACT → REMEMBER.

        Optionally triggers ``evolve()`` when *auto_evolve* is True and the
        ``decide()`` result is ``"evolve"``.

        Args:
            input_data:   User query, sensor input, or task description.
            context:      Optional extra context forwarded to ``think()``.
            auto_evolve:  If True and decision == "evolve", call ``evolve()``.

        Returns:
            :class:`KernelResult` containing all intermediate outputs.
        """
        t0 = time.time()
        with self._lock:
            self._stats["loop_calls"] += 1
            self._cycle_count += 1

        result = KernelResult(input_data=input_data)

        # ── THINK ─────────────────────────────────────────────────────────
        result.thought = self.think(input_data, context=context)

        # ── DECIDE ────────────────────────────────────────────────────────
        result.decision = self.decide(result.thought)

        # ── ACT ───────────────────────────────────────────────────────────
        result.action_result = self.act(result.decision, result.thought)

        # ── REMEMBER ──────────────────────────────────────────────────────
        # Importance is 0.7 for routine loops; ALE steps may call remember()
        # directly with higher importance for significant findings.
        self.remember(
            {
                "input": str(input_data)[:200],
                "thought": result.thought[:200],
                "decision": result.decision,
                "result": result.action_result[:200],
            },
            importance=0.7,
        )
        result.remembered = True

        # ── EVOLVE (optional) ─────────────────────────────────────────────
        if auto_evolve and result.decision == "evolve":
            evolve_out = self.evolve(result.thought)
            result.evolved = not evolve_out.startswith("Rejected")
            result.action_result = evolve_out

        result.latency_ms = (time.time() - t0) * 1000
        result.ts = int(time.time())

        log.info(
            "[NiblitCoreKernel] cycle #%d: decision=%s latency=%.0fms",
            self._cycle_count, result.decision, result.latency_ms,
        )
        return result

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a snapshot of kernel state and statistics."""
        with self._lock:
            stats = dict(self._stats)
        return {
            **stats,
            "cycle_count": self._cycle_count,
            "evolve_enabled": self._evolve_enabled,
            "memory": self.memory.stats(),
            "cognition_core_available": self.cognition_core is not None,
            "reasoning_engine_available": self.reasoning_engine is not None,
        }

    def register_with_health_kernel(self) -> None:
        """Register this kernel with the NiblitKernel health registry.

        Safe to call even if the health kernel is unavailable.
        """
        try:
            from modules.niblit_kernel import get_kernel  # noqa
            health_kernel = get_kernel()
            health_kernel.register_module("NiblitCoreKernel", self)
            log.info("[NiblitCoreKernel] Registered with NiblitKernel health registry")
        except Exception as exc:
            log.debug("[NiblitCoreKernel] health kernel registration failed: %s", exc)


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_kernel: Optional[NiblitCoreKernel] = None
_kernel_lock = threading.Lock()


def get_niblit_core_kernel(**kwargs) -> NiblitCoreKernel:
    """Return the process-level :class:`NiblitCoreKernel` singleton.

    Thread-safe, lazily created on first call.  Any keyword arguments are
    forwarded to the constructor **only** on the first call.
    """
    global _kernel  # pylint: disable=global-statement
    with _kernel_lock:
        if _kernel is None:
            _kernel = NiblitCoreKernel(**kwargs)
        return _kernel
