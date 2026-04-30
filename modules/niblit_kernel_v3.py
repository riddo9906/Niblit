#!/usr/bin/env python3
"""
modules/niblit_kernel_v3.py — Niblit Cognitive Kernel v3
=========================================================
The **unified** kernel that fuses v1 + v2 capabilities and adds a
kernel-mediated multi-agent system with centralized memory, reward scoring,
and a deterministic task scheduler.

Architecture
------------
::

    ┌──────────────────────────────────────────────┐
    │          NiblitCognitiveKernelV3             │
    │  ┌──────────────────────────────────────┐   │
    │  │  KernelCommunicationBus (KCB)         │   │
    │  │  • per-agent inboxes                  │   │
    │  │  • broadcast channel                  │   │
    │  │  • full trace log                     │   │
    │  └──────────────────────────────────────┘   │
    │  ┌──────────────────────────────────────┐   │
    │  │  7-step message pipeline              │   │
    │  │  1. Intent classification             │   │
    │  │  2. Memory injection                  │   │
    │  │  3. Reasoning expansion (v2 path)     │   │
    │  │  4. Safety + quality gate             │   │
    │  │  5. Routing decision                  │   │
    │  │  6. Dispatch to agent                 │   │
    │  │  7. Reward scoring                    │   │
    │  └──────────────────────────────────────┘   │
    │  ┌──────────────────────────────────────┐   │
    │  │  KernelScheduler — task DAG           │   │
    │  └──────────────────────────────────────┘   │
    │  ┌──────────────────────────────────────┐   │
    │  │  RewardEngine                         │   │
    │  └──────────────────────────────────────┘   │
    └──────────────────────────────────────────────┘
                   │
        ┌──────────┼──────────────────────────┐
        │          │                          │
   Research     Coder     Critic   Teacher  Explorer
    Agent        Agent    Agent    Agent    Agent
   (stateless)  (stateless)  ...


Hard rules
----------
* ❌ No direct agent-to-agent calls.  All messages go through KCB.
* ❌ Agents own no memory.  All state lives in KernelMemory.
* ❌ No execution without kernel validation (safety gate).
* ✅ Every message is traced.
* ✅ Every interaction is scored by RewardEngine.

v1 + v2 fusion
--------------
``NiblitCognitiveKernelV3.run_cognitive_loop()`` runs the full fused pipeline:

1. **v2 path** — embed → semantic search → graph expand → synthesize → classify.
2. **v1 path** — CognitionCore / ReasoningEngine fallback.
3. **v3 path** — KCB-mediated multi-agent task graph execution.
4. **Memory** — all results stored through KernelMemory (MWDS-backed).
5. **Reward** — every cycle scored; scores written back into memory.
6. **Sync** — cycle completion event written to SyncEngine (if available).

Singleton
---------
``get_niblit_kernel_v3()`` returns the process-wide
:class:`NiblitCognitiveKernelV3` instance.

Configuration (environment variables)
--------------------------------------
``NIBLIT_KV3_EVOLVE_ENABLED`` — ``0`` to disable evolve gate (default: 1)
``NIBLIT_KV3_SAFETY_STRICT``  — ``1`` for strict mode (default: 0)
``NIBLIT_KV3_REWARD_FLOOR``   — Minimum reward to accept (default: 0.2)
``NIBLIT_KV3_MAX_TASK_DEPTH`` — Max dependency depth in scheduler (default: 5)
``NIBLIT_KV3_AGENT_TIMEOUT``  — Max seconds per agent call (default: 30)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_EVOLVE_ENABLED = os.environ.get("NIBLIT_KV3_EVOLVE_ENABLED", "1") != "0"
_SAFETY_STRICT = os.environ.get("NIBLIT_KV3_SAFETY_STRICT", "0") == "1"
_REWARD_FLOOR = float(os.environ.get("NIBLIT_KV3_REWARD_FLOOR", "0.2"))
_MAX_TASK_DEPTH = int(os.environ.get("NIBLIT_KV3_MAX_TASK_DEPTH", "5"))
_AGENT_TIMEOUT = float(os.environ.get("NIBLIT_KV3_AGENT_TIMEOUT", "30"))

# Known agent IDs
_AGENT_RESEARCH = "research_agent"
_AGENT_CODER = "coder_agent"
_AGENT_CRITIC = "critic_agent"
_AGENT_TEACHER = "teacher_agent"
_AGENT_EXPLORER = "explorer_agent"
_ALL_AGENTS = [_AGENT_RESEARCH, _AGENT_CODER, _AGENT_CRITIC, _AGENT_TEACHER, _AGENT_EXPLORER]
_KERNEL_ID = "kernel"


# ═════════════════════════════════════════════════════════════════════════════
# KernelMessage — the universal inter-agent message schema
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class KernelMessage:
    """A typed message routed through the :class:`KernelCommunicationBus`.

    Attributes
    ----------
    id:          Unique message identifier (UUID if not set).
    sender:      Source agent/component ID (e.g. ``"research_agent"`` or
                 ``"kernel"``).
    target:      Destination agent ID or ``"broadcast"`` for all agents.
    intent:      Action label (``"generate_code"``, ``"research"``, etc.).
    payload:     Serialisable content dict.
    priority:    Message priority (higher = processed first).  Default 5.
    timestamp:   UNIX timestamp of creation.
    trace_id:    Correlation ID for request tracing across hops.
    reply_to:    Optional message ID this is a reply to.
    reward:      Reward score assigned after processing (0.0–1.0).
    result:      Output produced by the handler (filled in after dispatch).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = _KERNEL_ID
    target: str = "broadcast"
    intent: str = "respond"
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    timestamp: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    reply_to: Optional[str] = None
    reward: float = 0.0
    result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sender": self.sender,
            "target": self.target,
            "intent": self.intent,
            "payload": self.payload,
            "priority": self.priority,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "reply_to": self.reply_to,
            "reward": self.reward,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KernelMessage":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ═════════════════════════════════════════════════════════════════════════════
