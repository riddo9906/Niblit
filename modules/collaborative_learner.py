#!/usr/bin/env python3
"""
COLLABORATIVE LEARNING MODULE
Learn from other systems, share knowledge, enable peer learning
"""

import logging
from typing import Dict, List, Any

log = logging.getLogger("CollaborativeLearner")


class CollaborativeLearner:
    """Enable learning from and with other systems"""
    
    def __init__(self):
        self.peer_systems = {}
        self.shared_knowledge = []
        self.learning_agreements = []
    
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
        """
        Request knowledge from a peer system
        """
        log.info(f"📤 [COLLAB] Requesting '{topic}' from {peer_name}")
        
        if peer_name not in self.peer_systems:
            return {"error": f"Peer {peer_name} not registered"}
        
        # Simulate knowledge transfer
        knowledge = {
            "source": peer_name,
            "topic": topic,
            "data": f"Knowledge about {topic} from {peer_name}",
            "timestamp": "now"
        }
        
        log.info(f"✅ [COLLAB] Received knowledge from {peer_name}")
        return knowledge
    
    def share_knowledge(self, peer_name: str, knowledge: Dict) -> None:
        """
        Share knowledge with a peer system
        """
        log.info(f"📥 [COLLAB] Sharing knowledge with {peer_name}")
        
        if peer_name in self.peer_systems:
            self.peer_systems[peer_name]["knowledge_shared"] += 1
        
        self.shared_knowledge.append({
            "recipient": peer_name,
            "knowledge": knowledge
        })
        
        log.info(f"✅ [COLLAB] Knowledge shared")
    
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
