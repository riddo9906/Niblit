#!/usr/bin/env python3
"""
modules/niblit_core_kernel_v2.py — Niblit Cognitive Kernel v2
==============================================================
*A self-contained reasoning layer that works even without external LLMs.*

This is NOT a full generative language model.  It is a composed intelligence
layer built from four deterministic components:

1. :class:`Embedder`          — semantic *understanding* via sentence embeddings.
2. :class:`ConceptGraph`      — *knowledge* retrieval + graph expansion.
3. :class:`PatternSynthesizer`— structured *reasoning* + intent classification.
4. :class:`NiblitCoreKernelV2`— complete cognitive loop (think/decide/act/remember).

Architecture
------------
::

    INPUT
      ↓
    [Embedder]                    encode(text) → 384-D vector
      ↓
    [KernelMemory.semantic_search] cosine similarity over MemoryGraph nodes
      ↓
    [ConceptGraph.expand]         multi-hop graph expansion → concept list
      ↓
    [PatternSynthesizer.generate] structured reasoning string (no LLM needed)
      ↓
    [PatternSynthesizer.to_response] extract readable output from thought
      ↓
    OUTPUT

Design goals
------------
* **Offline-first** — works with zero network calls.  Sentence-transformers are
  used when available, but the system degrades gracefully to a pure-Python
  term-frequency embedding fallback.
* **Composable** — each component is independently usable.  Inject them into
  other parts of Niblit as needed.
* **Additive** — zero changes to existing modules.  All v1 behaviour is
  preserved; v2 is an opt-in upgrade path.
* **Testable** — all classes are pure Python with no mandatory I/O.

Relationships with v1
---------------------
* :class:`NiblitCoreKernelV2` delegates *act* to the existing
  :class:`~modules.niblit_core_kernel.ToolRouter`.
* *remember* writes through :class:`~modules.niblit_core_kernel.KernelMemory`
  (which in turn delegates to MWDS v2).
* The v1 singleton (``get_niblit_core_kernel()``) is **not** replaced; both
  kernels can coexist.  ``get_niblit_core_kernel_v2()`` manages its own
  singleton.

Singleton
---------
``get_niblit_core_kernel_v2()`` returns the process-wide
:class:`NiblitCoreKernelV2` instance.

Configuration (environment variables)
--------------------------------------
``NIBLIT_V2_EMBED_MODEL``  — SentenceTransformer model name
                             (default: ``all-MiniLM-L6-v2``).
``NIBLIT_V2_FOCUS_WINDOW`` — Seconds that count as "short period" for the
                             temporal focus boost (default: ``120``).
``NIBLIT_V2_FOCUS_BOOST``  — Importance multiplier applied during focus
                             window (default: ``0.15``).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_EMBED_MODEL = os.environ.get("NIBLIT_V2_EMBED_MODEL", "all-MiniLM-L6-v2")
_FOCUS_WINDOW = float(os.environ.get("NIBLIT_V2_FOCUS_WINDOW", "120"))
_FOCUS_BOOST = float(os.environ.get("NIBLIT_V2_FOCUS_BOOST", "0.15"))

# ── Optional numpy ────────────────────────────────────────────────────────────
try:
    import numpy as _np
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False


# ═════════════════════════════════════════════════════════════════════════════
# Helper: cosine similarity
# ═════════════════════════════════════════════════════════════════════════════

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two float lists.  Returns 0.0 on any error."""
    if _NP_AVAILABLE and _np is not None:
        try:
            va = _np.array(a, dtype="float32")
            vb = _np.array(b, dtype="float32")
            denom = float(_np.linalg.norm(va) * _np.linalg.norm(vb))
            if denom == 0:
                return 0.0
            return float(_np.dot(va, vb) / denom)
        except Exception:
            return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
    except Exception:
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
# Embedder
# ═════════════════════════════════════════════════════════════════════════════

