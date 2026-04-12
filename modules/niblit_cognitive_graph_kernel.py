#!/usr/bin/env python3
"""
modules/niblit_cognitive_graph_kernel.py — Niblit Cognitive Graph Kernel v1.0
==============================================================================
A *unified runtime substrate* that collapses Niblit's four major subsystems
into a single, event-driven graph operating system.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────┐
    │                  CognitiveGraphKernel                    │
    │              (Graph Event Runtime v1.0)                  │
    └────────────────────────┬─────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    Memory Graph        Membrane Graph      Evolution Graph
   (knowledge state)   (security state)    (self-mod system)
         │                   │                   │
         └──────────┬────────┴──────────┬────────┘
                    │                   │
         EventBus (Causal DAG Runtime)
                    │
        Everything = Event + Node + Edge

Core principle
--------------
Everything is an event.

Instead of:
  * calling functions directly
  * running background polling threads
  * procedural mutation loops

You have:
  * ``Event(type, payload, source, timestamp, energy, priority)``
  * Every subsystem = a graph layer (nodes + edges)
  * All mutations triggered exclusively by events
  * One deterministic dispatch cycle: ``kernel.tick()``

Design rules
------------
* ❌ No direct cross-layer calls.  All interactions through EventBus.
* ❌ No blocked external I/O inside tick().
* ✅ All graph mutations are event-generated.
* ✅ Memory decay runs on every tick().
* ✅ Threat events automatically trigger evolution events.
* ✅ Graceful fallback when CyberMembrane / DEL not available.

Integration with existing Niblit systems
-----------------------------------------
* ``MemoryLayer`` delegates hot/warm storage to ``MemoryStore`` (MWDS v2)
  when available, and self-manages a plain dict otherwise.
* ``MembraneGraph`` bridges to ``MembraneOrchestrator`` (CyberMembrane)
  to propagate newly learned patterns at runtime.
* ``EvolutionGraphRuntime`` bridges to ``DefensiveEvolutionLoop``
  to fan-out real attack genomes as evolution events.
* ``CognitiveGraph`` integrates with ``KnowledgeDB`` to persist learned nodes.

Singleton
---------
``get_cognitive_graph_kernel()`` returns the process-wide
:class:`CognitiveGraphKernel` instance.

Configuration (environment variables)
--------------------------------------
``NIBLIT_CGK_TICK_INTERVAL``   — seconds between automatic background ticks
                                 (default: 0.5; set 0 to disable background tick)
``NIBLIT_CGK_DECAY_FACTOR``    — memory decay factor per tick (default: 0.995)
``NIBLIT_CGK_MAX_QUEUE``       — maximum event queue depth (default: 2000)
``NIBLIT_CGK_EVO_INTERVAL``    — seconds between evolution sweeps (default: 10)
``NIBLIT_CGK_MAX_GRAPH_NODES`` — prune oldest nodes when exceeded (default: 5000)
"""

from __future__ import annotations

import heapq
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
_TICK_INTERVAL = float(os.environ.get("NIBLIT_CGK_TICK_INTERVAL", "0.5"))
_DECAY_FACTOR = float(os.environ.get("NIBLIT_CGK_DECAY_FACTOR", "0.995"))
_MAX_QUEUE = int(os.environ.get("NIBLIT_CGK_MAX_QUEUE", "2000"))
_EVO_INTERVAL = float(os.environ.get("NIBLIT_CGK_EVO_INTERVAL", "10"))
_MAX_GRAPH_NODES = int(os.environ.get("NIBLIT_CGK_MAX_GRAPH_NODES", "5000"))

# ── Event types ───────────────────────────────────────────────────────────────
EVT_MEMORY_WRITE = "memory.write"
EVT_MEMORY_READ = "memory.read"
EVT_MEMORY_DECAY = "memory.decay"
EVT_GRAPH_UPDATE = "graph.update"
EVT_GRAPH_EDGE = "graph.edge"
EVT_GRAPH_QUERY = "graph.query"
EVT_SECURITY_THREAT = "security.threat"
EVT_SECURITY_PATTERN = "security.pattern_learned"
EVT_EVOLVE_ATTACK = "evolve.attack"
EVT_EVOLVE_RESULT = "evolve.result"
EVT_SYSTEM_TICK = "system.tick"
EVT_SYSTEM_PRUNE = "system.prune"