# KernelCommunicationBus (KCB)
# ═════════════════════════════════════════════════════════════════════════════

class KernelCommunicationBus:
    """Thread-safe message bus for kernel-mediated inter-agent communication.

    All agents have an inbox (bounded deque).  The kernel is the only entity
    that calls ``route()``; agents never call each other directly.

    Maintains a full trace log for debugging and reward scoring.

    Args:
        max_inbox:  Maximum messages queued per agent.
        max_trace:  Maximum entries in the trace log.
    """

    def __init__(self, max_inbox: int = 100, max_trace: int = 500) -> None:
        self._inboxes: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_inbox))
        self._trace: deque = deque(maxlen=max_trace)
        self._lock = threading.Lock()

    def route(self, message: KernelMessage) -> None:
        """Deliver *message* to the target agent's inbox.

        If ``target == "broadcast"`` the message is copied to every known
        agent inbox.

        Args:
            message: The :class:`KernelMessage` to deliver.
        """
        with self._lock:
            self._trace.append(message.to_dict())
            if message.target == "broadcast":
                for agent_id in _ALL_AGENTS:
                    self._inboxes[agent_id].append(message)
            else:
                self._inboxes[message.target].append(message)

    def dequeue(self, agent_id: str) -> Optional[KernelMessage]:
        """Pop and return the next message for *agent_id*, or None.

        Args:
            agent_id: Agent identifier.

        Returns:
            Next :class:`KernelMessage` or ``None`` if inbox is empty.
        """
        with self._lock:
            q = self._inboxes[agent_id]
            return q.popleft() if q else None

    def submit_response(
        self,
        sender: str,
        original_msg: KernelMessage,
        result: str,
    ) -> KernelMessage:
        """Create a response message and route it back to the kernel.

        Args:
            sender:       Agent that produced the result.
            original_msg: The message that triggered this response.
            result:       The agent's output string.

        Returns:
            The constructed response :class:`KernelMessage`.
        """
        response = KernelMessage(
            sender=sender,
            target=_KERNEL_ID,
            intent=f"response:{original_msg.intent}",
            payload={"result": result, "original_id": original_msg.id},
            reply_to=original_msg.id,
            trace_id=original_msg.trace_id,
        )
        response.result = result
        with self._lock:
            self._trace.append(response.to_dict())
            self._inboxes[_KERNEL_ID].append(response)
        return response

    def inbox_size(self, agent_id: str) -> int:
        with self._lock:
            return len(self._inboxes[agent_id])

    def trace_snapshot(self, last_n: int = 20) -> List[Dict[str, Any]]:
        """Return the last *last_n* trace entries."""
        with self._lock:
            return list(self._trace)[-last_n:]

    def clear(self) -> None:
        with self._lock:
            self._inboxes.clear()
            self._trace.clear()


# ═════════════════════════════════════════════════════════════════════════════
# RewardEngine
# ═════════════════════════════════════════════════════════════════════════════

class RewardEngine:
    """Per-interaction reward scoring.

    Reward formula (all factors ∈ [0, 1])::

        reward = accuracy*0.4 + usefulness*0.3 + efficiency*0.2 + safety*0.1

    Per-agent reward histories are tracked for agent evolution signals.

    Args:
        floor:  Minimum acceptable reward (interactions below this are flagged).
    """

    def __init__(self, floor: float = _REWARD_FLOOR) -> None:
        self._floor = floor
        self._histories: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def score(
        self,
        agent_id: str,
        accuracy: float = 0.7,
        usefulness: float = 0.7,
        efficiency: float = 0.7,
        safety: float = 1.0,
    ) -> float:
        """Compute and record a reward score for *agent_id*.

        Args:
            agent_id:   The agent whose work is being scored.
            accuracy:   Was the output factually correct?
            usefulness: Was it actionable / relevant?
            efficiency: Was it fast (low latency)?
            safety:     No policy violations?

        Returns:
            Scalar reward ∈ [0, 1].
        """
        reward = (
            float(accuracy) * 0.4
            + float(usefulness) * 0.3
            + float(efficiency) * 0.2
            + float(safety) * 0.1
        )
        reward = round(max(0.0, min(1.0, reward)), 4)
        with self._lock:
            self._histories[agent_id].append(reward)
            # Keep last 200 scores per agent
            if len(self._histories[agent_id]) > 200:
                self._histories[agent_id] = self._histories[agent_id][-200:]
        return reward

    def score_from_latency(
        self,
        agent_id: str,
        latency_ms: float,
        result_len: int = 100,
        safe: bool = True,
    ) -> float:
        """Derive reward from measurable signals when ground-truth is unavailable.

        Args:
            agent_id:    Agent to score.
            latency_ms:  Wall-clock latency in milliseconds.
            result_len:  Length of output string (proxy for usefulness).
            safe:        Whether safety gate was passed.

        Returns:
            Reward scalar.
        """
        efficiency = max(0.0, 1.0 - latency_ms / (_AGENT_TIMEOUT * 1000))
        usefulness = min(1.0, result_len / 300.0)  # saturates at 300 chars
        accuracy = 0.7  # default assumed accuracy
        safety = 1.0 if safe else 0.0
        return self.score(agent_id, accuracy=accuracy, usefulness=usefulness,
                          efficiency=efficiency, safety=safety)

    def agent_mean_reward(self, agent_id: str) -> float:
        """Return the rolling mean reward for *agent_id* (0.0 if no data)."""
        with self._lock:
            hist = self._histories.get(agent_id, [])
        return (sum(hist) / len(hist)) if hist else 0.0

    def evolution_signals(self) -> Dict[str, float]:
        """Return {agent_id: mean_reward} for all tracked agents."""
        with self._lock:
            return {aid: (sum(h) / len(h)) if h else 0.0
                    for aid, h in self._histories.items()}

    def below_floor(self, agent_id: str) -> bool:
        """Return True if the agent's mean reward is below the reward floor."""
        return self.agent_mean_reward(agent_id) < self._floor


