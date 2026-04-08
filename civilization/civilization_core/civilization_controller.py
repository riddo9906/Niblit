"""CivilizationController — top-level orchestrator for the Niblit civilization loop.

Architecture
------------
The controller wires together all civilization subsystems into a single
run_cycle() call:

  PopulationManager  → spawns / tracks agents
  CivilizationScheduler → assigns tasks by role
  agent instances    → ResearchAgent / BuilderAgent / PlannerAgent /
                        AnalystAgent / EvolutionAgent
  ReputationEngine   → tracks agent quality scores (EWMA)
  AuditSystem        → immutable action log
  CivilizationMetrics → per-cycle aggregate statistics
  MessageBus         → intra-civilization pub/sub
  KnowledgeAPI       → civilization-internal vector+graph memory
  KnowledgeDB        → Niblit's production knowledge store (optional)
  GitHubCodeSearch   → live repository research for ResearchAgent (optional)
  PopulationOptimizer / ArchitectureEvolver  → evolution every N cycles

Usage example::

    controller = CivilizationController(
        knowledge_db=niblit_core.db,
        github_code_search=niblit_core.github_code_search,
    )
    controller.start()
    result = controller.run_cycle()
    findings = controller.to_findings_dict()
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Type

log = logging.getLogger("CivilizationController")

# ── role → agent class registry ──────────────────────────────────────────────
_ROLE_TOPIC_MAP: Dict[str, str] = {
    "researcher": "multi-agent-systems",
    "builder": "code-generation",
    "planner": "software-architecture",
    "analyst": "performance-analysis",
    "evolution_agent": "evolutionary-algorithms",
}

_EVOLUTION_INTERVAL = 5   # run evolution step every N cycles
_INITIAL_AGENTS_PER_ROLE = 1


class CivilizationController:
    """Coordinates the full civilization life-cycle.

    All heavy dependencies are injected (optional) so the controller degrades
    gracefully when components are unavailable.

    Args:
        knowledge_db:       Niblit's production KnowledgeDB (optional).
        github_code_search: GitHubCodeSearch instance for real research (optional).
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        github_code_search: Optional[Any] = None,
    ) -> None:
        self._running: bool = False
        self._cycle_count: int = 0
        self._started_at: Optional[float] = None
        self._knowledge_db = knowledge_db
        self._github_code_search = github_code_search

        # ── lazily-imported subsystems ────────────────────────────────────────
        self._pop_manager: Optional[Any] = None
        self._scheduler: Optional[Any] = None
        self._reputation: Optional[Any] = None
        self._audit: Optional[Any] = None
        self._metrics: Optional[Any] = None
        self._message_bus: Optional[Any] = None
        self._knowledge_api: Optional[Any] = None
        self._pop_optimizer: Optional[Any] = None
        self._arch_evolver: Optional[Any] = None

        # live agent objects keyed by agent_id
        self._agent_instances: Dict[str, Any] = {}

        # accumulated findings for to_findings_dict()
        self._all_insights: List[str] = []
        self._all_repos: List[str] = []

        self._init_subsystems()

    # ── initialisation ────────────────────────────────────────────────────────

    def _init_subsystems(self) -> None:
        """Lazy-import and instantiate all civilization subsystems."""
        try:
            from civilization.civilization_core.population_manager import PopulationManager
            from civilization.civilization_core.civilization_scheduler import CivilizationScheduler
            from civilization.civilization_core.civilization_metrics import CivilizationMetrics
            from civilization.governance.reputation_engine import ReputationEngine
            from civilization.governance.audit_system import AuditSystem
            from civilization.collaboration_network.message_bus import MessageBus
            from civilization.knowledge_ecosystem.vector_memory import VectorMemory
            from civilization.knowledge_ecosystem.graph_memory import GraphMemory
            from civilization.knowledge_ecosystem.embedding_service import EmbeddingService
            from civilization.knowledge_ecosystem.knowledge_api import KnowledgeAPI
            from civilization.evolution_engine.population_optimizer import PopulationOptimizer
            from civilization.evolution_engine.architecture_evolver import ArchitectureEvolver

            self._pop_manager = PopulationManager()
            self._scheduler = CivilizationScheduler()
            self._metrics = CivilizationMetrics()
            self._reputation = ReputationEngine()
            self._audit = AuditSystem()
            self._message_bus = MessageBus()
            self._knowledge_api = KnowledgeAPI(VectorMemory(), GraphMemory(), EmbeddingService())
            self._pop_optimizer = PopulationOptimizer()
            self._arch_evolver = ArchitectureEvolver()
            log.info("CivilizationController: subsystems initialised")
        except Exception as exc:
            log.debug("CivilizationController: subsystem init partial — %s", exc)

    def _get_agent_class(self, role: str) -> Optional[Type]:
        """Return the agent class for *role*, or None on import failure."""
        _map = {
            "researcher": "civilization.agent_population.research_agent.ResearchAgent",
            "builder": "civilization.agent_population.builder_agent.BuilderAgent",
            "planner": "civilization.agent_population.planner_agent.PlannerAgent",
            "analyst": "civilization.agent_population.analyst_agent.AnalystAgent",
            "evolution_agent": "civilization.agent_population.evolution_agent.EvolutionAgent",
        }
        dotpath = _map.get(role)
        if not dotpath:
            return None
        try:
            module_path, cls_name = dotpath.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)
        except Exception as exc:
            log.debug("CivilizationController: agent class import failed for %s — %s", role, exc)
            return None

    def _ensure_population(self) -> None:
        """Spawn the initial agent population if the population is empty."""
        if self._pop_manager is None:
            return
        if self._pop_manager.agent_count() > 0:
            return
        roles = list(_ROLE_TOPIC_MAP.keys())
        for role in roles:
            agent_ids = self._pop_manager.spawn(role, count=_INITIAL_AGENTS_PER_ROLE)
            for aid in agent_ids:
                cls = self._get_agent_class(role)
                if cls is not None:
                    agent_obj = cls(aid, role)
                    # Wire optional GitHubCodeSearch into ResearchAgent
                    if role == "researcher" and self._github_code_search is not None:
                        try:
                            agent_obj.github_code_search = self._github_code_search
                        except Exception:
                            pass
                    self._agent_instances[aid] = agent_obj

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Activate the running flag and ensure the initial population exists."""
        self._running = True
        self._started_at = time.time()
        self._ensure_population()
        log.info("CivilizationController: started — %d agents active",
                 self._pop_manager.agent_count() if self._pop_manager else 0)

    def stop(self) -> None:
        """Deactivate the running flag."""
        self._running = False
        log.info("CivilizationController: stopped after %d cycles", self._cycle_count)

    def run_cycle(self) -> Dict[str, Any]:
        """Execute one full civilisation cycle and return a results dict.

        Pipeline per cycle
        ------------------
        1. Ensure population is populated (lazy spawn on first cycle).
        2. For each active agent, assign a task via the scheduler.
        3. Execute the task through the agent object; record outcome.
        4. Store research insights into the KnowledgeAPI (and optionally KnowledgeDB).
        5. Publish a cycle_completed event to the MessageBus.
        6. Every _EVOLUTION_INTERVAL cycles, run a population evolution step.
        7. Record aggregate cycle data in CivilizationMetrics.
        """
        self._cycle_count += 1
        cycle_start = time.time()
        log.info("CivilizationController: cycle %d begin", self._cycle_count)

        self._ensure_population()

        agents_active = 0
        tasks_completed = 0
        cycle_insights: List[str] = []
        cycle_repos: List[str] = []
        errors: List[str] = []

        agents = (self._pop_manager.get_agents() if self._pop_manager else [])

        for agent_meta in agents:
            agent_id = agent_meta["agent_id"]
            role = agent_meta["role"]
            agent_obj = self._agent_instances.get(agent_id)
            if agent_obj is None:
                continue

            agents_active += 1

            # Build task dict
            task: Dict[str, Any] = {}
            if self._scheduler:
                task = self._scheduler.assign_task(agent_meta)
            topic = _ROLE_TOPIC_MAP.get(role, "general")
            task.setdefault("goal", topic)
            task.setdefault("topic", topic)
            task.setdefault("architecture", {"type": "ai-service", "language": "python"})
            task.setdefault("experiment", {"data": [0.75, 0.80, 0.85]})
            task.setdefault("system_state", {"accuracy": 0.78, "latency_ms": 120})

            # Execute
            try:
                result = agent_obj.execute(task)
                success = True
                tasks_completed += 1

                # Harvest insights from ResearchAgent
                for insight in result.get("insights", []):
                    cycle_insights.append(str(insight))
                    self._all_insights.append(str(insight))
                for src in result.get("sources", []):
                    cycle_repos.append(str(src))
                    self._all_repos.append(str(src))

                # Harvest hypotheses from EvolutionAgent
                hyp = result.get("hypothesis", {})
                if hyp and hyp.get("proposed_fix"):
                    fix = f"evolution: {hyp['proposed_fix']}"
                    cycle_insights.append(fix)
                    self._all_insights.append(fix)

                # Store insights into KnowledgeAPI
                if self._knowledge_api and cycle_insights:
                    for ins in cycle_insights[-3:]:  # cap per agent to avoid flood
                        try:
                            self._knowledge_api.store_knowledge(ins, tags=[role, "civilization"])
                        except Exception:
                            pass

                # Store into KnowledgeDB (Niblit's production KB)
                if self._knowledge_db and cycle_insights:
                    for ins in cycle_insights[-2:]:
                        try:
                            key = f"civilization:{role}:{uuid.uuid4().hex[:8]}"
                            self._knowledge_db.add_fact(key, ins, tags=["civilization", role])
                        except Exception:
                            pass

                # Reputation
                score = result.get("confidence", result.get("score", 0.7))
                if self._reputation:
                    self._reputation.record_action(agent_id, success=True, score=float(score))

                # Audit
                if self._audit:
                    self._audit.record(f"{role}_execute", agent_id,
                                       {"task_type": task.get("task_type", role),
                                        "success": True})

            except Exception as exc:
                errors.append(f"{agent_id}: {exc}")
                log.debug("CivilizationController: agent %s execute failed — %s", agent_id, exc)
                if self._reputation:
                    self._reputation.record_action(agent_id, success=False)
                if self._audit:
                    self._audit.record(f"{role}_error", agent_id, {"error": str(exc)})

        # Publish cycle event on the MessageBus
        if self._message_bus:
            try:
                self._message_bus.publish(
                    "cycle_completed",
                    "civilization_controller",
                    {
                        "cycle": self._cycle_count,
                        "agents_active": agents_active,
                        "tasks_completed": tasks_completed,
                        "new_insights": len(cycle_insights),
                    },
                )
            except Exception:
                pass

        # Run population evolution every _EVOLUTION_INTERVAL cycles
        if self._cycle_count % _EVOLUTION_INTERVAL == 0:
            self._run_evolution_step()

        elapsed_ms = round((time.time() - cycle_start) * 1000, 2)

        cycle_data = {
            "cycle": self._cycle_count,
            "agents_active": agents_active,
            "tasks_completed": tasks_completed,
            "new_insights": len(cycle_insights),
            "elapsed_ms": elapsed_ms,
            "errors": len(errors),
        }

        if self._metrics:
            try:
                self._metrics.record_cycle(cycle_data)
            except Exception:
                pass

        log.info(
            "CivilizationController: cycle %d done — agents=%d tasks=%d insights=%d elapsed=%.1f ms",
            self._cycle_count, agents_active, tasks_completed, len(cycle_insights), elapsed_ms,
        )
        return cycle_data

    def _run_evolution_step(self) -> None:
        """Run one population evolution step using PopulationOptimizer."""
        if self._pop_optimizer is None or self._reputation is None:
            return
        try:
            population = self._pop_manager.get_agents() if self._pop_manager else []
            if not population:
                return

            def _fitness(agent: Dict[str, Any]) -> float:
                return self._reputation.get_reputation(agent.get("agent_id", ""))

            result = self._pop_optimizer.optimize(population, _fitness, generations=2)
            log.info(
                "CivilizationController: evolution step — best_fitness=%.4f",
                result.get("best_fitness", 0.0),
            )
        except Exception as exc:
            log.debug("CivilizationController: evolution step failed — %s", exc)

    def to_findings_dict(self) -> Dict[str, Any]:
        """Return accumulated findings in the format expected by
        ``SelfImprovementOrchestrator.ingest_research_findings()``.
        """
        top_agents: List[Dict[str, Any]] = []
        if self._reputation:
            try:
                top_agents = self._reputation.top_agents(n=5)
            except Exception:
                pass

        patterns: Dict[str, List[str]] = {
            "Research Sources": list(dict.fromkeys(self._all_repos))[:10],
        }
        recommendations: List[str] = [
            f"{a['agent_id'][:8]}… (role={a.get('role','?')}) rep={a.get('reputation',0):.3f}"
            for a in top_agents
        ]

        return {
            "patterns": patterns,
            "top_repos": [{"full_name": r, "stars": 0} for r in self._all_repos[:5]],
            "new_insights": list(dict.fromkeys(self._all_insights))[:20],
            "recommendations": recommendations,
            "source": "civilization",
            "cycle_count": self._cycle_count,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return current controller status."""
        agent_count = self._pop_manager.agent_count() if self._pop_manager else 0
        metrics_summary = {}
        if self._metrics:
            try:
                metrics_summary = self._metrics.get_summary()
            except Exception:
                pass
        top_agents: List[Dict[str, Any]] = []
        if self._reputation:
            try:
                top_agents = self._reputation.top_agents(n=3)
            except Exception:
                pass
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "started_at": self._started_at,
            "agents_active": agent_count,
            "insights_accumulated": len(self._all_insights),
            "metrics": metrics_summary,
            "top_agents": top_agents,
        }

    def get_cycle_count(self) -> int:
        """Return total completed cycles."""
        return self._cycle_count