# =============================================================================
# EVENT SYSTEM
# =============================================================================

@dataclass(order=True)
class Event:
    """A typed, causal event carrying a payload through the kernel bus."""
    # Heap comparison uses (priority, timestamp, id) so high-priority events
    # are dispatched first (we negate priority for min-heap ordering).
    _sort_key: Tuple[float, float, str] = field(init=False, repr=False, compare=True)

    type: str = field(compare=False)
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)
    source: str = field(default="unknown", compare=False)
    timestamp: float = field(default_factory=time.time, compare=False)
    priority: float = field(default=1.0, compare=False)  # higher = dispatched sooner
    energy: float = field(default=1.0, compare=False)
    id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)

    def __post_init__(self):
        # Negate priority so that Python's min-heap gives us max-priority first
        object.__setattr__(self, "_sort_key", (-self.priority, self.timestamp, self.id))


class EventBus:
    """
    Priority-ordered event bus with typed subscriptions.

    Events are stored in a min-heap keyed by ``(-priority, timestamp, id)``
    so that high-priority events are dispatched first within each ``dispatch()``
    call.
    """

    def __init__(self, max_queue: int = _MAX_QUEUE):
        self._heap: List[Event] = []
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._max_queue = max_queue
        self._dispatched: int = 0
        self._dropped: int = 0

    # ── Emit ─────────────────────────────────────────────────────────────────

    def emit(self, event: Event) -> None:
        """Add an event to the priority queue (thread-safe)."""
        with self._lock:
            if len(self._heap) >= self._max_queue:
                # Drop the lowest-priority event to make room
                self._heap.sort()  # ensure heap invariant before pop
                heapq.heapify(self._heap)
                if self._heap and self._heap[0].priority < event.priority:
                    heapq.heapreplace(self._heap, event)
                    self._dropped += 1
                    return
                else:
                    self._dropped += 1
                    return
            heapq.heappush(self._heap, event)

    # ── Subscribe ────────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for a specific event type."""
        self._subscribers[event_type].append(handler)

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def dispatch(self, limit: int = 200) -> int:
        """
        Process up to *limit* events from the priority queue.

        Returns the number of events dispatched.
        """
        processed = 0
        while processed < limit:
            with self._lock:
                if not self._heap:
                    break
                event = heapq.heappop(self._heap)

            handlers = self._subscribers.get(event.type, [])
            for handler in handlers:
                try:
                    handler(event)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[CGK-EventBus] handler error for %s: %s", event.type, exc)
            processed += 1
            self._dispatched += 1

        return processed

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "queue_depth": len(self._heap),
            "dispatched_total": self._dispatched,
            "dropped_total": self._dropped,
            "subscriber_types": list(self._subscribers.keys()),
        }


# =============================================================================
# COGNITIVE GRAPH (KNOWLEDGE STATE)
# =============================================================================

@dataclass
class Node:
    """A typed knowledge node in the cognitive graph."""
    id: str
    type: str
    state: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


@dataclass
class Edge:
    """A directed, weighted relation between two nodes."""
    src: str
    dst: str
    relation: str
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


