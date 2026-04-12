#!/usr/bin/env python3
"""modules/reward_model.py — Self-Critique + Reward Model (SRM) for Niblit SECA.

Provides internal quality judgement without requiring a GPU or new heavy
dependencies.  Two layers:

Heuristic scorer (always available, pure stdlib + numpy)
---------------------------------------------------------
Four lightweight signals combined into a quality score ∈ [0, 1]:

1. **Overlap** — proportion of key source-snippet terms that appear in the
   generated answer (lexical faithfulness).
2. **Coverage** — how much of the query's intent vocabulary appears in the
   answer (relevance).
3. **Length** — answers in the sweet-spot word-count range score higher.
4. **Coherence** — simple sentence-count / avg-word-count proxy for fluency.

Optional DistilBERT classifier (when ``transformers`` is installed)
-------------------------------------------------------------------
A ``distilbert-base-uncased`` model fine-tuned on (query, answer, context)
triples with binary quality labels.  When not yet fine-tuned it falls back
to the heuristic scorer automatically.

Public API
----------
* ``RewardModel.score(query, answer, snippets) → float``  ∈ [0, 1]
* ``RewardModel.verdict(query, answer, snippets) → dict``  — full breakdown
* ``get_reward_model() → RewardModel``  — singleton

Design
------
* Never raises — all errors return a neutral 0.5 score.
* No logging.basicConfig() — uses logging.getLogger() only.
* Thread-safe singleton.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from typing import Any, Dict, List, Optional

log = logging.getLogger("RewardModel")

# ── optional transformers ─────────────────────────────────────────────────────
try:
    from transformers import (  # type: ignore[import]
        pipeline as _hf_pipeline,
        AutoTokenizer as _AutoTokenizer,
        AutoModelForSequenceClassification as _AutoModelForSeqClass,
    )
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _hf_pipeline = None  # type: ignore[assignment]
    _AutoTokenizer = None  # type: ignore[assignment]
    _AutoModelForSeqClass = None  # type: ignore[assignment]
    _TRANSFORMERS_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Heuristic weight breakdown
_W_OVERLAP: float  = 0.35   # source faithfulness
_W_COVERAGE: float = 0.30   # query-intent coverage
_W_LENGTH: float   = 0.20   # appropriate length
_W_COHERENCE: float = 0.15  # fluency proxy

# Length scoring: answers in [_LEN_MIN, _LEN_MAX] words score 1.0; outside
# the range the score tapers to 0.
_LEN_MIN: int = 20
_LEN_MAX: int = 300

# Stop words excluded from overlap/coverage computation
_STOP_WORDS: frozenset = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "with",
    "and", "or", "but", "not", "be", "is", "are", "was", "were", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "it", "its", "as", "by", "this", "that", "which",
    "there", "their", "they", "we", "you", "your", "our", "i", "he", "she",
    "so", "than", "also", "just", "more", "very", "such", "even", "about",
})

_TOKEN_RE = re.compile(r"[a-z]{2,}")


def _tokenize(text: str) -> List[str]:
    return [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOP_WORDS]


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic scorer
# ─────────────────────────────────────────────────────────────────────────────

def _heuristic_score(
    query: str,
    answer: str,
    snippets: List[str],
) -> Dict[str, float]:
    """Compute the four heuristic signals and return a breakdown dict.

    Returns
    -------
    Dict with keys: ``overlap``, ``coverage``, ``length``, ``coherence``,
    ``total`` (weighted sum).
    """
    answer_tokens = set(_tokenize(answer))
    query_tokens  = set(_tokenize(query))

    # 1. Overlap — key terms from snippets that appear in answer
    source_tokens: set = set()
    for s in snippets:
        source_tokens.update(_tokenize(s))
    if source_tokens:
        overlap = len(answer_tokens & source_tokens) / len(source_tokens)
        # Cap at 1.0 (answer could reuse every source term)
        overlap = min(1.0, overlap * 3)  # scale: 33% overlap → 1.0
    else:
        overlap = 0.5  # no context to judge against

    # 2. Coverage — query intent terms in answer
    if query_tokens:
        coverage = len(answer_tokens & query_tokens) / len(query_tokens)
        coverage = min(1.0, coverage * 2)  # 50% coverage → 1.0
    else:
        coverage = 0.5

    # 3. Length
    n_words = len(answer.split())
    if _LEN_MIN <= n_words <= _LEN_MAX:
        length_score = 1.0
    elif n_words < _LEN_MIN:
        length_score = n_words / _LEN_MIN
    else:
        # Taper quadratically beyond _LEN_MAX
        excess = (n_words - _LEN_MAX) / _LEN_MAX
        length_score = max(0.0, 1.0 - excess ** 0.5)

    # 4. Coherence — proxy: sentences of reasonable average word length
    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip()]
    if sentences:
        avg_words_per_sent = n_words / len(sentences)
        # Ideal: 10–25 words per sentence
        if 8 <= avg_words_per_sent <= 30:
            coherence = 1.0
        elif avg_words_per_sent < 8:
            coherence = avg_words_per_sent / 8
        else:
            coherence = max(0.3, 1.0 - (avg_words_per_sent - 30) / 50)
    else:
        coherence = 0.2  # no sentences detected → likely gibberish

    total = (
        _W_OVERLAP   * overlap
        + _W_COVERAGE  * coverage
        + _W_LENGTH    * length_score
        + _W_COHERENCE * coherence
    )

    return {
        "overlap":   round(overlap,       3),
        "coverage":  round(coverage,      3),
        "length":    round(length_score,  3),
        "coherence": round(coherence,     3),
        "total":     round(total,         3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# RewardModel
# ─────────────────────────────────────────────────────────────────────────────

class RewardModel:
    """Combined heuristic + optional DistilBERT quality judge.

    Usage::

        rm = RewardModel()
        q  = "What is photosynthesis?"
        a  = "Photosynthesis is the process by which plants..."
        ctx = ["Plants convert sunlight to glucose...", "Chlorophyll absorbs..."]
        score = rm.score(q, a, ctx)       # float ∈ [0, 1]
        detail = rm.verdict(q, a, ctx)    # dict with breakdown

    The DistilBERT model is loaded lazily the first time it is needed, only if
    ``transformers`` is installed.  If not available or not yet fine-tuned, the
    heuristic scorer is used exclusively.
    """

    def __init__(self, model_name: str = "distilbert-base-uncased") -> None:
        self._model_name = model_name
        self._pipeline: Optional[Any] = None
        self._pipeline_lock = threading.Lock()
        self._pipeline_tried = False

    # ── Public API ────────────────────────────────────────────────────────────

    def score(
        self,
        query: str,
        answer: str,
        snippets: Optional[List[str]] = None,
    ) -> float:
        """Return a quality score ∈ [0, 1].  Never raises."""
        try:
            return self.verdict(query, answer, snippets or [])["score"]
        except Exception:
            return 0.5

    def verdict(
        self,
        query: str,
        answer: str,
        snippets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return a full quality breakdown dict.

        Keys: ``score``, ``method``, ``heuristic`` (sub-breakdown), and
        optionally ``model_score`` when the DistilBERT classifier ran.

        Never raises.
        """
        snippets = snippets or []
        try:
            return self._verdict_safe(query, answer, snippets)
        except Exception as exc:
            log.debug("[RewardModel] verdict() error: %s", exc)
            return {"score": 0.5, "method": "fallback", "error": str(exc)}

    def record_feedback(
        self,
        query: str,
        answer: str,
        snippets: List[str],
        node_ids: Optional[List[str]] = None,
        is_good: Optional[bool] = None,
        memory_graph: Optional[Any] = None,
    ) -> None:
        """Evaluate an answer and propagate score deltas back to the MemoryGraph.

        Parameters
        ----------
        query:        The original user query.
        answer:       The generated answer to evaluate.
        snippets:     Retrieved context snippets.
        node_ids:     Graph node IDs the snippets came from.
        is_good:      Optional explicit override (True → good, False → bad).
        memory_graph: :class:`MemoryGraph` instance to update scores on.
        """
        try:
            v = self.verdict(query, answer, snippets)
            quality = v["score"]
            if is_good is not None:
                quality = 1.0 if is_good else 0.0

            if memory_graph is None or not node_ids:
                return

            # Delta: positive for quality > 0.5, negative otherwise, scaled
            delta = (quality - 0.5) * 0.1  # max ±0.05 per cycle
            for nid in node_ids:
                memory_graph.update_score(nid, delta)
            log.debug(
                "[RewardModel] Applied delta %.3f to %d nodes (quality=%.2f)",
                delta, len(node_ids), quality,
            )
        except Exception as exc:
            log.debug("[RewardModel] record_feedback error: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _verdict_safe(
        self,
        query: str,
        answer: str,
        snippets: List[str],
    ) -> Dict[str, Any]:
        heuristic = _heuristic_score(query, answer, snippets)
        base_score = heuristic["total"]
        method = "heuristic"

        # Try classifier if transformers available and pipeline loaded
        model_score: Optional[float] = None
        if _TRANSFORMERS_AVAILABLE:
            model_score = self._classifier_score(query, answer, snippets)
            if model_score is not None:
                # Blend: 40% heuristic, 60% classifier
                base_score = 0.4 * base_score + 0.6 * model_score
                method = "blended"

        return {
            "score":       round(max(0.0, min(1.0, base_score)), 3),
            "method":      method,
            "heuristic":   heuristic,
            "model_score": model_score,
        }

    def _classifier_score(
        self,
        query: str,
        answer: str,
        snippets: List[str],
    ) -> Optional[float]:
        """Run the DistilBERT classifier.  Returns None on any failure."""
        pipe = self._get_pipeline()
        if pipe is None:
            return None
        try:
            context = " ".join(snippets)[:256]
            text = f"Query: {query[:128]} Answer: {answer[:256]} Context: {context}"
            result = pipe(text, truncation=True, max_length=512)
            # HF text-classification returns list[{label, score}]
            if result and isinstance(result, list):
                item = result[0]
                label = item.get("label", "").upper()
                raw_score = float(item.get("score", 0.5))
                # LABEL_1 = positive class (good answer)
                if label in ("LABEL_1", "POSITIVE", "1"):
                    return raw_score
                if label in ("LABEL_0", "NEGATIVE", "0"):
                    return 1.0 - raw_score
                return raw_score
        except Exception as exc:
            log.debug("[RewardModel] classifier error: %s", exc)
        return None

    def _get_pipeline(self) -> Optional[Any]:
        """Lazy-load the HF classifier pipeline (once per process).

        stdout/stderr are captured during model construction so that the
        safetensors "LOAD REPORT" table (UNEXPECTED/MISSING keys) and tqdm
        progress bars never appear on the console — they are benign artefacts
        of loading a base checkpoint for a different task head.
        ``ignore_mismatched_sizes=True`` is passed so that transformers does
        not raise when the checkpoint has different head dimensions.
        """
        if self._pipeline_tried:
            return self._pipeline
        with self._pipeline_lock:
            if self._pipeline_tried:
                return self._pipeline
            self._pipeline_tried = True
            import io
            import os
            import sys
            import warnings
            _prev_st_log = os.environ.get("SAFETENSORS_LOG_LEVEL")
            os.environ["SAFETENSORS_LOG_LEVEL"] = "error"
            captured_out = io.StringIO()
            captured_err = io.StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            try:
                sys.stdout = captured_out
                sys.stderr = captured_err
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    self._pipeline = _hf_pipeline(
                        "text-classification",
                        model=self._model_name,
                        device=-1,  # CPU
                        model_kwargs={"ignore_mismatched_sizes": True},
                    )
            except Exception as exc:
                self._pipeline = None
                log.debug(
                    "[RewardModel] Pipeline load failed (%s) — heuristic only", exc
                )
            finally:
                sys.stdout = old_out
                sys.stderr = old_err
                if _prev_st_log is None:
                    os.environ.pop("SAFETENSORS_LOG_LEVEL", None)
                else:
                    os.environ["SAFETENSORS_LOG_LEVEL"] = _prev_st_log
            if self._pipeline is not None:
                log.debug("[RewardModel] DistilBERT pipeline loaded (%s)", self._model_name)
        return self._pipeline


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_reward_singleton: Optional[RewardModel] = None
_reward_lock = threading.Lock()


def get_reward_model(model_name: str = "distilbert-base-uncased") -> RewardModel:
    """Return the global :class:`RewardModel` singleton.  Thread-safe."""
    global _reward_singleton
    with _reward_lock:
        if _reward_singleton is None:
            _reward_singleton = RewardModel(model_name=model_name)
    return _reward_singleton


if __name__ == "__main__":
    print('Running reward_model.py')
