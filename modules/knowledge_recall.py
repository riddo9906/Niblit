#!/usr/bin/env python3
"""modules/knowledge_recall.py — Smart Knowledge Retrieval & Synthesis for Niblit.

Modern AI systems (like GitHub Copilot) retrieve knowledge in three layers:

  1. **Relevance ranking** — facts are scored against the query, not just
     matched by keyword presence.  This module implements TF-IDF style
     scoring in pure Python so no extra dependencies are needed.

  2. **Synthesis** — a collection of related facts is merged into a coherent
     narrative paragraph ("thinking about a topic"), similar to how an LLM
     synthesises retrieved context before answering.

  3. **Health / coverage awareness** — the system can inspect *how well* it
     knows a topic: how many facts exist, how fresh they are, and how
     confident they are, so it can decide whether to learn more.

  4. **Contradiction surface** — when two stored facts about the same concept
     contain mutually exclusive claims, both are surfaced so the higher-
     confidence one can be trusted.

Public API
----------
``SmartRecall(knowledge_db)``
    Wraps any KnowledgeDB instance.

``SmartRecall.recall(query, limit) → List[dict]``
    TF-IDF ranked fact retrieval.  Returns the *limit* most relevant facts.

``SmartRecall.think_about(topic) → str``
    Synthesise a human-readable paragraph from all facts about *topic*.

``SmartRecall.find_contradictions(topic) → List[Tuple[dict,dict,float]]``
    Return pairs of facts whose value text significantly disagrees.

``SmartRecall.knowledge_health(topic) → dict``
    Return ``{coverage, freshness, confidence, fact_count, verdict}``.

``SmartRecall.consolidate(dry_run) → dict``
    Merge duplicate facts (same key) and return a report.

``get_smart_recall(knowledge_db) → SmartRecall``
    Return (or build) the process-wide singleton.

Design
------
* Pure stdlib — no numpy/sklearn/transformers required.
* Additive — does not remove or rewrite any existing KB facts.
* Thread-safe singleton.
* Never raises — all methods return safe defaults on error.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("SmartRecall")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Minimum TF-IDF score to be included in results
_MIN_SCORE: float = 0.01

# Maximum characters used for scoring a single fact value
_SCORE_MAX_CHARS: int = 800

# Freshness half-life in days — confidence weight from recency
_FRESHNESS_HALF_LIFE_DAYS: float = 30.0

# Contradiction: two facts are "contradictory" when their cosine similarity
# over word overlap is below this threshold *and* they share key vocabulary.
_CONTRADICTION_THRESHOLD: float = 0.10

# Maximum fact pairs to check for contradictions (avoids O(n²) blowup)
_MAX_CONTRADICTION_CHECKS: int = 200

# Minimum word-level Jaccard overlap to consider two facts "about the same thing"
_SAME_TOPIC_JACCARD: float = 0.12

# English stop words — excluded from TF-IDF term lists
_STOP_WORDS: frozenset = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "with",
    "and", "or", "but", "not", "be", "is", "are", "was", "were", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "shall", "that", "this", "these",
    "those", "it", "its", "as", "by", "if", "then", "so", "than", "about",
    "into", "through", "after", "before", "between", "such", "each",
    "also", "which", "when", "where", "how", "what", "who", "why",
    "there", "their", "they", "we", "you", "your", "our", "more", "some",
    "any", "all", "both", "other", "most", "very", "just", "only",
    "no", "found", "data", "use", "used", "using", "based", "new", "get",
})

# Negation words — presence means "opposite claim" when comparing facts
_NEGATIONS: frozenset = frozenset({
    "not", "no", "never", "neither", "nor", "cannot", "can't", "won't",
    "isn't", "aren't", "wasn't", "weren't", "doesn't", "don't", "didn't",
})

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']*[a-zA-Z]|[a-zA-Z]{1,2}")


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Lowercase word tokens, stop-words removed."""
    return [
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(str(text)[:_SCORE_MAX_CHARS])
        if m.group(0).lower() not in _STOP_WORDS and len(m.group(0)) >= 3
    ]