class Embedder:
    """Semantic understanding layer.

    Wraps ``vector_store.load_sentence_transformer()`` (singleton cache,
    all-MiniLM-L6-v2 by default).  Falls back to a pure-Python term-frequency
    pseudo-embedding when sentence-transformers is not installed.

    The fallback produces a 64-dimensional vector built from character-trigram
    frequencies — dimensionality is low but is sufficient for approximate
    nearest-neighbour matching within a small knowledge base.

    Args:
        model_name: SentenceTransformer model identifier.
    """

    # Fallback vector dimensionality
    _FALLBACK_DIM: int = 64

    def __init__(self, model_name: str = _EMBED_MODEL) -> None:
        self._model_name = model_name
        self._model: Optional[Any] = None
        self._lock = threading.Lock()
        self._using_fallback: bool = False

    def _load(self) -> None:
        """Lazily load the embedding model (thread-safe)."""
        with self._lock:
            if self._model is not None:
                return
            try:
                from modules.vector_store import load_sentence_transformer
                self._model = load_sentence_transformer(self._model_name)
                self._using_fallback = False
                log.info(
                    "[Embedder] Loaded SentenceTransformer('%s')", self._model_name
                )
            except Exception as exc:
                log.debug(
                    "[Embedder] SentenceTransformer unavailable (%s); "
                    "using TF-fallback",
                    exc,
                )
                self._model = None
                self._using_fallback = True

    def encode(self, text: str) -> List[float]:
        """Encode *text* into a fixed-length float vector.

        Uses sentence-transformers if available; otherwise falls back to the
        character-trigram TF embedding (64-D).

        Args:
            text: Input text to embed (truncated to 512 chars internally).

        Returns:
            A non-empty ``list[float]``.
        """
        self._load()
        text = str(text)[:512]
        if self._model is not None and not self._using_fallback:
            try:
                vec = self._model.encode(text)
                if _NP_AVAILABLE and _np is not None:
                    return vec.tolist()
                return list(vec)
            except Exception as exc:
                log.debug("[Embedder] encode() failed: %s — using fallback", exc)
        return self._fallback_encode(text)

    def _fallback_encode(self, text: str) -> List[float]:
        """Character-trigram TF pseudo-embedding (64-D, L2-normalised)."""
        text = text.lower()[:256]
        counts: Dict[int, float] = defaultdict(float)
        dim = self._FALLBACK_DIM
        for i in range(len(text) - 2):
            trigram = text[i:i + 3]
            bucket = hash(trigram) % dim
            counts[bucket] += 1.0

        vec = [counts.get(i, 0.0) for i in range(dim)]
        mag = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / mag for v in vec]

    @property
    def using_fallback(self) -> bool:
        """True if the TF fallback is active (sentence-transformers unavailable)."""
        return self._using_fallback

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the output vectors."""
        if self._model is not None and not self._using_fallback:
            try:
                return int(self._model.get_sentence_embedding_dimension())
            except Exception:
                pass
        return self._FALLBACK_DIM


# ═════════════════════════════════════════════════════════════════════════════
# ConceptGraph
# ═════════════════════════════════════════════════════════════════════════════

class ConceptGraph:
    """Knowledge expansion layer.

    Wraps the existing :class:`~modules.memory_graph.MemoryGraph` to provide
    semantic concept expansion from a set of initial memory hits.

    ``expand(hits)`` traverses immediate graph neighbours of each hit and
    collects unique concept labels from:

    * Node IDs (stripped of hash suffixes).
    * Tags stored in the node's ``text`` field.
    * Direct MemoryGraph link partners (one hop).

    Args:
        memory_graph: Optional :class:`~modules.memory_graph.MemoryGraph`
                      (lazy-acquired if None).
    """

    def __init__(self, memory_graph: Optional[Any] = None) -> None:
        self._memory_graph = memory_graph
        self._lock = threading.Lock()

    @property
    def memory_graph(self) -> Optional[Any]:
        if self._memory_graph is None:
            try:
                from modules.memory_graph import get_memory_graph
                self._memory_graph = get_memory_graph()
            except Exception:
                pass
        return self._memory_graph

    def expand(
        self,
        memory_hits: List[Dict[str, Any]],
        max_concepts: int = 20,
    ) -> List[str]:
        """Expand *memory_hits* into a list of related concept labels.

        Concept extraction pipeline:

        1. Strip numeric hash suffixes from each hit's ``id`` → concept token.
        2. Tokenise each hit's ``text`` into meaningful words (≥4 chars).
        3. Follow direct graph links (one hop) and collect neighbour IDs.

        Returns at most *max_concepts* unique strings, ordered by frequency.

        Args:
            memory_hits: List of ``{"id", "text", "score", "hops"}`` dicts.
            max_concepts: Maximum number of concept labels to return.

        Returns:
            List of concept label strings.
        """
        frequency: Dict[str, int] = defaultdict(int)

        mg = self.memory_graph

        for hit in memory_hits:
            hit_id = str(hit.get("id", ""))
            hit_text = str(hit.get("text", ""))

            # 1. Clean ID → concept token
            concept = self._id_to_concept(hit_id)
            if concept:
                frequency[concept] += 2  # id tokens get double weight

            # 2. Tokenise text
            for word in self._text_tokens(hit_text):
                frequency[word] += 1

            # 3. Graph neighbour IDs (one hop)
            for nbr in self._neighbors(hit_id, mg):
                nbr_concept = self._id_to_concept(nbr)
                if nbr_concept:
                    frequency[nbr_concept] += 1

        # Sort by frequency descending
        ranked = sorted(frequency, key=lambda k: frequency[k], reverse=True)
        return ranked[:max_concepts]

    @staticmethod
    def _id_to_concept(node_id: str) -> str:
        """Strip hash suffixes and common prefixes from a node ID.

        Extracts a readable concept label from structured IDs like
        ``"ck_a1b2c3d4e5f6"`` (hash-based, returns ``""``),
        ``"python_topic"`` (returns ``"python_topic"``), or
        ``"slsa:machine_learning"`` (returns ``"machine_learning"``).
        """
        import re
        cleaned = node_id.lower()

        # Strip colon-separated namespace (e.g. "slsa:", "arc:")
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]

        # Strip known ID prefixes first
        for prefix in ("ck_", "km_", "abstract_"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        # Strip trailing hex hash segments (6+ hex chars, optionally preceded by _/-)
        cleaned = re.sub(r"[_\-]?[0-9a-f]{6,}$", "", cleaned)
        # If the remainder is itself all hex (pure hash), return empty
        if re.fullmatch(r"[0-9a-f]+", cleaned):
            return ""

        return cleaned.strip() if len(cleaned.strip()) >= 2 else ""

    @staticmethod
    def _text_tokens(text: str) -> List[str]:
        """Extract meaningful words (≥4 chars) from *text*."""
        import re
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        # Simple stopword filter
        stopwords = {
            "this", "that", "with", "from", "have", "been", "will", "more",
            "also", "such", "than", "when", "which", "their", "there",
            "what", "where", "about", "into", "some", "over", "your",
        }
        return [w for w in words if w not in stopwords]

    @staticmethod
    def _neighbors(node_id: str, memory_graph: Optional[Any]) -> List[str]:
        """Return the IDs of direct graph neighbours for *node_id*.

        Returns an empty list if the graph is unavailable or the node does not
        exist.
        """
        if memory_graph is None:
            return []
        try:
            with memory_graph._lock:
                node = memory_graph._nodes.get(node_id)
                if node is None:
                    return []
                return list(node.links.keys())
        except Exception:
            return []


# ═════════════════════════════════════════════════════════════════════════════
# Pattern Synthesizer
# ═════════════════════════════════════════════════════════════════════════════

# Pattern rules: (keyword, intent) evaluated in order.
# First match wins; "respond" is the catch-all.
_INTENT_PATTERNS: List[Tuple[str, str]] = [
    # debug / error
    ("error",        "debug"),
    ("exception",    "debug"),
    ("traceback",    "debug"),
    ("bug",          "debug"),
    ("fail",         "debug"),
    ("crash",        "debug"),
    # research / learn
    ("learn",        "research"),
    ("research",     "research"),
    ("study",        "research"),
    ("explore",      "research"),
    ("explain",      "research"),
    ("understand",   "research"),
    ("what is",      "research"),
    ("who is",       "research"),
    ("how does",     "research"),
    # code
    ("code",         "generate_code"),
    ("build",        "generate_code"),
    ("write",        "generate_code"),
    ("implement",    "generate_code"),
    ("create",       "generate_code"),
    ("function",     "generate_code"),
    ("class",        "generate_code"),
    ("script",       "generate_code"),
    ("program",      "generate_code"),
    ("refactor",     "generate_code"),
    # reflect
    ("reflect",      "reflect"),
    ("analyse",      "reflect"),
    ("analyze",      "reflect"),
    ("consider",     "reflect"),
    ("review",       "reflect"),
    ("critique",     "reflect"),
    # trade / finance
    ("trade",        "trade"),
    ("market",       "trade"),
    ("price",        "trade"),
    ("stock",        "trade"),
    ("portfolio",    "trade"),
    # evolve / improve
    ("evolve",       "evolve"),
    ("improve",      "evolve"),
    ("upgrade",      "evolve"),
]


class PatternSynthesizer:
    """Pattern-based reasoning engine — the "mini-LLM" brain.

    Replaces generative LLM calls with structured, deterministic reasoning:

    * ``generate(input_text, memory_hits, concepts)`` — produces a multi-line
      reasoning string (Input → Relevant → Concepts → Insight).
    * ``_infer(input_text, memory_hits, concepts)`` — pattern-matching insight.
    * ``intent_classify(thought)`` — keyword-bucket intent detection.
    * ``to_response(thought)`` — extract the readable insight from a thought.

    Unlike a neural LLM this synthesizer is:

    * **Deterministic** — same input always produces the same output.
    * **Transparent** — every step is readable plaintext.
    * **Fast** — no GPU, no model load time.
    * **Offline** — zero network calls.
    """

    def generate(
        self,
        input_text: str,
        memory_hits: List[Dict[str, Any]],
        concepts: List[str],
    ) -> str:
        """Build a structured reasoning string from the three input signals.

        Format::

            Input: <input_text>
            Relevant: <mem1>
            Relevant: <mem2>
            ...
            Concepts: <c1>, <c2>, ...
            Insight: <inferred insight>

        Args:
            input_text:   The original user query or task description.
            memory_hits:  List of ``{"id", "text", "score", "hops"}`` dicts.
            concepts:     Expanded concept labels from :class:`ConceptGraph`.

        Returns:
            Multi-line reasoning string.
        """
        reasoning: List[str] = []
        reasoning.append(f"Input: {str(input_text)[:200]}")

        for hit in memory_hits[:5]:
            text = str(hit.get("text", ""))[:150]
            score = float(hit.get("score", 0.0))
            reasoning.append(f"Relevant[{score:.2f}]: {text}")

        if concepts:
            reasoning.append(f"Concepts: {', '.join(concepts[:10])}")

        insight = self._infer(input_text, memory_hits, concepts)
        reasoning.append(f"Insight: {insight}")

        return "\n".join(reasoning)

    def _infer(
        self,
        input_text: str,
        memory_hits: List[Dict[str, Any]],
        concepts: List[str],
    ) -> str:
        """Derive a pattern-based insight from the three inputs.

        Rules (evaluated in priority order):

        1. **Error pattern** — if "error" / "exception" / "bug" in input → suggest debug.
        2. **Learning pattern** — if "learn" in input → propose concept study path.
        3. **Memory hit** — best memory match → suggest based on it.
        4. **Concept pattern** — has concepts but no memory → suggest research area.
        5. **Default** — recommend research.

        Args:
            input_text:  The original query.
            memory_hits: Semantic search results.
            concepts:    Concept labels from graph expansion.

        Returns:
            A single insight sentence.
        """
        lower = input_text.lower()

        # 1. Error/debug pattern
        error_keywords = ("error", "exception", "traceback", "bug", "crash", "fail")
        if any(kw in lower for kw in error_keywords):
            return (
                "Likely debugging scenario. "
                "Suggest analysing logs and recent code changes."
            )

        # 2. Learning pattern
        learn_keywords = ("learn", "study", "understand", "explore", "explain")
        if any(kw in lower for kw in learn_keywords):
            if concepts:
                return f"Learning path involves: {', '.join(concepts[:5])}"
            return "Consider exploring related knowledge nodes in the memory graph."

        # 3. Memory hit — best match
        if memory_hits:
            best = memory_hits[0]
            text = str(best.get("text", ""))[:100]
            score = float(best.get("score", 0.0))
            if score >= 0.5:
                return f"Similar past knowledge suggests: {text}"
            if score > 0.2:
                return f"Weakly related knowledge: {text} — consider reinforcing."

        # 4. Concept pattern
        if concepts:
            top = concepts[:3]
            return f"Key concepts detected: {', '.join(top)}. Recommend deeper exploration."

        # 5. Default
        return "No strong pattern found. Recommend research."

    def intent_classify(self, thought: str) -> str:
        """Classify *thought* into an intent string.

        Applies :data:`_INTENT_PATTERNS` rules in order; the first keyword
        match wins.  Falls back to ``"respond"`` when no pattern matches.

        Args:
            thought: Reasoning string (typically the output of ``generate()``).

        Returns:
            Intent label: one of ``"debug"``, ``"research"``,
            ``"generate_code"``, ``"reflect"``, ``"trade"``, ``"evolve"``,
            or ``"respond"``.
        """
        lower = thought.lower()
        for keyword, intent in _INTENT_PATTERNS:
            if keyword in lower:
                return intent
        return "respond"

    def to_response(self, thought: str) -> str:
        """Extract the human-readable insight from a structured *thought* string.

        Searches for a line starting with ``"Insight:"`` and returns the
        content after the colon.  Falls back to the full *thought* if no
        insight line is found.

        Args:
            thought: Multi-line string produced by ``generate()``.

        Returns:
            Clean, single-sentence insight.
        """
        for line in thought.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith("insight:"):
                return stripped[len("insight:"):].strip()
        return thought.strip()


# ═════════════════════════════════════════════════════════════════════════════
# Kernel v2 Result
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class KernelV2Result:
    """Output of a single ``run_cognitive_loop()`` pass through KernelV2.

    Attributes
    ----------
    input_data:     The raw input provided to the loop.
    embedding:      The computed embedding vector (may be empty list).
    memory_hits:    Semantic search results from the MemoryGraph.
    concepts:       Expanded concept labels from ConceptGraph.
    thought:        Structured reasoning string from PatternSynthesizer.
    response:       Clean insight extracted from *thought*.
    decision:       Intent label from ``intent_classify()``.
    action_result:  String returned by ToolRouter (if action != "respond").
    remembered:     Whether ``remember()`` was called for this cycle.
    latency_ms:     Total wall-clock time in milliseconds.
    ts:             UNIX timestamp of completion.
    """
    input_data: Any
    embedding: List[float] = field(default_factory=list)
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    thought: str = ""
    response: str = ""
    decision: str = "respond"
    action_result: str = ""
    remembered: bool = False
    latency_ms: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": str(self.input_data)[:200],
            "memory_hits_count": len(self.memory_hits),
            "concepts": self.concepts[:8],
            "thought": self.thought[:400],
            "response": self.response,
            "decision": self.decision,
            "action_result": self.action_result[:300],
            "remembered": self.remembered,
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Temporal Focus Tracker (Section 12 of spec)
# ═════════════════════════════════════════════════════════════════════════════

class _TemporalFocusTracker:
    """Track rapid repeated access to a topic and return a focus boost.

    If the same topic is accessed ≥3 times within :data:`_FOCUS_WINDOW`
    seconds, ``check(topic)`` returns :data:`_FOCUS_BOOST`; otherwise 0.0.

    This creates the "focus" / short-term working memory effect described in
    section 12 of the MWDS v2 spec.

    Args:
        window:    Time window in seconds to count repeated accesses.
        threshold: Minimum access count within window to trigger boost.
        boost:     Importance delta returned when focus is active.
    """

    def __init__(
        self,
        window: float = _FOCUS_WINDOW,
        threshold: int = 3,
        boost: float = _FOCUS_BOOST,
    ) -> None:
        self._window = window
        self._threshold = threshold
        self._boost = boost
        self._history: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, topic: str) -> float:
        """Record access to *topic* and return the focus boost (0.0 or _boost)."""
        key = topic.lower()[:80]
        now = time.time()
        with self._lock:
            if key not in self._history:
                self._history[key] = deque()
            q = self._history[key]
            # Record this access
            q.append(now)
            # Expire old entries
            cutoff = now - self._window
            while q and q[0] < cutoff:
                q.popleft()
            count = len(q)
        return self._boost if count >= self._threshold else 0.0

    def clear(self, topic: Optional[str] = None) -> None:
        """Clear history for *topic* (or all topics if None)."""
        with self._lock:
            if topic is None:
                self._history.clear()
            else:
                self._history.pop(topic.lower()[:80], None)


# ═════════════════════════════════════════════════════════════════════════════
# NiblitCoreKernelV2
# ═════════════════════════════════════════════════════════════════════════════

class NiblitCoreKernelV2:
    """Niblit Cognitive Kernel v2.

    A self-contained local reasoning system that does NOT require an external
    LLM.  The full cognitive pipeline:

    1. **Embed** — convert input to a semantic vector (:class:`Embedder`).
    2. **Semantic search** — retrieve similar memories from
       :class:`~modules.niblit_core_kernel.KernelMemory`.
    3. **Graph expand** — grow the candidate set via :class:`ConceptGraph`.
    4. **Synthesize** — build structured reasoning via
       :class:`PatternSynthesizer`.
    5. **Classify** — detect intent (debug / research / code / reflect / …).
    6. **Act** — dispatch to the existing :class:`ToolRouter` when needed.
    7. **Remember** — persist the result through :class:`KernelMemory` + MWDS.

    After-response reinforcement closes the RL loop: successful retrievals
    strengthen the memories used; failed ones weaken them.

    Args:
        embedder:     Optional :class:`Embedder` (created lazily if None).
        concept_graph:Optional :class:`ConceptGraph` (created lazily if None).
        synthesizer:  Optional :class:`PatternSynthesizer` (created lazily).
        kernel_memory:Optional :class:`~modules.niblit_core_kernel.KernelMemory`
                      (created lazily if None).
        tool_router:  Optional :class:`~modules.niblit_core_kernel.ToolRouter`
                      (created lazily if None).
        embed_model:  SentenceTransformer model name override.
        focus_window: Temporal focus tracking window (seconds).
        focus_boost:  Importance delta applied when focus is active.
    """

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        concept_graph: Optional[ConceptGraph] = None,
        synthesizer: Optional[PatternSynthesizer] = None,
        kernel_memory: Optional[Any] = None,
        tool_router: Optional[Any] = None,
        embed_model: str = _EMBED_MODEL,
        focus_window: float = _FOCUS_WINDOW,
        focus_boost: float = _FOCUS_BOOST,
    ) -> None:
        self._embedder = embedder
        self._concept_graph = concept_graph
        self._synthesizer = synthesizer
        self._kernel_memory = kernel_memory
        self._tool_router = tool_router
        self._embed_model = embed_model

        self._focus = _TemporalFocusTracker(
            window=focus_window, boost=focus_boost
        )
        self._lock = threading.Lock()
        self._cycle_count: int = 0
        self._stats: Dict[str, int] = {
            "think_calls": 0,
            "decide_calls": 0,
            "act_calls": 0,
            "remember_calls": 0,
            "loop_calls": 0,
        }

        log.info("[NiblitCoreKernelV2] Cognitive Kernel v2 initialised")

    # ── Lazy component accessors ──────────────────────────────────────────────

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(model_name=self._embed_model)
        return self._embedder

    @property
    def concept_graph(self) -> ConceptGraph:
        if self._concept_graph is None:
            self._concept_graph = ConceptGraph()
        return self._concept_graph

    @property
    def synthesizer(self) -> PatternSynthesizer:
        if self._synthesizer is None:
            self._synthesizer = PatternSynthesizer()
        return self._synthesizer

    @property
    def memory(self) -> Any:
        """Lazily acquire the :class:`~modules.niblit_core_kernel.KernelMemory`."""
        if self._kernel_memory is None:
            try:
                from modules.niblit_core_kernel import get_niblit_core_kernel
                self._kernel_memory = get_niblit_core_kernel().memory
            except Exception:
                # Last-resort: create a fresh KernelMemory
                try:
                    from modules.niblit_core_kernel import KernelMemory
                    self._kernel_memory = KernelMemory()
                except Exception as exc:
                    log.debug("[KernelV2] KernelMemory unavailable: %s", exc)
        return self._kernel_memory

    @property
    def tool_router(self) -> Any:
        """Lazily acquire a :class:`~modules.niblit_core_kernel.ToolRouter`."""
        if self._tool_router is None:
            try:
                from modules.niblit_core_kernel import ToolRouter
                self._tool_router = ToolRouter()
            except Exception as exc:
                log.debug("[KernelV2] ToolRouter unavailable: %s", exc)
        return self._tool_router

    # ══════════════════════════════════════════════════════════════════════════
    # 1. THINK — embed → retrieve → expand → synthesise
    # ══════════════════════════════════════════════════════════════════════════

    def think(
        self,
        input_text: str,
        top_k: int = 5,
    ) -> Tuple[str, List[Dict[str, Any]], List[str]]:
        """Full cognitive reasoning pass.

        Steps:

        1. Embed *input_text* → dense vector.
        2. Semantic search in MemoryGraph → memory hits.
        3. Expand hits via ConceptGraph → concept labels.
        4. Synthesize reasoning → structured thought string.

        Also applies a temporal focus boost to the memory store when the
        same topic has been accessed multiple times in a short window.

        Args:
            input_text: The user query or task description.
            top_k:      Maximum memory hits to retrieve.

        Returns:
            ``(thought, memory_hits, concepts)`` — the structured reasoning
            string, the raw memory hits list, and the concept labels.
        """
        with self._lock:
            self._stats["think_calls"] += 1

        input_text = str(input_text)[:512]

        # ── Step 1: Embed ────────────────────────────────────────────────
        embedding = self.embedder.encode(input_text)

        # ── Step 2: Semantic search ──────────────────────────────────────
        memory_hits: List[Dict[str, Any]] = []
        mem = self.memory
        if mem is not None:
            try:
                memory_hits = mem.semantic_search(embedding, top_k=top_k)
            except Exception as exc:
                log.debug("[KernelV2] semantic_search failed: %s", exc)

        # ── Step 3: Graph expansion ──────────────────────────────────────
        concepts = self.concept_graph.expand(memory_hits)

        # ── Step 4: Synthesize reasoning ─────────────────────────────────
        thought = self.synthesizer.generate(input_text, memory_hits, concepts)

        # ── Temporal focus boost (Section 12) ────────────────────────────
        boost = self._focus.check(input_text[:80])
        if boost > 0 and mem is not None:
            try:
                # Briefly store the topic with boosted importance
                mem.store(
                    f"[focus] {input_text[:200]}",
                    importance=min(1.0, 0.7 + boost),
                    source="kernel",
                )
            except Exception:
                pass

        log.debug("[KernelV2] think: hits=%d concepts=%d", len(memory_hits), len(concepts))
        return thought, memory_hits, concepts

    # ══════════════════════════════════════════════════════════════════════════
    # 2. DECIDE — intent classification
    # ══════════════════════════════════════════════════════════════════════════

    def decide(self, thought: str) -> str:
        """Classify *thought* into an action label.

        Delegates to :meth:`PatternSynthesizer.intent_classify`.

        Args:
            thought: Reasoning string from ``think()``.

        Returns:
            Intent label string.
        """
        with self._lock:
            self._stats["decide_calls"] += 1
        intent = self.synthesizer.intent_classify(thought)
        log.debug("[KernelV2] decide → '%s'", intent)
        return intent

    # ══════════════════════════════════════════════════════════════════════════
    # 3. ACT — safe tool execution
    # ══════════════════════════════════════════════════════════════════════════

    def act(self, decision: str, payload: Any) -> str:
        """Execute *decision* with *payload*.

        Dispatches to :class:`~modules.niblit_core_kernel.ToolRouter` for
        known actions (``research``, ``generate_code``, ``reflect``,
        ``trade``, ``evolve``).  Falls back to a local response for
        ``"respond"`` and ``"debug"``.

        Args:
            decision: Intent label from ``decide()``.
            payload:  The reasoning string or user input.

        Returns:
            Human-readable result string.
        """
        with self._lock:
            self._stats["act_calls"] += 1

        # Map v2 intent labels to v1 ToolRouter actions
        _intent_to_action: Dict[str, str] = {
            "debug":         "reflect",
            "research":      "research",
            "generate_code": "code",
            "reflect":       "reflect",
            "trade":         "trade",
            "evolve":        "evolve",
            "respond":       "respond",
        }
        action = _intent_to_action.get(decision, "respond")

        tr = self.tool_router
        if tr is not None:
            try:
                return tr.execute(action, payload)
            except Exception as exc:
                log.debug("[KernelV2] ToolRouter.execute failed: %s", exc)

        # Minimal local fallback
        return f"Niblit v2: processed — {str(payload)[:120]}"

    # ══════════════════════════════════════════════════════════════════════════
    # 4. REMEMBER — write result through KernelMemory + MWDS
    # ══════════════════════════════════════════════════════════════════════════

    def remember(
        self,
        data: Any,
        importance: float = 0.5,
        source: str = "kernel",
    ) -> None:
        """Store *data* in KernelMemory (which delegates to MWDS v2).

        Args:
            data:       Any serialisable item.
            importance: MWDS weight hint ∈ [0, 1].
            source:     Provenance tag.
        """
        with self._lock:
            self._stats["remember_calls"] += 1
        importance = float(max(0.0, min(1.0, importance)))
        mem = self.memory
        if mem is not None:
            try:
                mem.store(data, importance=importance, source=source)
            except Exception as exc:
                log.debug("[KernelV2] remember failed: %s", exc)

    # ══════════════════════════════════════════════════════════════════════════
    # 5. REINFORCE — close the RL loop
    # ══════════════════════════════════════════════════════════════════════════

    def reinforce(self, text: str, success: bool = True) -> None:
        """Reinforce memories that match *text* in the MWDS store.

        Should be called after each interaction to signal whether the
        memories retrieved were useful.  Delegates to
        :meth:`~modules.niblit_core_kernel.KernelMemory.reinforce_content`.

        Args:
            text:    The memory content to reinforce (first 60 chars matched).
            success: True → memory strengthened; False → memory weakened.
        """
        mem = self.memory
        if mem is not None and hasattr(mem, "reinforce_content"):
            try:
                mem.reinforce_content(text, success=success)
            except Exception as exc:
                log.debug("[KernelV2] reinforce failed: %s", exc)

    # ══════════════════════════════════════════════════════════════════════════
    # Full cognitive loop
    # ══════════════════════════════════════════════════════════════════════════

    def run_cognitive_loop(
        self,
        input_data: Any,
        top_k: int = 5,
        auto_act: bool = True,
    ) -> KernelV2Result:
        """Run one full cognitive cycle.

        Pipeline::

            EMBED → RETRIEVE → EXPAND → SYNTHESIZE → CLASSIFY → ACT → REMEMBER

        After the cycle, the best memory hit (if any) is reinforced as
        successful to close the RL loop.

        Args:
            input_data: User query, task description, or sensor input.
            top_k:      Maximum memory hits for retrieval.
            auto_act:   If True, call ``act()`` for non-respond intents.

        Returns:
            :class:`KernelV2Result` with all intermediate outputs.
        """
        t0 = time.time()
        with self._lock:
            self._stats["loop_calls"] += 1
            self._cycle_count += 1

        result = KernelV2Result(input_data=input_data)

        # ── THINK ─────────────────────────────────────────────────────────
        thought, hits, concepts = self.think(str(input_data), top_k=top_k)
        result.thought = thought
        result.memory_hits = hits
        result.concepts = concepts

        # ── EXTRACT RESPONSE ──────────────────────────────────────────────
        result.response = self.synthesizer.to_response(thought)

        # ── DECIDE ────────────────────────────────────────────────────────
        result.decision = self.decide(thought)

        # ── ACT ───────────────────────────────────────────────────────────
        if auto_act and result.decision != "respond":
            result.action_result = self.act(result.decision, thought)
        else:
            result.action_result = result.response

        # ── REMEMBER ──────────────────────────────────────────────────────
        self.remember(
            {
                "input": str(input_data)[:200],
                "thought": thought[:200],
                "response": result.response[:200],
                "decision": result.decision,
            },
            importance=0.7,
            source="kernel",
        )
        result.remembered = True

        # ── REINFORCE best hit (RL loop) ───────────────────────────────────
        if hits:
            best_text = str(hits[0].get("text", ""))[:200]
            if best_text:
                self.reinforce(best_text, success=True)

        result.latency_ms = (time.time() - t0) * 1000
        result.ts = int(time.time())

        log.info(
            "[NiblitCoreKernelV2] cycle #%d: decision=%s latency=%.0fms",
            self._cycle_count, result.decision, result.latency_ms,
        )
        return result

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a snapshot of kernel v2 state and component health."""
        with self._lock:
            stats = dict(self._stats)
        mem_stats: Dict[str, Any] = {}
        if self.memory is not None:
            try:
                mem_stats = self.memory.stats()
            except Exception:
                pass
        return {
            **stats,
            "cycle_count": self._cycle_count,
            "embedder_fallback": self.embedder.using_fallback,
            "embedding_dim": self.embedder.embedding_dim,
            "memory": mem_stats,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_kernel_v2: Optional[NiblitCoreKernelV2] = None
_kernel_v2_lock = threading.Lock()


def get_niblit_core_kernel_v2(**kwargs) -> NiblitCoreKernelV2:
    """Return the process-level :class:`NiblitCoreKernelV2` singleton.

    Thread-safe, lazily created on first call.  Any keyword arguments are
    forwarded to the constructor **only** on the first call.
    """
    global _kernel_v2  # pylint: disable=global-statement
    with _kernel_v2_lock:
        if _kernel_v2 is None:
            _kernel_v2 = NiblitCoreKernelV2(**kwargs)
        return _kernel_v2
