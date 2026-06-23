"""CivilizationController — top-level orchestrator for the Niblit civilization loop.

Architecture
------------
The controller wires together all civilization subsystems into a single
run_cycle() call:

  PopulationManager          → spawns / tracks agents
  CivilizationScheduler      → assigns tasks by role
  agent instances            → ResearchAgent / BuilderAgent / PlannerAgent /
                               AnalystAgent / EvolutionAgent
  ReputationEngine           → tracks agent quality scores (EWMA)
  SelectionEngine            → elite selection for evolution
  MutationEngine             → mutates agent parameters
  PopulationOptimizer        → generational population optimisation
  ArchitectureEvolver        → evolves agent architecture configurations
  AuditSystem                → immutable action log
  CivilizationMetrics        → per-cycle aggregate statistics
  MessageBus                 → intra-civilization pub/sub
  KnowledgeAPI               → civilization-internal vector+graph memory
  SafetyPolicies             → governance guardrails
  KnowledgeDB                → Niblit's production knowledge store (optional)
  GitHubCodeSearch           → live repository research for ResearchAgent (optional)

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

import importlib
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("CivilizationController")

# How many cycles between evolution (selection + mutation) steps.
_EVOLVE_EVERY: int = 3
# Slower generational evolution via PopulationOptimizer (every N cycles).
_EVOLUTION_INTERVAL: int = 5
# Default roles spawned at civilization start (two researchers for coverage).
_DEFAULT_ROLES: List[str] = ["researcher", "researcher", "builder", "planner", "evolution_agent"]
# Initial agents per role when spawned via _ensure_population().
_INITIAL_AGENTS_PER_ROLE: int = 1
# Maps each agent role to its primary research topic (used for task enrichment).
_ROLE_TOPIC_MAP: Dict[str, str] = {
    "researcher": "multi-agent-systems",
    "builder": "code-generation",
    "planner": "software-architecture",
    "analyst": "performance-analysis",
    "evolution_agent": "evolutionary-algorithms",
}


def _load_symbol(module_name: str, attr_name: str) -> Any:
    """Load a symbol from the package using a resilient import strategy."""
    for dotted_path in (module_name, f"civilization.{module_name}"):
        try:
            module = importlib.import_module(dotted_path)
            return getattr(module, attr_name)
        except (ImportError, AttributeError):
            continue
    raise ImportError(f"Unable to import {module_name}.{attr_name}")


def _make_typed_agent(agent_id: str, role: str) -> Any:
    """Return a typed BaseAgent subclass for *role*, or a plain BaseAgent fallback."""
    try:
        ResearchAgent = _load_symbol("agent_population.research_agent", "ResearchAgent")
        BuilderAgent = _load_symbol("agent_population.builder_agent", "BuilderAgent")
        PlannerAgent = _load_symbol("agent_population.planner_agent", "PlannerAgent")
        AnalystAgent = _load_symbol("agent_population.analyst_agent", "AnalystAgent")
        EvolutionAgent = _load_symbol("agent_population.evolution_agent", "EvolutionAgent")
        BaseAgent = _load_symbol("agent_population.base_agent", "BaseAgent")

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
            BaseAgent = _load_symbol("agent_population.base_agent", "BaseAgent")
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
        hf_brain:           HuggingFace inference provider (``HFBrain``) — injected
                            into every typed agent so they can generate LLM-based
                            insights via ``_ask_llm()`` (optional; agents degrade
                            gracefully to rule-based output when absent).
    """

    def __init__(
        self,
        initial_roles: Optional[List[str]] = None,
        knowledge_db: Optional[Any] = None,
        github_code_search: Optional[Any] = None,
        hf_brain: Optional[Any] = None,
    ) -> None:
        self._running: bool = False
        self._cycle_count: int = 0
        self._started_at: Optional[float] = None
        self._initial_roles: List[str] = initial_roles or list(_DEFAULT_ROLES)
        self._knowledge_db = knowledge_db
        self._github_code_search = github_code_search
        # HuggingFace inference provider — injected by niblit_core when available.
        # Forwarded to every typed agent so they can generate LLM-based insights.
        self._hf_brain = hf_brain

        # ── subsystem instances ──
        self._pop_manager: Any = None
        self._scheduler: Any = None
        self._metrics: Any = None
        self._message_bus: Any = None
        self._reputation: Any = None
        self._selector: Any = None
        self._mutator: Any = None
        self._pop_optimizer: Any = None
        self._arch_evolver: Any = None
        self._knowledge_api: Any = None
        self._safety: Any = None
        self._audit: Any = None

        # agent_id → typed BaseAgent instance
        self._agent_instances: Dict[str, Any] = {}

        # pending insights (consumed + cleared by to_findings_dict())
        self._insights_buffer: List[str] = []
        # lifetime accumulations (never cleared — used for status + richer findings)
        self._all_insights: List[str] = []
        self._all_repos: List[str] = []

        self._init_subsystems()

    # ── initialisation ────────────────────────────────────────────────────────

    def _init_subsystems(self) -> None:
        """Instantiate all civilization subsystems; failures are non-fatal."""
        try:
            PopulationManager = _load_symbol("civilization_core.population_manager", "PopulationManager")
            self._pop_manager = PopulationManager()
        except Exception as exc:
            log.debug("CivilizationController: PopulationManager unavailable: %s", exc)

        try:
            CivilizationScheduler = _load_symbol("civilization_core.civilization_scheduler", "CivilizationScheduler")
            self._scheduler = CivilizationScheduler()
        except Exception as exc:
            log.debug("CivilizationController: CivilizationScheduler unavailable: %s", exc)

        try:
            CivilizationMetrics = _load_symbol("civilization_core.civilization_metrics", "CivilizationMetrics")
            self._metrics = CivilizationMetrics()
        except Exception as exc:
            log.debug("CivilizationController: CivilizationMetrics unavailable: %s", exc)

        try:
            MessageBus = _load_symbol("collaboration_network.message_bus", "MessageBus")
            self._message_bus = MessageBus()
        except Exception as exc:
            log.debug("CivilizationController: MessageBus unavailable: %s", exc)

        try:
            ReputationEngine = _load_symbol("governance.reputation_engine", "ReputationEngine")
            self._reputation = ReputationEngine()
        except Exception as exc:
            log.debug("CivilizationController: ReputationEngine unavailable: %s", exc)

        try:
            SelectionEngine = _load_symbol("evolution_engine.selection_engine", "SelectionEngine")
            MutationEngine = _load_symbol("evolution_engine.mutation_engine", "MutationEngine")
            self._selector = SelectionEngine()
            self._mutator = MutationEngine()
        except Exception as exc:
            log.debug("CivilizationController: evolution engine unavailable: %s", exc)

        try:
            PopulationOptimizer = _load_symbol("evolution_engine.population_optimizer", "PopulationOptimizer")
            ArchitectureEvolver = _load_symbol("evolution_engine.architecture_evolver", "ArchitectureEvolver")
            self._pop_optimizer = PopulationOptimizer()
            self._arch_evolver = ArchitectureEvolver()
        except Exception as exc:
            log.debug("CivilizationController: PopulationOptimizer/ArchitectureEvolver unavailable: %s", exc)

        try:
            VectorMemory = _load_symbol("knowledge_ecosystem.vector_memory", "VectorMemory")
            GraphMemory = _load_symbol("knowledge_ecosystem.graph_memory", "GraphMemory")
            EmbeddingService = _load_symbol("knowledge_ecosystem.embedding_service", "EmbeddingService")
            KnowledgeAPI = _load_symbol("knowledge_ecosystem.knowledge_api", "KnowledgeAPI")
            self._knowledge_api = KnowledgeAPI(VectorMemory(), GraphMemory(), EmbeddingService())
        except Exception as exc:
            log.debug("CivilizationController: KnowledgeAPI unavailable: %s", exc)

        try:
            SafetyPolicies = _load_symbol("governance.safety_policies", "SafetyPolicies")
            self._safety = SafetyPolicies()
        except Exception as exc:
            log.debug("CivilizationController: SafetyPolicies unavailable: %s", exc)

        try:
            AuditSystem = _load_symbol("governance.audit_system", "AuditSystem")
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
                # Inject HuggingFace inference provider into every agent so they
                # can call _ask_llm() for LLM-based output enrichment.
                if self._hf_brain is not None and hasattr(typed, "hf_brain"):
                    try:
                        typed.hf_brain = self._hf_brain
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

    def _ensure_population(self) -> None:
        """Spawn the initial agent population if the population is currently empty."""
        if self._pop_manager is None or self._pop_manager.agent_count() > 0:
            return
        for role in self._initial_roles:
            self._spawn_agent(role)

    # ── public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Activate the running flag and seed the initial population."""
        self._running = True
        self._started_at = time.time()
        # Seed initial population if empty
        self._ensure_population()
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
             Enrich each task with role-specific topic defaults.
          3. Execute each typed agent; collect results.
          4. Harvest insights + sources from ResearchAgent results;
             harvest evolution hypotheses from EvolutionAgent results.
          5. Store insights per-agent in KnowledgeAPI (role-tagged) and
             optionally in Niblit's production KnowledgeDB.
          6. Update ReputationEngine and AuditSystem per agent.
          7. Publish per-agent result events + a cycle_completed summary on
             the MessageBus.
          8. Every ``_EVOLVE_EVERY`` cycles, run selection + mutation
             (SelectionEngine / MutationEngine). Every ``_EVOLUTION_INTERVAL``
             cycles also run a full PopulationOptimizer pass.
          9. Record cycle metrics.

        Returns a dict with cycle metadata.
        """
        self._cycle_count += 1
        log.info("CivilizationController: cycle %d begin", self._cycle_count)
        cycle_start = time.time()

        # 1. Ensure population is seeded ──────────────────────────────────────
        self._ensure_population()

        agents: List[Dict[str, Any]] = []
        if self._pop_manager:
            agents = self._pop_manager.get_agents()

        agents_active = 0
        tasks_completed = 0
        cycle_insights: List[str] = []
        cycle_repos: List[str] = []
        errors: List[str] = []

        for agent_meta in agents:
            agent_id = agent_meta.get("agent_id", "")
            role = agent_meta.get("role", "researcher")
            typed = self._agent_instances.get(agent_id)

            agents_active += 1

            # 2. Assign task ───────────────────────────────────────────────────
            task: Dict[str, Any] = {}
            if self._scheduler:
                try:
                    task = self._scheduler.assign_task(agent_meta)
                except Exception as exc:
                    log.debug("CivilizationController: scheduler.assign_task failed: %s", exc)
            # Enrich task with a research goal from the ALE topics if available
            topic = _ROLE_TOPIC_MAP.get(role, "general")
            task.setdefault("goal", topic)
            task.setdefault("topic", topic)
            task.setdefault("architecture", {"type": "ai-service", "language": "python"})
            task.setdefault("experiment", {"data": [0.75, 0.80, 0.85]})
            task.setdefault("system_state", {"accuracy": 0.78, "latency_ms": 120})

            # 3. Execute typed agent ───────────────────────────────────────────
            result: Dict[str, Any] = {}
            success = False
            if typed is not None:
                try:
                    result = typed.execute(task)
                    success = True
                    tasks_completed += 1

                    # 4a. Harvest insights from all agents ────────────────────
                    for insight in result.get("insights", []):
                        text = str(insight)
                        cycle_insights.append(text)
                        self._all_insights.append(text)

                    # 4b. Harvest sources/repos from ResearchAgent ────────────
                    for src in result.get("sources", []):
                        src_str = str(src)
                        cycle_repos.append(src_str)
                        self._all_repos.append(src_str)

                    # 4c. Harvest evolution hypotheses from EvolutionAgent ─────
                    hyp = result.get("hypothesis", {})
                    if hyp and hyp.get("proposed_fix"):
                        fix = f"evolution: {hyp['proposed_fix']}"
                        cycle_insights.append(fix)
                        self._all_insights.append(fix)

                    # 5. Store per-agent into KnowledgeAPI (role-tagged) ───────
                    if self._knowledge_api and cycle_insights:
                        for ins in cycle_insights[-3:]:  # cap per agent to avoid flood
                            try:
                                self._knowledge_api.store_knowledge(
                                    ins, tags=[role, "civilization", f"cycle_{self._cycle_count}"],
                                )
                            except Exception:
                                pass

                    # 5b. Persist into Niblit's production KnowledgeDB when wired
                    if self._knowledge_db and hasattr(self._knowledge_db, "add_fact"):
                        for ins in cycle_insights[-2:]:
                            try:
                                key = f"civilization:{role}:{uuid.uuid4().hex[:8]}"
                                self._knowledge_db.add_fact(
                                    key, ins, tags=["civilization", role]
                                )
                            except Exception:
                                pass

                    # 6a. Reputation: use result confidence when available ──────
                    score = float(result.get("confidence", result.get("score", 0.7)))
                    if self._reputation and agent_id:
                        try:
                            self._reputation.record_action(agent_id, success=True, score=score)
                        except Exception:
                            pass

                except NotImplementedError:
                    pass
                except Exception as exc:
                    errors.append(f"{agent_id}: {exc}")
                    log.debug("CivilizationController: agent %s execute failed: %s", agent_id, exc)
                    if self._reputation and agent_id:
                        try:
                            self._reputation.record_action(agent_id, success=False)
                        except Exception:
                            pass

            # 6b. Audit every agent regardless of outcome ─────────────────────
            if self._audit and agent_id:
                try:
                    self._audit.record(
                        action_type=task.get("task_type", "execute"),
                        agent_id=agent_id,
                        details={"role": role, "success": success},
                    )
                except Exception:
                    pass

            # 7a. Publish per-agent result on MessageBus ───────────────────────
            if self._message_bus and result:
                try:
                    self._message_bus.publish(
                        msg_type=f"{role}_result",
                        sender_id=agent_id,
                        payload=result,
                    )
                except Exception:
                    pass

        self._insights_buffer.extend(cycle_insights)

        # 7b. Publish cycle_completed summary event on MessageBus ─────────────
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

        # 8. Evolution step (every _EVOLVE_EVERY cycles) ──────────────────────
        if (
            self._cycle_count % _EVOLVE_EVERY == 0
            and agents
        ):
            self._run_evolution_step(agents)

        # 8b. Full PopulationOptimizer pass (every _EVOLUTION_INTERVAL cycles) ─
        if self._cycle_count % _EVOLUTION_INTERVAL == 0 and self._pop_optimizer and self._reputation:
            self._run_optimizer_step()

        # 9. Record metrics ────────────────────────────────────────────────────
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
            "CivilizationController: cycle %d done — agents=%d tasks=%d insights=%d (%.1f ms)",
            self._cycle_count, agents_active, tasks_completed, len(cycle_insights), elapsed_ms,
        )
        return cycle_data

    def _run_evolution_step(self, agents: List[Dict[str, Any]]) -> None:
        """Select top agents by reputation and replace the bottom half with offspring."""
        if not agents:
            return
        try:
            # Build fitness scores from ReputationEngine
            fitness: Dict[str, float] = {}
            for a in agents:
                aid = a.get("agent_id", "")
                fitness[aid] = self._reputation.get_reputation(aid) if self._reputation else 0.5

            # Elite selection (keep top half)
            n_keep = max(1, len(agents) // 2)
            survivors = self._selector.elite_select(agents, fitness, n=n_keep)
            survivor_ids = {a["agent_id"] for a in survivors}

            # Despawn the bottom half
            for a in agents:
                if a["agent_id"] not in survivor_ids:
                    self._despawn_agent(a["agent_id"])

            # Spawn replacement offspring from survivors' roles (mutated params)
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

    def _run_optimizer_step(self) -> None:
        """Run one generational optimisation pass via PopulationOptimizer."""
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
                "CivilizationController: optimizer step — best_fitness=%.4f",
                result.get("best_fitness", 0.0),
            )
        except Exception as exc:
            log.debug("CivilizationController: optimizer step failed — %s", exc)

    def to_findings_dict(self) -> Dict[str, Any]:
        """Serialize accumulated civilization insights into the format expected
        by ``SelfImprovementOrchestrator.ingest_research_findings()``.

        Returns::

            {
                "patterns": {
                    "Civilization Research": [<insight_text>, ...],
                    "Research Sources": [<repo_name>, ...],
                },
                "top_repos": [{"full_name": <name>, "stars": 0}, ...],
                "new_insights": [<insight_text>, ...],
                "recommendations": [<summary_str>],
                "source": "civilization",
                "cycle_count": <int>,
            }

        The internal insights buffer is cleared after this call so repeated
        calls do not double-ingest the same findings.
        """
        insights = list(dict.fromkeys(self._insights_buffer))[:20]
        # Clear consumed insights to prevent double-ingestion
        self._insights_buffer.clear()

        top_agents: List[Dict[str, Any]] = []
        if self._reputation:
            try:
                top_agents = self._reputation.top_agents(n=5)
            except Exception:
                pass

        metrics_summary: Dict[str, Any] = {}
        if self._metrics:
            try:
                metrics_summary = self._metrics.get_summary()
            except Exception:
                pass

        n_agents = self._pop_manager.agent_count() if self._pop_manager else 0
        recommendations: List[str] = [
            f"{a['agent_id'][:8]}… (role={a.get('role', '?')}) rep={a.get('reputation', 0):.3f}"
            for a in top_agents
        ]
        if metrics_summary:
            recommendations.append(
                f"Civilization ran {metrics_summary.get('total_cycles', self._cycle_count)} cycles "
                f"with avg {metrics_summary.get('avg_agents', 0)} agents."
            )
        if n_agents:
            recommendations.append(f"Active agent count: {n_agents}")

        return {
            "patterns": {
                "Civilization Research": insights,
                "Research Sources": list(dict.fromkeys(self._all_repos))[:10],
            },
            "top_repos": [{"full_name": r, "stars": 0} for r in self._all_repos[:5]],
            "new_insights": insights,
            "recommendations": recommendations,
            "source": "civilization",
            "cycle_count": self._cycle_count,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return current controller status."""
        agent_count = self._pop_manager.agent_count() if self._pop_manager else 0
        metrics_summary: Dict[str, Any] = {}
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
            "knowledge_items": (
                self._knowledge_api.vector_count() if self._knowledge_api else 0
            ),
            "metrics": metrics_summary,
            "top_agents": top_agents,
        }

    def get_cycle_count(self) -> int:
        """Return total completed cycles."""
        return self._cycle_count


if __name__ == "__main__":
    print('Running civilization_controller.py')