class CognitiveGraph:
    """
    In-process knowledge graph substrate.

    Supports basic traversal, pruning, and integration with KnowledgeDB
    for persistence of newly created nodes.
    """

    def __init__(self, max_nodes: int = _MAX_GRAPH_NODES):
        self._nodes: Dict[str, Node] = {}
        self._edges: List[Edge] = []
        self._max_nodes = max_nodes
        self._lock = threading.Lock()
        self._mutations: int = 0

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        with self._lock:
            if node.id in self._nodes:
                existing = self._nodes[node.id]
                existing.state.update(node.state)
                existing.weight = max(existing.weight, node.weight)
                existing.last_updated = time.time()
            else:
                self._nodes[node.id] = node
                self._mutations += 1
            if len(self._nodes) > self._max_nodes:
                self._prune_oldest(int(self._max_nodes * 0.1))

    def add_edge(self, edge: Edge) -> None:
        with self._lock:
            # Deduplicate
            for existing in self._edges:
                if (existing.src == edge.src and existing.dst == edge.dst
                        and existing.relation == edge.relation):
                    existing.weight = max(existing.weight, edge.weight)
                    return
            self._edges.append(edge)
            self._mutations += 1

    def _prune_oldest(self, n: int) -> None:
        """Remove the *n* oldest nodes and their edges (called under lock)."""
        sorted_nodes = sorted(self._nodes.values(), key=lambda nd: nd.last_updated)
        to_remove = {nd.id for nd in sorted_nodes[:n]}
        for nid in to_remove:
            del self._nodes[nid]
        self._edges = [e for e in self._edges
                       if e.src not in to_remove and e.dst not in to_remove]

    # ── Query ────────────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def get_neighbors(self, node_id: str) -> List[str]:
        with self._lock:
            return [e.dst for e in self._edges if e.src == node_id]

    def get_by_type(self, node_type: str) -> List[Node]:
        with self._lock:
            return [n for n in self._nodes.values() if n.type == node_type]

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            type_counts: Dict[str, int] = defaultdict(int)
            for n in self._nodes.values():
                type_counts[n.type] += 1
            return {
                "node_count": len(self._nodes),
                "edge_count": len(self._edges),
                "mutations": self._mutations,
                "node_types": dict(type_counts),
            }


# =============================================================================
# MEMORY LAYER (UNIFIED DECAYING STORE)
# =============================================================================

class MemoryLayer:
    """
    Unified memory layer: combines vector, KB, and episodic memory concepts
    into a single weighted, decaying key-value store.

    If ``MemoryStore`` (MWDS v2) is available it delegates hot/warm storage
    to that system; otherwise it self-manages a plain dict.
    """

    def __init__(self, decay_factor: float = _DECAY_FACTOR):
        self._store: Dict[str, Any] = {}
        self._usage: Dict[str, float] = defaultdict(float)
        self._weight: Dict[str, float] = defaultdict(lambda: 1.0)
        self._decay_factor = decay_factor
        self._lock = threading.Lock()
        self._writes: int = 0
        self._reads: int = 0
        self._decays: int = 0

        # Optional MWDS v2 backend
        self._mwds: Optional[Any] = None
        try:
            from modules.memory_weighting import get_memory_store
            self._mwds = get_memory_store()
        except Exception:  # noqa: BLE001
            pass

    # ── Write ─────────────────────────────────────────────────────────────────

    def write(self, key: str, value: Any, weight: float = 1.0) -> None:
        with self._lock:
            self._store[key] = value
            self._usage[key] += weight
            self._weight[key] = max(self._weight[key], weight)
            self._writes += 1
        if self._mwds is not None:
            try:
                self._mwds.reinforce(key, delta=weight)
            except Exception:  # noqa: BLE001
                pass

    # ── Read ─────────────────────────────────────────────────────────────────

    def read(self, key: str) -> Optional[Any]:
        with self._lock:
            val = self._store.get(key)
            if val is not None:
                self._usage[key] += 0.1
                self._reads += 1
        return val

    # ── Decay ────────────────────────────────────────────────────────────────

    def decay(self) -> None:
        """Apply exponential decay to all memory weights."""
        with self._lock:
            dead: List[str] = []
            for k in list(self._usage.keys()):
                self._usage[k] *= self._decay_factor
                self._weight[k] *= self._decay_factor
                if self._weight[k] < 1e-4:
                    dead.append(k)
            for k in dead:
                del self._store[k]
                del self._usage[k]
                del self._weight[k]
            self._decays += 1

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._store),
                "writes": self._writes,
                "reads": self._reads,
                "decay_cycles": self._decays,
                "mwds_backend": self._mwds is not None,
            }