# ═════════════════════════════════════════════════════════════════════════════
# KernelScheduler — DAG task graph executor
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class TaskNode:
    """A node in a kernel task graph.

    Attributes
    ----------
    agent:   Target agent ID.
    intent:  Action to request.
    payload: Input payload dict.
    depends: List of agent IDs that must complete first.
    """
    agent: str
    intent: str
    payload: Dict[str, Any] = field(default_factory=dict)
    depends: List[str] = field(default_factory=list)


class KernelScheduler:
    """Topological task graph executor.

    Takes a list of :class:`TaskNode` objects (with dependency declarations),
    orders them by dependency resolution, and returns an execution plan in
    the order the kernel should dispatch them.

    Args:
        max_depth: Maximum dependency chain depth before cycle detection.
    """

    def __init__(self, max_depth: int = _MAX_TASK_DEPTH) -> None:
        self._max_depth = max_depth

    def plan(self, nodes: List[TaskNode]) -> List[TaskNode]:
        """Return *nodes* in topological execution order.

        If a cycle is detected the order falls back to declaration order.

        Args:
            nodes: List of :class:`TaskNode` with dependency declarations.

        Returns:
            Ordered list of :class:`TaskNode`.
        """
        if not nodes:
            return []

        # Build index
        by_agent: Dict[str, TaskNode] = {n.agent: n for n in nodes}
        visited: set = set()
        result: List[TaskNode] = []

        def visit(node: TaskNode, depth: int = 0) -> None:
            if depth > self._max_depth:
                return
            if node.agent in visited:
                return
            # Resolve dependencies first
            for dep in node.depends:
                if dep in by_agent and dep not in visited:
                    visit(by_agent[dep], depth + 1)
            visited.add(node.agent)
            result.append(node)

        for node in nodes:
            visit(node)

        return result


# ═════════════════════════════════════════════════════════════════════════════
# Agent base interface + concrete agents
# ═════════════════════════════════════════════════════════════════════════════

class BaseAgent:
    """Stateless kernel-mediated agent.

    All agents:
    * Receive a :class:`KernelMessage` from the kernel.
    * Execute a narrow, well-scoped function.
    * Return a plain string result to the kernel.
    * Never store state or memory (all memory is kernel-owned).

    Args:
        kernel: The hosting :class:`NiblitCognitiveKernelV3` instance.
    """

    agent_id: str = "base_agent"

    def __init__(self, kernel: Optional[Any] = None) -> None:
        self._kernel = kernel

    @property
    def kernel(self) -> Optional[Any]:
        return self._kernel

    def handle(self, message: KernelMessage) -> str:
        """Process *message* and return a result string.

        This must be overridden in every subclass.  The default raises
        ``NotImplementedError``.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.handle() not implemented")


class ResearchAgent(BaseAgent):
    """Gather information on a topic via the kernel's research tool."""

    agent_id = _AGENT_RESEARCH

    def handle(self, message: KernelMessage) -> str:
        topic = str(message.payload.get("topic", message.payload.get("query", "")))[:200]
        if not topic:
            return "No topic provided."

        # Try PhasedResearchEngine via kernel's ToolRouter
        if self._kernel is not None:
            try:
                result = self._kernel._tool_execute("research", topic)
                if result and not result.startswith("Error"):
                    return result[:500]
            except Exception:
                pass

        # Memory-based fallback: retrieve related knowledge
        if self._kernel is not None:
            try:
                memories = self._kernel._retrieve_memory(topic)
                if memories:
                    return f"[Memory] {'; '.join(memories[:3])[:400]}"
            except Exception:
                pass

        return f"Researched: {topic[:100]}. No additional data available."


class CoderAgent(BaseAgent):
    """Generate code or fix errors via the kernel's code tool."""

    agent_id = _AGENT_CODER

    def handle(self, message: KernelMessage) -> str:
        prompt = str(message.payload.get("prompt", message.payload.get("topic", "")))[:300]
        language = str(message.payload.get("language", "python"))
        if not prompt:
            return "No coding prompt provided."

        if self._kernel is not None:
            try:
                result = self._kernel._tool_execute("code", f"{language}: {prompt}")
                if result and not result.startswith("Error"):
                    return result[:500]
            except Exception:
                pass

        return f"[CoderAgent] Would generate {language} code for: {prompt[:100]}"


class CriticAgent(BaseAgent):
    """Validate, critique and score content."""

    agent_id = _AGENT_CRITIC

    _SAFETY_KEYWORDS = frozenset({
        "delete all", "rm -rf", "drop table", "format c:", "shutdown", "nuke",
        "sys.exit", "os.system", "subprocess.call", "eval(", "exec(",
    })

    def handle(self, message: KernelMessage) -> str:
        content = str(message.payload.get("content", message.payload.get("code", "")))[:1000]
        if not content:
            return "Nothing to critique."

        # Safety scan
        lower = content.lower()
        violations = [kw for kw in self._SAFETY_KEYWORDS if kw in lower]
        if violations:
            return f"⚠️ Safety violation(s) detected: {', '.join(violations[:3])}"

        # Quality heuristics
        issues: List[str] = []
        if len(content) < 20:
            issues.append("output too short")
        if content.count("\n") == 0 and len(content) > 200:
            issues.append("no line breaks in long output")
        if "TODO" in content or "FIXME" in content:
            issues.append("unresolved TODO/FIXME markers")

        if issues:
            return f"Quality issues: {', '.join(issues)}. Content passed safety check."
        return "✅ Content passed safety and quality checks."


