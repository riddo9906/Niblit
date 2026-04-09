#!/usr/bin/env python3
"""modules/concept_synthesizer.py — Memory Compression + Abstraction for Niblit SECA.

As Niblit's knowledge base grows, raw snippets accumulate.  This module
periodically clusters similar snippets into *meta-nodes* — compact
abstractions that replace redundant detail with distilled understanding.

Architecture
------------
::

    raw snippets  →  embed  →  cluster (k-means or greedy cosine)
                 →  summarise each cluster  →  meta-node stored in KB + MemoryGraph

Two clustering strategies (selected automatically)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* **scikit-learn k-means** (preferred, when ``sklearn`` is installed) — fast,
  stable, supports any *k*.
* **Greedy cosine grouping** (stdlib fallback) — O(n²) but correct; suitable
  for up to ~500 nodes.

Abstraction hierarchy
~~~~~~~~~~~~~~~~~~~~~
::

    Level 0: raw snippet nodes (created by MemoryGraph.add())
    Level 1: concept clusters (created by ConceptSynthesizer.synthesize())
    Level 2: meta-clusters  (future: second pass over level-1 nodes)

Public API
----------
* ``ConceptSynthesizer.synthesize(node_records, k) → list[meta-node dicts]``
* ``ConceptSynthesizer.maybe_synthesize(graph, knowledge_db, min_new) → int``
  — convenience: runs synthesis when enough new nodes have accumulated.
* ``get_concept_synthesizer() → ConceptSynthesizer``  — singleton.

Design
------
* No new mandatory dependencies (sklearn is optional).
* Uses the existing MemoryGraph to store meta-nodes.
* Writes ``arc:<topic>:<ts>`` KB facts for each abstraction cluster.
* Thread-safe singleton.
* Never raises — all errors are logged at DEBUG level.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("ConceptSynthesizer")

# ── optional sklearn ──────────────────────────────────────────────────────────
try:
    from sklearn.cluster import KMeans as _KMeans  # type: ignore[import]
    _SKLEARN_AVAILABLE = True
except ImportError:
    _KMeans = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False

# ── optional numpy ────────────────────────────────────────────────────────────
try:
    import numpy as _np
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Minimum number of new nodes added since last synthesis to trigger a pass
_MIN_NEW_NODES_DEFAULT: int = 50

# Default number of clusters (k) for synthesis
_DEFAULT_K: int = 8

# Maximum text length for a meta-node summary (chars)
_META_NODE_MAX_LEN: int = 400

# Cosine similarity threshold for greedy grouping fallback
_GREEDY_SIM_THRESHOLD: float = 0.55

# Prefix used for meta-node IDs
_META_PREFIX: str = "meta:"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity (falls back gracefully from numpy)."""
    if _NP_AVAILABLE:
        try:
            va = _np.array(a, dtype="float32")
            vb = _np.array(b, dtype="float32")
            denom = float(_np.linalg.norm(va) * _np.linalg.norm(vb))
            return float(_np.dot(va, vb) / denom) if denom else 0.0
        except Exception:
            return 0.0
    try:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        return dot / (mag_a * mag_b) if (mag_a and mag_b) else 0.0
    except Exception:
        return 0.0


def _mean_vector(vectors: List[List[float]]) -> Optional[List[float]]:
    """Element-wise mean of a list of float vectors."""
    if not vectors:
        return None
    dim = len(vectors[0])
    if _NP_AVAILABLE:
        try:
            arr = _np.array(vectors, dtype="float32")
            return arr.mean(axis=0).tolist()
        except Exception:
            pass
    # Pure-Python fallback
    try:
        result = [0.0] * dim
        n = len(vectors)
        for v in vectors:
            for i, x in enumerate(v):
                result[i] += x / n
        return result
    except Exception:
        return None


def _cluster_summary(texts: List[str]) -> str:
    """Produce a compact text summary for a cluster by combining key phrases.

    Takes the longest text as the "anchor" and prepends token-frequency-derived
    key phrases from the rest of the cluster.
    """
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0][:_META_NODE_MAX_LEN]

    # Gather top-frequency non-stop-word tokens across all texts
    _stop = frozenset({
        "the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
        "and", "or", "is", "are", "was", "it", "its", "by", "be", "been",
        "this", "that", "which", "they", "we", "as", "so", "than",
    })
    freq: Dict[str, int] = {}
    for t in texts:
        words = re.findall(r"[a-z]{3,}", t.lower())
        for w in words:
            if w not in _stop:
                freq[w] = freq.get(w, 0) + 1

    top_terms = sorted(freq, key=lambda w: freq[w], reverse=True)[:5]
    anchor = max(texts, key=len)
    prefix = f"[Concepts: {', '.join(top_terms)}] " if top_terms else ""
    summary = (prefix + anchor.strip())[:_META_NODE_MAX_LEN]
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# ConceptSynthesizer
# ─────────────────────────────────────────────────────────────────────────────