def _fact_text(fact: Any) -> str:
    """Extract a flat string representation of a fact value for scoring."""
    if not isinstance(fact, dict):
        return str(fact)[:_SCORE_MAX_CHARS]
    value = fact.get("value", "")
    if isinstance(value, dict):
        # Pull the most informative field
        for field in ("summary", "text", "content", "research", "reflection", "direction"):
            if field in value:
                value = value[field]
                break
        else:
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
    key = str(fact.get("key", ""))
    return f"{key} {value}"[:_SCORE_MAX_CHARS]


def _cosine_token(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Cosine similarity over bag-of-words token counts."""
    if not tokens_a or not tokens_b:
        return 0.0
    c_a = Counter(tokens_a)
    c_b = Counter(tokens_b)
    vocab = set(c_a) | set(c_b)
    dot = sum(c_a.get(w, 0) * c_b.get(w, 0) for w in vocab)
    norm_a = math.sqrt(sum(v * v for v in c_a.values())) or 1.0
    norm_b = math.sqrt(sum(v * v for v in c_b.values())) or 1.0
    return dot / (norm_a * norm_b)


def _jaccard(tokens_a: List[str], tokens_b: List[str]) -> float:
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ─────────────────────────────────────────────────────────────────────────────
# TF-IDF index (built lazily over a fact corpus)
# ─────────────────────────────────────────────────────────────────────────────

class _TFIDFIndex:
    """Minimal in-memory TF-IDF index built over a list of text documents."""

    def __init__(self, docs: List[str]) -> None:
        self._n = len(docs)
        self._token_lists: List[List[str]] = [_tokenize(d) for d in docs]
        # DF: how many documents contain each term
        df: Counter = Counter()
        for tokens in self._token_lists:
            for tok in set(tokens):
                df[tok] += 1
        self._idf: Dict[str, float] = {
            term: math.log((self._n + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

    def score(self, query_tokens: List[str], doc_idx: int) -> float:
        """TF-IDF score of *query_tokens* against document *doc_idx*."""
        doc_tokens = self._token_lists[doc_idx]
        if not doc_tokens:
            return 0.0
        tf: Counter = Counter(doc_tokens)
        max_tf = max(tf.values(), default=1)
        total = 0.0
        for qt in query_tokens:
            if qt in tf:
                normalized_tf = tf[qt] / max_tf
                idf = self._idf.get(qt, 1.0)
                total += normalized_tf * idf
        # Length normalisation
        return total / (math.sqrt(len(doc_tokens)) or 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# SmartRecall
# ─────────────────────────────────────────────────────────────────────────────

class SmartRecall:
    """Smart knowledge retrieval and synthesis over a KnowledgeDB instance.

    Designed to mirror how a capable AI system:
    * Ranks facts by relevance (TF-IDF) rather than string containment
    * Synthesises related facts into coherent answers
    * Detects contradictory beliefs
    * Scores knowledge health (coverage, freshness, confidence)
    * Prunes and consolidates duplicates
    """

    def __init__(self, knowledge_db: Any) -> None:
        self._db = knowledge_db

    # ── helpers ───────────────────────────────────────────────────────────────

    def _all_facts(self) -> List[Dict[str, Any]]:
        """Return all stored facts as a list of dicts."""
        try:
            facts = self._db.list_facts(limit=5000)
        except Exception:
            facts = []
        return [f for f in facts if isinstance(f, dict)]

    # ── public API ────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        limit: int = 10,
        min_score: float = _MIN_SCORE,
    ) -> List[Dict[str, Any]]:
        """Return the *limit* most relevant facts for *query* using TF-IDF.

        Falls back to an empty list on any error.  Results are sorted by
        descending TF-IDF score and include a ``"_score"`` field.
        """
        if not query:
            return []
        try:
            facts = self._all_facts()
            if not facts:
                return []
            docs = [_fact_text(f) for f in facts]
            index = _TFIDFIndex(docs)
            query_tokens = _tokenize(query)
            if not query_tokens:
                return []
            scored: List[Tuple[float, Dict[str, Any]]] = []
            for i, fact in enumerate(facts):
                s = index.score(query_tokens, i)
                if s >= min_score:
                    copy = dict(fact)
                    copy["_score"] = round(s, 4)
                    scored.append((s, copy))
            scored.sort(key=lambda x: -x[0])
            return [item for _, item in scored[:limit]]
        except Exception as exc:
            log.debug("[SmartRecall.recall] error: %s", exc)
            return []

    def think_about(self, topic: str, max_facts: int = 20) -> str:
        """Synthesise a human-readable summary of what Niblit knows about *topic*.

        Retrieves the most relevant facts (TF-IDF), then assembles them into a
        structured answer grouped by source/tag category.  This mirrors how an
        AI system synthesises retrieved context before generating a response.

        Returns a multi-line string suitable for display.  Never raises.
        """
        if not topic:
            return "(no topic provided)"
        try:
            facts = self.recall(topic, limit=max_facts)
            if not facts:
                return (
                    f"I have no stored knowledge about '{topic}' yet.\n"
                    f"Try: self-teach {topic}  — to learn more about it."
                )

            # Group by inferred category (tags or key prefix)
            groups: Dict[str, List[str]] = {}
            for fact in facts:
                tags = fact.get("tags", [])
                cat = _infer_category(fact.get("key", ""), tags)
                text = _readable_value(fact)
                if text:
                    groups.setdefault(cat, []).append(text)

            health = self.knowledge_health(topic)
            conf_pct = int(health.get("avg_confidence", 1.0) * 100)
            freshness_pct = int(health.get("freshness", 1.0) * 100)
            fact_count = health.get("fact_count", len(facts))

            lines = [
                f"🧠 What Niblit knows about «{topic}»",
                f"   ({fact_count} facts | confidence {conf_pct}% | freshness {freshness_pct}%)",
                "",
            ]
            for cat, texts in groups.items():
                lines.append(f"▸ {cat}:")
                for t in texts[:5]:
                    lines.append(f"  • {t[:140]}")
            lines.append("")
            lines.append(
                f"  Use 'kb health {topic}' for coverage details or "
                f"'self-teach {topic}' to learn more."
            )
            return "\n".join(lines)
        except Exception as exc:
            log.debug("[SmartRecall.think_about] error: %s", exc)
            return f"[think_about error: {exc}]"

    def find_contradictions(
        self,
        topic: str = "",
        max_pairs: int = 10,
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
        """Find pairs of facts that may contain contradictory claims.

        Two facts are considered potentially contradictory when:
        1. They share substantial vocabulary about the same subject (Jaccard ≥
           ``_SAME_TOPIC_JACCARD``).
        2. One contains negation words that invert the other's claim, OR their
           bag-of-words cosine similarity is very low despite shared vocabulary.

        Returns a list of ``(fact_a, fact_b, conflict_score)`` triples sorted
        by descending conflict score.  ``conflict_score`` ∈ [0, 1].
        """
        try:
            if topic:
                candidates = self.recall(topic, limit=50)
            else:
                facts = self._all_facts()
                candidates = facts[:_MAX_CONTRADICTION_CHECKS]

            pairs: List[Tuple[Dict, Dict, float]] = []
            n = len(candidates)
            for i in range(min(n, _MAX_CONTRADICTION_CHECKS)):
                for j in range(i + 1, min(n, _MAX_CONTRADICTION_CHECKS)):
                    fa, fb = candidates[i], candidates[j]
                    score = _contradiction_score(fa, fb)
                    if score > 0.0:
                        pairs.append((fa, fb, score))

            pairs.sort(key=lambda x: -x[2])
            return pairs[:max_pairs]
        except Exception as exc:
            log.debug("[SmartRecall.find_contradictions] error: %s", exc)
            return []

    def knowledge_health(self, topic: str = "") -> Dict[str, Any]:
        """Assess the health of stored knowledge about *topic*.

        Returns::

            {
                "fact_count":       int,
                "avg_confidence":   float,     # 0.0–1.0
                "freshness":        float,      # 0.0–1.0 (1.0 = all very recent)
                "coverage_score":   float,      # 0.0–1.0 combined
                "verdict":          str,        # "strong" / "moderate" / "sparse" / "unknown"
            }
        """
        try:
            if topic:
                facts = self.recall(topic, limit=100)
            else:
                facts = self._all_facts()[:200]

            if not facts:
                return {
                    "fact_count": 0,
                    "avg_confidence": 0.0,
                    "freshness": 0.0,
                    "coverage_score": 0.0,
                    "verdict": "unknown",
                }

            now = time.time()
            confidences: List[float] = []
            freshnesses: List[float] = []
            for fact in facts:
                conf = float(fact.get("confidence", 1.0))
                confidences.append(conf)
                ts = float(fact.get("ts", now))
                age_days = (now - ts) / 86400.0
                fresh = math.exp(
                    -math.log(2) * age_days / _FRESHNESS_HALF_LIFE_DAYS
                )
                freshnesses.append(fresh)

            avg_conf = sum(confidences) / len(confidences)
            avg_fresh = sum(freshnesses) / len(freshnesses)
            coverage = (avg_conf * 0.6 + avg_fresh * 0.4)

            if coverage >= 0.70 and len(facts) >= 5:
                verdict = "strong"
            elif coverage >= 0.40 or len(facts) >= 3:
                verdict = "moderate"
            elif len(facts) >= 1:
                verdict = "sparse"
            else:
                verdict = "unknown"

            return {
                "fact_count": len(facts),
                "avg_confidence": round(avg_conf, 3),
                "freshness": round(avg_fresh, 3),
                "coverage_score": round(coverage, 3),
                "verdict": verdict,
            }
        except Exception as exc:
            log.debug("[SmartRecall.knowledge_health] error: %s", exc)
            return {
                "fact_count": 0,
                "avg_confidence": 0.0,
                "freshness": 0.0,
                "coverage_score": 0.0,
                "verdict": "unknown",
            }

    def consolidate(self, dry_run: bool = False) -> Dict[str, Any]:
        """Merge duplicate facts (same key, deduplicate) and optionally prune
        low-confidence stale facts.

        Parameters
        ----------
        dry_run: When True, only reports what *would* change, without modifying
                 the database.

        Returns a report dict::

            {
                "duplicate_groups": int,
                "facts_merged":     int,
                "facts_pruned":     int,
                "dry_run":          bool,
            }
        """
        try:
            facts = self._all_facts()
            # Group facts by key
            by_key: Dict[str, List[Dict[str, Any]]] = {}
            for fact in facts:
                key = str(fact.get("key", ""))
                by_key.setdefault(key, []).append(fact)

            merged = 0
            dup_groups = 0
            for key, group in by_key.items():
                if len(group) < 2:
                    continue
                dup_groups += 1
                if dry_run:
                    merged += len(group) - 1
                    continue
                # Keep the fact with the highest confidence (or most recent)
                best = max(
                    group,
                    key=lambda f: (
                        float(f.get("confidence", 1.0)),
                        float(f.get("ts", 0)),
                    ),
                )
                # Merge tags from all duplicates
                merged_tags: List[str] = []
                for f in group:
                    merged_tags.extend(f.get("tags", []))
                best["tags"] = list(set(merged_tags))
                # Remove duplicates, keep best
                for f in group:
                    if f is not best:
                        try:
                            self._db.delete_fact(key)
                        except Exception:
                            pass
                        merged += 1

            return {
                "duplicate_groups": dup_groups,
                "facts_merged": merged,
                "facts_pruned": 0,
                "dry_run": dry_run,
            }
        except Exception as exc:
            log.debug("[SmartRecall.consolidate] error: %s", exc)
            return {
                "duplicate_groups": 0,
                "facts_merged": 0,
                "facts_pruned": 0,
                "dry_run": dry_run,
                "error": str(exc),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _infer_category(key: str, tags: List[str]) -> str:
    """Map a key + tags to a readable category label."""
    tags_lower = {str(t).lower() for t in (tags or [])}
    key_lower = key.lower()

    _CAT_MAP = [
        ("trading",     "Trading & Finance"),
        ("trade",       "Trading & Finance"),
        ("market",      "Trading & Finance"),
        ("code",        "Code & Programming"),
        ("compiled",    "Code & Programming"),
        ("research",    "Research"),
        ("science",     "Science & Technology"),
        ("learning",    "Learning"),
        ("ale",         "Autonomous Learning"),
        ("topic",       "Topic Knowledge"),
        ("concept",     "Concepts"),
        ("study",       "Study Sessions"),
        ("software",    "Software"),
    ]
    for keyword, label in _CAT_MAP:
        if keyword in key_lower or any(keyword in t for t in tags_lower):
            return label
    return "General Knowledge"


def _readable_value(fact: Dict[str, Any]) -> str:
    """Extract a short readable string from a fact for display."""
    value = fact.get("value", "")
    if isinstance(value, dict):
        for field in ("summary", "text", "research", "content", "reflection", "direction"):
            if field in value:
                value = value[field]
                break
        else:
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
    text = str(value).strip()
    # Remove internal system prefixes like [ALE] step X
    text = re.sub(r"^\s*\[ALE\]\s*step\s*\d+[^:]*:\s*", "", text)
    text = re.sub(r"^\s*\{.*?'step':\s*'[^']*'\s*,\s*", "", text)
    return text[:200]


def _contradiction_score(fa: Dict[str, Any], fb: Dict[str, Any]) -> float:
    """Return a conflict score ∈ [0, 1] between two facts.

    High score → likely contradictory.  0 → no evidence of conflict.
    """
    text_a = _fact_text(fa)
    text_b = _fact_text(fb)
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    # Must share enough vocabulary to be "about the same thing"
    jaccard = _jaccard(tokens_a, tokens_b)
    if jaccard < _SAME_TOPIC_JACCARD:
        return 0.0

    cos = _cosine_token(tokens_a, tokens_b)

    # Check for negation asymmetry: one has negation words, the other doesn't
    neg_a = bool(_NEGATIONS & set(tokens_a))
    neg_b = bool(_NEGATIONS & set(tokens_b))
    negation_flip = neg_a != neg_b  # one asserts positive, other asserts negative

    # Low cosine + shared vocabulary = different things said about same concept
    divergence = 1.0 - cos

    if negation_flip:
        # Strong signal of contradiction
        score = min(1.0, jaccard * 2.0 * divergence + 0.3)
    else:
        score = jaccard * divergence

    return round(score, 4) if score > _CONTRADICTION_THRESHOLD else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[SmartRecall] = None
_instance_lock = threading.Lock()


def get_smart_recall(knowledge_db: Any = None) -> SmartRecall:
    """Return (or build) the process-wide :class:`SmartRecall` singleton.

    If *knowledge_db* is provided, it will be used when constructing the
    instance.  Subsequent calls return the existing singleton regardless.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                if knowledge_db is None:
                    try:
                        from niblit_memory import GLOBAL_KNOWLEDGE
                        knowledge_db = GLOBAL_KNOWLEDGE
                    except Exception:
                        pass
                _instance = SmartRecall(knowledge_db)
    return _instance


if __name__ == "__main__":
    print("Running knowledge_recall.py — SmartRecall engine")
