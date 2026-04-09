"""distributed_niblit — distributed multi-node runtime for Niblit AI agents.

Architecture overview::

    ┌─────────────────────────────────────────────────┐
    │                 distributed_niblit              │
    ├──────────┬──────────┬──────────┬────────────────┤
    │  network │orchestrat│api_gatew │  agent_node    │
    │          │    or    │   ay     │                │
    ├──────────┴──────────┴──────────┴────────────────┤
    │  knowledge_node  │ experiment_node │ scheduler  │
    ├──────────────────┴─────────────────┴────────────┤
    │                  observability                  │
    └─────────────────────────────────────────────────┘

Usage example::

    from distributed_niblit.network import MessageBus
    from distributed_niblit.orchestrator import NodeRegistry
    bus = MessageBus()
    registry = NodeRegistry()
"""

from .agent_node import AgentRuntime, CodeGenerator, PlannerAgent, ResearchAgent, TaskExecutor
from .api_gateway import AuthLayer, GatewayServer, RateLimiter, RoutingLayer
from .experiment_node import BenchmarkEngine, ExperimentRunner, ResultsCollector, SandboxExecutor
from .knowledge_node import EmbeddingService, GraphStore, KnowledgeAPI, VectorStore
from .network import MessageBus, NodeProtocol, ServiceRegistry
from .observability import AnomalyDetector, LogAggregator, MetricsCollector
from .orchestrator import JobDispatcher, NodeRegistry, TaskRouter, WorkloadBalancer
from .scheduler import EvolutionScheduler, ExperimentScheduler, ResearchScheduler, TaskScheduler

__all__ = [
    # network
    "MessageBus", "NodeProtocol", "ServiceRegistry",
    # orchestrator
    "NodeRegistry", "TaskRouter", "JobDispatcher", "WorkloadBalancer",
    # api_gateway
    "GatewayServer", "AuthLayer", "RoutingLayer", "RateLimiter",
    # agent_node
    "AgentRuntime", "TaskExecutor", "ResearchAgent", "PlannerAgent", "CodeGenerator",
    # knowledge_node
    "VectorStore", "GraphStore", "EmbeddingService", "KnowledgeAPI",
    # experiment_node
    "ExperimentRunner", "SandboxExecutor", "BenchmarkEngine", "ResultsCollector",
    # scheduler
    "TaskScheduler", "ResearchScheduler", "ExperimentScheduler", "EvolutionScheduler",
    # observability
    "MetricsCollector", "LogAggregator", "AnomalyDetector",
]
if __name__ == "__main__":
    print('Running __init__.py')