class ConceptSynthesizer:
    """Clusters raw graph nodes into compact meta-nodes (abstractions).

    Usage::

        cs = ConceptSynthesizer()
        # node_records: list of {"id", "text", "embedding"} dicts
        meta_nodes = cs.synthesize(node_records, k=8)
        # meta_nodes: list of {"meta_id", "text", "embedding",
        #                       "member_ids", "cluster_size"} dicts

    Typical integration::

        cs.maybe_synthesize(
            graph=get_memory_graph(),
            knowledge_db=self.knowledge_db,
            min_new=50,
        )
    """

    def __init__(self) -> None:
        self._last_node_count: int = 0
        self._synthesis_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def synthesize(
        self,
        node_records: List[Dict[str, Any]],
        k: int = _DEFAULT_K,
    ) -> List[Dict[str, Any]]:
        """Cluster *node_records* and return a list of meta-node dicts.

        Parameters
        ----------
        node_records: List of dicts with at least ``"id"``, ``"text"``, and
                      optionally ``"embedding"`` (list[float]).
        k:            Target number of clusters.  Capped at len(node_records).

        Returns
        -------
        List of ``{"meta_id", "text", "embedding", "member_ids",
        "cluster_size"}`` dicts.  Empty list on any failure.
        """
        try:
            return self._synthesize_safe(node_records, k)
        except Exception as exc:
            log.debug("[ConceptSynthesizer] synthesize() error: %s", exc)
            return []

    def maybe_synthesize(
        self,
        graph: Any,
        knowledge_db: Optional[Any] = None,
        min_new: int = _MIN_NEW_NODES_DEFAULT,
        k: int = _DEFAULT_K,
    ) -> int:
        """Run synthesis when enough new nodes have accumulated.

        Parameters
        ----------
        graph:        :class:`~modules.memory_graph.MemoryGraph` instance.
        knowledge_db: KnowledgeDB for storing abstraction facts.
        min_new:      Minimum new nodes since last synthesis to trigger a pass.
        k:            Target cluster count.

        Returns
        -------
        Number of meta-nodes created (0 if synthesis was skipped).
        """
        try:
            return self._maybe_synthesize_safe(graph, knowledge_db, min_new, k)
        except Exception as exc:
            log.debug("[ConceptSynthesizer] maybe_synthesize() error: %s", exc)
            return 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _synthesize_safe(
        self,
        node_records: List[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        if not node_records:
            return []

        k = max(1, min(k, len(node_records)))
        embeddings = [r.get("embedding") for r in node_records]
        valid_mask = [e is not None and len(e) > 0 for e in embeddings]
        has_embeddings = any(valid_mask)

        if has_embeddings and (len(node_records) >= 2):
            clusters = self._cluster(node_records, embeddings, valid_mask, k)
        else:
            # Trivial: all in one cluster
            clusters = {0: list(range(len(node_records)))}

        meta_nodes: List[Dict[str, Any]] = []
        for _cluster_id, indices in clusters.items():
            if not indices:
                continue
            members = [node_records[i] for i in indices]
            member_ids = [m["id"] for m in members]
            texts = [m["text"] for m in members if m.get("text")]
            summary = _cluster_summary(texts)
            if not summary:
                continue

            # Compute centroid embedding
            member_embeddings = [
                m["embedding"] for m in members
                if m.get("embedding") is not None
            ]
            centroid = _mean_vector(member_embeddings) if member_embeddings else None

            # Stable meta_id from member IDs
            meta_id = _META_PREFIX + hashlib.md5(
                "|".join(sorted(member_ids)).encode()
            ).hexdigest()[:12]

            meta_nodes.append({
                "meta_id":      meta_id,
                "text":         summary,
                "embedding":    centroid,
                "member_ids":   member_ids,
                "cluster_size": len(members),
            })

        self._synthesis_count += 1
        log.debug(
            "[ConceptSynthesizer] Pass #%d: %d nodes → %d meta-nodes",
            self._synthesis_count, len(node_records), len(meta_nodes),
        )
        return meta_nodes

    def _maybe_synthesize_safe(
        self,
        graph: Any,
        knowledge_db: Optional[Any],
        min_new: int,
        k: int,
    ) -> int:
        current_count = graph.count() if hasattr(graph, "count") else 0
        new_since_last = current_count - self._last_node_count
        if new_since_last < min_new:
            return 0

        # Extract node records from the graph
        with graph._lock:
            nodes_snapshot = dict(graph._nodes)

        node_records = [
            {
                "id":        nid,
                "text":      nd.text,
                "embedding": nd.embedding,
            }
            for nid, nd in nodes_snapshot.items()
        ]

        meta_nodes = self.synthesize(node_records, k=k)
        if not meta_nodes:
            return 0

        ts = int(time.time())
        # Add meta-nodes to the graph and KB
        for mn in meta_nodes:
            graph.add(
                node_id=mn["meta_id"],
                text=mn["text"],
                embedding=mn["embedding"],
            )
            if knowledge_db is not None:
                try:
                    knowledge_db.add_fact(
                        f"arc:meta:{mn['meta_id']}:{ts}",
                        {
                            "meta_id":      mn["meta_id"],
                            "text":         mn["text"],
                            "member_ids":   mn["member_ids"],
                            "cluster_size": mn["cluster_size"],
                            "synthesis":    self._synthesis_count,
                        },
                        tags=["arc", "meta_node", "synthesis", "seca"],
                    )
                except Exception as exc:
                    log.debug("[ConceptSynthesizer] KB write error: %s", exc)

        self._last_node_count = current_count
        log.debug(
            "[ConceptSynthesizer] Created %d meta-nodes from %d raw nodes",
            len(meta_nodes), current_count,
        )
        return len(meta_nodes)

    def _cluster(
        self,
        node_records: List[Dict[str, Any]],
        embeddings: List[Optional[List[float]]],
        valid_mask: List[bool],
        k: int,
    ) -> Dict[int, List[int]]:
        """Route to k-means (sklearn) or greedy cosine grouping."""
        if _SKLEARN_AVAILABLE and _NP_AVAILABLE:
            return self._kmeans_cluster(node_records, embeddings, valid_mask, k)
        return self._greedy_cluster(node_records, embeddings, valid_mask)

    def _kmeans_cluster(
        self,
        node_records: List[Dict[str, Any]],
        embeddings: List[Optional[List[float]]],
        valid_mask: List[bool],
        k: int,
    ) -> Dict[int, List[int]]:
        """scikit-learn k-means clustering on valid embeddings."""
        valid_indices = [i for i, v in enumerate(valid_mask) if v]
        valid_embs = _np.array(
            [embeddings[i] for i in valid_indices], dtype="float32"
        )
        km = _KMeans(n_clusters=min(k, len(valid_indices)), random_state=42, n_init="auto")
        labels = km.fit_predict(valid_embs)

        clusters: Dict[int, List[int]] = {}
        for pos, idx in enumerate(valid_indices):
            lbl = int(labels[pos])
            clusters.setdefault(lbl, []).append(idx)

        # Assign nodes with missing embeddings to cluster 0
        for i, v in enumerate(valid_mask):
            if not v:
                clusters.setdefault(0, []).append(i)

        return clusters

    def _greedy_cluster(
        self,
        node_records: List[Dict[str, Any]],
        embeddings: List[Optional[List[float]]],
        valid_mask: List[bool],
    ) -> Dict[int, List[int]]:
        """O(n²) greedy cosine grouping: first-available seed."""
        clusters: Dict[int, List[int]] = {}
        assigned = [False] * len(node_records)
        cluster_id = 0

        for i in range(len(node_records)):
            if assigned[i]:
                continue
            clusters[cluster_id] = [i]
            assigned[i] = True
            if valid_mask[i] and embeddings[i] is not None:
                seed_emb = embeddings[i]
                for j in range(i + 1, len(node_records)):
                    if assigned[j]:
                        continue
                    if valid_mask[j] and embeddings[j] is not None:
                        sim = _cosine_sim(seed_emb, embeddings[j])
                        if sim >= _GREEDY_SIM_THRESHOLD:
                            clusters[cluster_id].append(j)
                            assigned[j] = True
            cluster_id += 1

        return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_synthesizer_singleton: Optional[ConceptSynthesizer] = None
_synthesizer_lock = threading.Lock()


def get_concept_synthesizer() -> ConceptSynthesizer:
    """Return the global :class:`ConceptSynthesizer` singleton.  Thread-safe."""
    global _synthesizer_singleton
    with _synthesizer_lock:
        if _synthesizer_singleton is None:
            _synthesizer_singleton = ConceptSynthesizer()
    return _synthesizer_singleton


if __name__ == "__main__":
    print('Running concept_synthesizer.py')
