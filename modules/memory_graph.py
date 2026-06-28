#!/usr/bin/env python3
"""modules/memory_graph.py — Active Retrieval Graph (ARG) for Niblit SECA.

Replaces flat FAISS top-k retrieval with a graph-structured memory where:

  Nodes  = concept snippets, each with a 384-D embedding
  Edges  = semantic + co-occurrence relationships (weighted by cosine similarity)
  Scores = per-node correctness confidence (updated by the reward model)
  Usage  = how many times a node has been retrieved

Query flow
----------
1. Embed query (via the existing VectorStore embedding service).
2. Cosine-sim against all node embeddings → initial candidates.
3. Graph-walk expansion: traverse top candidates' neighbours (multi-hop).
4. Re-rank with a weighted combination::

       rank = α * cos_sim + β * node.score + γ * recency + δ * usage_norm

5. Return top-k ``{"id", "text", "score", "hops"}`` dicts.

Design
------
* **Pure stdlib** for the graph structure — no networkx dependency.
* numpy is used for cosine-similarity (already in requirements.txt).
* Persistence: pickle-based save/load to a configurable path.
* Thread-safe via a single ``threading.Lock()``.
* Degrades gracefully: if numpy is unavailable, falls back to linear dot-product
  computed in pure Python.
* Singleton: ``get_memory_graph()`` returns the shared instance.
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("MemoryGraph")

# ── optional numpy ────────────────────────────────────────────────────────────
try:
    import numpy as _np
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Tuning constants
# ─────────────────────────────────────────────────────────────────────────────

# Re-ranking weights (must sum to ≤ 1; remainder doesn't matter)
_ALPHA: float = 0.50   # cosine similarity weight
_BETA:  float = 0.25   # node correctness score weight
_GAMMA: float = 0.15   # recency weight
_DELTA: float = 0.10   # usage frequency weight

# Maximum edges stored per node (keeps memory bounded)
_MAX_EDGES_PER_NODE: int = 20

# Minimum cosine similarity to create an edge between two nodes
_EDGE_SIM_THRESHOLD: float = 0.45

# Maximum multi-hop traversal depth
_MAX_HOP_DEPTH: int = 2

# Maximum nodes in the expanded candidate pool before re-ranking
_MAX_CANDIDATE_POOL: int = 50

# Maximum total nodes in the graph (prune oldest when exceeded)
_MAX_GRAPH_NODES: int = 5_000

# ─────────────────────────────────────────────────────────────────────────────
# ConceptNode
# ─────────────────────────────────────────────────────────────────────────────

class ConceptNode:
    """A single knowledge unit inside the Active Retrieval Graph.

    Attributes
    ----------
    node_id:    Stable string identifier (e.g. hash of the text).
    text:       The raw snippet or concept phrase.
    embedding:  384-D float list (None when embedding unavailable).
    links:      Mapping ``{neighbour_node_id: edge_weight}``.
    score:      Correctness confidence ∈ [0, 1].  Starts at 0.5.
    usage:      How many times this node has been retrieved.
    created_at: UNIX timestamp of insertion.
    last_used:  UNIX timestamp of most recent retrieval (0 = never).
    """

    __slots__ = (
        "node_id", "text", "embedding",
        "links", "score", "usage",
        "created_at", "last_used", "metadata",
    )

    def __init__(
        self,
        node_id: str,
        text: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.node_id: str = node_id
        self.text: str = text
        self.embedding: Optional[List[float]] = embedding
        self.links: Dict[str, float] = {}
        self.score: float = 0.5
        self.usage: int = 0
        self.created_at: int = int(time.time())
        self.last_used: int = 0
        self.metadata: Dict[str, Any] = dict(metadata or {})

    def touch(self) -> None:
        """Record a retrieval: bump usage count and update last_used timestamp."""
        self.usage += 1
        self.last_used = int(time.time())

    def adjust_score(self, delta: float) -> None:
        """Apply a reward-model delta to the correctness score, clamped to [0, 1]."""
        self.score = max(0.0, min(1.0, self.score + delta))


# ─────────────────────────────────────────────────────────────────────────────
# Low-level similarity helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two float lists.  Returns 0.0 on any error."""
    if _NP_AVAILABLE:
        try:
            va = _np.array(a, dtype="float32")
            vb = _np.array(b, dtype="float32")
            denom = _np.linalg.norm(va) * _np.linalg.norm(vb)
            if denom == 0:
                return 0.0
            return float(_np.dot(va, vb) / denom)
        except Exception:
            return 0.0
    # Pure-Python fallback
    try:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# MemoryGraph
