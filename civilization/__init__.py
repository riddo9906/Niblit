"""civilization — self-evolving multi-agent civilisation for Niblit AI.

Architecture overview::

    ┌────────────────────────────────────────────────────────┐
    │                     civilization                       │
    ├─────────────────┬──────────────────┬───────────────────┤
    │ civilization_   │ agent_population  │ training_arena   │
    │ core            │                  │                   │
    ├─────────────────┼──────────────────┼───────────────────┤
    │ collaboration_  │ evolution_engine  │ knowledge_       │
    │ network         │                  │ ecosystem        │
    ├─────────────────┼──────────────────┼───────────────────┤
    │ experiment_labs │ governance       │ infrastructure   │
    ├─────────────────┴──────────────────┴───────────────────┤
    │                     api_gateway                        │
    └────────────────────────────────────────────────────────┘

Usage example::

    from civilization.civilization_core import CivilizationController
    controller = CivilizationController()
    controller.start()
    result = controller.run_cycle()
"""

from .agent_population import (
    AnalystAgent,
    BaseAgent,
    BuilderAgent,
    EvolutionAgent,
    PlannerAgent,
    ResearchAgent,
)
from .api_gateway import APIServer, Authentication, KnowledgeAPI, TaskAPI
from .civilization_core import (
    CivilizationController,
    CivilizationMetrics,
    CivilizationScheduler,
    PopulationManager,
)
from .collaboration_network import AgentProtocol, MessageBus, ServiceRegistry
from .evolution_engine import (
    ArchitectureEvolver,
    MutationEngine,
    PopulationOptimizer,
    SelectionEngine,
)
from .experiment_labs import BenchmarkEngine, ExperimentManager, ResultAnalyzer, SandboxRunner
from .governance import AuditSystem, ReputationEngine, ResourceLimits, SafetyPolicies
from .infrastructure import ClusterManager, ContainerManager, NodeRegistry, WorkloadBalancer
from .knowledge_ecosystem import EmbeddingService, GraphMemory, VectorMemory
from .training_arena import ArenaManager, ChallengeGenerator, CompetitionEngine, ScoringSystem

__all__ = [
    # civilization_core
    "CivilizationController", "PopulationManager", "CivilizationScheduler", "CivilizationMetrics",
    # agent_population
    "BaseAgent", "ResearchAgent", "BuilderAgent", "PlannerAgent", "AnalystAgent", "EvolutionAgent",
    # training_arena
    "ArenaManager", "ChallengeGenerator", "CompetitionEngine", "ScoringSystem",
    # collaboration_network
    "MessageBus", "AgentProtocol", "ServiceRegistry",
    # evolution_engine
    "MutationEngine", "SelectionEngine", "PopulationOptimizer", "ArchitectureEvolver",
    # knowledge_ecosystem
    "VectorMemory", "GraphMemory", "EmbeddingService", "KnowledgeAPI",
    # experiment_labs
    "ExperimentManager", "SandboxRunner", "BenchmarkEngine", "ResultAnalyzer",
    # governance
    "SafetyPolicies", "ResourceLimits", "AuditSystem", "ReputationEngine",
    # infrastructure
    "ClusterManager", "NodeRegistry", "WorkloadBalancer", "ContainerManager",
    # api_gateway
    "Authentication", "TaskAPI", "APIServer",
]
