"""CivilizationController — top-level orchestrator for the Niblit civilization loop.

Architecture
------------
The controller wires together all civilization subsystems into a single
run_cycle() call:

  PopulationManager     → spawns / tracks agents
  CivilizationScheduler → assigns tasks by role
  agent instances       → ResearchAgent / BuilderAgent / PlannerAgent /
                          AnalystAgent / EvolutionAgent
  ReputationEngine      → tracks agent quality scores (EWMA)
  SelectionEngine       → elite selection for evolution
  MutationEngine        → mutates agent parameters
  AuditSystem           → immutable action log
  CivilizationMetrics   → per-cycle aggregate statistics
  MessageBus            → intra-civilization pub/sub
  KnowledgeAPI          → civilization-internal vector+graph memory
  SafetyPolicies        → governance guardrails
  KnowledgeDB           → Niblit's production knowledge store (optional)
  GitHubCodeSearch      → live repository research for ResearchAgent (optional)

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
from typing import Any, Dict, List, Optional

log = logging.getLogger("CivilizationController")

# How many cycles between evolution (selection + mutation) steps.
_EVOLVE_EVERY: int = 3
# Default roles spawned at civilization start (two researchers for coverage).
_DEFAULT_ROLES: List[str] = ["researcher", "researcher", "builder", "planner", "evolution_agent"]


def _make_typed_agent(agent_id: str, role: str) -> Any:
    """Return a typed BaseAgent subclass for *role*, or a plain BaseAgent fallback."""
    try:
        from civilization.agent_population.research_agent import ResearchAgent
        from civilization.agent_population.builder_agent import BuilderAgent
        from civilization.agent_population.planner_agent import PlannerAgent
        from civilization.agent_population.analyst_agent import AnalystAgent
        from civilization.agent_population.evolution_agent import EvolutionAgent
        from civilization.agent_population.base_agent import BaseAgent

        _role_map = {
            "researcher": ResearchAgent,
            "builder": BuilderAgent,
            "planner": PlannerAgent,
            "analyst": AnalystAgent,
            "evolution_agent": EvolutionAgent,
        }
        cls = _role_map.get(role, BaseAgent)
        return cls(agent_id, role)
    except Exception as exc:
        log.debug(
            "CivilizationController: typed agent creation failed (%s), using BaseAgent fallback: %s",
            role, exc,
        )
        try:
            from civilization.agent_population.base_agent import BaseAgent
            return BaseAgent(agent_id, role)
        except Exception:
            return None


class CivilizationController:
    """Coordinates the civilization life-cycle.

    All internal subsystems (PopulationManager, Scheduler, Metrics, etc.) are
    created during ``__init__`` so the controller is fully self-contained.
    ``niblit_core`` only needs to call ``start()`` and optionally
    ``run_cycle()`` / ``to_findings_dict()``.

    Args:
        initial_roles:      Roles to spawn at startup (default: ``_DEFAULT_ROLES``).
        knowledge_db:       Niblit's production KnowledgeDB — written after each
                            cycle so civilization insights persist across restarts
                            (optional).
        github_code_search: GitHubCodeSearch instance injected into every
                            ResearchAgent for live GitHub repository search
                            (optional; agents fall back to static list).
    """

    def __init__(
        self,
        initial_roles: Optional[List[str]] = None,
        knowledge_db: Optional[Any] = None,
        github_code_search: Optional[Any] = None,
    ) -> None:
        self._running: bool = False
        self._cycle_count: int = 0
        self._started_at: Optional[float] = None
        self._initial_roles: List[str] = initial_roles or list(_DEFAULT_ROLES)
        self._knowledge_db = knowledge_db
        self._github_code_search = github_code_search

        # ── subsystem instances ──
        self._pop_manager: Any = None
        self._scheduler: Any = None
        self._metrics: Any = None
        self._message_bus: Any = None
        self._reputation: Any = None
        self._selector: Any = None
        self._mutator: Any = None
        self._knowledge_api: Any = None
        self._safety: Any = None
        self._audit: Any = None

        # agent_id → typed BaseAgent instance
        self._agent_instances: Dict[str, Any] = {}

        # accumulated insights for to_findings_dict()
        self._insights_buffer: List[str] = []

        self._init_subsystems()

    # ── initialisation ────────────────────────────────────────────────────────

    def _init_subsystems(self) -> None:
        """Instantiate all civilization subsystems; failures are non-fatal."""
        try:
            from civilization.civilization_core.population_manager import PopulationManager
            self._pop_manager = PopulationManager()
        except Exception as exc:
            log.debug("CivilizationController: PopulationManager unavailable: %s", exc)

        try:
            from civilization.civilization_core.civilization_scheduler import CivilizationScheduler
            self._scheduler = CivilizationScheduler()
        except Exception as exc:
            log.debug("CivilizationController: CivilizationScheduler unavailable: %s", exc)

        try:
            from civilization.civilization_core.civilization_metrics import CivilizationMetrics
            self._metrics = CivilizationMetrics()
        except Exception as exc:
            log.debug("CivilizationController: CivilizationMetrics unavailable: %s", exc)

        try:
            from civilization.collaboration_network.message_bus import MessageBus
            self._message_bus = MessageBus()
        except Exception as exc:
            log.debug("CivilizationController: MessageBus unavailable: %s", exc)

        try:
            from civilization.governance.reputation_engine import ReputationEngine
            self._reputation = ReputationEngine()
        except Exception as exc:
            log.debug("CivilizationController: ReputationEngine unavailable: %s", exc)

        try:
            from civilization.evolution_engine.selection_engine import SelectionEngine
            from civilization.evolution_engine.mutation_engine import MutationEngine
            self._selector = SelectionEngine()
            self._mutator = MutationEngine()
        except Exception as exc:
            log.debug("CivilizationController: evolution engine unavailable: %s", exc)

        try:
            from civilization.knowledge_ecosystem.vector_memory import VectorMemory
            from civilization.knowledge_ecosystem.graph_memory import GraphMemory
            from civilization.knowledge_ecosystem.embedding_service import EmbeddingService
            from civilization.knowledge_ecosystem.knowledge_api import KnowledgeAPI
            self._knowledge_api = KnowledgeAPI(VectorMemory(), GraphMemory(), EmbeddingService())
        except Exception as exc:
            log.debug("CivilizationController: KnowledgeAPI unavailable: %s", exc)

        try:
            from civilization.governance.safety_policies import SafetyPolicies
            self._safety = SafetyPolicies()
        except Exception as exc:
            log.debug("CivilizationController: SafetyPolicies unavailable: %s", exc)

        try:
            from civilization.governance.audit_system import AuditSystem
            self._audit = AuditSystem()
        except Exception as exc:
            log.debug("CivilizationController: AuditSystem unavailable: %s", exc)

    def _spawn_agent(self, role: str) -> Optional[str]:
        """Spawn one agent of *role*; return the new agent_id or None."""
        if not self._pop_manager:
            return None
        try:
            ids = self._pop_manager.spawn(role, count=1)
            agent_id = ids[0]
            typed = _make_typed_agent(agent_id, role)
            if typed is not None:
                # Inject optional external dependencies
                if self._github_code_search is not None and role == "researcher":
                    try:
                        typed.github_code_search = self._github_code_search
                    except Exception:
                        pass
                self._agent_instances[agent_id] = typed
            return agent_id
        except Exception as exc:
            log.debug("CivilizationController: spawn(%s) failed: %s", role, exc)
            return None

    def _despawn_agent(self, agent_id: str) -> None:
        """Remove agent from PopulationManager and instance registry."""
        if self._pop_manager:
            try:
                self._pop_manager.despawn(agent_id)
            except Exception:
                pass
        self._agent_instances.pop(agent_id, None)

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Activate the running flag and seed the initial population."""
        self._running = True
        self._started_at = time.time()
        if self._pop_manager and self._pop_manager.agent_count() == 0:
            for role in self._initial_roles:
                self._spawn_agent(role)
        log.info(
            "CivilizationController: started with %d agents",
            self._pop_manager.agent_count() if self._pop_manager else 0,
        )

    def stop(self) -> None:
        """Deactivate the running flag."""
        self._running = False
        log.info("CivilizationController: stopped after %d cycles", self._cycle_count)

    def run_cycle(self) -> Dict[str, Any]:
        """Execute one full civilisation cycle.

        Steps:
          1. Ensure population is seeded.
          2. Assign a task to every active agent via CivilizationScheduler.
          3. Execute each typed agent; collect results.
          4. Record action in AuditSystem; update ReputationEngine scores.
          5. Store ResearchAgent insights in KnowledgeAPI; buffer for findings.
             Also write new insights to the production KnowledgeDB when wired.
          6. Every ``_EVOLVE_EVERY`` cycles, run selection + mutation on the
             population and replace the bottom half with fresh offspring.
          7. Record cycle metrics.

        Returns a dict with cycle metadata.
        """
        self._cycle_count += 1
        log.info("CivilizationController: cycle %d begin", self._cycle_count)
        cycle_start = time.time()

        # 1. Ensure population is seeded ──────────────────────────────────────
        if self._pop_manager and self._pop_manager.agent_count() == 0:
            for role in self._initial_roles:
                self._spawn_agent(role)

        agents: List[Dict[str, Any]] = []
        if self._pop_manager:
            agents = self._pop_manager.get_agents()

        tasks_completed = 0
        cycle_insights: List[str] = []
        system_state: Dict[str, Any] = {"accuracy": 0.75, "latency_ms": 120}

        for agent_meta in agents:
            agent_id = agent_meta.get("agent_id", "")
            role = agent_meta.get("role", "researcher")
            typed = self._agent_instances.get(agent_id)

            # 2. Assign task ───────────────────────────────────────────────────
            task: Dict[str, Any] = {}
            if self._scheduler:
                try:
                    task = self._scheduler.assign_task(agent_meta)
                except Exception as exc:
                    log.debug("CivilizationController: scheduler.assign_task failed: %s", exc)
            if not task.get("goal"):
                task["goal"] = f"civilization cycle {self._cycle_count} — {role} research"
            task["system_state"] = system_state

            # 3. Execute typed agent ───────────────────────────────────────────
            result: Dict[str, Any] = {}
            success = False
            if typed is not None:
                try:
                    result = typed.execute(task)
                    success = True
                    tasks_completed += 1
                except NotImplementedError:
                    pass
                except Exception as exc:
                    log.debug("CivilizationController: agent %s execute failed: %s", agent_id, exc)

            # 4. Audit + reputation ────────────────────────────────────────────
            if self._audit and agent_id:
                try:
                    self._audit.record(
                        action_type=task.get("task_type", "execute"),
                        agent_id=agent_id,
                        details={"role": role, "success": success},
                    )
                except Exception:
                    pass
            if self._reputation and agent_id:
                try:
                    self._reputation.record_action(agent_id, success=success, score=1.0)
                except Exception:
                    pass

            # 5. Publish on MessageBus; harvest research insights ──────────────
            if self._message_bus and result:
                try:
                    self._message_bus.publish(
                        msg_type=f"{role}_result",
                        sender_id=agent_id,
                        payload=result,
                    )
                except Exception:
                    pass
            if role == "researcher" and isinstance(result.get("insights"), list):
                for insight in result["insights"]:
                    text = str(insight)
                    cycle_insights.append(text)
                    if self._knowledge_api:
                        try:
                            self._knowledge_api.store_knowledge(
                                text,
                                tags=["civilization", "research", f"cycle_{self._cycle_count}"],
                            )
                        except Exception:
                            pass
                    # Persist into Niblit's production KnowledgeDB when wired
                    if self._knowledge_db and hasattr(self._knowledge_db, "add_fact"):
                        try:
                            key = f"civilization:research:{uuid.uuid4().hex[:8]}"
                            self._knowledge_db.add_fact(
                                key, text, tags=["civilization", "research"]
                            )
                        except Exception:
                            pass

        self._insights_buffer.extend(cycle_insights)

        # 6. Evolution step (every _EVOLVE_EVERY cycles) ──────────────────────
        if (
            self._cycle_count % _EVOLVE_EVERY == 0
            and self._pop_manager
            and self._selector
            and self._mutator
            and self._reputation
        ):
            self._run_evolution_step(agents)

        # 7. Record metrics ────────────────────────────────────────────────────
        elapsed_ms = round((time.time() - cycle_start) * 1000, 2)
        cycle_data = {
            "cycle": self._cycle_count,
            "agents_active": len(agents),
            "tasks_completed": tasks_completed,
            "new_insights": len(cycle_insights),
            "elapsed_ms": elapsed_ms,
        }
        if self._metrics:
            try:
                self._metrics.record_cycle(cycle_data)
            except Exception:
                pass

        log.info(
            "CivilizationController: cycle %d done — agents=%d tasks=%d insights=%d (%.1f ms)",
            self._cycle_count, len(agents), tasks_completed, len(cycle_insights), elapsed_ms,
        )
        return cycle_data

    def _run_evolution_step(self, agents: List[Dict[str, Any]]) -> None:
        """Select top agents by reputation and replace the bottom half with offspring."""
        if not agents:
            return
        try:
            fitness: Dict[str, float] = {}
            for a in agents:
                aid = a.get("agent_id", "")
                fitness[aid] = self._reputation.get_reputation(aid) if self._reputation else 0.5

            n_keep = max(1, len(agents) // 2)
            survivors = self._selector.elite_select(agents, fitness, n=n_keep)
            survivor_ids = {a["agent_id"] for a in survivors}

            for a in agents:
                if a["agent_id"] not in survivor_ids:
                    self._despawn_agent(a["agent_id"])

            for a in survivors:
                role = a.get("role", "researcher")
                params = {"role": role, "fitness": fitness.get(a["agent_id"], 0.5)}
                try:
                    mutated = self._mutator.mutate(params, mutation_rate=0.15)
                    new_role = mutated.get("role", role)
                    self._spawn_agent(new_role)
                except Exception:
                    self._spawn_agent(role)

            log.info(
                "CivilizationController: evolution step — kept=%d spawned=%d",
                len(survivors), len(agents) - len(survivors),
            )
        except Exception as exc:
            log.debug("CivilizationController: evolution step failed: %s", exc)

    def to_findings_dict(self) -> Dict[str, Any]:
        """Serialize accumulated civilization insights into the format expected
        by ``SelfImprovementOrchestrator.ingest_research_findings()``.

        Returns::

            {
                "patterns": {"Civilization Research": [<insight_text>, ...]},
                "top_repos": [],
                "new_insights": [<insight_text>, ...],
                "recommendations": [<summary_str>],
            }

        The internal insights buffer is cleared after this call so repeated
        calls do not double-ingest the same findings.
        """
        insights = list(dict.fromkeys(self._insights_buffer))[:20]
        # Clear consumed insights to prevent double-ingestion
        self._insights_buffer.clear()

        metrics_summary: Dict[str, Any] = {}
        if self._metrics:
            try:
                metrics_summary = self._metrics.get_summary()
            except Exception:
                pass

        n_agents = self._pop_manager.agent_count() if self._pop_manager else 0
        recommendations: List[str] = []
        if metrics_summary:
            recommendations.append(
                f"Civilization ran {metrics_summary.get('total_cycles', self._cycle_count)} cycles "
                f"with avg {metrics_summary.get('avg_agents', 0)} agents."
            )
        if n_agents:
            recommendations.append(f"Active agent count: {n_agents}")

        return {
            "patterns": {"Civilization Research": insights},
            "top_repos": [],
            "new_insights": insights,
            "recommendations": recommendations,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return current controller status."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "started_at": self._started_at,
            "agents_active": self._pop_manager.agent_count() if self._pop_manager else 0,
        }

    def get_cycle_count(self) -> int:
        """Return total completed cycles."""
        return self._cycle_count
