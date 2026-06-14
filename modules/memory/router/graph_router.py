from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict

from modules.memory.graph.memory_graph import MemoryEdge, MemoryGraph, MemoryNode
from modules.memory.router.memory_router import MemoryRouterCore, RoutedMemory


class GraphMemoryRouter:
    """Bridge MemoryRouterCore, vector storage, and the directed memory graph."""

    def __init__(
        self,
        router: MemoryRouterCore,
        graph: MemoryGraph,
        *,
        write_callback: Callable[[RoutedMemory, str], Dict[str, Any]] | None = None,
    ) -> None:
        self.router = router
        self.graph = graph
        self._write_callback = write_callback

    def insert(self, text: str, meta: Dict[str, Any]) -> MemoryNode:
        routed = self.router.route(text, meta)
        write_status = self._write_callback(routed, text) if self._write_callback is not None else {}
        payload = dict(routed.payload)
        if write_status:
            payload["_graph_write"] = dict(write_status)
        node = MemoryNode(
            id=routed.id,
            text=text,
            type=str(payload.get("memory_type", meta.get("type", "memory"))),
            collection=routed.collection,
            metadata=payload,
        )
        self.graph.add_node(node)
        self.auto_link(node)
        return node

    def link(self, source_id: str, target_id: str, relation: str, weight: float = 1.0) -> None:
        if source_id == target_id:
            return
        if self.graph.get_node(source_id) is None or self.graph.get_node(target_id) is None:
            return
        self.graph.add_edge(
            MemoryEdge(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                weight=weight,
            )
        )

    def auto_link(self, new_node: MemoryNode) -> None:
        graph_meta = dict(new_node.metadata.get("graph") or {})
        trace_id = str((new_node.metadata.get("replay_metadata") or {}).get("trace_id", "")).strip()
        causal_refs = [
            str(item).strip()
            for item in (
                list(new_node.metadata.get("causal_chain") or [])
                + list((new_node.metadata.get("replay_metadata") or {}).get("causal_references") or [])
            )
            if str(item).strip()
        ]
        for ref_id in causal_refs:
            if self.graph.get_node(ref_id) is not None:
                self.link(ref_id, new_node.id, "causes", 0.95)

        if trace_id:
            for node in self.graph.nodes.values():
                if node.id == new_node.id:
                    continue
                other_trace = str((node.metadata.get("replay_metadata") or {}).get("trace_id", "")).strip()
                if other_trace == trace_id:
                    relation = "derived_from" if node.id in causal_refs else "relates_to"
                    self.link(node.id, new_node.id, relation, 0.65 if relation == "relates_to" else 0.9)

        text = new_node.text.lower()
        if any(token in text for token in ("fix", "fixed", "resolve", "resolved", "patch", "patched")):
            for node in self.graph.nodes.values():
                if node.id == new_node.id:
                    continue
                other = node.text.lower()
                if any(token in other for token in ("error", "exception", "failure", "failed", "bug")):
                    self.link(node.id, new_node.id, "fixed_by", 0.9)
        if any(token in text for token in ("outcome", "result", "successful", "success")):
            for node in self.graph.nodes.values():
                if node.id == new_node.id:
                    continue
                other = node.text.lower()
                if any(token in other for token in ("fix", "fixed", "resolve", "resolved", "patch", "patched")):
                    self.link(node.id, new_node.id, "leads_to", 0.8)

        graph_meta["edge_count"] = self.graph.edge_count(new_node.id)
        new_node.metadata["graph"] = graph_meta