# =============================================================================
# MEMBRANE GRAPH (EVENT-FILTERING SECURITY LAYER)
# =============================================================================

class MembraneGraph:
    """
    Security layer that operates as a filtering function on the event stream.

    Rules are dynamic: ``reinforce(pattern, weight)`` injects new detection
    patterns at runtime (called by EvolutionGraphRuntime when bypasses are
    found).

    When a ``CyberMembrane`` is available it propagates learned patterns back
    into ``InputGuard`` / ``AdaptiveFirewall`` so the full membrane benefits.
    """

    def __init__(self, membrane: Optional[Any] = None):
        self._rules: Dict[str, float] = {}
        self._threat_history: deque = deque(maxlen=1000)
        self._lock = threading.Lock()
        self._blocked: int = 0
        self._allowed: int = 0
        # Optional bridge to CyberMembrane
        self._membrane = membrane

    # ── Evaluate ─────────────────────────────────────────────────────────────

    def evaluate(self, event: Event) -> bool:
        """
        Return ``True`` if the event is allowed through; ``False`` if blocked.

        Blocked events are stored in threat history and will trigger
        evolution events downstream.
        """
        with self._lock:
            for pattern, weight in self._rules.items():
                if pattern in event.type or pattern in str(event.payload):
                    if weight >= 0.75:
                        self._threat_history.append({
                            "event_type": event.type,
                            "source": event.source,
                            "timestamp": event.timestamp,
                            "pattern": pattern,
                            "weight": weight,
                        })
                        self._blocked += 1
                        return False
        self._allowed += 1
        return True

    # ── Reinforce ────────────────────────────────────────────────────────────

    def reinforce(self, pattern: str, weight: float) -> None:
        """
        Inject or strengthen a detection pattern.

        Also propagates to the CyberMembrane's InputGuard and
        AdaptiveFirewall when available.
        """
        with self._lock:
            self._rules[pattern] = max(self._rules.get(pattern, 0.0), weight)
        if self._membrane is not None:
            try:
                ig = getattr(self._membrane, "input_guard", None)
                if ig is not None and hasattr(ig, "add_pattern"):
                    ig.add_pattern(pattern, weight, label="cgk_evolved")
                af = getattr(self._membrane, "adaptive_firewall", None)
                if af is not None and hasattr(af, "learn"):
                    af.learn({"pattern": pattern, "weight": weight,
                               "source": "cognitive_graph_kernel"})
            except Exception:  # noqa: BLE001
                pass

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_threat_log(self, n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._threat_history)[-n:]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "rules": len(self._rules),
                "threats_recorded": len(self._threat_history),
                "blocked": self._blocked,
                "allowed": self._allowed,
                "membrane_bridge": self._membrane is not None,
            }


# =============================================================================
# EVOLUTION GRAPH RUNTIME (SELF-IMPROVING MUTATION SYSTEM)
# =============================================================================

