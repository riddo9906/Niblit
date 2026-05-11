#!/usr/bin/env python3
"""Phase Ω.5 Coherent Multi-Agent Consciousness."""

from __future__ import annotations

import collections
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AgentProfile:
    personality_vector: Dict[str, float]
    domain_pressure: Dict[str, float]


class MultiAgentConsciousness:
    """Tracks inter-agent debate memory, trust ecology, and coalition formation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: Dict[str, AgentProfile] = {}
        self._trust_edges: Dict[str, float] = {}
        self._debate_memory: List[Dict[str, Any]] = []
        self._coalitions: collections.Counter[str] = collections.Counter()

    def register_agent(self, agent_id: str, personality_vector: Optional[Dict[str, float]] = None) -> None:
        with self._lock:
            self._profiles.setdefault(
                agent_id,
                AgentProfile(
                    personality_vector=dict(personality_vector or {"critical": 0.5, "creative": 0.5}),
                    domain_pressure={},
                ),
            )

    def record_debate(self, topic: str, participants: List[str], winner: str, dissenters: List[str]) -> None:
        with self._lock:
            self._debate_memory.append(
                {
                    "topic": topic,
                    "participants": list(participants),
                    "winner": winner,
                    "dissenters": list(dissenters),
                }
            )
            if len(self._debate_memory) > 500:
                self._debate_memory = self._debate_memory[-500:]
            if len(participants) >= 2:
                coalition = "+".join(sorted(set(participants)))
                self._coalitions[coalition] += 1

    def update_trust(self, src_agent: str, dst_agent: str, delta: float) -> None:
        key = f"{src_agent}->{dst_agent}"
        with self._lock:
            self._trust_edges[key] = max(0.0, min(1.0, self._trust_edges.get(key, 0.5) + delta))

    def apply_domain_specialization_pressure(self, agent_id: str, domain: str, pressure: float) -> None:
        with self._lock:
            if agent_id not in self._profiles:
                self.register_agent(agent_id)
            p = self._profiles[agent_id].domain_pressure
            p[domain] = max(0.0, p.get(domain, 0.0) + pressure)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "agent_count": len(self._profiles),
                "debate_memory_count": len(self._debate_memory),
                "trust_edge_count": len(self._trust_edges),
                "top_coalitions": self._coalitions.most_common(5),
            }


_mac: Optional[MultiAgentConsciousness] = None
_mac_lock = threading.Lock()


def get_multi_agent_consciousness() -> MultiAgentConsciousness:
    global _mac
    with _mac_lock:
        if _mac is None:
            _mac = MultiAgentConsciousness()
    return _mac