class TeacherAgent(BaseAgent):
    """Explain reasoning, concepts and decisions."""

    agent_id = _AGENT_TEACHER

    def handle(self, message: KernelMessage) -> str:
        topic = str(message.payload.get("topic", message.payload.get("content", "")))[:300]
        concepts: List[str] = message.payload.get("concepts", [])

        explanation = f"[TeacherAgent] Topic: {topic[:100]}"
        if concepts:
            explanation += f". Key concepts: {', '.join(str(c) for c in concepts[:5])}"
        explanation += (
            ". Understanding this requires exploring the underlying principles, "
            "examining related examples, and connecting to prior knowledge."
        )
        return explanation[:500]


class ExplorerAgent(BaseAgent):
    """Discover novel connections and suggest next steps."""

    agent_id = _AGENT_EXPLORER

    def handle(self, message: KernelMessage) -> str:
        topic = str(message.payload.get("topic", ""))[:200]
        memory_hits: List[Any] = message.payload.get("memory_hits", [])
        concepts: List[str] = message.payload.get("concepts", [])

        suggestions = []
        if concepts:
            suggestions.append(f"Deepen understanding of: {', '.join(concepts[:3])}")
        if memory_hits:
            suggestions.append(f"Reinforce memory about: {str(memory_hits[0])[:80]}")
        if topic:
            suggestions.append(f"Cross-link '{topic[:60]}' with adjacent knowledge domains")

        if not suggestions:
            return "Explore: research adjacent topics and test new hypotheses."
        return "[ExplorerAgent] Suggestions: " + "; ".join(suggestions)[:450]


# ═════════════════════════════════════════════════════════════════════════════
# Intent → task graph mapping
# ═════════════════════════════════════════════════════════════════════════════

def _build_task_graph(intent: str, payload: Dict[str, Any]) -> List[TaskNode]:
    """Return the default task graph for a given *intent*.

    Args:
        intent:  Intent label from the kernel's classify step.
        payload: The enriched payload dict (contains topic, concepts, etc.).

    Returns:
        List of :class:`TaskNode` objects (unordered; scheduler handles DAG).
    """
    graphs: Dict[str, List[TaskNode]] = {
        "research": [
            TaskNode(agent=_AGENT_RESEARCH, intent="research", payload=payload),
            TaskNode(agent=_AGENT_TEACHER, intent="explain", payload=payload,
                     depends=[_AGENT_RESEARCH]),
            TaskNode(agent=_AGENT_EXPLORER, intent="explore", payload=payload,
                     depends=[_AGENT_RESEARCH]),
        ],
        "generate_code": [
            TaskNode(agent=_AGENT_RESEARCH, intent="research", payload=payload),
            TaskNode(agent=_AGENT_CODER, intent="code", payload=payload,
                     depends=[_AGENT_RESEARCH]),
            TaskNode(agent=_AGENT_CRITIC, intent="critique",
                     payload={**payload, "content": ""},  # filled after coder runs
                     depends=[_AGENT_CODER]),
            TaskNode(agent=_AGENT_TEACHER, intent="explain", payload=payload,
                     depends=[_AGENT_CRITIC]),
        ],
        "debug": [
            TaskNode(agent=_AGENT_CRITIC, intent="critique", payload=payload),
            TaskNode(agent=_AGENT_CODER, intent="fix", payload=payload,
                     depends=[_AGENT_CRITIC]),
        ],
        "reflect": [
            TaskNode(agent=_AGENT_TEACHER, intent="explain", payload=payload),
            TaskNode(agent=_AGENT_EXPLORER, intent="explore", payload=payload,
                     depends=[_AGENT_TEACHER]),
        ],
        "trade": [
            TaskNode(agent=_AGENT_RESEARCH, intent="research", payload=payload),
            TaskNode(agent=_AGENT_CRITIC, intent="validate", payload=payload,
                     depends=[_AGENT_RESEARCH]),
        ],
        "evolve": [
            TaskNode(agent=_AGENT_CRITIC, intent="validate", payload=payload),
            TaskNode(agent=_AGENT_RESEARCH, intent="research", payload=payload,
                     depends=[_AGENT_CRITIC]),
        ],
    }
    return graphs.get(intent, [
        TaskNode(agent=_AGENT_TEACHER, intent="explain", payload=payload),
    ])


# ═════════════════════════════════════════════════════════════════════════════
# KernelV3 Result
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class KernelV3Result:
    """Full output of one ``run_cognitive_loop()`` pass through v3.

    Attributes
    ----------
    input_data:      Raw input.
    thought:         Structured reasoning string (from v1/v2 path).
    response:        Clean insight.
    decision:        Intent label.
    action_result:   Final consolidated result string.
    agent_outputs:   {agent_id: result_string} for each dispatched agent.
    rewards:         {agent_id: reward_score} for each agent.
    messages:        All KernelMessages created during this cycle.
    concepts:        Concept labels from ConceptGraph.
    memory_hits:     Semantic search results.
    remembered:      Whether persist step ran.
    latency_ms:      Wall-clock time.
    ts:              UNIX timestamp of completion.
    """
    input_data: Any = ""
    thought: str = ""
    response: str = ""
    decision: str = "respond"
    action_result: str = ""
    agent_outputs: Dict[str, str] = field(default_factory=dict)
    rewards: Dict[str, float] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    remembered: bool = False
    latency_ms: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": str(self.input_data)[:200],
            "thought": self.thought[:300],
            "response": self.response,
            "decision": self.decision,
            "action_result": self.action_result[:300],
            "agent_outputs": {k: v[:200] for k, v in self.agent_outputs.items()},
            "rewards": self.rewards,
            "concepts": self.concepts[:8],
            "memory_hits_count": len(self.memory_hits),
            "remembered": self.remembered,
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ═════════════════════════════════════════════════════════════════════════════
# NiblitCognitiveKernelV3 — unified kernel
# ═════════════════════════════════════════════════════════════════════════════

