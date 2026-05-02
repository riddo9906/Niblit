#!/usr/bin/env python3
"""
COLLABORATIVE LEARNING MODULE
Learn from other systems, share knowledge, enable peer learning
"""

import logging
from typing import Dict, List, Any

try:
    from niblit_memory import NiblitMemory as _NiblitMemory
    _GLOBAL_MEMORY = _NiblitMemory()
except Exception:
    _GLOBAL_MEMORY = None  # type: ignore[assignment]

log = logging.getLogger("CollaborativeLearner")


class CollaborativeLearner:
    """Enable learning from and with other systems"""

    def __init__(self, memory=None):
        self.peer_systems = {}
        self.shared_knowledge = []
        self.learning_agreements = []
        # Use canonical niblit_memory singleton if no memory provided
        self.memory = memory or _GLOBAL_MEMORY

    def register_peer(self, system_name: str, capabilities: List[str]) -> None:
        """
        Register a peer AI system to learn from
        """
        log.info(f"🤝 [COLLAB] Registering peer: {system_name}")

        self.peer_systems[system_name] = {
            "name": system_name,
            "capabilities": capabilities,
            "knowledge_shared": 0,
            "last_sync": None
        }

        log.info(f"✅ [COLLAB] Peer registered with {len(capabilities)} capabilities")

    def request_knowledge(self, peer_name: str, topic: str) -> Dict[str, Any]:
        """Request knowledge from a peer system.

        First tries to satisfy the request from the local KB (so Niblit can
        answer from its own accumulated knowledge base).  Falls back to a
        peer-specific stub only when nothing is found locally.
        """
        log.info("📤 [COLLAB] Requesting '%s' from %s", peer_name, topic)

        if peer_name not in self.peer_systems:
            return {"error": f"Peer {peer_name} not registered"}

        # Try the local KB first — return real content if available
        local_data: str = ""
        if self.memory is not None:
            try:
                if hasattr(self.memory, "smart_recall"):
                    hits = self.memory.smart_recall(topic, limit=1)
                    if hits:
                        local_data = str(hits[0].get("value") or hits[0].get("text") or "")
                elif hasattr(self.memory, "recall"):
                    hits = self.memory.recall(topic, limit=1)
                    if hits:
                        local_data = str(hits[0].get("value") or "")
                elif hasattr(self.memory, "search"):
                    hits = self.memory.search(topic, top_k=1)
                    if hits:
                        local_data = str(hits[0].get("text") or "")
            except Exception as exc:
                log.debug("[CollaborativeLearner] KB lookup failed: %s", exc)

        knowledge = {
            "source": peer_name,
            "topic": topic,
            "data": local_data if local_data else f"No local knowledge found for '{topic}'",
            "from_kb": bool(local_data),
        }

        # Persist to canonical memory
        self._store(f"collab:{peer_name}:{topic}", knowledge)

        log.info("✅ [COLLAB] Knowledge request fulfilled (from_kb=%s)", knowledge["from_kb"])
        return knowledge

    def share_knowledge(self, peer_name: str, knowledge: Dict) -> None:
        """Share knowledge with a peer system.

        Persists the shared knowledge to the local KB with a ``collab:shared``
        prefix so it can be retrieved later by either the sender or receiver.
        """
        log.info("📥 [COLLAB] Sharing knowledge with %s", peer_name)

        if peer_name in self.peer_systems:
            self.peer_systems[peer_name]["knowledge_shared"] += 1

        entry = {
            "recipient": peer_name,
            "knowledge": knowledge,
        }
        self.shared_knowledge.append(entry)

        # Determine a meaningful key from the knowledge dict
        topic = (
            knowledge.get("topic")
            or knowledge.get("key")
            or knowledge.get("subject")
            or "unknown"
        )
        data_str = (
            knowledge.get("data")
            or knowledge.get("value")
            or knowledge.get("text")
            or str(knowledge)
        )

        # Persist to canonical memory with the real content (truncated to 500 chars)
        self._store(
            f"collab:shared:{peer_name}:{topic}",
            {
                "recipient": peer_name,
                "topic": topic,
                "data": str(data_str)[:500],
            },
        )

        log.info("✅ [COLLAB] Knowledge shared with %s (topic: %s)", peer_name, topic)

    def get_collaboration_status(self) -> Dict[str, Any]:
        """Get status of collaborative learning"""
        log.info(f"📊 [COLLAB] Getting collaboration status")

        status = {
            "peers_connected": len(self.peer_systems),
            "total_knowledge_shared": sum(p["knowledge_shared"] for p in self.peer_systems.values()),
            "peers": list(self.peer_systems.keys()),
            "capability": "Cross-system learning",
            "status": "Ready for peer collaboration"
        }

        log.info(f"✅ [COLLAB] Status: {len(self.peer_systems)} peers connected")
        return status

    # ── private ───────────────────────────────────────────────────────────────

    def _store(self, key: str, data: Any) -> None:
        """Persist a fact to niblit_memory (any backend that has add_fact/store_learning)."""
        if self.memory is None:
            return
        try:
            if hasattr(self.memory, "add_fact"):
                self.memory.add_fact(key, data, tags=["collaborative_learning"])
            elif hasattr(self.memory, "store_learning"):
                self.memory.store_learning({"key": key, "data": data, "tags": ["collaborative_learning"]})
        except Exception as exc:
            log.debug("[CollaborativeLearner] memory store failed: %s", exc)



if __name__ == "__main__":
    print('Running collaborative_learner.py')