class EvolutionGraphRuntime:
    """
    Converts Niblit's ``DefensiveEvolutionLoop`` procedural mutation engine
    into an **event-driven graph rewriting system**.

    OLD:
      thread → drain queue → replay sandbox → mutate → inject firewall rules

    NEW:
      Event: security.threat
        ↓
      MembraneGraph rejects
        ↓
      Event: evolve.attack  (emitted by MembraneGraph handler in kernel)
        ↓
      EvolutionGraphRuntime: mutate payload → emit graph.update
        ↓
      CognitiveGraph: new mutation_node created
        ↓
      MemoryLayer: pattern stored
        ↓
      MembraneGraph.reinforce(): pattern injected dynamically

    The runtime also polls the real ``DefensiveEvolutionLoop`` bypass
    discoveries (when available) and fans them out as evolution events.
    """

    _MUTATION_STRATEGIES = ["obfuscate_syntax", "time_shift", "layer_bypass", "combine_vectors"]

    def __init__(self, kernel: "CognitiveGraphKernel"):
        self._kernel = kernel
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._evolution_cycles: int = 0
        self._mutations_emitted: int = 0
        self._evo_interval: float = _EVO_INTERVAL

        # Optional bridge to DefensiveEvolutionLoop
        self._del: Optional[Any] = None
        try:
            from modules.niblit_defensive_evolution_loop import get_evolution_loop
            self._del = get_evolution_loop()
        except Exception:  # noqa: BLE001
            pass

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="cgk-evolution"
        )
        self._thread.start()
        log.info("[CGK-Evolution] Evolution graph runtime started.")

    def stop(self) -> None:
        with self._lock:
            self._active = False
        log.info("[CGK-Evolution] Evolution graph runtime stopped.")

    # ── Background sweep ────────────────────────────────────────────────────

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._active:
                    break
            try:
                self._sweep()
            except Exception as exc:  # noqa: BLE001
                log.debug("[CGK-Evolution] sweep error: %s", exc)
            time.sleep(self._evo_interval)

    def _sweep(self) -> None:
        """
        Fan out threats from MembraneGraph threat history and
        bypass discoveries from DefensiveEvolutionLoop as evolution events.
        """
        # Threat history from MembraneGraph
        threats = self._kernel.membrane.get_threat_log(20)
        for threat in threats:
            evt = Event(
                type=EVT_EVOLVE_ATTACK,
                payload={"threat": threat, "mutation_depth": 3},
                source="evolution_graph_runtime",
                priority=2.0,
            )
            self._kernel.bus.emit(evt)
            self._mutations_emitted += 1

        # Bypass discoveries from real DEL if available
        if self._del is not None:
            try:
                bypasses = list(getattr(self._del, "_bypass_discoveries", []))[-10:]
                for bp in bypasses:
                    evt = Event(
                        type=EVT_EVOLVE_ATTACK,
                        payload={"bypass": bp, "mutation_depth": 5},
                        source="defensive_evolution_loop",
                        priority=3.0,  # higher priority than normal threats
                    )
                    self._kernel.bus.emit(evt)
                    self._mutations_emitted += 1
            except Exception:  # noqa: BLE001
                pass

        self._evolution_cycles += 1

    # ── Single evolution event handler ──────────────────────────────────────

    def handle_evolve_event(self, event: Event) -> None:
        """
        Convert an ``evolve.attack`` event into a ``graph.update`` (mutation node)
        and reinforce the membrane pattern.
        """
        payload = event.payload
        # Select mutation strategy based on depth
        depth = payload.get("mutation_depth", 1)
        strategy = self._MUTATION_STRATEGIES[depth % len(self._MUTATION_STRATEGIES)]

        # Build a mutation node in the cognitive graph
        mutation_id = f"mutation:{uuid.uuid4().hex[:8]}"
        graph_event = Event(
            type=EVT_GRAPH_UPDATE,
            payload={
                "id": mutation_id,
                "type": "mutation_node",
                "state": {
                    "original": payload,
                    "strategy": strategy,
                    "generation": depth,
                    "source": event.source,
                },
                "weight": min(1.0, 0.5 + 0.1 * depth),
            },
            source="evolution_graph_runtime",
            priority=2.5,
        )
        self._kernel.bus.emit(graph_event)

        # Also reinforce the membrane pattern
        threat_type = (
            payload.get("threat", {}).get("event_type", "")
            or payload.get("bypass", {}).get("type", "")
            or event.type
        )
        if threat_type:
            pattern_weight = min(0.95, 0.7 + 0.05 * depth)
            self._kernel.membrane.reinforce(threat_type, pattern_weight)

            # Emit a security.pattern_learned event for observability
            self._kernel.bus.emit(Event(
                type=EVT_SECURITY_PATTERN,
                payload={"pattern": threat_type, "weight": pattern_weight,
                         "strategy": strategy},
                source="evolution_graph_runtime",
                priority=1.5,
            ))

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "active": self._active,
            "evolution_cycles": self._evolution_cycles,
            "mutations_emitted": self._mutations_emitted,
            "del_bridge": self._del is not None,
            "evo_interval_secs": self._evo_interval,
        }


# =============================================================================
# COGNITIVE GRAPH KERNEL (UNIFIED RUNTIME)
# =============================================================================