class NiblitCognitiveKernelV3:
    """Niblit Cognitive Kernel v3 — the unified thinking, deciding and improving system.

    Fuses all v1 + v2 capabilities and adds:
    * :class:`KernelCommunicationBus` for kernel-mediated agent messaging.
    * :class:`RewardEngine` for per-interaction RL scoring.
    * :class:`KernelScheduler` for DAG-ordered task execution.
    * Five built-in agents (Research, Coder, Critic, Teacher, Explorer).
    * Single ``run_cognitive_loop()`` entry point that exercises all layers.

    Memory design
    -------------
    Agents own **no** memory.  All persistent state lives in the shared
    ``KernelMemory`` (from v1) which is MWDS-backed and SyncEngine-aware.
    After each cycle the result is written via ``_remember()`` and the best
    memory hit is reinforced (RL loop closure).

    Args:
        kernel_v1:    Optional v1 :class:`~modules.niblit_core_kernel.NiblitCoreKernel`.
        kernel_v2:    Optional v2 :class:`~modules.niblit_core_kernel_v2.NiblitCoreKernelV2`.
        evolve_enabled: Whether the evolve gate is active.
        strict_safety:  Whether to enable strict safety mode.
        reward_floor:   Minimum acceptable reward.
    """

    def __init__(
        self,
        kernel_v1: Optional[Any] = None,
        kernel_v2: Optional[Any] = None,
        evolve_enabled: bool = _EVOLVE_ENABLED,
        strict_safety: bool = _SAFETY_STRICT,
        reward_floor: float = _REWARD_FLOOR,
    ) -> None:
        self._kernel_v1 = kernel_v1
        self._kernel_v2 = kernel_v2
        self._evolve_enabled = evolve_enabled

        # Core v3 subsystems
        self.bus = KernelCommunicationBus()
        self.reward_engine = RewardEngine(floor=reward_floor)
        self.scheduler = KernelScheduler()

        # Agents — kernel reference injected
        self._agents: Dict[str, BaseAgent] = {
            _AGENT_RESEARCH: ResearchAgent(kernel=self),
            _AGENT_CODER:    CoderAgent(kernel=self),
            _AGENT_CRITIC:   CriticAgent(kernel=self),
            _AGENT_TEACHER:  TeacherAgent(kernel=self),
            _AGENT_EXPLORER: ExplorerAgent(kernel=self),
        }

        # State
        self._lock = threading.Lock()
        self._cycle_count = 0
        self._stats: Dict[str, int] = {
            "loop_calls": 0,
            "messages_routed": 0,
            "agent_calls": 0,
            "memory_writes": 0,
            "reward_scores": 0,
        }

        log.info(
            "[KernelV3] Cognitive Kernel v3 initialised — "
            "agents=%d evolve=%s safety_strict=%s",
            len(self._agents), evolve_enabled, strict_safety,
        )

    # ── Lazy v1/v2 accessors ─────────────────────────────────────────────────

    @property
    def v1(self) -> Optional[Any]:
        """Lazy accessor for kernel v1."""
        if self._kernel_v1 is None:
            try:
                from modules.niblit_core_kernel import get_niblit_core_kernel
                self._kernel_v1 = get_niblit_core_kernel()
            except Exception:
                pass
        return self._kernel_v1

    @property
    def v2(self) -> Optional[Any]:
        """Lazy accessor for kernel v2."""
        if self._kernel_v2 is None:
            try:
                from modules.niblit_core_kernel_v2 import get_niblit_core_kernel_v2
                self._kernel_v2 = get_niblit_core_kernel_v2()
            except Exception:
                pass
        return self._kernel_v2

    @property
    def memory(self) -> Optional[Any]:
        """Unified KernelMemory from v1 (or standalone if v1 unavailable)."""
        if self.v1 is not None:
            return getattr(self.v1, "memory", None)
        try:
            from modules.niblit_core_kernel import KernelMemory
            return KernelMemory()
        except Exception:
            return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _retrieve_memory(self, query: str, top_k: int = 5) -> List[str]:
        """Retrieve relevant memories from KernelMemory."""
        mem = self.memory
        if mem is not None:
            try:
                return mem.retrieve(query, top_k=top_k)
            except Exception:
                pass
        return []

    def _remember(self, data: Any, importance: float = 0.7) -> None:
        """Write *data* to KernelMemory (v1 MWDS-backed)."""
        mem = self.memory
        if mem is not None:
            try:
                mem.store(data, importance=importance, source="kernel_v3")
                with self._lock:
                    self._stats["memory_writes"] += 1
            except Exception:
                pass

    def _tool_execute(self, action: str, payload: Any) -> str:
        """Dispatch an action through v1's ToolRouter."""
        if self.v1 is not None:
            try:
                return self.v1.tool_router.execute(action, payload)
            except Exception as exc:
                log.debug("[KernelV3] ToolRouter.execute failed: %s", exc)
        return f"[KernelV3] Processed: {str(payload)[:100]}"

    def _classify_intent(self, text: str) -> str:
        """Classify *text* intent using v2 synthesizer (preferred) or v1 decision engine."""
        # Try v2 PatternSynthesizer
        if self.v2 is not None:
            try:
                return self.v2.synthesizer.intent_classify(text)
            except Exception:
                pass
        # Try v1 DecisionEngine
        if self.v1 is not None:
            try:
                return self.v1.decision_engine.decide(text)
            except Exception:
                pass
        # Lightweight keyword fallback
        lower = text.lower()
        for kw, intent in [
            ("code", "generate_code"), ("build", "generate_code"), ("write", "generate_code"),
            ("research", "research"), ("learn", "research"), ("find", "research"),
            ("debug", "debug"), ("error", "debug"), ("fix", "debug"),
            ("reflect", "reflect"), ("why", "reflect"),
            ("trade", "trade"), ("market", "trade"),
            ("evolve", "evolve"), ("improve", "evolve"),
        ]:
            if kw in lower:
                return intent
        return "respond"

    def _think_v2(self, input_text: str) -> Tuple[str, List[Any], List[str]]:
        """Run the v2 embed→retrieve→expand→synthesize pipeline.

        Returns:
            ``(thought, memory_hits, concepts)``
        """
        if self.v2 is not None:
            try:
                return self.v2.think(input_text)
            except Exception as exc:
                log.debug("[KernelV3] v2.think failed: %s", exc)
        # Fallback — simple text recall
        memories = self._retrieve_memory(input_text)
        thought = f"Input: {input_text[:200]}\nRelevant: {'; '.join(memories[:2])}"
        return thought, [], []

    def _think_v1(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Run the v1 CognitionCore/ReasoningEngine path."""
        if self.v1 is not None:
            try:
                return self.v1.think(input_text, context=context)
            except Exception as exc:
                log.debug("[KernelV3] v1.think failed: %s", exc)
        return input_text

    # ── Safety gate ───────────────────────────────────────────────────────────

    _BLOCKED_PATTERNS = frozenset({
        "rm -rf", "delete all", "drop table", "format c:", "sys.exit(0)",
        "os.system(", "subprocess.call(", "__import__('os').system",
    })

    def _safety_gate(self, message: KernelMessage) -> bool:
        """Return True if *message* passes the safety gate.

        Blocks messages that contain known dangerous patterns.
        """
        text = (str(message.intent) + " " + str(message.payload)).lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in text:
                log.warning("[KernelV3] Blocked message %s — safety pattern '%s'",
                             message.id[:8], pattern)
                return False
        return True

    # ── 7-step kernel pipeline ────────────────────────────────────────────────

    def process(
        self,
        message: KernelMessage,
        collect_results: bool = True,
    ) -> Optional[str]:
        """Run the 7-step kernel pipeline for *message*.

        Steps:

        1. Intent classification
        2. Memory injection into payload
        3. Reasoning expansion (v2 PatternSynthesizer)
        4. Safety + quality gate
        5. Routing decision
        6. Dispatch to target agent
        7. Reward scoring + kernel feedback

        Args:
            message:         The inbound :class:`KernelMessage`.
            collect_results: If True, return the agent's result string.

        Returns:
            Agent result string, or ``None`` if blocked / no agent.
        """
        with self._lock:
            self._stats["messages_routed"] += 1

        # ── Step 1: Intent classification ────────────────────────────────
        if message.intent in ("broadcast", "respond", ""):
            query = str(message.payload.get("query", message.payload.get("topic", "")))
            message.intent = self._classify_intent(query) or "respond"

        # ── Step 2: Memory injection ─────────────────────────────────────
        query = str(message.payload.get("query",
                    message.payload.get("topic",
                    message.payload.get("prompt", ""))))[:200]
        if query:
            context_memories = self._retrieve_memory(query)
            message.payload["_kernel_context"] = context_memories[:3]

        # ── Step 3: Reasoning expansion ──────────────────────────────────
        if query:
            thought, hits, concepts = self._think_v2(query)
            message.payload["_thought"] = thought[:300]
            message.payload["_concepts"] = concepts[:8]
            message.payload["memory_hits"] = hits[:3]
            if not message.payload.get("topic"):
                message.payload["topic"] = query
            if not message.payload.get("concepts"):
                message.payload["concepts"] = concepts

        # ── Step 4: Safety + quality gate ────────────────────────────────
        if not self._safety_gate(message):
            return None

        # ── Step 5: Routing decision ─────────────────────────────────────
        if message.target in ("broadcast", _KERNEL_ID, ""):
            # Route to the most appropriate agent
            intent_to_agent: Dict[str, str] = {
                "generate_code": _AGENT_CODER,
                "debug":         _AGENT_CODER,
                "research":      _AGENT_RESEARCH,
                "reflect":       _AGENT_TEACHER,
                "trade":         _AGENT_RESEARCH,
                "evolve":        _AGENT_CRITIC,
                "respond":       _AGENT_TEACHER,
            }
            message.target = intent_to_agent.get(message.intent, _AGENT_TEACHER)

        # ── Step 6: Dispatch ─────────────────────────────────────────────
        self.bus.route(message)
        result = self._dispatch_agent(message.target, message)

        # ── Step 7: Reward scoring ────────────────────────────────────────
        if result is not None:
            latency_ms = (time.time() - message.timestamp) * 1000
            reward = self.reward_engine.score_from_latency(
                message.target, latency_ms=latency_ms, result_len=len(result)
            )
            message.reward = reward
            message.result = result
            with self._lock:
                self._stats["reward_scores"] += 1
            # Feedback reward into kernel memory
            self._remember(
                {"event": "agent_response", "agent": message.target,
                 "intent": message.intent, "reward": reward,
                 "trace_id": message.trace_id},
                importance=0.4,
            )
            # ── Bridge kernel reward into PolicyOptimizer ─────────────────
            # Each agent dispatch is a mini-decision: routing to a specific
            # agent for an intent.  Recording these episodes lets
            # PolicyOptimizer learn which intents are handled well over time.
            try:
                from modules.policy_optimizer import get_policy_optimizer
                _po = get_policy_optimizer()
                _po.record_episode(
                    context_type=message.intent or "chat",
                    advisor_chosen=f"kernel_{message.target}",
                    advisor_confidences={f"kernel_{message.target}": reward},
                    outcome_score=reward,
                )
            except Exception as _po_kv3_err:
                log.debug("[KernelV3] PolicyOptimizer episode skipped: %s", _po_kv3_err)

        return result

    def _dispatch_agent(self, agent_id: str, message: KernelMessage) -> Optional[str]:
        """Deliver *message* to the named agent and return its response.

        Args:
            agent_id: Target agent identifier.
            message:  The message to handle.

        Returns:
            Agent result string or None if the agent is not found.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            log.debug("[KernelV3] Unknown agent_id: %s", agent_id)
            return None
        with self._lock:
            self._stats["agent_calls"] += 1
        try:
            return agent.handle(message)
        except Exception as exc:
            log.debug("[KernelV3] agent %s failed: %s", agent_id, exc)
            return f"[Error] {agent_id}: {exc}"

    # ── Multi-agent orchestration ─────────────────────────────────────────────

    def orchestrate(
        self,
        intent: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build and execute the task graph for *intent*.

        Builds a DAG of :class:`TaskNode` objects, orders them via the
        :class:`KernelScheduler`, dispatches each through the 7-step
        kernel pipeline, and forwards results as context to downstream nodes.

        Args:
            intent:    The high-level intent (``"generate_code"``, etc.).
            payload:   The enriched payload dict.
            trace_id:  Optional trace ID for correlation.

        Returns:
            ``{agent_id: result_string}`` for each executed agent.
        """
        nodes = _build_task_graph(intent, dict(payload))
        ordered = self.scheduler.plan(nodes)
        agent_outputs: Dict[str, str] = {}

        tid = trace_id or str(uuid.uuid4())[:8]

        for node in ordered:
            # Inject results from completed dependencies
            for dep_agent in node.depends:
                if dep_agent in agent_outputs:
                    node.payload[f"_{dep_agent}_result"] = agent_outputs[dep_agent][:200]

            msg = KernelMessage(
                sender=_KERNEL_ID,
                target=node.agent,
                intent=node.intent,
                payload=node.payload,
                trace_id=tid,
            )
            result = self.process(msg, collect_results=True)
            agent_outputs[node.agent] = result or ""

        return agent_outputs

    # ══════════════════════════════════════════════════════════════════════════
    # Unified cognitive loop (fused v1 + v2 + v3)
    # ══════════════════════════════════════════════════════════════════════════

    def run_cognitive_loop(
        self,
        input_data: Any,
        context: Optional[Dict[str, Any]] = None,
        auto_act: bool = True,
        use_agents: bool = True,
    ) -> KernelV3Result:
        """Run one full fused cognitive cycle.

        Pipeline::

            v2: EMBED → RETRIEVE → EXPAND → SYNTHESIZE
            v1: CognitionCore/ReasoningEngine fallback
            classify intent
            v3: orchestrate agent task graph (kernel-mediated)
            REMEMBER → REINFORCE (RL loop)

        Args:
            input_data:  User query, task description, or sensor input.
            context:     Optional extra context for v1 think path.
            auto_act:    Execute tool actions for non-respond intents.
            use_agents:  Run KCB multi-agent orchestration.

        Returns:
            :class:`KernelV3Result` with all intermediate outputs.
        """
        t0 = time.time()
        with self._lock:
            self._stats["loop_calls"] += 1
            self._cycle_count += 1

        result = KernelV3Result(input_data=input_data)
        text = str(input_data)[:512]

        # ── Phase 1: v2 embed → retrieve → expand → synthesize ──────────────
        thought_v2, hits, concepts = self._think_v2(text)
        result.memory_hits = hits
        result.concepts = concepts

        # ── Phase 2: v1 CognitionCore/ReasoningEngine path ───────────────────
        thought_v1 = self._think_v1(text, context=context)

        # Fuse: v2 thought is richer when hits exist; otherwise use v1
        result.thought = thought_v2 if hits else thought_v1

        # ── Phase 3: Intent classification ───────────────────────────────────
        result.decision = self._classify_intent(result.thought)

        # Extract readable response from v2 synthesizer
        if self.v2 is not None:
            try:
                result.response = self.v2.synthesizer.to_response(result.thought)
            except Exception:
                result.response = result.thought[:200]
        else:
            result.response = result.thought[:200]

        # ── Phase 3b: BrainRouter augmentation ───────────────────────────────
        # If the local response is weak/empty, ask BrainRouter to produce or
        # improve the answer.  This gives the kernel access to Qwen local brain
        # and cloud escalation without duplicating the routing logic here.
        if not result.response or result.response.startswith("No strong"):
            try:
                from modules.brain_router import get_brain_router
                _br = get_brain_router()
                _kv3_ctx = result.thought[:400] if result.thought else ""
                _br_resp = _br.route(text, context=_kv3_ctx)
                if _br_resp and isinstance(_br_resp, str) and len(_br_resp) > 5:
                    result.response = _br_resp
            except Exception as _br_kv3_err:
                log.debug("[KernelV3] BrainRouter augmentation skipped: %s", _br_kv3_err)
        # ─────────────────────────────────────────────────────────────────────

        # ── Phase 4: v3 multi-agent orchestration ─────────────────────────────
        trace_id = str(uuid.uuid4())[:8]
        if use_agents:
            payload = {
                "topic": text,
                "query": text,
                "concepts": concepts,
                "memory_hits": [h.get("text", "")[:80] for h in hits[:3]],
                **(context or {}),
            }
            agent_outputs = self.orchestrate(result.decision, payload, trace_id=trace_id)
            result.agent_outputs = agent_outputs

            # Synthesize final result from agent outputs
            if agent_outputs:
                parts = [v for v in agent_outputs.values() if v]
                result.action_result = " | ".join(parts[:3])[:500] if parts else result.response
            else:
                result.action_result = result.response
        else:
            # Fallback: single tool dispatch through v1
            if auto_act and result.decision != "respond" and self.v1 is not None:
                try:
                    result.action_result = self.v1.act(result.decision, result.thought)
                except Exception:
                    result.action_result = result.response
            else:
                result.action_result = result.response

        # ── Phase 5: Remember (centralized memory write) ──────────────────────
        self._remember(
            {
                "input": text[:200],
                "thought": result.thought[:200],
                "response": result.response[:200],
                "decision": result.decision,
                "agent_outputs": {k: v[:100] for k, v in result.agent_outputs.items()},
                "trace_id": trace_id,
            },
            importance=0.75,
        )
        result.remembered = True

        # ── Phase 6: RL reinforcement ─────────────────────────────────────────
        if hits:
            best_text = str(hits[0].get("text", ""))[:200]
            if best_text and self.v2 is not None:
                try:
                    self.v2.reinforce(best_text, success=True)
                except Exception:
                    pass
            elif best_text and self.v1 is not None:
                try:
                    self.v1.memory.reinforce_content(best_text, success=True)
                except Exception:
                    pass

        # ── Phase 7: Aggregate rewards ────────────────────────────────────────
        result.rewards = {
            aid: self.reward_engine.agent_mean_reward(aid)
            for aid in result.agent_outputs
        }

        # ── Phase 8: Sync engine feedback ────────────────────────────────────
        self._feedback_sync(result)

        # ── Phase 9: EventBus notification ───────────────────────────────────
        # Publish a kernel cycle event so MetaEngine and PolicyOptimizer can
        # subscribe to kernel cycle completions without tight coupling.
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_POLICY_OPTIMIZED
            mean_reward = (
                sum(result.rewards.values()) / len(result.rewards)
                if result.rewards else 0.5
            )
            get_event_bus().publish(NiblitEvent(
                type=EVENT_POLICY_OPTIMIZED,
                source="niblit_kernel_v3",
                payload={
                    "cycle": self._cycle_count,
                    "decision": result.decision,
                    "agents": list(result.agent_outputs.keys()),
                    "mean_reward": round(mean_reward, 4),
                    "latency_ms": round(result.latency_ms, 1),
                },
            ))
        except Exception as _ev_err:
            log.debug("[KernelV3] EventBus publish skipped: %s", _ev_err)

        result.latency_ms = (time.time() - t0) * 1000
        result.ts = int(time.time())
        result.messages = self.bus.trace_snapshot(last_n=10)

        log.info(
            "[KernelV3] cycle #%d: decision=%s agents=%d latency=%.0fms",
            self._cycle_count, result.decision,
            len(result.agent_outputs), result.latency_ms,
        )
        return result

    def _feedback_sync(self, result: KernelV3Result) -> None:
        """Write cycle completion event to SyncEngine (if available)."""
        try:
            from modules.sync_engine import get_sync_engine, SyncArtifact
            se = get_sync_engine()
            artifact = SyncArtifact(
                type="event",
                content={
                    "event": "kernel_v3_cycle",
                    "decision": result.decision,
                    "latency_ms": result.latency_ms,
                    "agents": list(result.agent_outputs.keys()),
                },
                priority=0.45,
                source="local",
            )
            se.queue_artifact(artifact)
        except Exception:
            pass

    # ── Public API surface mirrors (v1 / v2 drop-in compatibility) ───────────

    def think(self, input_data: Any, context: Optional[Dict[str, Any]] = None) -> str:
        """Think pass (v1-compatible API, uses fused v1+v2 path)."""
        thought_v2, hits, _ = self._think_v2(str(input_data)[:512])
        if hits:
            return thought_v2
        return self._think_v1(str(input_data), context=context)

    def remember(self, data: Any, importance: float = 0.7) -> None:
        """Store *data* in KernelMemory (v1-compatible API)."""
        self._remember(data, importance=importance)

    def decide(self, thought: str) -> str:
        """Classify *thought* into an intent (v1-compatible API)."""
        return self._classify_intent(thought)

    def act(self, decision: str, payload: Any) -> str:
        """Execute *decision* with *payload* (v1-compatible API)."""
        return self._tool_execute(decision, payload)

    def evolve(self, proposal: str) -> str:
        """Run evolution proposal through v1 gate (v1-compatible API)."""
        if not self._evolve_enabled:
            return "[KernelV3] Evolution disabled."
        if self.v1 is not None:
            try:
                return self.v1.evolve(proposal)
            except Exception as exc:
                return f"[KernelV3] evolve failed: {exc}"
        return f"[KernelV3] Would evolve: {proposal[:100]}"

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a full snapshot of v3 kernel state."""
        with self._lock:
            stats = dict(self._stats)
        return {
            **stats,
            "cycle_count": self._cycle_count,
            "agents": list(self._agents.keys()),
            "bus_kernel_inbox": self.bus.inbox_size(_KERNEL_ID),
            "reward_signals": self.reward_engine.evolution_signals(),
            "below_floor": [
                aid for aid in _ALL_AGENTS
                if self.reward_engine.below_floor(aid)
            ],
        }


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_kernel_v3: Optional[NiblitCognitiveKernelV3] = None
_kernel_v3_lock = threading.Lock()


def get_niblit_kernel_v3(**kwargs) -> NiblitCognitiveKernelV3:
    """Return the process-level :class:`NiblitCognitiveKernelV3` singleton.

    Thread-safe, lazily created on first call.  Any keyword arguments are
    forwarded to the constructor **only** on the first call.
    """
    global _kernel_v3  # pylint: disable=global-statement
    with _kernel_v3_lock:
        if _kernel_v3 is None:
            _kernel_v3 = NiblitCognitiveKernelV3(**kwargs)
        return _kernel_v3


if __name__ == "__main__":
    print('Running niblit_kernel_v3.py')
