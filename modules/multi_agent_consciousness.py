#!/usr/bin/env python3
"""Phase Ω.5 Multi-Agent Consciousness."""

from __future__ import annotations

import collections
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "multi_agent_consciousness_state.json"


@dataclass
class AgentProfile:
    personality_vector: dict[str, float]
    specialization_scores: dict[str, float]
    adversarial_role: str = "neutral"


class MultiAgentConsciousness:
    """Transform agents into distributed cognitive perspectives."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: dict[str, AgentProfile] = {}
        self._trust: dict[str, float] = {}
        self._debates: list[dict[str, Any]] = []
        self._coalitions: collections.Counter[str] = collections.Counter()
        self._load_state()

    def register_agent(self, agent_id: str, personality_vector: dict[str, float] | None = None) -> None:
        with self._lock:
            self._profiles.setdefault(
                agent_id,
                AgentProfile(
                    personality_vector=dict(personality_vector or {"critical": 0.5, "creative": 0.5, "cautious": 0.5}),
                    specialization_scores={},
                ),
            )

    def form_coalitions(self, participants: list[str]) -> str:
        coalition = "+".join(sorted(set(participants)))
        with self._lock:
            self._coalitions[coalition] += 1
        self._emit("EVENT_AGENT_COALITION", {"coalition": coalition, "participants": participants})
        return coalition

    def update_agent_trust(self, src_agent: str, dst_agent: str, delta: float) -> float:
        key = f"{src_agent}->{dst_agent}"
        with self._lock:
            self._trust[key] = max(0.0, min(1.0, self._trust.get(key, 0.5) + delta))
            return self._trust[key]

    def assign_reasoning_roles(self, roles: dict[str, str]) -> None:
        with self._lock:
            for aid, role in roles.items():
                if aid not in self._profiles:
                    self.register_agent(aid)
                self._profiles[aid].adversarial_role = role

    def apply_domain_specialization_pressure(self, agent_id: str, domain: str, pressure: float) -> None:
        with self._lock:
            if agent_id not in self._profiles:
                self.register_agent(agent_id)
            scores = self._profiles[agent_id].specialization_scores
            scores[domain] = max(0.0, min(1.0, scores.get(domain, 0.0) + pressure))

    def record_debate(self, topic: str, participants: list[str], winner: str, dissenters: list[str]) -> None:
        row = {
            "topic": topic,
            "participants": list(participants),
            "winner": winner,
            "dissenters": list(dissenters),
            "ts": time.time(),
        }
        with self._lock:
            self._debates.append(row)
            if len(self._debates) > 1000:
                self._debates = self._debates[-1000:]
        if len(participants) >= 2:
            self.form_coalitions(participants)
        self._emit("EVENT_DEBATE_RECORDED", {"topic": topic, "winner": winner})

    def compute_collective_alignment(self) -> float:
        with self._lock:
            if not self._trust:
                return 0.7
            return sum(self._trust.values()) / len(self._trust)

    def update_trust(self, src_agent: str, dst_agent: str, delta: float) -> None:
        self.update_agent_trust(src_agent, dst_agent, delta)

    def status(self) -> dict[str, Any]:
        alignment = self.compute_collective_alignment()
        out = {
            "agent_alignment": alignment,
            "coalition_history": self._coalitions.most_common(20),
            "debate_outcomes": self._debates[-20:],
            "specialization_scores": {k: v.specialization_scores for k, v in self._profiles.items()},
            "adversarial_balance": {k: v.adversarial_role for k, v in self._profiles.items()},
            "agent_count": len(self._profiles),
            "debate_memory_count": len(self._debates),
            "trust_edge_count": len(self._trust),
            "confidence": max(0.0, min(1.0, alignment)),
            "stability_impact": max(0.0, min(1.0, alignment)),
            "coherence_impact": max(0.0, min(1.0, alignment)),
            "causal_trace_metadata": {"coalition_count": len(self._coalitions)},
            "rationale": "Collective alignment based on trust ecology and debate outcomes.",
            "epoch": _safe_epoch(),
        }
        self._emit("EVENT_COLLECTIVE_ALIGNMENT", {"agent_alignment": alignment})
        self._save_state()
        return out

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        try:
            from modules import event_bus as eb
            from modules.event_bus import NiblitEvent, get_event_bus

            evt = getattr(eb, event_name)
            pl = {
                **payload,
                "confidence": 0.75,
                "stability_impact": 0.72,
                "coherence_impact": 0.75,
                "causal_trace_metadata": {"source": "multi_agent_consciousness"},
                "rationale": "Multi-agent cognition update emitted.",
                "epoch": _safe_epoch(),
            }
            get_event_bus().publish(NiblitEvent(type=evt, source="multi_agent_consciousness", payload=pl))
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "profiles": {
                    k: {
                        "personality_vector": v.personality_vector,
                        "specialization_scores": v.specialization_scores,
                        "adversarial_role": v.adversarial_role,
                    }
                    for k, v in self._profiles.items()
                },
                "trust": self._trust,
                "debates": self._debates[-200:],
                "coalitions": dict(self._coalitions),
            }
            tmp = _STATE_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            tmp.replace(_STATE_PATH)
        except Exception:
            pass

    def _load_state(self) -> None:
        try:
            if not _STATE_PATH.exists():
                return
            with _STATE_PATH.open(encoding="utf-8") as fh:
                data = json.load(fh)
            self._profiles = {
                k: AgentProfile(
                    personality_vector=dict(v.get("personality_vector", {})),
                    specialization_scores=dict(v.get("specialization_scores", {})),
                    adversarial_role=str(v.get("adversarial_role", "neutral")),
                )
                for k, v in data.get("profiles", {}).items()
            }
            self._trust = dict(data.get("trust", {}))
            self._debates = list(data.get("debates", []))
            self._coalitions = collections.Counter(data.get("coalitions", {}))
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_mac: MultiAgentConsciousness | None = None
_mac_lock = threading.Lock()


def get_multi_agent_consciousness() -> MultiAgentConsciousness:
    global _mac
    with _mac_lock:
        if _mac is None:
            _mac = MultiAgentConsciousness()
    return _mac