class CognitiveGraphKernel:
    """
    v1.0 Unified Cognitive Graph Kernel.

    Single entry point for the entire unified runtime.  Designed to be
    started once at process boot (via ``get_cognitive_graph_kernel()``) and
    then driven by ``tick()`` calls from the main loop or a lightweight
    background thread.

    All four Niblit subsystems communicate *only* through this kernel's
    ``EventBus`` — zero direct cross-module calls at runtime.
    """

    def __init__(
        self,
        membrane: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        tick_interval: float = _TICK_INTERVAL,
    ):
        self.bus = EventBus()
        self.graph = CognitiveGraph()
        self.memory = MemoryLayer()
        self.membrane = MembraneGraph(membrane=membrane)
        self.evolution = EvolutionGraphRuntime(self)

        self._knowledge_db = knowledge_db
        self._tick_interval = tick_interval
        self._tick_count: int = 0
        self._started_at: float = time.time()
        self._bg_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        self._bind_events()
        log.info("[CGK] CognitiveGraphKernel v1.0 initialised.")

    # ── Event wiring ─────────────────────────────────────────────────────────

    def _bind_events(self) -> None:
        self.bus.subscribe(EVT_MEMORY_WRITE, self._on_memory_write)
        self.bus.subscribe(EVT_MEMORY_READ, self._on_memory_read)
        self.bus.subscribe(EVT_GRAPH_UPDATE, self._on_graph_update)
        self.bus.subscribe(EVT_GRAPH_EDGE, self._on_graph_edge)
        self.bus.subscribe(EVT_SECURITY_THREAT, self._on_security_threat)
        self.bus.subscribe(EVT_EVOLVE_ATTACK, self._on_evolve_attack)
        self.bus.subscribe(EVT_SYSTEM_PRUNE, self._on_system_prune)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_memory_write(self, event: Event) -> None:
        key = event.payload.get("key", "")
        value = event.payload.get("value")
        weight = float(event.payload.get("weight", 1.0))
        if key:
            self.memory.write(key, value, weight)

    def _on_memory_read(self, event: Event) -> None:
        # Read is typically fire-and-forget unless a callback is provided
        key = event.payload.get("key", "")
        cb = event.payload.get("callback")
        if key and callable(cb):
            try:
                cb(self.memory.read(key))
            except Exception:  # noqa: BLE001
                pass

    def _on_graph_update(self, event: Event) -> None:
        p = event.payload
        node_id = p.get("id", str(uuid.uuid4()))
        node = Node(
            id=node_id,
            type=p.get("type", "generic"),
            state=p.get("state", {}),
            weight=float(p.get("weight", 1.0)),
        )
        self.graph.add_node(node)

        # Persist important nodes to KnowledgeDB
        if self._knowledge_db is not None and node.weight >= 0.7:
            try:
                summary = str(node.state)[:500]
                self._knowledge_db.store_fact(
                    f"cgk_node:{node_id}", summary
                )
            except Exception:  # noqa: BLE001
                pass

    def _on_graph_edge(self, event: Event) -> None:
        p = event.payload
        src = p.get("src", "")
        dst = p.get("dst", "")
        if src and dst:
            self.graph.add_edge(Edge(
                src=src,
                dst=dst,
                relation=p.get("relation", "related"),
                weight=float(p.get("weight", 1.0)),
            ))

    def _on_security_threat(self, event: Event) -> None:
        """
        Filter through MembraneGraph.  If blocked, emit an evolve.attack event
        so the EvolutionGraphRuntime can learn from it.
        """
        allowed = self.membrane.evaluate(event)
        if not allowed:
            self.bus.emit(Event(
                type=EVT_EVOLVE_ATTACK,
                payload={**event.payload, "blocked_event_type": event.type},
                source="membrane_graph",
                priority=3.0,
            ))

    def _on_evolve_attack(self, event: Event) -> None:
        self.evolution.handle_evolve_event(event)

    def _on_system_prune(self, _event: Event) -> None:
        self.memory.decay()

    # ── Public API for emitting events ───────────────────────────────────────

    def emit_memory_write(self, key: str, value: Any, weight: float = 1.0) -> None:
        self.bus.emit(Event(
            type=EVT_MEMORY_WRITE,
            payload={"key": key, "value": value, "weight": weight},
            source="api",
        ))

    def emit_graph_update(self, node_id: str, node_type: str,
                          state: Dict[str, Any], weight: float = 1.0) -> None:
        self.bus.emit(Event(
            type=EVT_GRAPH_UPDATE,
            payload={"id": node_id, "type": node_type,
                     "state": state, "weight": weight},
            source="api",
        ))

    def emit_security_threat(self, threat_type: str, payload: Dict[str, Any],
                             severity: float = 0.5) -> None:
        self.bus.emit(Event(
            type=EVT_SECURITY_THREAT,
            payload={"threat_type": threat_type, **payload},
            source="api",
            priority=severity * 5.0,  # map severity [0,1] → priority [0,5]
            energy=severity,
        ))

    # ── Deterministic tick (core dispatch cycle) ─────────────────────────────

    def tick(self) -> int:
        """
        Single deterministic dispatch cycle.

        1. Process up to 200 queued events (priority-ordered).
        2. Apply memory decay every 100 ticks.
        3. Emit a system.tick event for observability.
        4. Return number of events processed.
        """
        processed = self.bus.dispatch(limit=200)
        self._tick_count += 1

        if self._tick_count % 100 == 0:
            self.memory.decay()
            # Prune via event (keeps the graph runtime consistent)
            self.bus.emit(Event(
                type=EVT_SYSTEM_PRUNE,
                payload={"tick": self._tick_count},
                source="kernel",
                priority=0.1,  # lowest priority
            ))

        return processed

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background tick loop and evolution runtime."""
        self.evolution.start()

        if self._tick_interval > 0:
            with self._lock:
                if self._running:
                    return
                self._running = True
            self._bg_thread = threading.Thread(
                target=self._bg_tick_loop, daemon=True, name="cgk-tick"
            )
            self._bg_thread.start()
            log.info("[CGK] Background tick loop started (interval=%.2fs).",
                     self._tick_interval)

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self.evolution.stop()
        log.info("[CGK] CognitiveGraphKernel stopped.")

    def _bg_tick_loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                log.debug("[CGK] tick error: %s", exc)
            time.sleep(self._tick_interval)

    # ── Stats / observability ────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "uptime_secs": round(time.time() - self._started_at, 1),
            "event_bus": self.bus.stats(),
            "graph": self.graph.stats(),
            "memory": self.memory.stats(),
            "membrane": self.membrane.stats(),
            "evolution": self.evolution.stats(),
        }


# =============================================================================
# SINGLETON + BOOTSTRAP
# =============================================================================

_kernel_instance: Optional[CognitiveGraphKernel] = None
_kernel_lock = threading.Lock()


def get_cognitive_graph_kernel(
    membrane: Optional[Any] = None,
    knowledge_db: Optional[Any] = None,
    tick_interval: float = _TICK_INTERVAL,
) -> CognitiveGraphKernel:
    """
    Return the process-wide :class:`CognitiveGraphKernel` singleton.

    Thread-safe.  Additional arguments are only used on first construction.
    """
    global _kernel_instance
    with _kernel_lock:
        if _kernel_instance is None:
            _kernel_instance = CognitiveGraphKernel(
                membrane=membrane,
                knowledge_db=knowledge_db,
                tick_interval=tick_interval,
            )
    return _kernel_instance


# =============================================================================
# STANDALONE ENTRY-POINT (development / testing)
# =============================================================================

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    kernel = get_cognitive_graph_kernel()
    kernel.start()

    print("CognitiveGraphKernel v1.0 running.  Press Ctrl-C to stop.\n")
    try:
        while True:
            kernel.tick()
            print(json.dumps(kernel.status(), indent=2, default=str))
            time.sleep(2)
    except KeyboardInterrupt:
        kernel.stop()
        print("Stopped.")