# ─────────────────────────────────────────────────────────────────────────────

class MemoryGraph:
    """Graph-structured episodic memory that replaces flat FAISS top-k retrieval.

    Usage::

        mg = MemoryGraph()
        mg.add("node-1", "Python uses indentation...", embedding=[...])
        mg.add("node-2", "Indentation defines code blocks...", embedding=[...])
        results = mg.search(query_embedding=[...], top_k=5)
        # Returns list of {"id", "text", "score", "hops"} dicts.
    """

    def __init__(self, persist_path: str = "", persistence_manager: Any = None) -> None:
        self._nodes: Dict[str, ConceptNode] = {}
        self._lock = threading.Lock()
        self._persistence_manager = persistence_manager
        _default_persist_path = os.path.join(
            os.path.expanduser("~"),
            ".niblit",
            "niblit_memory_graph.pkl",
        )
        if persistence_manager is not None and not persist_path:
            try:
                persist_path = os.path.join(persistence_manager.indexes_dir, "memory_graph.pkl")
            except Exception:
                pass
        self._persist_path: str = persist_path or os.getenv(
            "NIBLIT_MEMORY_GRAPH_PATH",
            _default_persist_path,
        )
        self._total_adds: int = 0
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load graph state from disk if a snapshot exists."""
        path = os.path.abspath(self._persist_path)
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            self._nodes = {}
            for node_id, payload in (state.get("nodes") or {}).items():
                if isinstance(payload, dict):
                    node = ConceptNode(node_id=node_id, text=str(payload.get("text") or ""), embedding=payload.get("embedding"), metadata=dict(payload.get("metadata") or {}))
                    node.score = float(payload.get("score", node.score))
                    node.usage = int(payload.get("usage", node.usage))
                    node.created_at = int(payload.get("created_at", node.created_at))
                    node.last_used = int(payload.get("last_used", node.last_used))
                    node.links = {str(k): float(v) for k, v in (payload.get("links") or {}).items()}
                    self._nodes[node_id] = node
            self._total_adds = int(state.get("total_adds", len(self._nodes)))
            log.debug("[MemoryGraph] Loaded %d nodes from %s", len(self._nodes), path)
        except Exception as exc:
            try:
                with open(path, "rb") as fh:
                    state = pickle.load(fh)
                self._nodes = state.get("nodes", {})
                self._total_adds = state.get("total_adds", len(self._nodes))
                log.debug("[MemoryGraph] Loaded %d nodes from %s", len(self._nodes), path)
            except Exception as load_exc:
                log.debug("[MemoryGraph] Load failed (%s) — starting fresh", load_exc)

    def save(self) -> None:
        """Persist graph state to disk.  Called automatically on add() every 100 nodes."""
        path = os.path.abspath(self._persist_path)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            pass
        try:
            with self._lock:
                state = {
                    "nodes": {
                        node_id: {
                            "text": node.text,
                            "embedding": node.embedding,
                            "score": node.score,
                            "usage": node.usage,
                            "created_at": node.created_at,
                            "last_used": node.last_used,
                            "metadata": dict(node.metadata),
                            "links": dict(node.links),
                        }
                        for node_id, node in self._nodes.items()
                    },
                    "total_adds": self._total_adds,
                }
            if self._persistence_manager is not None:
                self._persistence_manager.write_json_file(path, state)
            else:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(state, fh, indent=2, ensure_ascii=False)
            log.debug("[MemoryGraph] Saved %d nodes to %s", len(self._nodes), path)
        except Exception as exc:
            log.debug("[MemoryGraph] Save failed: %s", exc)

    # ── Graph mutation ────────────────────────────────────────────────────────

    def add(
        self,
        node_id: str,
        text: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConceptNode:
        """Insert or update a node.  Automatically links to similar existing nodes.

        Returns the upserted :class:`ConceptNode`.
        """
        with self._lock:
            if node_id in self._nodes:
                # Update text and embedding if new info is available
                node = self._nodes[node_id]
                node.text = text
                if embedding is not None:
                    node.embedding = embedding
                if metadata is not None:
                    node.metadata.update(metadata)
                return node

            node = ConceptNode(node_id, text, embedding, metadata=metadata)
            self._nodes[node_id] = node
            self._total_adds += 1

            # Auto-link to similar existing nodes
            if embedding is not None:
                self._auto_link(node)

            # Prune when over capacity
            if len(self._nodes) > _MAX_GRAPH_NODES:
                self._prune_oldest()

        # Persist immediately so runtime restarts and reloads observe the latest
        # graph state instead of only checkpointing every 100 additions.
        self.save()

        return node

    def link(self, id_a: str, id_b: str, weight: float, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Create a bidirectional weighted edge between two nodes."""
        with self._lock:
            if id_a not in self._nodes or id_b not in self._nodes:
                return
            node_a = self._nodes[id_a]
            node_b = self._nodes[id_b]
            # Keep only the strongest _MAX_EDGES_PER_NODE links
            node_a.links[id_b] = weight
            node_b.links[id_a] = weight
            if metadata is not None:
                node_a.metadata.setdefault("links", {})[id_b] = metadata
                node_b.metadata.setdefault("links", {})[id_a] = metadata
            if len(node_a.links) > _MAX_EDGES_PER_NODE:
                min_key = min(node_a.links, key=lambda k: node_a.links[k])
                del node_a.links[min_key]
            if len(node_b.links) > _MAX_EDGES_PER_NODE:
                min_key = min(node_b.links, key=lambda k: node_b.links[k])
                del node_b.links[min_key]

    def update_score(self, node_id: str, delta: float) -> None:
        """Adjust a node's correctness score by *delta* (clamped to [0, 1])."""
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].adjust_score(delta)

    def reinforce(self, node_id: str, delta: float = 0.05) -> None:
        """Positively reinforce a node by increasing its correctness score.

        Convenience wrapper around :meth:`update_score` with explicit positive
        semantics for high-value pattern reinforcement.

        Args:
            node_id: Target node identifier.
            delta:   Score increase (default 0.05, clamped to keep score ≤ 1).
        """
        self.update_score(node_id, abs(delta))

    def apply_decay(
        self,
        days_inactive: float = 7.0,
        decay_factor: float = 0.95,
        min_score_floor: float = 0.05,
    ) -> int:
        """Apply temporal decay to nodes that have not been accessed recently.

        Nodes whose ``last_used`` timestamp is older than *days_inactive* days
        (and which have never been used, i.e. ``usage == 0`` and
        ``last_used == 0``) receive a score penalty of
        ``score × decay_factor`` — their importance diminishes over time when
        they are never retrieved.  The score is clamped to
        *min_score_floor* to avoid hitting exactly zero (which would prevent
        recovery via reinforcement).

        Args:
            days_inactive:   Minimum age (days since ``last_used``) before
                             decay is applied (default 7 days).
            decay_factor:    Multiplicative decay factor applied per call
                             (default 0.95 = 5 % reduction).
            min_score_floor: Lower bound for decayed scores (default 0.05).

        Returns:
            Number of nodes that had decay applied.
        """
        now = int(time.time())
        cutoff = now - int(days_inactive * 86_400)
        decayed = 0

        with self._lock:
            for nd in self._nodes.values():
                # Decay only if the node has never been used OR was last used
                # before the cutoff window
                if nd.last_used == 0 or nd.last_used < cutoff:
                    old_score = nd.score
                    nd.score = max(min_score_floor, old_score * decay_factor)
                    if nd.score < old_score - 1e-6:
                        decayed += 1

        if decayed:
            log.debug(
                "[MemoryGraph] apply_decay: decayed %d nodes "
                "(inactive > %.1f days, factor=%.2f)",
                decayed, days_inactive, decay_factor,
            )
        return decayed

    def prune_low_score(self, min_score: float = 0.10) -> int:
        """Remove nodes whose correctness score has fallen below *min_score*.

        This is the "forgetting" mechanism — after repeated decay passes,
        nodes that are never reinforced will eventually drop below the
        threshold and be removed.  Edges pointing to removed nodes are also
        cleaned up.

        Args:
            min_score: Score threshold below which a node is removed
                       (default 0.10).

        Returns:
            Number of nodes removed.
        """
        with self._lock:
            to_remove = [
                nid for nid, nd in self._nodes.items()
                if nd.score < min_score and nd.usage == 0
            ]
            for nid in to_remove:
                for neighbour_id in list(self._nodes[nid].links):
                    if neighbour_id in self._nodes:
                        self._nodes[neighbour_id].links.pop(nid, None)
                del self._nodes[nid]

        if to_remove:
            log.debug(
                "[MemoryGraph] prune_low_score: removed %d nodes (score < %.2f)",
                len(to_remove), min_score,
            )
        return len(to_remove)

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: Optional[List[float]],
        top_k: int = 5,
        depth: int = _MAX_HOP_DEPTH,
        alpha: float = _ALPHA,
        beta: float = _BETA,
        gamma: float = _GAMMA,
        delta: float = _DELTA,
    ) -> List[Dict[str, Any]]:
        """Multi-hop graph search with re-ranking.

        Steps
        -----
        1. Cosine-sim against all nodes → initial candidates.
        2. Graph-walk expansion up to *depth* hops.
        3. Re-rank pool with weighted formula.
        4. Mark retrieved nodes as used.

        Returns
        -------
        List of ``{"id", "text", "score", "hops"}`` dicts, best first.
        Never raises.
        """
        try:
            return self._search_safe(
                query_embedding, top_k, depth, alpha, beta, gamma, delta
            )
        except Exception as exc:
            log.debug("[MemoryGraph] search error: %s", exc)
            return []

    def count(self) -> int:
        """Number of nodes in the graph."""
        with self._lock:
            return len(self._nodes)

    def stats(self) -> Dict[str, Any]:
        """Return basic graph statistics."""
        with self._lock:
            n = len(self._nodes)
            total_edges = sum(len(nd.links) for nd in self._nodes.values()) // 2
            avg_usage = (
                sum(nd.usage for nd in self._nodes.values()) / n if n else 0
            )
            avg_score = (
                sum(nd.score for nd in self._nodes.values()) / n if n else 0
            )
            now = int(time.time())
            inactive_7d = sum(
                1 for nd in self._nodes.values()
                if nd.last_used == 0 or nd.last_used < now - 7 * 86_400
            )
        return {
            "nodes": n,
            "edges": total_edges,
            "total_adds": self._total_adds,
            "avg_usage": round(avg_usage, 2),
            "avg_score": round(avg_score, 3),
            "inactive_7d": inactive_7d,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _search_safe(
        self,
        query_embedding: Optional[List[float]],
        top_k: int,
        depth: int,
        alpha: float,
        beta: float,
        gamma: float,
        delta: float,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            nodes_snapshot = dict(self._nodes)

        if not nodes_snapshot:
            return []

        now = int(time.time())

        # Step 1: cosine-sim against all nodes that have embeddings
        if query_embedding is not None:
            scored: List[Tuple[str, float]] = []
            for nid, nd in nodes_snapshot.items():
                if nd.embedding is not None:
                    sim = _cosine_sim(query_embedding, nd.embedding)
                    scored.append((nid, sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            initial_ids = [nid for nid, _ in scored[:top_k * 2]]
            sim_map: Dict[str, float] = {nid: sim for nid, sim in scored}
        else:
            # No embedding — fall back to score + recency ordering
            scored_fb = sorted(
                nodes_snapshot.keys(),
                key=lambda nid: (nodes_snapshot[nid].score, nodes_snapshot[nid].created_at),
                reverse=True,
            )
            initial_ids = scored_fb[: top_k * 2]
            sim_map = {nid: 0.0 for nid in initial_ids}

        # Step 2: Graph-walk expansion
        candidate_ids = set(initial_ids)
        frontier = set(initial_ids)
        for _hop in range(depth):
            next_frontier: set = set()
            for nid in frontier:
                nd = nodes_snapshot.get(nid)
                if nd is None:
                    continue
                for neighbour_id, edge_weight in nd.links.items():
                    if neighbour_id not in candidate_ids:
                        candidate_ids.add(neighbour_id)
                        next_frontier.add(neighbour_id)
                        # Inherit a partial similarity from the parent
                        parent_sim = sim_map.get(nid, 0.0)
                        sim_map[neighbour_id] = sim_map.get(
                            neighbour_id,
                            parent_sim * edge_weight * 0.8,  # decay per hop
                        )
                    if len(candidate_ids) >= _MAX_CANDIDATE_POOL:
                        break
                if len(candidate_ids) >= _MAX_CANDIDATE_POOL:
                    break
            frontier = next_frontier
            if not frontier:
                break

        # Step 3: Re-rank
        # Normalise usage across candidate pool to get usage_norm ∈ [0, 1]
        max_usage = max(
            (nodes_snapshot[nid].usage for nid in candidate_ids if nid in nodes_snapshot),
            default=1,
        ) or 1
        oldest = min(
            (nodes_snapshot[nid].created_at for nid in candidate_ids if nid in nodes_snapshot),
            default=now,
        )
        age_span = max(now - oldest, 1)

        reranked: List[Tuple[str, float, int]] = []  # (id, rank_score, hops)
        for nid in candidate_ids:
            nd = nodes_snapshot.get(nid)
            if nd is None:
                continue
            cos = sim_map.get(nid, 0.0)
            recency = 1.0 - (now - nd.created_at) / age_span  # newer → higher
            usage_norm = nd.usage / max_usage
            hops = 0 if nid in set(initial_ids) else 1  # simplified hop label
            rank = (
                alpha * cos
                + beta * nd.score
                + gamma * recency
                + delta * usage_norm
            )
            reranked.append((nid, rank, hops))

        reranked.sort(key=lambda x: x[1], reverse=True)

        # Step 4: Mark used and build result
        results: List[Dict[str, Any]] = []
        with self._lock:
            for nid, rank, hops in reranked[:top_k]:
                if nid in self._nodes:
                    self._nodes[nid].touch()
                nd = nodes_snapshot.get(nid)
                if nd:
                    results.append({
                        "id": nid,
                        "text": nd.text,
                        "score": round(rank, 4),
                        "hops": hops,
                    })

        return results

    def _auto_link(self, new_node: ConceptNode) -> None:
        """Link *new_node* to existing nodes whose cosine-sim exceeds the threshold.

        Caller must hold ``self._lock``.
        """
        if new_node.embedding is None:
            return
        candidates: List[Tuple[str, float]] = []
        for nid, nd in self._nodes.items():
            if nid == new_node.node_id or nd.embedding is None:
                continue
            sim = _cosine_sim(new_node.embedding, nd.embedding)
            if sim >= _EDGE_SIM_THRESHOLD:
                candidates.append((nid, sim))
        # Keep only the top _MAX_EDGES_PER_NODE similar nodes
        candidates.sort(key=lambda x: x[1], reverse=True)
        for nid, sim in candidates[:_MAX_EDGES_PER_NODE]:
            new_node.links[nid] = sim
            neighbour = self._nodes[nid]
            neighbour.links[new_node.node_id] = sim
            # Trim neighbour's links if over cap
            if len(neighbour.links) > _MAX_EDGES_PER_NODE:
                min_key = min(neighbour.links, key=lambda k: neighbour.links[k])
                del neighbour.links[min_key]

    def _prune_oldest(self) -> None:
        """Remove the oldest, least-used nodes until below _MAX_GRAPH_NODES.

        Caller must hold ``self._lock``.
        """
        to_remove = len(self._nodes) - _MAX_GRAPH_NODES
        if to_remove <= 0:
            return
        # Sort by (usage ASC, created_at ASC) — remove cheapest first
        sorted_ids = sorted(
            self._nodes.keys(),
            key=lambda nid: (self._nodes[nid].usage, self._nodes[nid].created_at),
        )
        for nid in sorted_ids[:to_remove]:
            # Remove edges pointing to this node from neighbours
            for neighbour_id in list(self._nodes[nid].links):
                if neighbour_id in self._nodes:
                    self._nodes[neighbour_id].links.pop(nid, None)
            del self._nodes[nid]
        log.debug("[MemoryGraph] Pruned %d old nodes", to_remove)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_graph_singleton: Optional[MemoryGraph] = None
_graph_lock = threading.Lock()


def get_memory_graph(persist_path: str = "", persistence_manager: Any = None) -> MemoryGraph:
    """Return the global :class:`MemoryGraph` singleton.

    Lazily created on first call.  Thread-safe.
    """
    global _graph_singleton
    with _graph_lock:
        if _graph_singleton is None:
            _graph_singleton = MemoryGraph(persist_path=persist_path, persistence_manager=persistence_manager)
    return _graph_singleton


if __name__ == "__main__":
    print('Running memory_graph.py')
